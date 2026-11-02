"""Real PostgreSQL publication/rollback checks in the dedicated TEST_DATABASE_URL.

Controlled records below are isolated test inputs, never deployed application data.
"""

import os
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from fluxlake.api import create_app
from fluxlake.workspace import IngestionBusy, PublicWorkspace, WorkspaceUnavailable

pytestmark = pytest.mark.postgres


@pytest.fixture
def store():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; actual PostgreSQL required")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(Path("sql/workspace.sql").read_text())
        conn.execute(
            "TRUNCATE flux_public_silver,flux_public_bronze,flux_public_schema,flux_public_quarantine,flux_public_runs CASCADE"
        )
    yield PublicWorkspace(url)


def event(identity="1", kind="PushEvent"):
    return {
        "id": identity,
        "type": kind,
        "public": True,
        "created_at": "2026-11-01T00:00:00Z",
        "repo": {"name": "isolated-test/repository"},
        "actor": {"login": "isolated-test-actor"},
        "payload": {},
    }


def fetcher(events):
    return lambda: (
        events,
        {"http_status": 200, "response_sha256": "test-response-fingerprint", "poll_seconds": 60},
    )


def allow_next_run(store):
    with psycopg.connect(store.database_url) as conn:
        conn.execute("UPDATE flux_public_runs SET started_at=started_at-interval '2 minutes'")


def test_atomic_publication_duplicate_receipts_and_identity_conflict(store):
    first = store.ingest(fetcher([event()]))
    assert first["inserted"] == 1
    assert first["finished_at"] > first["started_at"]
    with pytest.raises(IngestionBusy):
        store.ingest(fetcher([event()]))
    allow_next_run(store)
    second = store.ingest(fetcher([event()]))
    assert second["inserted"] == 0 and second["duplicates"] == 1
    allow_next_run(store)
    changed = event()
    changed["payload"] = {"action": "changed"}
    third = store.ingest(fetcher([changed]))
    assert third["inserted"] == 0 and third["quarantined"] == 1
    assert store.event("1")["raw"]["payload"] == {}
    counts = store.overview()["counts"]
    assert counts["events"] == counts["bronze_events"] == 1
    assert counts["run_count"] == 3 and counts["quarantined"] == 1
    assert "conflicting content" in store.quarantine()["rows"][0]["reason"]
    assert any(r["path"] == "actor.login" for r in store.schema()["rows"])


def test_source_failure_persists_failure_without_publishing_events(store):
    def unavailable():
        raise WorkspaceUnavailable("Controlled test source is unavailable")

    with pytest.raises(WorkspaceUnavailable):
        store.ingest(unavailable)
    runs = store.runs()["rows"]
    assert len(runs) == 1 and runs[0]["status"] == "failed"
    assert runs[0]["inserted"] == 0
    assert store.overview()["counts"]["events"] == 0


def test_replay_real_postgres_is_stable_read_only_and_detects_exact_damage(store):
    first = store.ingest(fetcher([event("10"), event("2")]))
    before = store.overview()["counts"]
    report = store.replay([str(first["id"])])
    assert report["status"] == "consistent"
    assert report["counts"]["retained_events"] == 2
    assert [row["event_id"] for row in report["events"]] == ["2", "10"]
    assert report["evidence_sha256"] == store.replay([str(first["id"])])["evidence_sha256"]
    assert store.overview()["counts"] == before
    # Damage is introduced only into the isolated disposable test database.
    with psycopg.connect(store.database_url) as conn:
        conn.execute("UPDATE flux_public_silver SET repository='damaged/repo' WHERE event_id='2'")
        conn.execute("DELETE FROM flux_public_silver WHERE event_id='10'")
    damaged = store.replay([str(first["id"])])
    assert damaged["status"] == "differences"
    assert damaged["counts"]["affected_events"] == 2
    assert damaged["evidence_sha256"] != report["evidence_sha256"]
    differences = {row["event_id"]: row["differences"] for row in damaged["events"]}
    assert differences["2"] == [
        {"field": "repository", "expected": "isolated-test/repository", "actual": "damaged/repo"}
    ]
    assert differences["10"] == [{"field": "silver_presence", "expected": True, "actual": False}]
    assert store.event("2")["repository"] == "damaged/repo"  # Audit never repairs or writes.


def test_replay_actual_duplicate_and_conflict_receipts_keep_provenance(store):
    first = store.ingest(fetcher([event()]))
    allow_next_run(store)
    duplicate = store.ingest(fetcher([event()]))
    allow_next_run(store)
    changed = event()
    changed["payload"] = {"action": "changed"}
    conflict = store.ingest(fetcher([changed]))
    report = store.replay([str(duplicate["id"]), str(conflict["id"])])
    assert report["status"] == "consistent"
    assert report["events"] == []
    assert report["counts"]["observed_duplicate_count"] == 1
    assert report["counts"]["conflicting_identity_receipts"] == 1
    assert str(first["id"]) not in {row["id"] for row in report["runs"]}


def test_drift_filtered_api_export_and_original_hash_use_real_store(store, tmp_path, monkeypatch):
    first = store.ingest(fetcher([event(str(i), "PushEvent") for i in range(1, 31)]))
    allow_next_run(store)
    second = store.ingest(fetcher([event(str(i), "CreateEvent") for i in range(31, 61)]))
    drift = store.drift(str(first["id"]), str(second["id"]))
    assert drift["status"] == "compared" and drift["js_bits"] == 1.0
    assert drift["baseline_n"] == drift["candidate_n"] == 30
    monkeypatch.setenv("DATABASE_URL", store.database_url)
    client = TestClient(create_app(tmp_path))
    assert client.get("/api/workspace/overview").json()["counts"]["events"] == 60
    filtered = client.get("/api/workspace/silver?event_type=CreateEvent&limit=5&offset=5").json()
    assert filtered["total"] == 30 and len(filtered["rows"]) == 5
    assert all(r["event_type"] == "CreateEvent" for r in filtered["rows"])
    assert client.get("/api/workspace/events/1").json()["raw"] == event("1")
    assert client.get("/api/workspace/events/9999").status_code == 404
    assert len(client.get("/api/workspace/export.csv").text.splitlines()) == 61
    assert (
        sum(r["events"] for r in client.get("/api/workspace/gold?group=event_type").json()["rows"])
        == 60
    )
