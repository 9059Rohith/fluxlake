"""Bounded request-triggered, read-only outbox replay for ephemeral HTTP instances.

No source acknowledgement and no high-watermark: each independent replica reconstructs
from a complete repeatable-read history snapshot. This is not a continuous worker.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timezone

import psycopg
from psycopg import IsolationLevel

from fluxlake.bootstrap import initialize_synthetic_source

from fluxlake.lake import Lake, canonical, fsync_directory
from fluxlake.limits import MAX_EVENT_BYTES

LOG = logging.getLogger(__name__)


class ProjectionUnavailable(RuntimeError):
    pass


class SourceProjection:
    def __init__(
        self,
        lake: Lake,
        database_url: str,
        *,
        max_events: int = 5000,
        max_bytes: int = 16 * 1024 * 1024,
        cache_seconds: int = 5,
        seed_demo: bool = False,
    ):
        if not 1 <= max_events <= 5000 or not 1 <= max_bytes <= 16 * 1024 * 1024:
            raise ValueError("Projection bounds exceed supported demo capacity")
        self.lake = lake
        self._database_url = database_url
        self._max_events = max_events
        self._max_bytes = max_bytes
        self._cache_seconds = cache_seconds
        self._seed_demo = seed_demo
        self._initialized = False
        self._lock = threading.RLock()
        self._history_digest = None
        self._next_refresh = 0.0
        self.ready = False
        self.last_success = None

    def refresh(self, *, force: bool = False) -> None:
        with self._lock:
            self._refresh(force=force)

    def read(self, query):
        """Keep local readers protected while a refresh replaces/prunes cache files."""
        with self._lock:
            self._refresh()
            return query()

    def _refresh(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now < self._next_refresh:
            if not self.ready:
                raise ProjectionUnavailable("Source replay unavailable")
            return
        self.ready = False
        try:
            if not self._database_url:
                raise ValueError("Source is not configured")
            if self._seed_demo and not self._initialized:
                initialize_synthetic_source(self._database_url)
                self._initialized = True
            events = []
            digest = hashlib.sha256()
            total_bytes = 0
            with psycopg.connect(self._database_url, connect_timeout=5) as conn:
                conn.isolation_level = IsolationLevel.REPEATABLE_READ
                conn.read_only = True
                with conn.transaction():
                    conn.execute("SET LOCAL statement_timeout='5s'")
                    conn.execute("SET LOCAL lock_timeout='2s'")
                    with conn.cursor(name="fluxlake_source_history") as cursor:
                        cursor.itersize = 250
                        cursor.execute(
                            """SELECT event_id,aggregate_id,version,operation,occurred_at,
                            CASE WHEN octet_length(data::text)<=65536 THEN data ELSE NULL END
                            FROM public.transaction_outbox ORDER BY id LIMIT %s""",
                            (self._max_events + 1,),
                        )
                        for row in cursor:
                            if len(events) >= self._max_events or row[5] is None:
                                raise ValueError("Source exceeds projection bounds")
                            event = {
                                "event_id": str(row[0]),
                                "key": row[1],
                                "version": row[2],
                                "op": row[3],
                                "occurred_at": row[4].isoformat(),
                                "data": row[5],
                            }
                            encoded = canonical(event)
                            digest.update(encoded)
                            size = len(encoded)
                            total_bytes += size
                            if size > MAX_EVENT_BYTES or total_bytes > self._max_bytes:
                                raise ValueError("Source exceeds projection bounds")
                            events.append(event)
            # Validate complete history bounds before publishing any part of it.
            fingerprint = digest.hexdigest()
            if fingerprint != self._history_digest or not self.lake.ready():
                self.lake.apply(events)
                with self.lake.lock:
                    current = self.lake._snapshot()
                    for previous in current.parent.glob("snapshot-*.parquet"):
                        if previous != current:
                            previous.unlink()
                    fsync_directory(current.parent)
                self._history_digest = fingerprint
            self.last_success = datetime.now(timezone.utc).isoformat()
            self.ready = True
        except Exception as exc:
            # Credentials and database exception messages never enter HTTP/log output.
            LOG.warning("source_projection_unavailable error_type=%s", type(exc).__name__)
            raise ProjectionUnavailable("Source replay unavailable") from None
        finally:
            self._next_refresh = time.monotonic() + self._cache_seconds
