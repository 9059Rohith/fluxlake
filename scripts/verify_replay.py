"""Verify bounded hosted replay against actual retained public acquisitions."""

import argparse
import hashlib
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from fluxlake.workspace import canonical


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://rohith-fluxlake.vercel.app")
    parser.add_argument("--output", default="evidence/replay-verification.json")
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, timeout=60) as client:
        before = client.get("/api/workspace/overview").raise_for_status().json()["counts"]
        retained = client.get("/api/workspace/runs").raise_for_status().json()["rows"][:2]
        params = [("run", row["id"]) for row in retained]
        real_ms, fingerprints = [], []
        for _ in range(3):
            began = time.perf_counter()
            response = client.get("/api/workspace/replay", params=params).raise_for_status()
            real_ms.append((time.perf_counter() - began) * 1000)
            actual = response.json()
            assert actual["status"] == "consistent"
            assert response.headers["cache-control"] == "no-store"
            assert "unsafe-inline" not in response.headers["content-security-policy"]
            fingerprint = actual.pop("evidence_sha256")
            actual.pop("source_snapshot")
            assert hashlib.sha256(canonical(actual)).hexdigest() == fingerprint
            fingerprints.append(fingerprint)
        assert len(set(fingerprints)) == 1
        exported = client.get("/api/workspace/replay", params=[*params, ("download", "true")])
        assert "attachment" in exported.headers["content-disposition"]
        assert exported.json()["evidence_sha256"] == fingerprints[0]
        assert client.get("/api/workspace/replay?run=not-uuid").status_code == 422
        assert client.get("/api/workspace/replay", params=[params[0]] * 3).status_code == 422
        assert client.get("/api/workspace/replay", params=[params[0]] * 2).status_code == 422
        assert (
            client.get("/api/workspace/replay?run=00000000-0000-0000-0000-000000000000").status_code
            == 404
        )
        for path in ("/api/workspace/ingest", "/api/workspace/migrate", "/api/workspace/agent"):
            assert client.post(path, content="[" * 5000).status_code == 401
        assert client.get("/workspace/replay").status_code == 200
        after = client.get("/api/workspace/overview").raise_for_status().json()["counts"]
        assert before == after
    result = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.url,
        "actual_public_api": {
            "label": "Real retained GitHub acquisition evidence; HTTP latency includes network and database",
            "selected_runs": [row["id"] for row in retained],
            "counts": actual["counts"],
            "repeats": 3,
            "median_ms": statistics.median(real_ms),
            "max_ms": max(real_ms),
            "stable_evidence_sha256": fingerprints[0],
            "stored_counts_unchanged": before == after,
        },
        "download_and_bounds_verified": True,
        "private_mutations_anonymously_denied": True,
    }
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
