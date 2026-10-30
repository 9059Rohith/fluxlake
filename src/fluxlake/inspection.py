"""Read-only, selected-key diagnostics across two explicitly separate snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import psycopg
import pyarrow.parquet as pq
from psycopg import IsolationLevel

from fluxlake.lake import IDENTIFIER, Lake, canonical
from fluxlake.limits import MAX_EVENT_BYTES


class InspectionUnavailable(RuntimeError):
    pass


def inspect(lake: Lake, database_url: str, keys: list[str]) -> dict:
    """Compare selected keys, never repair or claim global/source-table equality.

    The local lock spans both observations, not a distributed transaction. The source
    observation can include a newer commit than this instance's published projection.
    Latest outbox rows are evidence only while source history is retained and trusted.
    """
    if not 1 <= len(keys) <= 100 or any(
        not isinstance(key, str) or not IDENTIFIER.fullmatch(key) for key in keys
    ):
        raise ValueError("Provide 1 to 100 safe keys")
    keys = sorted(set(keys))
    try:
        if not database_url:
            raise ValueError("Source not configured")
        with lake.lock:
            snapshot = lake._snapshot()
            if snapshot.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("Projection exceeds inspection bounds")
            parquet = pq.ParquetFile(snapshot)
            if parquet.metadata.num_rows > 5000:
                raise ValueError("Projection exceeds inspection bounds")
            silver = {}
            repeated = set()
            for batch in parquet.iter_batches(batch_size=100):
                for row in batch.to_pylist():
                    if row["key"] in keys:
                        if row["key"] in silver:
                            repeated.add(row["key"])
                        silver[row["key"]] = row
            with lake._connect() as db:
                placeholders = ",".join("?" for _ in keys)
                state = {
                    row["key"]: dict(row)
                    for row in db.execute(
                        f"SELECT * FROM state WHERE key IN ({placeholders})", keys
                    )
                }
            local = {
                "file": snapshot.name,
                "rows": parquet.metadata.num_rows,
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
            with psycopg.connect(database_url, connect_timeout=5) as conn:
                conn.isolation_level = IsolationLevel.REPEATABLE_READ
                conn.read_only = True
                with conn.transaction():
                    conn.execute("SET LOCAL statement_timeout='5s'")
                    conn.execute("SET LOCAL lock_timeout='2s'")
                    source_id, source_time = conn.execute(
                        "SELECT pg_current_snapshot()::text, statement_timestamp()"
                    ).fetchone()
                    # Existing UNIQUE(aggregate_id, version) supports each backwards lookup.
                    rows = conn.execute(
                        """SELECT event_id,aggregate_id,version,operation,occurred_at,
                        CASE WHEN octet_length(data::text)<=65536 THEN data ELSE NULL END
                        FROM unnest(%s::text[]) AS requested(key)
                        CROSS JOIN LATERAL (
                          SELECT * FROM public.transaction_outbox
                          WHERE aggregate_id=requested.key ORDER BY version DESC LIMIT 1
                        ) AS latest""",
                        (keys,),
                    ).fetchall()
            source = {}
            total = 0
            for row in rows:
                event = {
                    "event_id": str(row[0]),
                    "key": row[1],
                    "version": row[2],
                    "op": row[3],
                    "occurred_at": row[4].isoformat(),
                    "data": row[5],
                }
                raw = canonical(event)
                total += len(raw)
                if row[5] is None or len(raw) > MAX_EVENT_BYTES or total > 1024 * 1024:
                    raise ValueError("Source exceeds inspection bounds")
                source[row[1]] = event
            results = [
                _compare(key, source.get(key), state.get(key), silver.get(key), key in repeated)
                for key in keys
            ]
            return {
                "scope": "selected_keys_observed_snapshots",
                "semantics": "Two observations, not a distributed snapshot; no replay, acknowledgement or repair. Latest retained outbox evidence, not source-table or global equality.",
                "source_snapshot": {
                    "id": source_id,
                    "captured_at": source_time.isoformat(),
                    "isolation": "repeatable read",
                    "read_only": True,
                },
                "projection_snapshot": local,
                "requested_keys": len(keys),
                "counts": {
                    status: sum(row["status"] == status for row in results)
                    for status in ("match", "mismatch", "absent")
                },
                "results": results,
            }
    except Exception:
        # Never return/log driver errors, connection URLs or raw transaction payloads.
        raise InspectionUnavailable("Inspection unavailable or beyond bounded capacity") from None


def _compare(key, source, state, silver, repeated):
    differences = []
    if source is None:
        if state is not None or silver is not None:
            differences.append("source_absent")
    else:
        try:
            data, attrs = Lake._validate(source)
        except (ValueError, TypeError, OverflowError):
            differences.append("source_contract")
        else:
            deleted = source["op"] == "delete"
            expected = {
                "key": key,
                "version": source["version"],
                "occurred_at": source["occurred_at"],
                **data,
                "attributes": attrs,
            }
            if state is None:
                differences.append("state_missing")
            else:
                if state["version"] != source["version"]:
                    differences.append("revision")
                if bool(state["deleted"]) != deleted:
                    differences.append("deletion")
                if state["event_hash"] != hashlib.sha256(canonical(source)).hexdigest():
                    differences.append("event_identity")
                if canonical(json.loads(state["payload"])) != canonical(expected):
                    differences.append("state_payload")
            if deleted:
                if silver is not None:
                    differences.append("silver_unexpected")
            elif silver is None:
                differences.append("silver_missing")
            else:
                expected_silver = {
                    name: expected.get(name)
                    for name in (
                        "key",
                        "version",
                        "amount_minor",
                        "currency",
                        "status",
                        "occurred_at",
                    )
                }
                expected_silver["attributes_json"] = canonical(attrs).decode()
                actual = {name: silver.get(name) for name in expected_silver}
                columns = {
                    name[5:]: value
                    for name, value in silver.items()
                    if name.startswith("attr_") and value is not None
                }
                if canonical(actual) != canonical(expected_silver) or canonical(
                    columns
                ) != canonical(attrs):
                    differences.append("silver_payload")
    if repeated:
        differences.append("silver_duplicate_key")
    return {
        "key": key,
        "status": "mismatch" if differences else ("absent" if source is None else "match"),
        "source_version": source["version"] if source else None,
        "projection_version": state["version"] if state else None,
        "source_deleted": source["op"] == "delete" if source else None,
        "differences": differences,
    }
