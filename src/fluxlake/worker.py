from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from fluxlake.lake import Lake, canonical, durable_write

LOG = logging.getLogger(__name__)


def drain_once(conn: psycopg.Connection, lake: Lake, batch_size: int = 250) -> int:
    """Hold source row locks until durable sink publication, then ack those exact rows.

    Acknowledgements and source row locks share one PostgreSQL transaction. Sequence IDs
    are never used as commit-order checkpoints. A source rollback after sink commit causes
    replay; receipts make it idempotent. Quarantined records are durably recorded then acked.
    """
    with conn.transaction():
        rows = conn.execute(
            """SELECT id,event_id,aggregate_id,version,operation,occurred_at,data
            FROM public.transaction_outbox WHERE processed_at IS NULL
            ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED""",
            (batch_size,),
        ).fetchall()
        events = [
            {
                "event_id": str(row[1]),
                "key": row[2],
                "version": row[3],
                "op": row[4],
                "occurred_at": row[5].isoformat(),
                "data": row[6],
            }
            for row in rows
        ]
        if events:
            result = lake.apply(events)
            conn.execute(
                "UPDATE public.transaction_outbox SET processed_at=clock_timestamp() WHERE id=ANY(%s)",
                ([row[0] for row in rows],),
            )
            LOG.info(json.dumps({"event": "batch", "rows": len(rows), **result}))
    durable_write(
        lake.root / "worker-heartbeat.json",
        canonical({"last_success": datetime.now(timezone.utc).isoformat(), "rows": len(rows)}),
    )
    return len(rows)


def run(root: Path | str, database_url: str | None = None, poll_seconds: float = 1.0) -> None:
    url = database_url or os.environ["DATABASE_URL"]
    lake = Lake(root)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    delay = 1.0
    while not stopping:
        try:
            with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
                delay = 1.0
                while not stopping:
                    count = drain_once(conn, lake)
                    if count == 0:
                        time.sleep(poll_seconds)
        except (psycopg.Error, OSError, TimeoutError) as exc:
            LOG.error(
                json.dumps(
                    {
                        "event": "worker_retry",
                        "error_type": type(exc).__name__,
                        "backoff_seconds": delay,
                    }
                )
            )
            time.sleep(delay)
            delay = min(delay * 2, 30)
