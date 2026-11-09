"""Reproduce portable public-source evidence in disposable local PostgreSQL."""

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient

from benchmark_archive_replay import (
    ARCHIVE_URL,
    archive_digest,
    isolated_postgres,
    publish,
    publisher_inventory,
    select_cohort,
)
from fluxlake.api import create_app
from fluxlake.replay_bundle import verify_bundle
from fluxlake.workspace import PublicWorkspace, canonical

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--postgres-bin", required=True, type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evidence/replay-bundle-verification.json"
    )
    args = parser.parse_args()
    source_digest = archive_digest(args.archive)
    batches, source_selection = select_cohort(args.archive, 200)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bundle_path = args.output.with_name("replay-bundle-archive.json")

    with isolated_postgres(args.postgres_bin) as (cluster, _):
        store = PublicWorkspace(cluster.dsn)
        with psycopg.connect(cluster.dsn) as conn:
            conn.execute((ROOT / "sql/workspace.sql").read_text(encoding="utf-8"))
        runs = [publish(store, batch) for batch in batches]
        selected = [str(row["id"]) for row in runs]
        before = publisher_inventory(cluster.dsn)
        with (
            tempfile.TemporaryDirectory(prefix="fluxlake-bundle-api-") as web_root,
            patch.dict(os.environ, {"DATABASE_URL": cluster.dsn}),
            TestClient(create_app(web_root)) as client,
        ):
            response = client.get(
                "/api/workspace/replay/bundle", params=[("run", value) for value in selected]
            )
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert "attachment" in response.headers["content-disposition"]
            exported = response.json()
            assert exported["evidence"]["bronze"][0]["raw"]["public"] is True
        verified = verify_bundle(exported)
        assert verified["publication_status"] == "consistent"
        assert verified["counts"]["retained_events"] == 200
        assert publisher_inventory(cluster.dsn) == before
        bundle_path.write_bytes(canonical(exported) + b"\n")
        offline = subprocess.run(
            [
                sys.executable,
                "-m",
                "fluxlake.replay_bundle",
                str(bundle_path),
                "--expected-sha256",
                exported["bundle_sha256"],
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        assert json.loads(offline.stdout) == verified
        # A real local publication discrepancy must be reproducible, not disguised as invalid JSON.
        identity = exported["evidence"]["silver"][0]["event_id"]
        with psycopg.connect(cluster.dsn) as conn:
            conn.execute(
                "UPDATE flux_public_silver SET actor='damage-probe' WHERE event_id=%s", (identity,)
            )
        damaged = store.replay(selected, bundle=True)
        assert verify_bundle(damaged)["publication_status"] == "differences"
        assert verify_bundle(damaged)["counts"]["affected_events"] == 1
        altered = copy.deepcopy(exported)
        altered["evidence"]["silver"][0]["actor"] = "tampered-export"
        try:
            verify_bundle(altered)
        except ValueError:
            tamper_rejected = True
        else:
            raise AssertionError("Edited evidence was accepted")

        # Existing integration tests write only into this newly initialized disposable cluster.
        environment = {**os.environ, "TEST_DATABASE_URL": cluster.dsn}
        junit = args.output.with_name("replay-bundle-junit.xml")
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=short", f"--junitxml={junit}"],
            cwd=ROOT,
            env=environment,
            check=True,
        )

    result = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Local disposable PostgreSQL; real historical archive inputs, not hosted release",
        "source_url": ARCHIVE_URL,
        "archive_sha256": source_digest,
        "source_selection": source_selection,
        "acquisitions": selected,
        "verification": verified,
        "public_download": {"status": response.status_code, "bytes": len(response.content)},
        "publisher_inventory_unchanged_after_export": before,
        "offline_cli_exit": offline.returncode,
        "edited_export_rejected": tamper_rejected,
        "controlled_database_damage_reproduced": {"affected_events": 1, "field": "actor"},
        "bundle_file": bundle_path.relative_to(ROOT).as_posix(),
        "suite_junit": junit.relative_to(ROOT).as_posix(),
        "disposable_cluster_removed": True,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
