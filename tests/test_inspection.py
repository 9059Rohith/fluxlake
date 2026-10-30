import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from fluxlake.api import create_app
from fluxlake.lake import Lake
from test_lake import event

TOKEN = "test-only-fluxlake-token-0123456789"
AUTH = {"Authorization": "Bearer " + TOKEN}


def test_inspection_auth_validation_and_source_failure_are_closed(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    marker = "never-expose-inspection-secret"
    monkeypatch.setenv("DATABASE_URL", f"postgresql://private:{marker}@127.0.0.1:1/private")
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    assert client.get("/inspection?key=tx1").status_code == 401
    for params in ({}, {"key": "bad/key"}, [("key", "a")] * 101):
        assert client.get("/inspection", params=params, headers=AUTH).status_code == 422
    response = client.get("/inspection?key=tx1", headers=AUTH)
    assert response.status_code == 503
    assert marker not in response.text + caplog.text
    assert "private" not in response.text


@pytest.mark.postgres
def test_inspection_finds_drift_tombstones_absence_and_never_repairs(tmp_path, monkeypatch):
    from fluxlake.inspection import inspect
    from fluxlake.projection import SourceProjection

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; needs actual PostgreSQL")
    prefix = "inspect-" + uuid.uuid4().hex
    live, deleted, absent = [prefix + suffix for suffix in ("-live", "-delete", "-absent")]
    with psycopg.connect(url, autocommit=True) as db:
        for key in (live, deleted):
            db.execute(
                "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,10,'USD','settled')",
                (key,),
            )
        lake = Lake(tmp_path)
        projection = SourceProjection(lake, url)
        projection.refresh(force=True)
        before = (tmp_path / "silver/manifest.json").read_bytes()
        result = inspect(lake, url, [live, deleted, absent])
        assert result["scope"] == "selected_keys_observed_snapshots"
        assert result["counts"] == {"match": 2, "mismatch": 0, "absent": 1}
        assert result["source_snapshot"]["isolation"] == "repeatable read"
        assert result["source_snapshot"]["id"]
        assert result["projection_snapshot"]["file"].endswith(".parquet")
        assert result["projection_snapshot"]["captured_at"]
        db.execute("UPDATE transactions SET amount_minor=11 WHERE id=%s", (live,))
        db.execute("DELETE FROM transactions WHERE id=%s", (deleted,))
        result = inspect(lake, url, [live, deleted, absent])
        assert result["counts"] == {"match": 0, "mismatch": 2, "absent": 1}
        assert all(
            "revision" in item["differences"]
            for item in result["results"]
            if item["status"] == "mismatch"
        )
        assert (tmp_path / "silver/manifest.json").read_bytes() == before
        assert (
            db.execute(
                "SELECT count(*) FROM transaction_outbox WHERE aggregate_id=ANY(%s) AND processed_at IS NOT NULL",
                ([live, deleted],),
            ).fetchone()[0]
            == 0
        )
        projection.refresh(force=True)
        result = inspect(lake, url, [live, deleted, absent])
        assert result["counts"] == {"match": 2, "mismatch": 0, "absent": 1}
        assert next(r for r in result["results"] if r["key"] == deleted)["source_deleted"] is True
        # Same revision but altered Parquet payload is detected independently of SQLite.
        import pyarrow as pa
        import pyarrow.parquet as pq

        snapshot = lake._snapshot()
        table = pq.read_table(snapshot)
        rows = table.to_pylist()
        next(row for row in rows if row["key"] == live)["amount_minor"] = 999
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), snapshot)
        result = inspect(lake, url, [live])
        assert result["results"][0]["differences"] == ["silver_payload"]
        assert "999" not in str(result)


def test_inspection_bounds_before_database_work(tmp_path):
    from fluxlake.inspection import inspect

    lake = Lake(tmp_path)
    for keys in ([], ["bad/key"], ["a"] * 101):
        with pytest.raises(ValueError):
            inspect(lake, "not-a-database", keys)
    lake.apply([event()])


@pytest.mark.postgres
def test_inspection_source_snapshot_excludes_later_concurrent_commit(tmp_path, monkeypatch):
    from fluxlake.inspection import inspect
    from fluxlake.projection import SourceProjection

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; needs actual PostgreSQL")
    key = "snapshot-" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as writer:
        writer.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,12,'USD','settled')",
            (key,),
        )
        lake = Lake(tmp_path)
        SourceProjection(lake, url).refresh(force=True)

        class ObservedConnection(psycopg.Connection):
            def execute(self, query, *args, **kwargs):
                cursor = super().execute(query, *args, **kwargs)
                if isinstance(query, str) and query.startswith("SELECT pg_current_snapshot()"):
                    assert (
                        super().execute("SHOW transaction_isolation").fetchone()[0]
                        == "repeatable read"
                    )
                    assert super().execute("SHOW transaction_read_only").fetchone()[0] == "on"
                    writer.execute("UPDATE transactions SET amount_minor=13 WHERE id=%s", (key,))
                return cursor

        monkeypatch.setattr(psycopg, "connect", ObservedConnection.connect)
        result = inspect(lake, url, [key])
        assert result["counts"]["match"] == 1
        assert result["results"][0]["source_version"] == 1
        assert (
            writer.execute(
                "SELECT version FROM transaction_versions WHERE aggregate_id=%s", (key,)
            ).fetchone()[0]
            == 2
        )


@pytest.mark.postgres
def test_request_inspection_does_not_hide_drift_by_refreshing(tmp_path, monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; needs actual PostgreSQL")
    key = "no-refresh-" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as writer:
        writer.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,14,'USD','settled')",
            (key,),
        )
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("FLUXLAKE_SOURCE_SYNC", "request")
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    client = TestClient(create_app(tmp_path))
    before = (tmp_path / "silver/manifest.json").read_bytes()
    first = client.get("/inspection", params={"key": key}, headers=AUTH)
    assert first.status_code == 200
    assert first.json()["results"][0]["differences"] == ["state_missing", "silver_missing"]
    assert (tmp_path / "silver/manifest.json").read_bytes() == before
    assert client.get("/transactions", headers=AUTH).status_code == 200
    assert (
        client.get("/inspection", params={"key": key}, headers=AUTH).json()["counts"]["match"] == 1
    )


def test_inspection_checks_silver_duplicate_and_state_identity():
    import hashlib
    from fluxlake.inspection import _compare
    from fluxlake.lake import canonical

    source = event()
    data, attrs = Lake._validate(source)
    payload = {
        "key": source["key"],
        "version": source["version"],
        "occurred_at": source["occurred_at"],
        **data,
        "attributes": attrs,
    }
    state = {
        "version": 1,
        "deleted": False,
        "event_hash": hashlib.sha256(canonical(source)).hexdigest(),
        "payload": canonical(payload).decode(),
    }
    silver = {
        name: payload[name]
        for name in ("key", "version", "occurred_at", "amount_minor", "currency", "status")
    }
    silver["attributes_json"] = "{}"
    assert _compare("tx1", source, state, silver, False)["status"] == "match"
    assert _compare("tx1", source, state, silver, True)["differences"] == ["silver_duplicate_key"]
    state["event_hash"] = "wrong"
    assert _compare("tx1", source, state, silver, False)["differences"] == ["event_identity"]
    assert _compare("tx1", None, state, None, False)["differences"] == ["source_absent"]
    source["data"]["currency"] = "invalid"
    assert _compare("tx1", source, state, silver, False)["differences"] == ["source_contract"]


@pytest.mark.postgres
def test_inspection_refuses_oversized_source_and_local_snapshot(tmp_path):
    from fluxlake.inspection import InspectionUnavailable, inspect
    import pyarrow as pa
    import pyarrow.parquet as pq

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; needs actual PostgreSQL")
    key = "oversized-" + uuid.uuid4().hex
    lake = Lake(tmp_path)
    with psycopg.connect(url, autocommit=True) as writer:
        writer.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status,attributes) VALUES (%s,1,'USD','settled',%s)",
            (key, psycopg.types.json.Jsonb({"padding": "x" * 70000})),
        )
    try:
        with pytest.raises(InspectionUnavailable):
            inspect(lake, url, [key])
    finally:
        with psycopg.connect(url, autocommit=True) as writer:
            writer.execute("DELETE FROM transactions WHERE id=%s", (key,))
            writer.execute("DELETE FROM transaction_outbox WHERE aggregate_id=%s", (key,))
            writer.execute("DELETE FROM transaction_versions WHERE aggregate_id=%s", (key,))
    pq.write_table(pa.table({"key": ["a"] * 5001}), lake._snapshot())
    with pytest.raises(InspectionUnavailable):
        inspect(lake, url, ["a"])


def test_inspection_preserves_scalar_types_in_payload_comparison():
    import hashlib
    from fluxlake.inspection import _compare
    from fluxlake.lake import canonical

    source = event(flag=1)
    data, attrs = Lake._validate(source)
    payload = {
        "key": source["key"],
        "version": source["version"],
        "occurred_at": source["occurred_at"],
        **data,
        "attributes": attrs,
    }
    state = {
        "version": 1,
        "deleted": False,
        "event_hash": hashlib.sha256(canonical(source)).hexdigest(),
        "payload": canonical(payload).decode(),
    }
    silver = {
        name: payload[name]
        for name in ("key", "version", "occurred_at", "amount_minor", "currency", "status")
    }
    silver["attributes_json"] = canonical(attrs).decode()
    silver["attr_flag"] = True  # Python's True == 1 must not hide schema/value drift.
    assert _compare("tx1", source, state, silver, False)["differences"] == ["silver_payload"]
    silver["attr_flag"] = 1
    payload["attributes"]["flag"] = True
    payload["flag"] = True
    state["payload"] = canonical(payload).decode()
    assert _compare("tx1", source, state, silver, False)["differences"] == ["state_payload"]
