"""Controlled test-only inputs; public replay only consumes retained PostgreSQL rows."""

import copy
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from fluxlake.replay import admit_identity, audit_publication
from fluxlake.workspace import canonical, normalize

RUN = "08d6d9b9-e6da-4bb9-82a0-a7a29ef689e8"
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def test_identity_reducer_rejects_changed_content_without_overwriting_original():
    state = {}
    assert admit_identity(state, "1", "a" * 64) == "accepted"
    assert admit_identity(state, "1", "a" * 64) == "duplicate"
    assert admit_identity(state, "1", "b" * 64) == "conflict"
    assert state == {"1": "a" * 64}


def evidence(identity="10"):
    raw = {
        "id": identity,
        "type": "PushEvent",
        "public": True,
        "created_at": "2026-11-01T00:00:00Z",
        "repo": {"name": "test/repo"},
        "actor": {"login": "actor"},
        "payload": {},
    }
    values = normalize(raw)
    silver = dict(
        zip(
            (
                "event_id",
                "event_type",
                "repository",
                "actor",
                "occurred_at",
                "action",
                "organization",
            ),
            values,
            strict=True,
        )
    )
    return (
        {
            "event_id": identity,
            "run_id": RUN,
            "raw": raw,
            "sha256": hashlib.sha256(canonical(raw)).hexdigest(),
            "bytes": len(canonical(raw)),
        },
        {**silver, "run_id": RUN},
    )


def receipt(**overrides):
    return {
        "id": RUN,
        "started_at": NOW,
        "status": "succeeded",
        "fetched": 1,
        "inserted": 1,
        "duplicates": 0,
        "quarantined": 0,
        "response_sha256": "f" * 64,
        **overrides,
    }


def test_replay_reconstructs_actual_evidence_without_mutation_and_is_deterministic():
    bronze, silver = zip(evidence("10"), evidence("2"), strict=True)
    args = ([receipt(fetched=2, inserted=2)], list(bronze), list(silver), [])
    before = copy.deepcopy(args)
    report = audit_publication(*args)
    assert args == before
    assert report["status"] == "consistent"
    assert [r["event_id"] for r in report["events"]] == ["2", "10"]
    assert report["controlled_redelivery"] == {
        "label": "Controlled in-memory second pass; not observed source deliveries",
        "accepted_first_pass": 2,
        "duplicates_second_pass": 2,
        "conflicts": 0,
        "state_unchanged": True,
    }
    reversed_report = audit_publication(args[0], list(reversed(bronze)), list(reversed(silver)), [])
    assert report == reversed_report
    assert len(report["evidence_sha256"]) == 64


def test_exact_hash_bytes_and_typed_publication_differences():
    bronze, silver = evidence()
    bronze["sha256"] = "0" * 64
    bronze["bytes"] += 1
    silver["repository"] = "wrong/repo"
    report = audit_publication([receipt()], [bronze], [silver], [])
    assert report["status"] == "differences"
    differences = {d["field"]: d for d in report["events"][0]["differences"]}
    assert set(differences) == {"sha256", "bytes", "repository"}
    assert differences["repository"] == {
        "field": "repository",
        "expected": "test/repo",
        "actual": "wrong/repo",
    }
    assert report["counts"]["affected_events"] == 1


def test_missing_silver_invalid_raw_and_silver_only_rows_are_visible():
    bronze, silver = evidence()
    report = audit_publication([receipt()], [bronze], [], [])
    assert report["events"][0]["differences"][0]["field"] == "silver_presence"
    report = audit_publication([receipt()], [], [silver], [])
    assert report["events"][0]["differences"][0]["field"] == "bronze_presence"
    bronze["raw"]["public"] = False
    report = audit_publication([receipt()], [bronze], [silver], [])
    assert any(d["field"] == "source_contract" for d in report["events"][0]["differences"])


def test_duplicate_and_conflict_receipts_do_not_invent_delivery_bodies():
    rejected = {
        "id": 1,
        "run_id": RUN,
        "event_id": "10",
        "sha256": "c" * 64,
        "reason": "Existing event identity has conflicting content",
    }
    report = audit_publication(
        [receipt(fetched=3, inserted=0, duplicates=2, quarantined=1)], [], [], [rejected]
    )
    assert report["status"] == "consistent"
    assert report["counts"]["observed_duplicate_count"] == 2
    assert report["counts"]["conflicting_identity_receipts"] == 1
    assert report["quarantine"][0]["classification"] == "conflicting_identity_receipt"
    assert "not retained" in " ".join(report["limitations"])
    assert report["events"] == []


def test_receipt_reconciliation_detects_missing_publication_and_count_errors():
    report = audit_publication([receipt(fetched=5)], [], [], [])
    assert {d["field"] for d in report["runs"][0]["differences"]} == {
        "inserted_bronze",
        "inserted_silver",
        "fetched_accounting",
    }
    assert report["status"] == "differences"


def test_empty_failed_run_is_auditable_without_claiming_source_success():
    report = audit_publication([receipt(status="failed", fetched=0, inserted=0)], [], [], [])
    assert report["runs"][0]["status"] == "failed"
    assert report["counts"]["retained_events"] == 0


def test_bounded_capacity_and_duplicate_identity_are_rejected():
    bronze, silver = evidence()
    with pytest.raises(ValueError):
        audit_publication([receipt()], [bronze] * 201, [], [])
    with pytest.raises(ValueError):
        audit_publication([receipt()], [bronze, bronze], [], [])
    with pytest.raises(ValueError):
        audit_publication([receipt()] * 3, [], [], [])
    bronze["raw"]["payload"] = {"large": "x" * 65536}
    with pytest.raises(ValueError):
        audit_publication([receipt()], [bronze], [silver], [])


def test_read_only_acquisition_checks_budget_before_transferring_raw(monkeypatch):
    from fluxlake.workspace import PublicWorkspace, WorkspaceUnavailable

    queries = []

    class Result:
        def __init__(self, data):
            self.data = data

        def fetchone(self):
            return self.data

        def fetchall(self):
            return self.data

    class Connection:
        def execute(self, sql, args=None):
            queries.append(sql)
            if "flux_public_runs" in sql:
                return Result([receipt()])
            if "pg_current_snapshot" in sql:
                return Result({"id": "1:2:", "captured_at": NOW})
            return Result({"events": 201, "total_bytes": 100, "largest": 10})

    @contextmanager
    def connection(write=False):
        assert write is False
        yield Connection()

    store = PublicWorkspace("unused")
    monkeypatch.setattr(store, "connection", connection)
    with pytest.raises(WorkspaceUnavailable, match="capacity"):
        store.replay([RUN])
    assert all(sql.lstrip().startswith("SELECT") for sql in queries)
    assert not any("SELECT b.*" in sql for sql in queries)


def test_replay_route_selection_download_and_private_boundary(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from fluxlake.api import create_app
    from fluxlake.workspace import PublicWorkspace

    monkeypatch.delenv("DATABASE_URL", raising=False)
    selected = []

    def replay(self, run_ids=None):
        selected.append(run_ids)
        return {"status": "consistent", "evidence_sha256": "a" * 64}

    monkeypatch.setattr(PublicWorkspace, "replay", replay)
    client = TestClient(create_app(tmp_path))
    response = client.get("/api/workspace/replay", params={"run": RUN, "download": "true"})
    assert response.status_code == 200
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="fluxlake-replay-evidence.json"'
    )
    assert selected == [[RUN]]
    assert client.get("/workspace/replay").status_code == 200
    assert client.get("/api/workspace/replay?run=not-uuid").status_code == 422
    assert client.get("/api/workspace/replay", params={"run": [RUN] * 3}).status_code == 422
    assert client.get("/api/workspace/replay", params={"run": [RUN] * 2}).status_code == 422
    assert client.post("/api/workspace/ingest").status_code in {401, 503}
