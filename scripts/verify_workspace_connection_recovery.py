"""Verify real isolated PostgreSQL recovery and uncertain-commit behavior."""

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from unittest.mock import patch

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from benchmark_archive_replay import (
    ARCHIVE_URL,
    archive_digest,
    isolated_postgres,
    select_cohort,
    workspace_diagnostics,
)
from fluxlake.workspace import PublicWorkspace, WorkspaceUnavailable

ROOT = Path(__file__).resolve().parents[1]


class RecoverySignal(logging.Handler):
    def __init__(self, failed):
        super().__init__()
        self.failed = failed

    def emit(self, record):
        diagnostic = getattr(record, "workspace_diagnostic", {})
        if diagnostic.get("phase") == "connect" and diagnostic.get("retrying"):
            self.failed.set()


class LostCommitAcknowledgement:
    """Commit to real PostgreSQL, then deliberately lose the client acknowledgement."""

    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        return self

    def __exit__(self, error_type, error, trace):
        if error_type:
            return self.connection.__exit__(error_type, error, trace)
        self.connection.commit()
        self.connection.close()
        raise psycopg.OperationalError("Controlled acknowledgement loss after a real commit")


def verify(cluster, batches):
    store = PublicWorkspace(cluster.dsn)
    with psycopg.connect(cluster.dsn) as conn:
        conn.execute((ROOT / "sql/workspace.sql").read_text(encoding="utf-8"))

    # Gracefully stop only the postmaster owned by this disposable cluster.
    cluster.close()
    failed = Event()
    signal = RecoverySignal(failed)
    recovered_body_calls = []

    def recovered_source():
        recovered_body_calls.append(1)
        return batches[0].events, {}

    logger = logging.getLogger("fluxlake.workspace")
    logger.addHandler(signal)
    with workspace_diagnostics() as recovery_diagnostics:
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                writer = pool.submit(
                    store._publish,
                    recovered_source,
                    source_url=ARCHIVE_URL,
                    enforce_poll_interval=False,
                )
                if not failed.wait(10):
                    raise RuntimeError("The unavailable-server connection was not observed")
                cluster.start()
                first = writer.result(timeout=20)
        finally:
            logger.removeHandler(signal)
    assert first["inserted"] == len(batches[0].events)
    assert len(recovered_body_calls) == 1
    assert recovery_diagnostics and all(row["phase"] == "connect" for row in recovery_diagnostics)
    with psycopg.connect(cluster.dsn) as conn:
        assert conn.execute("SELECT count(*) FROM public.flux_public_runs").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM public.flux_public_silver").fetchone() == (100,)

    original_connect = psycopg.connect
    connects, body_calls = [], []

    def uncertain_connect(*args, **kwargs):
        connects.append(1)
        return LostCommitAcknowledgement(original_connect(*args, **kwargs))

    def source():
        body_calls.append(1)
        return batches[1].events, {}

    with workspace_diagnostics() as commit_diagnostics:
        with patch("fluxlake.workspace.psycopg.connect", uncertain_connect):
            try:
                store._publish(
                    source,
                    source_url=ARCHIVE_URL,
                    enforce_poll_interval=False,
                )
            except WorkspaceUnavailable as error:
                assert error.diagnostic["phase"] == "commit"
            else:
                raise AssertionError("Expected acknowledgement loss to fail at the client")
    assert len(connects) == len(body_calls) == 1
    assert commit_diagnostics[-1]["phase"] == "commit" and not commit_diagnostics[-1]["retrying"]
    with original_connect(cluster.dsn) as conn:
        assert conn.execute("SELECT count(*) FROM public.flux_public_runs").fetchone() == (2,)
        assert conn.execute("SELECT count(*) FROM public.flux_public_silver").fetchone() == (200,)

    settings = conninfo_to_dict(cluster.dsn)
    settings["password"] = "deliberately-invalid-password"
    with workspace_diagnostics() as authentication_diagnostics:
        try:
            with PublicWorkspace(make_conninfo(**settings)).connection():
                raise AssertionError("Invalid authentication entered the caller body")
        except WorkspaceUnavailable as error:
            assert error.diagnostic["attempt"] == 1
    assert len(authentication_diagnostics) == 1
    assert not authentication_diagnostics[0]["retrying"]
    return {
        "unavailable_to_available": {
            "diagnostics": recovery_diagnostics,
            "persisted_events": 100,
            "publication_receipts": 1,
            "body_calls": len(recovered_body_calls),
        },
        "controlled_lost_acknowledgement": {
            "fault": "Real PostgreSQL commit succeeds, then client wrapper raises acknowledgement loss",
            "diagnostics": commit_diagnostics,
            "body_calls": len(body_calls),
            "connection_calls": len(connects),
            "total_persisted_events": 200,
            "total_publication_receipts": 2,
        },
        "real_authentication_failure": {"diagnostics": authentication_diagnostics, "attempts": 1},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evidence/workspace-connection-recovery.json"
    )
    args = parser.parse_args()
    source_sha = archive_digest(args.archive)
    batches, _ = select_cohort(args.archive, 200)
    with isolated_postgres(args.postgres_bin) as (cluster, _):
        result = verify(cluster, batches)
    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "archive_sha256": source_sha,
        **result,
    }
    encoded = json.dumps(report, indent=2) + "\n"
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")


if __name__ == "__main__":
    main()
