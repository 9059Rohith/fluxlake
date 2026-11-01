"""Verify the actual public deployment without creating fixture data or disclosing secrets."""

import argparse
import csv
import hashlib
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

from fluxlake.workspace import canonical
from fluxlake.workspace_web import PAGES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://rohith-fluxlake.vercel.app")
    parser.add_argument("--output", default="evidence/workspace-live.json")
    args = parser.parse_args()
    checks = []

    def get(path, expected=200):
        response = httpx.get(args.url + path, timeout=60)
        assert response.status_code == expected, (path, response.status_code)
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("cache-control") == "no-store"
        checks.append({"path": path, "status": response.status_code})
        return response

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda page: get("/workspace/" + page), PAGES))
    overview = get("/api/workspace/overview").json()
    counts = overview["counts"]
    assert counts["events"] > 0 and counts["events"] == counts["bronze_events"]
    assert sum(t["events"] for t in overview["event_types"]) == counts["events"]
    silver = get("/api/workspace/silver?limit=5").json()
    assert len(silver["rows"]) == min(5, counts["events"])
    bronze = get("/api/workspace/bronze?limit=5").json()
    assert bronze["total"] == silver["total"]
    observed = silver["rows"][0]
    detail = get("/api/workspace/events/" + observed["event_id"]).json()
    assert detail["raw"]["public"] is True
    assert hashlib.sha256(canonical(detail["raw"])).hexdigest() == detail["sha256"]
    filtered = get("/api/workspace/silver?q=" + observed["event_id"]).json()
    assert any(r["event_id"] == observed["event_id"] for r in filtered["rows"])
    typed = get("/api/workspace/silver?event_type=" + observed["event_type"]).json()
    assert all(r["event_type"] == observed["event_type"] for r in typed["rows"])
    gold = get("/api/workspace/gold?group=event_type").json()
    assert sum(r["events"] for r in gold["rows"]) == counts["events"]
    schema = get("/api/workspace/schema").json()
    assert any(r["path"] == "actor.login" and r["value_type"] == "string" for r in schema["rows"])
    quarantine = get("/api/workspace/quarantine").json()
    runs = get("/api/workspace/runs").json()
    assert sum(r["inserted"] for r in runs["rows"]) == counts["events"]
    drift = get("/api/workspace/drift").json()
    if drift["status"] in {"compared", "insufficient_samples"}:
        assert 0 <= drift["js_bits"] <= 1
        assert sum(r["baseline"] for r in drift["rows"]) == drift["baseline_n"]
        assert sum(r["candidate"] for r in drift["rows"]) == drift["candidate_n"]
    sources = get("/api/workspace/sources").json()
    exported = list(csv.DictReader(io.StringIO(get("/api/workspace/export.csv").text)))
    assert len(exported) == min(counts["events"], 1000)
    status = get("/api/workspace/agent/status").json()
    get("/demo/summary", 410)
    for path in (
        "/transactions",
        "/gold",
        "/schema",
        "/quarantine",
        "/metrics",
        "/pipeline",
        "/openapi.json",
    ):
        get(path, 401)
    for path in ("/api/workspace/ingest", "/api/workspace/agent", "/api/workspace/migrate"):
        r = httpx.post(args.url + path, content="[" * 5000, timeout=30)
        assert r.status_code == 401
        checks.append({"path": path, "method": "POST anonymous malformed body", "status": 401})
    private_token = os.getenv("FLUXLAKE_API_TOKEN")
    if private_token:
        r = httpx.get(
            args.url + "/pipeline", headers={"Authorization": "Bearer " + private_token}, timeout=30
        )
        assert r.status_code == 200
        checks.append({"path": "/pipeline", "method": "GET authenticated", "status": 200})
        if not status["configured"]:
            r = httpx.post(
                args.url + "/api/workspace/agent",
                headers={"Authorization": "Bearer " + private_token},
                json={"question": "Summarize the observed event sample."},
                timeout=30,
            )
            assert r.status_code == 503 and "not configured" in r.text
            checks.append(
                {
                    "path": "/api/workspace/agent",
                    "method": "POST authenticated missing-provider",
                    "status": 503,
                }
            )
    evidence = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.url,
        "page_count": len(PAGES),
        "checks": sorted(checks, key=lambda row: row["path"]),
        "actual_counts": counts,
        "source": sources["sources"][0],
        "latest_run": overview["latest_run"],
        "drift": drift,
        "quarantine_count": len(quarantine["rows"]),
        "evidence_event_id": detail["event_id"],
        "canonical_hash_verified": True,
        "csv_rows": len(exported),
        "provider": status,
        "limitations": [
            "Incomplete operator-acquired GitHub sample",
            "No live provider verification without authorized credentials",
            "HTTP smoke is separate from database fault/concurrency validation; see workspace-postgres-junit.xml",
        ],
    }
    Path(args.output).write_text(
        json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "checks": len(checks),
                "pages": len(PAGES),
                "actual_events": counts["events"],
                "drift_status": drift["status"],
                "provider_configured": status["configured"],
                "evidence": args.output,
            }
        )
    )


if __name__ == "__main__":
    main()
