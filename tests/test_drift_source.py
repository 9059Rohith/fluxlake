import os
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from fluxlake.api import create_app
from test_drift_api import AUTH, TOKEN

pytestmark = pytest.mark.postgres


@pytest.fixture
def source():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; actual PostgreSQL required")
    with psycopg.connect(url, autocommit=True) as writer:
        writer.execute(Path("sql/source.sql").read_text())
        before = writer.execute("SELECT coalesce(max(id),0) FROM transaction_outbox").fetchone()[0]
        try:
            yield url, writer
        finally:
            # Corrupt-history fixtures must not poison later complete-history replay tests.
            keys = [
                row[0]
                for row in writer.execute(
                    "SELECT DISTINCT aggregate_id FROM transaction_outbox WHERE id>%s", (before,)
                )
            ]
            writer.execute("DELETE FROM transactions WHERE id=ANY(%s)", (keys,))
            writer.execute("DELETE FROM transaction_versions WHERE aggregate_id=ANY(%s)", (keys,))
            writer.execute("DELETE FROM transaction_outbox WHERE id>%s", (before,))


def add(writer, amount=10, currency="USD", key=None):
    key = key or "drift-" + uuid.uuid4().hex
    writer.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,%s,%s,'settled')",
        (key, amount, currency),
    )
    index = writer.execute(
        "SELECT max(id) FROM transaction_outbox WHERE aggregate_id=%s", (key,)
    ).fetchone()[0]
    return index, key


def pair(left, right):
    from fluxlake.drift_contracts import CompareRequest

    return CompareRequest.model_validate(
        {"baseline": {"start": left, "end": left}, "candidate": {"start": right, "end": right}}
    )


def test_source_reads_acknowledged_history_excludes_tombstones_and_never_refreshes(
    source, tmp_path, monkeypatch
):
    url, writer = source
    left, key = add(writer)
    writer.execute(
        "UPDATE transaction_outbox SET processed_at=clock_timestamp() WHERE id=%s", (left,)
    )
    right, _ = add(writer, 30)
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("FLUXLAKE_SOURCE_SYNC", "request")
    client = TestClient(create_app(tmp_path))
    before = (tmp_path / "silver/manifest.json").read_bytes()
    ack_before = writer.execute(
        "SELECT id,processed_at FROM transaction_outbox ORDER BY id"
    ).fetchall()
    response = client.post("/drift/compare", json=pair(left, right).model_dump(), headers=AUTH)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["baseline"]["analyzed_events"] == 1
    assert report["source_snapshot"]["read_only"] is True
    assert report["source_snapshot"]["isolation"] == "repeatable read"
    assert report["source_snapshot"]["id"]
    assert key not in response.text
    assert (tmp_path / "silver/manifest.json").read_bytes() == before
    assert (
        writer.execute("SELECT id,processed_at FROM transaction_outbox ORDER BY id").fetchall()
        == ack_before
    )
    repeat = client.post("/drift/compare", json=pair(left, right).model_dump(), headers=AUTH)
    assert repeat.json()["fingerprint"] == report["fingerprint"]
    writer.execute("DELETE FROM transactions WHERE id=%s", (key,))
    tombstone = writer.execute(
        "SELECT max(id) FROM transaction_outbox WHERE aggregate_id=%s", (key,)
    ).fetchone()[0]
    report = client.post(
        "/drift/compare", json=pair(tombstone, right).model_dump(), headers=AUTH
    ).json()
    assert report["baseline"]["tombstones"] == 1
    assert report["baseline"]["analyzed_events"] == 0


def test_both_windows_share_snapshot_and_late_lower_id_changes_later_fingerprint(
    source, monkeypatch
):
    from fluxlake.drift_source import compare_source

    url, writer = source
    with psycopg.connect(url, autocommit=True) as slow:
        slow.execute("BEGIN")
        low, _ = add(slow)
        high, _ = add(writer, 20)
        req = pair(low, high)

        class ObservedConnection(psycopg.Connection):
            def execute(self, query, *args, **kwargs):
                cursor = super().execute(query, *args, **kwargs)
                if isinstance(query, str) and query.startswith("SELECT pg_current_snapshot()"):
                    assert (
                        super().execute("SHOW transaction_isolation").fetchone()[0]
                        == "repeatable read"
                    )
                    assert super().execute("SHOW transaction_read_only").fetchone()[0] == "on"
                    slow.execute("COMMIT")
                    writer.execute(
                        "UPDATE transactions SET amount_minor=21 WHERE id IN "
                        "(SELECT aggregate_id FROM transaction_outbox WHERE id=%s)",
                        (high,),
                    )
                return cursor

        original_connect = psycopg.connect
        monkeypatch.setattr(psycopg, "connect", ObservedConnection.connect)
        report = compare_source(url, req)
        assert report.baseline.observed_rows == 0
        assert report.baseline.missing_identity_positions == 1
        assert report.candidate.observed_rows == 1
        monkeypatch.setattr(psycopg, "connect", original_connect)
        later = compare_source(url, req)
        assert later.baseline.observed_rows == 1
        assert later.fingerprint != report.fingerprint


def test_pruned_gap_and_altered_payload_change_evidence_not_acknowledgement(source):
    from fluxlake.drift_source import compare_source

    url, writer = source
    left, _ = add(writer)
    right, _ = add(writer)
    req = pair(left, right)
    first = compare_source(url, req)
    writer.execute(
        "UPDATE transaction_outbox SET data=jsonb_set(data,'{amount_minor}','99') WHERE id=%s",
        (right,),
    )
    changed = compare_source(url, req)
    assert changed.fingerprint != first.fingerprint
    writer.execute("DELETE FROM transaction_outbox WHERE id=%s", (left,))
    gap = compare_source(url, req)
    assert gap.baseline.missing_identity_positions == 1


@pytest.mark.parametrize(
    "data",
    [
        {"amount_minor": True, "currency": "USD", "status": "settled"},
        {"amount_minor": 1.0, "currency": "USD", "status": "settled"},
        {"amount_minor": 1, "currency": "usd", "status": "settled"},
        {"amount_minor": 1, "currency": "USD", "status": "other"},
        {"amount_minor": 1, "currency": "USD", "status": "settled", "large": "x" * 65536},
    ],
)
def test_source_rejects_invalid_or_oversized_retained_evidence(source, data):
    from fluxlake.drift_source import DriftUnavailable, compare_source

    url, writer = source
    left, _ = add(writer)
    right, _ = add(writer)
    writer.execute(
        "UPDATE transaction_outbox SET data=%s WHERE id=%s", (psycopg.types.json.Jsonb(data), right)
    )
    with pytest.raises(DriftUnavailable, match="unavailable"):
        compare_source(url, pair(left, right))


def test_total_payload_budget_is_checked_before_any_payload_transfer(source, monkeypatch):
    from fluxlake.drift_source import DriftUnavailable, compare_source
    from fluxlake.drift_contracts import CompareRequest

    url, writer = source
    prefix = "budget-" + uuid.uuid4().hex
    writer.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status,attributes) "
        "SELECT %s || n,1,'USD','settled',jsonb_build_object('padding',repeat('x',60000)) "
        "FROM generate_series(1,72) n",
        (prefix,),
    )
    low, high = writer.execute(
        "SELECT min(id),max(id) FROM transaction_outbox WHERE aggregate_id LIKE %s", (prefix + "%",)
    ).fetchone()
    right, _ = add(writer)
    payload_queries = []

    class ObservedConnection(psycopg.Connection):
        def execute(self, query, *args, **kwargs):
            if isinstance(query, str) and query.startswith("SELECT id,event_id"):
                payload_queries.append(query)
            return super().execute(query, *args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", ObservedConnection.connect)
    req = CompareRequest.model_validate(
        {"baseline": {"start": low, "end": high}, "candidate": {"start": right, "end": right}}
    )
    with pytest.raises(DriftUnavailable):
        compare_source(url, req)
    assert payload_queries == []


def test_oversized_outbox_metadata_is_rejected_before_transfer(source, monkeypatch):
    from fluxlake.drift_source import DriftUnavailable, compare_source

    url, writer = source
    left, _ = add(writer)
    right, _ = add(writer)
    writer.execute(
        "UPDATE transaction_outbox SET operation=repeat('x',100000) WHERE id=%s", (right,)
    )
    payload_queries = []

    class ObservedConnection(psycopg.Connection):
        def execute(self, query, *args, **kwargs):
            if isinstance(query, str) and query.startswith("SELECT id,event_id"):
                payload_queries.append(query)
            return super().execute(query, *args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", ObservedConnection.connect)
    with pytest.raises(DriftUnavailable):
        compare_source(url, pair(left, right))
    assert payload_queries == []
