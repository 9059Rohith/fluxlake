import os
from pathlib import Path
import uuid

import psycopg
import pytest

from fluxlake.lake import Lake
from fluxlake.worker import drain_once

pytestmark = pytest.mark.postgres


@pytest.fixture
def db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; needs actual PostgreSQL")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(Path("sql/source.sql").read_text())
        yield conn


def test_postgres_rollback_update_delete_and_worker_replay(db, tmp_path):
    key = "test-" + uuid.uuid4().hex
    lake = Lake(tmp_path)
    db.execute("BEGIN")
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,100,'USD','settled')",
        (key,),
    )
    db.execute("ROLLBACK")
    assert (
        db.execute(
            "SELECT count(*) FROM transaction_outbox WHERE aggregate_id=%s", (key,)
        ).fetchone()[0]
        == 0
    )
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,100,'USD','settled')",
        (key,),
    )
    db.execute("UPDATE transactions SET amount_minor=200 WHERE id=%s", (key,))
    db.execute("DELETE FROM transactions WHERE id=%s", (key,))
    versions = db.execute(
        "SELECT version FROM transaction_outbox WHERE aggregate_id=%s ORDER BY id", (key,)
    ).fetchall()
    assert versions == [(1,), (2,), (3,)]
    assert drain_once(db, lake, 10000) >= 3
    assert not [row for row in lake.current() if row["key"] == key]
    db.execute("UPDATE transaction_outbox SET processed_at=NULL WHERE aggregate_id=%s", (key,))
    assert drain_once(db, Lake(tmp_path), 10000) == 3
    assert not [row for row in lake.current() if row["key"] == key]
    # Reinsert same key must not reset revision after a delete.
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,300,'USD','settled')",
        (key,),
    )
    drain_once(db, lake, 10000)
    assert [r for r in lake.current() if r["key"] == key][0]["version"] == 4


def test_source_late_lower_sequence_commit_is_not_lost(db, tmp_path):
    # A high-watermark implementation would ack the larger id then skip this
    # late-committing lower identity. Different keys avoid intentional per-key locks.
    url = os.environ["TEST_DATABASE_URL"]
    low, high = "low-" + uuid.uuid4().hex, "high-" + uuid.uuid4().hex
    lake = Lake(tmp_path)
    with psycopg.connect(url, autocommit=True) as slow:
        slow.execute("BEGIN")
        slow.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,1,'USD','settled')",
            (low,),
        )
        db.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,2,'USD','settled')",
            (high,),
        )
        drain_once(db, lake, 10000)
        assert high in [r["key"] for r in lake.current()]
        assert low not in [r["key"] for r in lake.current()]
        slow.execute("COMMIT")
        drain_once(db, lake, 10000)
    assert {low, high}.issubset({r["key"] for r in lake.current()})


def test_sink_failure_does_not_ack_source(db, tmp_path, monkeypatch):
    key = "fail-" + uuid.uuid4().hex
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,5,'USD','settled')",
        (key,),
    )
    lake = Lake(tmp_path)

    def crash():
        raise OSError("disk full")

    monkeypatch.setattr(lake, "_publish", crash)
    with pytest.raises(OSError):
        drain_once(db, lake, 10000)
    assert (
        db.execute(
            "SELECT processed_at FROM transaction_outbox WHERE aggregate_id=%s", (key,)
        ).fetchone()[0]
        is None
    )
    restarted = Lake(tmp_path)
    drain_once(db, restarted, 10000)
    assert [r for r in restarted.current() if r["key"] == key][0]["amount_minor"] == 5


def test_source_attributes_cannot_override_core_amount(db):
    key = "reserved-" + uuid.uuid4().hex
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status,attributes) VALUES (%s,100,'USD','settled','{\"amount_minor\":1}')",
            (key,),
        )


def test_cli_init_uses_explicit_schema_file(db, tmp_path, monkeypatch):
    import sys
    from fluxlake.cli import main

    name = "cli_probe_" + uuid.uuid4().hex
    schema = tmp_path / "probe.sql"
    schema.write_text(f"CREATE TABLE {name} (value integer)")
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setattr(sys, "argv", ["fluxlake", "init-source", "--file", str(schema)])
    main()
    assert db.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] == name
    db.execute(f"DROP TABLE {name}")


def test_least_privilege_relay_can_ack_but_cannot_change_source_or_event_body(db, tmp_path):
    db.execute(Path("sql/relay-role.sql").read_text())
    key = "relay-role-" + uuid.uuid4().hex
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,10,'USD','settled')",
        (key,),
    )
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as relay:
        relay.execute("SET ROLE fluxlake_relay")
        assert drain_once(relay, Lake(tmp_path), 10000) >= 1
        assert relay.execute(
            "SELECT processed_at IS NOT NULL FROM transaction_outbox WHERE aggregate_id=%s", (key,)
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            relay.execute("UPDATE transaction_outbox SET data='{}' WHERE aggregate_id=%s", (key,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            relay.execute("DELETE FROM transactions WHERE id=%s", (key,))


def test_request_projection_replays_acknowledged_history_without_acknowledging_new_rows(
    db, tmp_path
):
    from fluxlake.projection import SourceProjection

    key = "projection-" + uuid.uuid4().hex
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,7,'USD','settled')",
        (key,),
    )
    db.execute(
        "UPDATE transaction_outbox SET processed_at=clock_timestamp() WHERE aggregate_id=%s", (key,)
    )
    lake = Lake(tmp_path)
    projection = SourceProjection(lake, os.environ["TEST_DATABASE_URL"])
    assert not projection.ready
    projection.refresh(force=True)
    assert projection.ready
    assert [row for row in lake.current() if row["key"] == key][0]["amount_minor"] == 7
    db.execute("UPDATE transactions SET amount_minor=9 WHERE id=%s", (key,))
    projection.refresh(force=True)
    assert [row for row in lake.current() if row["key"] == key][0]["amount_minor"] == 9
    assert (
        db.execute(
            "SELECT processed_at FROM transaction_outbox WHERE aggregate_id=%s AND version=2",
            (key,),
        ).fetchone()[0]
        is None
    )


def test_request_projection_replays_late_lower_id_commit(db, tmp_path):
    from fluxlake.projection import SourceProjection

    key = "late-projection-" + uuid.uuid4().hex
    lake = Lake(tmp_path)
    projection = SourceProjection(lake, os.environ["TEST_DATABASE_URL"])
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as slow:
        slow.execute("BEGIN")
        slow.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,8,'USD','settled')",
            (key,),
        )
        db.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,10,'USD','settled')",
            ("high-" + key,),
        )
        projection.refresh(force=True)
        assert key not in [row["key"] for row in lake.current()]
        slow.execute("COMMIT")
        projection.refresh(force=True)
    assert key in [row["key"] for row in lake.current()]


def test_request_projection_limit_fails_before_partial_publication(db, tmp_path):
    from fluxlake.projection import ProjectionUnavailable, SourceProjection

    lake = Lake(tmp_path)
    projection = SourceProjection(lake, os.environ["TEST_DATABASE_URL"], max_events=1)
    with pytest.raises(ProjectionUnavailable):
        projection.refresh(force=True)
    assert not projection.ready
    assert lake.current() == []


def test_request_profile_exposes_actual_synthetic_source_without_fixture_writes(
    db, tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient
    from fluxlake.api import create_app

    token = "test-only-fluxlake-token-0123456789"
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", token)
    monkeypatch.setenv("FLUXLAKE_PUBLIC_DEMO", "true")
    monkeypatch.setenv("FLUXLAKE_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("FLUXLAKE_SOURCE_SYNC", "request")
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    key = "http-projection-" + uuid.uuid4().hex
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status,attributes) VALUES (%s,11,'EUR','settled','{\"synthetic\":true}')",
        (key,),
    )
    client = TestClient(create_app(tmp_path))
    assert client.get("/ready").status_code == 200
    assert client.get("/demo/summary").status_code == 410
    pipeline = client.get("/pipeline", headers={"Authorization": "Bearer " + token}).json()
    assert pipeline["status"] == "request-synchronized"
    assert "request" in pipeline["profile"]
    rows = client.get("/transactions", headers={"Authorization": "Bearer " + token}).json()
    assert [r for r in rows if r["key"] == key][0]["amount_minor"] == 11
    assert (
        client.post("/events", headers={"Authorization": "Bearer " + token}, json=[]).status_code
        == 403
    )
    assert (
        db.execute(
            "SELECT processed_at FROM transaction_outbox WHERE aggregate_id=%s", (key,)
        ).fetchone()[0]
        is None
    )


def test_request_projection_bounds_cache_files_and_skips_unchanged_publications(db, tmp_path):
    from fluxlake.projection import SourceProjection

    key = "bounded-projection-" + uuid.uuid4().hex
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,20,'USD','settled')",
        (key,),
    )
    lake = Lake(tmp_path)
    projection = SourceProjection(lake, os.environ["TEST_DATABASE_URL"])
    projection.refresh(force=True)
    initial = (tmp_path / "silver" / "manifest.json").read_bytes()
    projection.refresh(force=True)
    assert (tmp_path / "silver" / "manifest.json").read_bytes() == initial
    db.execute("UPDATE transactions SET amount_minor=21 WHERE id=%s", (key,))
    projection.refresh(force=True)
    assert len(list((tmp_path / "silver").glob("snapshot-*.parquet"))) == 1
    assert (
        projection.read(lambda: [r for r in lake.current() if r["key"] == key])[0]["amount_minor"]
        == 21
    )


def test_opt_in_synthetic_bootstrap_is_real_and_once_per_empty_database(db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from fluxlake.api import create_app
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    name = "fluxlake_bootstrap_" + uuid.uuid4().hex
    db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        url = make_conninfo(os.environ["TEST_DATABASE_URL"], dbname=name)
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("FLUXLAKE_SOURCE_SYNC", "request")
        monkeypatch.setenv("FLUXLAKE_SEED_DEMO", "true")
        monkeypatch.setenv("FLUXLAKE_PUBLIC_DEMO", "true")
        monkeypatch.setenv("FLUXLAKE_ALLOWED_HOSTS", "testserver")
        token = "test-only-fluxlake-token-0123456789"
        monkeypatch.setenv("FLUXLAKE_API_TOKEN", token)
        auth = {"Authorization": "Bearer " + token}
        first = TestClient(create_app(tmp_path / "one"))
        assert first.get("/ready").status_code == 200
        assert first.get("/demo/summary").status_code == 410
        gold = first.get("/gold", headers=auth).json()
        assert sorted(gold, key=lambda row: row["currency"]) == [
            {"currency": "INR", "transaction_count": 10, "total_minor": 126250},
            {"currency": "USD", "transaction_count": 9, "total_minor": 102375},
        ]
        second = TestClient(create_app(tmp_path / "two"))
        assert second.get("/ready").status_code == 200
        assert second.get("/demo/summary").status_code == 410
        assert sorted(
            second.get("/gold", headers=auth).json(), key=lambda row: row["currency"]
        ) == sorted(gold, key=lambda row: row["currency"])
        with psycopg.connect(url, autocommit=True) as source:
            assert source.execute("SELECT count(*) FROM transaction_outbox").fetchone()[0] == 22
            assert (
                source.execute(
                    "SELECT count(*) FROM transaction_outbox WHERE processed_at IS NOT NULL"
                ).fetchone()[0]
                == 0
            )
    finally:
        db.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_automatic_seed_refuses_existing_nonempty_unmarked_source(db, tmp_path):
    from fluxlake.projection import ProjectionUnavailable, SourceProjection

    before = db.execute("SELECT count(*) FROM transactions").fetchone()[0]
    assert before > 0
    projection = SourceProjection(Lake(tmp_path), os.environ["TEST_DATABASE_URL"], seed_demo=True)
    with pytest.raises(ProjectionUnavailable):
        projection.refresh(force=True)
    assert db.execute("SELECT count(*) FROM transactions").fetchone()[0] == before
    assert db.execute("SELECT to_regclass('public.fluxlake_demo_bootstrap')").fetchone()[0] is None
