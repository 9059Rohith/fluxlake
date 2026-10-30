"""Bounded read-only PostgreSQL acquisition for retained outbox distributions."""

from __future__ import annotations

import hashlib
from datetime import timezone

import psycopg
from psycopg import IsolationLevel

from fluxlake.drift import compare_events
from fluxlake.drift_contracts import CompareRequest, DriftReport, EvidenceEvent, SourceSnapshot
from fluxlake.lake import canonical
from fluxlake.limits import validate_shape

MAX_PAYLOAD_BYTES = 65536
MAX_TOTAL_BYTES = 4 * 1024 * 1024


class DriftUnavailable(RuntimeError):
    """Sanitized operational failure, never a driver error or raw payload."""


def compare_source(database_url: str, request: CompareRequest) -> DriftReport:
    """Observe both ranges in one snapshot, including acknowledged retained rows.

    Intentionally independent of SourceProjection and Lake. A diagnostic must not
    refresh the observation it is intended to explain or acknowledge any CDC row.
    """
    try:
        if not database_url:
            raise ValueError("Source not configured")
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            connection.isolation_level = IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            with connection.transaction():
                connection.execute("SET LOCAL statement_timeout='5s'")
                connection.execute("SET LOCAL lock_timeout='2s'")
                snapshot_id, captured_at = connection.execute(
                    "SELECT pg_current_snapshot()::text, statement_timestamp()"
                ).fetchone()
                # Check all payload sizes server-side before transferring JSON. Checking
                # only after fetchall would allow 4000 * 64 KiB into client memory.
                count, total, largest, key_size, operation_size = connection.execute(
                    """SELECT count(*),coalesce(sum(octet_length(data::text)),0),
                    coalesce(max(octet_length(data::text)),0),
                    coalesce(max(octet_length(aggregate_id)),0),
                    coalesce(max(octet_length(operation)),0)
                    FROM public.transaction_outbox
                    WHERE id BETWEEN %s AND %s OR id BETWEEN %s AND %s""",
                    (
                        request.baseline.start,
                        request.baseline.end,
                        request.candidate.start,
                        request.candidate.end,
                    ),
                ).fetchone()
                if (
                    count > 4000
                    or total > MAX_TOTAL_BYTES
                    or largest > MAX_PAYLOAD_BYTES
                    or key_size > 128
                    or operation_size > 6
                ):
                    raise ValueError("Source evidence exceeds payload budget")
                windows = []
                total_bytes = 0
                for window in (request.baseline, request.candidate):
                    rows = connection.execute(
                        """SELECT id,event_id,aggregate_id,version,operation,occurred_at,
                        octet_length(data::text),
                        CASE WHEN octet_length(data::text)<=65536 THEN data ELSE NULL END
                        FROM public.transaction_outbox
                        WHERE id BETWEEN %s AND %s ORDER BY id LIMIT 2001""",
                        (window.start, window.end),
                    ).fetchall()
                    events = []
                    for index, event_id, key, version, operation, occurred_at, size, data in rows:
                        total_bytes += size
                        if (
                            data is None
                            or size > MAX_PAYLOAD_BYTES
                            or total_bytes > MAX_TOTAL_BYTES
                        ):
                            raise ValueError("Source evidence exceeds payload budget")
                        validate_shape(data)
                        if not isinstance(data, dict):
                            raise ValueError("Expected business object")
                        events.append(
                            EvidenceEvent(
                                index=index,
                                event_id=str(event_id),
                                key=key,
                                version=version,
                                operation=operation,
                                occurred_at=occurred_at.astimezone(timezone.utc).isoformat(),
                                amount_minor=data.get("amount_minor"),
                                currency=data.get("currency"),
                                status=data.get("status"),
                                payload_sha256=hashlib.sha256(canonical(data)).hexdigest(),
                            )
                        )
                    windows.append(events)
        return compare_events(
            request,
            *windows,
            source_snapshot=SourceSnapshot(
                id=snapshot_id,
                captured_at=captured_at.astimezone(timezone.utc).isoformat(),
            ),
        )
    except Exception:
        # Neither logging nor exception chaining may leak credentials/business payloads.
        raise DriftUnavailable("Drift comparison unavailable or beyond bounded capacity") from None
