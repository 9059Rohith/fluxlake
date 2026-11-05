"""Exercise the incremental PostgreSQL model on the verified GH Archive cohort."""

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from benchmark_archive_replay import (
    ARCHIVE_URL,
    archive_digest,
    isolated_postgres,
    publish,
    select_cohort,
)
from fluxlake.workspace import PublicWorkspace

ROOT = Path(__file__).resolve().parents[1]
MODEL_READ = "SELECT * FROM flux_analytics.hourly_mix ORDER BY utc_hour, event_type"
FULL_READ = """WITH hourly AS (
    SELECT date_trunc('hour', occurred_at, 'UTC') AS utc_hour, event_type,
           count(*) AS events, min(occurred_at) AS first_event, max(occurred_at) AS last_event
    FROM public.flux_public_silver GROUP BY 1, 2
)
SELECT *, round(events::numeric / sum(events) OVER (PARTITION BY utc_hour), 6) AS share,
          dense_rank() OVER (PARTITION BY utc_hour ORDER BY events DESC) AS type_rank
FROM hourly ORDER BY utc_hour, event_type"""


def refresh(conn, limit=32, *, rollback=False):
    with conn.transaction(force_rollback=rollback):
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SET LOCAL statement_timeout = '15s'")
        return conn.execute("SELECT * FROM flux_analytics.refresh_hourly(%s)", (limit,)).fetchone()


def hour(value):
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def event_time(event):
    return datetime.fromisoformat(event["created_at"]).astimezone(timezone.utc)


def python_totals(batches):
    groups = defaultdict(list)
    for batch in batches:
        for event in batch.events:
            timestamp = event_time(event)
            groups[(hour(timestamp), event["type"])].append(timestamp)
    return {
        key: (len(timestamps), min(timestamps), max(timestamps))
        for key, timestamps in groups.items()
    }


def latency(values):
    ordered = sorted(values)
    return {
        "samples": len(ordered),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 3),
        "max_ms": round(ordered[-1], 3),
    }


def read_cost(conn, query):
    plan = conn.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}").fetchone()[0][0]
    return {
        "server_execution_ms": plan["Execution Time"],
        "shared_hit_blocks": plan["Plan"]["Shared Hit Blocks"],
        "shared_read_blocks": plan["Plan"]["Shared Read Blocks"],
    }


def run(dsn, batches):
    store = PublicWorkspace(dsn)
    warm, arriving = batches[:-20], batches[-20:]
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute((ROOT / "sql/workspace.sql").read_text(encoding="utf-8"))
        conn.execute((ROOT / "sql/hourly_public_model.sql").read_text(encoding="utf-8"))
        version = conn.execute("SHOW server_version").fetchone()[0]
        warm_rows = sum(publish(store, batch)["inserted"] for batch in warm)
        assert warm_rows == sum(len(batch.events) for batch in warm)

        started = time.perf_counter()
        backfill = [refresh(conn) for _ in range(math.ceil(len(warm) / 32))]
        backfill_ms = (time.perf_counter() - started) * 1000
        assert sum(row[0] for row in backfill) == len(warm)
        assert sum(row[1] for row in backfill) == warm_rows
        before = conn.execute(MODEL_READ).fetchall()
        assert before == conn.execute(FULL_READ).fetchall()
        print(
            f"Applied {warm_rows:,} warm records in {len(backfill)} bounded refreshes", flush=True
        )

        first = publish(store, arriving[0])
        expected = first["inserted"]
        assert expected == len(arriving[0].events)
        assert refresh(conn, rollback=True)[1] == expected
        assert conn.execute(MODEL_READ).fetchall() == before
        assert conn.execute("SELECT count(*) FROM flux_analytics.applied_runs").fetchone()[
            0
        ] == len(warm)

        def worker(_):
            with psycopg.connect(dsn, autocommit=True) as session:
                return refresh(session)

        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent = list(pool.map(worker, range(2)))
        assert sorted((row[0], row[1]) for row in concurrent) == [(0, 0), (1, expected)]
        assert conn.execute(MODEL_READ).fetchall() == conn.execute(FULL_READ).fetchall()

        refresh_ms, publish_to_gold_ms = [], []
        maximum_time = max(
            event_time(event) for batch in [*warm, arriving[0]] for event in batch.events
        )
        late_events = earlier_hours = 0
        for batch in arriving[1:]:
            timestamps = [event_time(event) for event in batch.events]
            late_events += sum(timestamp < maximum_time for timestamp in timestamps)
            earlier_hours += sum(hour(timestamp) < hour(maximum_time) for timestamp in timestamps)
            maximum_time = max(maximum_time, *timestamps)
            started = time.perf_counter()
            receipt = publish(store, batch)
            published_at = time.perf_counter()
            assert receipt["inserted"] == len(batch.events)
            applied = refresh(conn)
            ready_at = time.perf_counter()
            assert applied[:2] == (1, len(batch.events))
            refresh_ms.append((ready_at - published_at) * 1000)
            publish_to_gold_ms.append((ready_at - started) * 1000)
            assert conn.execute(MODEL_READ).fetchall() == conn.execute(FULL_READ).fetchall()

        model = conn.execute(MODEL_READ).fetchall()
        assert {(hour(row[0]), row[1]): tuple(row[2:5]) for row in model} == python_totals(batches)
        assert sum(row[2] for row in model) == 20_000
        assert conn.execute("SELECT count(*) FROM flux_analytics.applied_runs").fetchone()[
            0
        ] == len(batches)
        duplicate = publish(store, batches[-1])
        assert duplicate["inserted"] == 0 and duplicate["duplicates"] == len(batches[-1].events)
        assert refresh(conn) == (0, 0, 0) and conn.execute(MODEL_READ).fetchall() == model
        print(
            "Verified rollback, concurrent retry, exact incremental results and duplicate redelivery",
            flush=True,
        )

        for query in (MODEL_READ, FULL_READ):
            for _ in range(3):
                assert conn.execute(query).fetchall() == model
        timings = {MODEL_READ: [], FULL_READ: []}
        for index in range(40):
            order = (MODEL_READ, FULL_READ) if index % 2 else (FULL_READ, MODEL_READ)
            for query in order:
                started = time.perf_counter()
                rows = conn.execute(query).fetchall()
                timings[query].append((time.perf_counter() - started) * 1000)
                assert rows == model

        normalized = [
            [
                value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) else value
                for value in row
            ]
            for row in model
        ]
        digest = hashlib.sha256(
            json.dumps(normalized, default=str, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "postgresql_version": version,
            "unique_events": sum(row[2] for row in model),
            "result_buckets": len(model),
            "modeled_runs": len(batches),
            "backfill": {
                "events": warm_rows,
                "refreshes": len(backfill),
                "wall_ms": round(backfill_ms, 3),
            },
            "steady": {
                "events": sum(len(batch.events) for batch in arriving[1:]),
                "publisher_commit_to_model_commit": latency(refresh_ms),
                "publish_start_to_model_commit": latency(publish_to_gold_ms),
                "older_than_previous_event_time_max": late_events,
                "in_prior_utc_hour": earlier_hours,
            },
            "rollback_and_retry": {
                "events": expected,
                "rolled_back_delta": True,
                "concurrent_retry_runs": sorted(row[0] for row in concurrent),
            },
            "duplicate_redelivery_events": duplicate["duplicates"],
            "read_benchmark": {
                "materialized": {**latency(timings[MODEL_READ]), **read_cost(conn, MODEL_READ)},
                "full_silver_recompute": {
                    **latency(timings[FULL_READ]),
                    **read_cost(conn, FULL_READ),
                },
            },
            "python_source_parity": True,
            "sql_full_recompute_parity": True,
            "result_sha256": digest,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/hourly-public-model.json")
    args = parser.parse_args()
    source_sha = archive_digest(args.archive)
    batches, selection = select_cohort(args.archive, 20_000)
    with isolated_postgres(args.postgres_bin) as (cluster, _):
        measured = run(cluster.dsn, batches)
    evidence = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": {"archive_url": ARCHIVE_URL, "archive_sha256": source_sha, **selection},
        "scope": "Sequential local PostgreSQL microbatches replayed from archived public events. Query timings use one warm connection and alternate identical output queries.",
        **measured,
    }
    encoded = json.dumps(evidence, indent=2) + "\n"
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run with assertions enabled to verify the measured result")
    main()
