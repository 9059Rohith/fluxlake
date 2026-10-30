from __future__ import annotations

import argparse
import json
import math
import platform
import tempfile
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from fluxlake.lake import Lake


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def main():
    parser = argparse.ArgumentParser(
        description="Measured durable local sink latency, not a cloud claim"
    )
    parser.add_argument("--events", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("evidence/benchmark.json"))
    args = parser.parse_args()
    if args.events < 10 or args.batch_size < 1:
        parser.error("Use at least 10 measured events and a positive batch size")
    with tempfile.TemporaryDirectory(prefix="fluxlake-bench-") as temp:
        lake = Lake(temp)

        def records(offset, count):
            return [
                {
                    "event_id": f"e{i}",
                    "key": f"tx{i}",
                    "version": 1,
                    "op": "insert",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "data": {"amount_minor": 100 + i, "currency": "USD", "status": "settled"},
                }
                for i in range(offset, offset + count)
            ]

        lake.apply(records(0, 10))  # warm filesystem/import paths, excluded
        samples = []
        started = time.perf_counter()
        for offset in range(10, 10 + args.events, args.batch_size):
            batch = records(offset, min(args.batch_size, 10 + args.events - offset))
            before = time.perf_counter_ns()
            lake.apply(batch)
            # Return latency includes bronze fsync, SQLite commit and Parquet publication.
            samples.append((time.perf_counter_ns() - before) / 1e6)
        elapsed = time.perf_counter() - started
        assert len(lake.current()) == args.events + 10
        assert lake.gold()[0]["transaction_count"] == args.events + 10
    result = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "dependencies": {
            name: version(name) for name in ("pyarrow", "duckdb", "filelock", "psycopg")
        },
        "scope": "local sink apply batch latency; excludes PostgreSQL poll, network and AWS",
        "events": args.events,
        "batch_size": args.batch_size,
        "batches": len(samples),
        "warmup_events": 10,
        "elapsed_seconds": elapsed,
        "events_per_second": args.events / elapsed,
        "latency_ms": {
            "p50": percentile(samples, 0.50),
            "p95": percentile(samples, 0.95),
            "p99": percentile(samples, 0.99),
            "min": min(samples),
            "max": max(samples),
        },
        "samples_ms": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "samples_ms"}, indent=2))


if __name__ == "__main__":
    main()
