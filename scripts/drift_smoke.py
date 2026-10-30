"""Real HTTP/PostgreSQL DriftLab smoke. Writes fixtures ONLY to an explicit *_test DB.

Run a FluxLake API pointed at the same disposable database, then supply DATABASE_URL,
FLUXLAKE_URL and FLUXLAKE_API_TOKEN. The comparison is read-only; this harness writes
and removes its own synthetic source fixtures to make the check reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from fluxlake.drift_client import fetch_report
from fluxlake.drift_contracts import CompareRequest
from fluxlake.drift_scenarios import generate_scenario
from fluxlake.lake import canonical


def _post(origin, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(origin + "/drift/compare", data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(262145)
    except urllib.error.HTTPError as error:
        return error.code, error.read(4096)


def smoke(manifest: Path | None = None) -> dict:
    url = os.environ["DATABASE_URL"]
    database = conninfo_to_dict(url).get("dbname", "")
    if not database.endswith("_test"):
        raise ValueError("Smoke fixtures require an explicitly disposable *_test database")
    origin = os.getenv("FLUXLAKE_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.environ["FLUXLAKE_API_TOKEN"]
    prefix = "driftsmoke-" + uuid.uuid4().hex + "-"
    _, baseline, candidate = generate_scenario("amount_shift", seed=20261030, samples=300)
    keys = [prefix + str(event.index) for event in baseline + candidate]
    with psycopg.connect(url, autocommit=True) as writer:
        try:
            ranges = []
            for events in (baseline, candidate):
                with writer.transaction():
                    with writer.cursor() as cursor:
                        cursor.executemany(
                            "INSERT INTO transactions(id,amount_minor,currency,status,attributes) "
                            "VALUES (%s,%s,%s,%s,'{\"synthetic\":true}')",
                            [
                                (
                                    prefix + str(event.index),
                                    event.amount_minor,
                                    event.currency,
                                    event.status,
                                )
                                for event in events
                            ],
                        )
                start, end = writer.execute(
                    "SELECT min(id),max(id) FROM transaction_outbox WHERE aggregate_id=ANY(%s)",
                    ([prefix + str(event.index) for event in events],),
                ).fetchone()
                ranges.append({"start": start, "end": end})
            request = CompareRequest.model_validate({"baseline": ranges[0], "candidate": ranges[1]})
            before = writer.execute(
                "SELECT id,processed_at,data::text FROM transaction_outbox WHERE aggregate_id=ANY(%s) "
                "ORDER BY id",
                (keys,),
            ).fetchall()
            local_before = manifest.read_bytes() if manifest else None
            report = fetch_report(origin, token, request)
            assert report.disposition == "effect_detected"
            assert all(group.amount_effect_detected for group in report.currencies)
            assert not report.currency_mix.effect_detected
            assert report.source_snapshot.read_only
            assert report.baseline.observed_rows == report.candidate.observed_rows == 300
            assert fetch_report(origin, token, request).fingerprint == report.fingerprint
            status, _ = _post(origin, request.model_dump_json().encode())
            assert status == 401
            status, _ = _post(origin, b"x" * 4097, token)
            assert status == 413
            marker = "DO-NOT-ECHO-PRIVATE-BODY"
            status, body = _post(origin, json.dumps({"private": marker}).encode(), token)
            assert status == 422 and marker.encode() not in body
            command = [
                sys.executable,
                "-m",
                "fluxlake.cli",
                "drift",
                "--url",
                origin,
                "--baseline",
                f"{ranges[0]['start']}:{ranges[0]['end']}",
                "--candidate",
                f"{ranges[1]['start']}:{ranges[1]['end']}",
            ]
            cli = subprocess.run(command, capture_output=True, text=True, check=False)
            assert cli.returncode == 0, "Authenticated CLI did not complete"
            assert json.loads(cli.stdout)["fingerprint"] == report.fingerprint
            after = writer.execute(
                "SELECT id,processed_at,data::text FROM transaction_outbox WHERE aggregate_id=ANY(%s) "
                "ORDER BY id",
                (keys,),
            ).fetchall()
            assert before == after
            if manifest:
                assert manifest.read_bytes() == local_before
            return {
                "synthetic": True,
                "http": "actual running API, authenticated HTTP and CLI",
                "algorithm": report.algorithm,
                "scope": report.scope,
                "source_snapshot": report.source_snapshot.model_dump(),
                "request": request.model_dump(),
                "fingerprint": report.fingerprint,
                "baseline": report.baseline.model_dump(),
                "candidate": report.candidate.model_dump(),
                "currencies": [group.model_dump() for group in report.currencies],
                "currency_mix": report.currency_mix.model_dump(),
                "disposition": report.disposition,
                "source_rows_and_acknowledgements_unchanged": True,
                "projection_manifest_unchanged": True if manifest else "not checked by harness",
                "manifest_sha256": hashlib.sha256(local_before).hexdigest() if manifest else None,
                "anonymous": 401,
                "oversized_body": 413,
                "redacted_validation": 422,
                "cli_fingerprint_matches": True,
            }
        finally:
            writer.execute("DELETE FROM transactions WHERE id=ANY(%s)", (keys,))
            writer.execute("DELETE FROM transaction_outbox WHERE aggregate_id=ANY(%s)", (keys,))
            writer.execute("DELETE FROM transaction_versions WHERE aggregate_id=ANY(%s)", (keys,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = smoke(args.manifest)
    if args.output:
        args.output.write_bytes(canonical(result) + b"\n")
    print(
        json.dumps(
            {
                "disposition": result["disposition"],
                "fingerprint": result["fingerprint"],
                "source_unchanged": result["source_rows_and_acknowledgements_unchanged"],
                "projection_unchanged": result["projection_manifest_unchanged"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
