"""Publish, interrupt, recover and redeliver a pinned GH Archive cohort on local PostgreSQL."""

import argparse
import gzip
import hashlib
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import batched
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from fluxlake.workspace import PublicWorkspace, WorkspaceUnavailable, normalize

ARCHIVE_URL = "https://data.gharchive.org/2025-01-01-15.json.gz"
ARCHIVE_BYTES = 72_578_615
ARCHIVE_MD5 = "432312db553b5e96f65022444dd82e8b"
BATCH_ROWS = 100
BATCH_BYTES = 1_500_000


@dataclass
class Batch:
    events: list[dict]
    source_lines_sha256: str


def archive_digest(path):
    if path.stat().st_size != ARCHIVE_BYTES:
        raise ValueError("The archive byte count differs from the pinned GH Archive object")
    with path.open("rb") as source:
        md5 = hashlib.file_digest(source, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()
    if md5 != ARCHIVE_MD5:
        raise ValueError("The archive differs from the GH Archive object MD5")
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def canonical_bytes(value):
    """Independent serialization of the publisher's documented canonical JSON contract."""
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def select_cohort(path, limit):
    batches, seen, skipped = [], set(), Counter()
    events, lines, payload_bytes = [], hashlib.sha256(), 0
    with gzip.open(path, "rb") as source:
        for line_number, line in enumerate(source, 1):
            event = json.loads(line)
            try:
                event_id = normalize(event)[0]
                body = canonical_bytes(event)
            except (ValueError, TypeError, RecursionError):
                skipped["source_contract"] += 1
                continue
            if len(body) > 65536:
                skipped["record_exceeds_64_kib"] += 1
                continue
            if event_id in seen:
                skipped["repeated_archive_identity"] += 1
                continue
            if len(events) == BATCH_ROWS or payload_bytes + len(body) > BATCH_BYTES:
                batches.append(Batch(events, lines.hexdigest()))
                events, lines, payload_bytes = [], hashlib.sha256(), 0
            seen.add(event_id)
            events.append(event)
            lines.update(line)
            payload_bytes += len(body)
            if len(seen) == limit:
                batches.append(Batch(events, lines.hexdigest()))
                return batches, {"archive_lines_scanned": line_number, "skipped": dict(skipped)}
    raise ValueError(f"Only {len(seen)} eligible unique public events in the pinned archive")


def wait_for_postgres(dsn, process):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("The isolated PostgreSQL process exited during startup")
        try:
            with psycopg.connect(dsn) as conn:
                return conn.execute("SELECT pg_postmaster_start_time()").fetchone()[0]
        except psycopg.OperationalError:
            time.sleep(0.1)
    raise RuntimeError("The isolated PostgreSQL server did not become ready")


@dataclass
class LocalPostgres:
    bin_dir: Path
    work_dir: Path
    port: int
    dsn: str
    process: subprocess.Popen | None = None

    @property
    def data_dir(self):
        return self.work_dir / "database"

    @property
    def log(self):
        return self.work_dir / "postgres.log"

    def program(self, name):
        return self.bin_dir / (name + ".exe" if os.name == "nt" else name)

    def start(self):
        with self.log.open("ab") as output:
            self.process = subprocess.Popen(
                [
                    self.program("postgres"),
                    "-D",
                    self.data_dir,
                    "-p",
                    str(self.port),
                    "-h",
                    "127.0.0.1",
                    "-k",
                    "",
                ],
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        return wait_for_postgres(self.dsn, self.process)

    def close(self):
        if self.process is not None and self.process.poll() is None:
            try:
                subprocess.run(
                    [
                        self.program("pg_ctl"),
                        "stop",
                        "-D",
                        self.data_dir,
                        "-m",
                        "fast",
                        "-w",
                        "-t",
                        "10",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=15,
                )
                self.process.wait(timeout=5)
            finally:
                if self.process.poll() is None:
                    self.process.kill()
                    self.process.wait(timeout=5)


@contextmanager
def isolated_postgres(bin_dir):
    password = secrets.token_urlsafe(32)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    scratch = Path(__file__).resolve().parents[1] / ".downloads"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fluxlake-archive-", dir=scratch) as work:
        work_dir = Path(work).resolve()
        if work_dir.parent != scratch.resolve():
            raise RuntimeError("Unexpected disposable PostgreSQL directory")
        dsn = make_conninfo(
            host="127.0.0.1",
            port=port,
            dbname="postgres",
            user="postgres",
            password=password,
            connect_timeout=1,
        )
        cluster = LocalPostgres(bin_dir.resolve(), work_dir, port, dsn)
        password_file = work_dir / "password"
        with password_file.open("x", encoding="utf-8") as file:
            file.write(password + "\n")
        try:
            result = subprocess.run(
                [
                    cluster.program("initdb"),
                    "-D",
                    cluster.data_dir,
                    "--username=postgres",
                    "--auth=scram-sha-256",
                    "--locale=C",
                    "--encoding=UTF8",
                    "--pwfile",
                    password_file,
                ],
                capture_output=True,
                timeout=60,
            )
            if result.returncode:
                raise RuntimeError(
                    f"Disposable PostgreSQL initialization failed ({result.returncode})"
                )
        finally:
            password_file.unlink()
        try:
            yield cluster, cluster.start()
        finally:
            cluster.close()


def publish(store, batch):
    return store._publish(
        lambda: (batch.events, {}), source_url=ARCHIVE_URL, enforce_poll_interval=False
    )


def publisher_inventory(dsn):
    with psycopg.connect(dsn) as conn:
        row = conn.execute("""SELECT
            (SELECT count(*) FROM flux_public_bronze),
            (SELECT count(*) FROM flux_public_silver),
            (SELECT count(*) FROM flux_public_runs),
            (SELECT count(*) FROM flux_public_quarantine),
            (SELECT coalesce(sum(observations),0) FROM flux_public_schema)""").fetchone()
    return dict(
        zip(("bronze", "silver", "runs", "quarantine", "schema_observations"), row, strict=True)
    )


def crash_during_silver(cluster, store, batch, first_started):
    dsn = cluster.dsn
    with psycopg.connect(dsn) as conn:
        conn.execute("""CREATE FUNCTION archive_test_pause_silver() RETURNS trigger LANGUAGE plpgsql
            AS $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM flux_public_bronze b JOIN flux_public_runs r
                               ON r.id=b.run_id WHERE r.status='running') THEN
                    RAISE EXCEPTION 'expected pending bronze before silver';
                END IF;
                PERFORM pg_sleep(30);
                RETURN NEW;
            END $$""")
        conn.execute("""CREATE TRIGGER archive_test_pause BEFORE INSERT ON flux_public_silver
            FOR EACH STATEMENT EXECUTE FUNCTION archive_test_pause_silver()""")

    with (
        ThreadPoolExecutor(max_workers=1) as executor,
        closing(psycopg.connect(dsn, autocommit=True)) as observer,
    ):
        writer = executor.submit(publish, store, batch)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if observer.execute("""SELECT 1 FROM pg_stat_activity
                WHERE wait_event='PgSleep' AND query LIKE 'INSERT INTO public.flux_public_silver%'""").fetchone():
                break
            if writer.done():
                raise RuntimeError("The archive publisher ended before the silver insert pause")
            time.sleep(0.02)
        else:
            raise RuntimeError("The in-flight silver statement was not observed")
        interrupted = time.perf_counter()
        cluster.process.kill()
        exit_code = cluster.process.wait(timeout=10)
        try:
            writer.result(timeout=15)
        except WorkspaceUnavailable:
            pass
        else:
            raise RuntimeError("The interrupted writer did not report a database failure")

    expected_exit = 1 if os.name == "nt" else -9
    if exit_code != expected_exit:
        raise RuntimeError(
            f"Expected abrupt process termination {expected_exit}, observed {exit_code}"
        )
    restarted = cluster.start()
    elapsed = round((time.perf_counter() - interrupted) * 1000, 3)
    if restarted <= first_started:
        raise RuntimeError("PostgreSQL start timestamp did not advance")
    logs = cluster.log.read_text(encoding="utf-8", errors="replace")
    if "automatic recovery in progress" not in logs:
        raise RuntimeError("The restarted database did not report automatic WAL recovery")
    if "canceling statement due to statement timeout" in logs:
        raise RuntimeError("The writer reached its statement deadline before the database kill")
    return {
        "termination": "TerminateProcess" if os.name == "nt" else "SIGKILL",
        "exit_code": exit_code,
        "observed_statement": "silver INSERT paused after the trigger confirmed pending bronze rows",
        "writer_result": "WorkspaceUnavailable",
        "automatic_wal_recovery_observed": True,
        "original_postmaster_started_at": first_started.isoformat(),
        "restarted_postmaster_started_at": restarted.isoformat(),
        "kill_to_sql_ready_ms": elapsed,
    }


def verify_manifest(dsn, batches, run_ids):
    """Verify every ID, body hash, byte count, projected field and original run via SQL."""
    expected = {
        event["id"]: (event, str(run_id))
        for batch, run_id in zip(batches, run_ids, strict=True)
        for event in batch.events
    }
    manifest = hashlib.sha256()
    types = Counter()
    canonical_total = 0
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        with conn.cursor(name="archive_inventory") as cursor:
            cursor.itersize = 200
            cursor.execute("""SELECT b.event_id, b.raw, b.sha256, b.bytes, b.run_id,
                s.event_type,s.repository,s.actor,s.occurred_at,s.action,s.organization,s.run_id
                FROM flux_public_bronze b FULL JOIN flux_public_silver s USING(event_id)
                ORDER BY b.event_id COLLATE "C"
                """)
            for row in cursor:
                event_id, raw, stored_hash, stored_bytes, bronze_run, *silver = row
                event, run_id = expected.pop(event_id)
                body = canonical_bytes(event)
                fingerprint = hashlib.sha256(body).hexdigest()
                assert canonical_bytes(raw) == body
                assert (stored_hash, stored_bytes, str(bronze_run)) == (
                    fingerprint,
                    len(body),
                    run_id,
                )
                organization = event.get("org")
                assert silver == [
                    event["type"],
                    event["repo"]["name"],
                    event["actor"]["login"],
                    datetime.fromisoformat(event["created_at"]),
                    event["payload"].get("action"),
                    organization.get("login") if isinstance(organization, dict) else None,
                    bronze_run,
                ]
                manifest.update(f"{event_id}\t{fingerprint}\t{len(body)}\n".encode())
                types[event["type"]] += 1
                canonical_total += len(body)
        assert not expected
        sql_types = dict(
            conn.execute("SELECT event_type,count(*) FROM flux_public_silver GROUP BY 1")
        )
        assert sql_types == dict(types)
    return {
        "identity_sha256": manifest.hexdigest(),
        "canonical_bytes": canonical_total,
        "event_types": dict(sorted(types.items())),
    }


def duration(started, rows):
    seconds = time.perf_counter() - started
    return {"seconds": round(seconds, 6), "events_per_second": round(rows / seconds, 2)}


def benchmark(batches, rows, migration_path, postgres_bin):
    with isolated_postgres(postgres_bin) as (cluster, first_started):
        dsn = cluster.dsn
        store = PublicWorkspace(dsn)
        with psycopg.connect(dsn) as conn:
            conn.execute(migration_path.read_text(encoding="utf-8"))
            server = conn.execute(
                "SELECT version(), current_setting('fsync'), current_setting('synchronous_commit')"
            ).fetchone()
        assert server[1:] == ("on", "on")
        first = publish(store, batches[0])
        assert first["inserted"] == len(batches[0].events)
        before_crash = publisher_inventory(dsn)
        failure = crash_during_silver(cluster, store, batches[1], first_started)
        after_crash = publisher_inventory(dsn)
        assert before_crash == after_crash
        verify_manifest(dsn, batches[:1], [first["id"]])
        with psycopg.connect(dsn) as conn:
            conn.execute("DROP TRIGGER archive_test_pause ON flux_public_silver")
            conn.execute("DROP FUNCTION archive_test_pause_silver()")

        receipts = [first]
        retry_started = time.perf_counter()
        retry = publish(store, batches[1])
        retry_ms = round((time.perf_counter() - retry_started) * 1000, 3)
        assert retry["inserted"] == len(batches[1].events)
        receipts.append(retry)
        failure.update(
            {
                "before_crash": before_crash,
                "after_restart": after_crash,
                "retry_source_lines_sha256": batches[1].source_lines_sha256,
                "retry_published_events": retry["inserted"],
                "retry_commit_ms": retry_ms,
            }
        )
        print(
            f"Observed database kill and WAL recovery; retried {retry['inserted']} real events",
            flush=True,
        )

        started = time.perf_counter()
        receipts.extend(publish(store, batch) for batch in batches[2:])
        steady_rows = rows - sum(len(batch.events) for batch in batches[:2])
        publication = {"events": steady_rows, **duration(started, steady_rows)}
        assert all(
            row["status"] == "succeeded"
            and row["source_url"] == ARCHIVE_URL
            and row["inserted"] == len(batch.events)
            and row["duplicates"] == row["quarantined"] == 0
            for row, batch in zip(receipts, batches, strict=True)
        )
        run_ids = [row["id"] for row in receipts]
        manifest = verify_manifest(dsn, batches, run_ids)
        before_replay = publisher_inventory(dsn)
        assert before_replay["bronze"] == before_replay["silver"] == rows
        print(f"Published and independently verified {rows:,} unique archive events", flush=True)

        started = time.perf_counter()
        redeliveries = [publish(store, batch) for batch in batches]
        replay = duration(started, rows)
        assert all(
            row["status"] == "succeeded"
            and row["inserted"] == row["quarantined"] == 0
            and row["duplicates"] == len(batch.events)
            for row, batch in zip(redeliveries, batches, strict=True)
        )
        after_replay = publisher_inventory(dsn)
        assert after_replay == {**before_replay, "runs": before_replay["runs"] + len(batches)}
        assert verify_manifest(dsn, batches, run_ids) == manifest
        replay.update(
            {
                "matching_duplicates": rows,
                "new_events": 0,
                "before": before_replay,
                "after": after_replay,
            }
        )

        started = time.perf_counter()
        audits, count = [], 0
        for run_pair in batched(run_ids, 2):
            report = store.replay([str(run_id) for run_id in run_pair])
            assert report["status"] == "consistent" and report["counts"]["affected_events"] == 0
            count += report["counts"]["retained_events"]
            audits.append(report["evidence_sha256"])
        audit = duration(started, count)
        assert count == rows and publisher_inventory(dsn) == after_replay
        audit.update(
            {
                "events_reconstructed": count,
                "requests": len(audits),
                "differences": 0,
                "report_fingerprints_sha256": hashlib.sha256(
                    "\n".join(audits).encode()
                ).hexdigest(),
            }
        )
        return {
            "postgres_version": server[0],
            "fsync": server[1],
            "synchronous_commit": server[2],
            "batch_count": len(batches),
            "unique_events": rows,
            "publication": publication,
            "crash_and_restart": failure,
            "redelivery": replay,
            "read_only_audit": audit,
            "identity_verification": manifest,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Pinned 2025-01-01-15.json.gz from GH Archive")
    parser.add_argument(
        "--limit", type=int, default=20_000, choices=range(200, 30_001), metavar="200..30000"
    )
    parser.add_argument(
        "--postgres-bin",
        type=Path,
        required=True,
        help="Directory containing local PostgreSQL binaries",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive_sha256 = archive_digest(args.archive)
    batches, selection = select_cohort(args.archive, args.limit)
    print(
        f"Verified pinned gzip; selected {args.limit:,} actual events in {len(batches)} batches",
        flush=True,
    )
    result = benchmark(
        batches,
        args.limit,
        Path(__file__).resolve().parents[1] / "sql/workspace.sql",
        args.postgres_bin,
    )
    report = {
        "benchmark": "GH Archive isolated PostgreSQL publication and crash recovery",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "url": ARCHIVE_URL,
            "compressed_bytes": ARCHIVE_BYTES,
            "object_md5": ARCHIVE_MD5,
            "sha256": archive_sha256,
            "selection": "First unique admitted public events in archive order; payloads unmodified",
            **selection,
        },
        "environment": {
            "platform": platform.system(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "postgres_runtime": "disposable native PostgreSQL cluster",
        },
        **result,
        "timing_scope": "Single local run. Sequential batches with connection/transaction costs; excludes download, cohort selection and independent manifest scans. Hosted replay is separately bounded.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"unique_events": result["unique_events"], "output": str(args.output)}))


if __name__ == "__main__":
    if not __debug__:
        sys.exit("Run with assertions enabled so benchmark evidence cannot skip verification")
    main()
