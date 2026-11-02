"""Read-only publication reconstruction; GitHub samples are not database CDC logs."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fluxlake.workspace import canonical, normalize

MAX_EVENTS = 200
MAX_BYTES = 4 * 1024 * 1024
FIELDS = ("event_id", "event_type", "repository", "actor", "occurred_at", "action", "organization")
LIMITATIONS = [
    "Only first accepted event JSON is retained. Individual duplicate delivery bodies and "
    "delivery order are not retained; duplicate counts cannot identify which events repeated.",
    "Rejected content has a hash and reason only. Its exact changed fields cannot be recovered.",
    "Event-time order is a deterministic presentation, not delivery, commit or database CDC order. "
    "Stale deliveries, complete history and exactly-once processing cannot be established.",
    "The response hash identifies the original HTTP bytes, which are not retained. It cannot be "
    "recomputed from deduplicated bronze. Evidence hashes are fingerprints, not authentication.",
    "The second pass repeats retained identities in memory only; no source fetch, publication, "
    "counter update or model call occurs. Checks cover selected acquisitions only.",
]


def _plain(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    # PostgreSQL UUIDs are provenance, not JSON-native values.
    if type(value).__name__ == "UUID":
        return str(value)
    return value


def _sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _difference(field, expected, actual):
    return {"field": field, "expected": _plain(expected), "actual": _plain(actual)}


def admit_identity(state, identity, digest):
    """In-memory equivalent of immutable identity/content admission; never overwrite."""
    if identity not in state:
        state[identity] = digest
        return "accepted"
    return "duplicate" if state[identity] == digest else "conflict"


def audit_publication(runs, bronze, silver, quarantine):
    """Reproduce normalization and compare immutable first-publication evidence.

    Acquisition order has no role in identity admission. The controlled second pass
    exercises the same identity/content policy as ingest without touching its store.
    """
    if not 1 <= len(runs) <= 2 or any(
        len(rows) > MAX_EVENTS for rows in (bronze, silver, quarantine)
    ):
        raise ValueError("Replay exceeds bounded capacity")
    runs, bronze, silver, quarantine = (_plain(rows) for rows in (runs, bronze, silver, quarantine))
    run_ids = {row["id"] for row in runs}
    if len(run_ids) != len(runs):
        raise ValueError("Select distinct acquisition identities")
    for rows, identity in ((bronze, "event_id"), (silver, "event_id"), (quarantine, "id")):
        if len({row[identity] for row in rows}) != len(rows):
            raise ValueError("Repeated retained identity")
    if any(row["run_id"] not in run_ids for row in quarantine):
        raise ValueError("Quarantine provenance is outside the selection")
    bodies = [canonical(row["raw"]) for row in bronze]
    if sum(map(len, bodies)) > MAX_BYTES or any(len(body) > 65536 for body in bodies):
        raise ValueError("Replay exceeds payload budget")
    by_bronze = {row["event_id"]: row for row in bronze}
    by_silver = {row["event_id"]: row for row in silver}
    events, replay_state, fingerprints = [], {}, {}
    for identity in sorted(set(by_bronze) | set(by_silver), key=lambda value: (int(value), value)):
        original, published = by_bronze.get(identity), by_silver.get(identity)
        differences, expected = [], None
        if original is None:
            differences.append(_difference("bronze_presence", True, False))
        else:
            try:
                normalized = normalize(original["raw"])
                expected = _plain(dict(zip(FIELDS, normalized, strict=True)))
            except (ValueError, TypeError, RecursionError):
                differences.append(
                    _difference("source_contract", "valid public event", "invalid retained JSON")
                )
            computed = _sha(original["raw"])
            for field, expected_value in (
                ("sha256", computed),
                ("bytes", len(canonical(original["raw"]))),
            ):
                if original[field] != expected_value:
                    differences.append(_difference(field, expected_value, original[field]))
            if expected and expected["event_id"] != identity:
                differences.append(_difference("bronze_identity", expected["event_id"], identity))
            fingerprints[identity] = computed
            if expected and expected["event_id"] == identity:
                admit_identity(replay_state, identity, computed)
        if published is None:
            differences.append(_difference("silver_presence", True, False))
        elif original:
            for field in FIELDS:
                if expected and expected[field] != published[field]:
                    differences.append(_difference(field, expected[field], published[field]))
            if original["run_id"] != published["run_id"]:
                differences.append(_difference("run_id", original["run_id"], published["run_id"]))
        representative = expected or published or {}
        events.append(
            {
                "event_id": identity,
                "run_id": (original or published)["run_id"],
                "occurred_at": representative.get("occurred_at"),
                "repository": representative.get("repository"),
                "event_type": representative.get("event_type"),
                "canonical_sha256": fingerprints.get(identity),
                "stored_sha256": original["sha256"] if original else None,
                "status": "differences" if differences else "matched",
                "differences": differences,
            }
        )
    events.sort(key=lambda row: (row["occurred_at"] or "", int(row["event_id"]), row["event_id"]))
    run_reports = []
    for run in sorted(runs, key=lambda row: (row["started_at"], row["id"])):
        differences = []
        counts = {
            "inserted_bronze": sum(row["run_id"] == run["id"] for row in bronze),
            "inserted_silver": sum(row["run_id"] == run["id"] for row in silver),
            "quarantined": sum(row["run_id"] == run["id"] for row in quarantine),
        }
        for field, observed in counts.items():
            expected_count = run["quarantined" if field == "quarantined" else "inserted"]
            if expected_count != observed:
                differences.append(_difference(field, expected_count, observed))
        accounted = run["inserted"] + run["duplicates"] + run["quarantined"]
        if run["fetched"] != accounted:
            differences.append(_difference("fetched_accounting", run["fetched"], accounted))
        run_reports.append({**run, "observed": counts, "differences": differences})
    rejected = [
        {
            **row,
            "classification": "conflicting_identity_receipt"
            if row["reason"] == "Existing event identity has conflicting content"
            else "rejected_contract_receipt",
        }
        for row in sorted(quarantine, key=lambda row: (row["run_id"], row["id"]))
    ]
    # A second pass over exactly the retained identity+content pairs. No writes.
    before = _sha(replay_state)
    duplicates = conflicts = 0
    for identity in reversed(list(replay_state)):
        outcome = admit_identity(replay_state, identity, fingerprints[identity])
        duplicates += outcome == "duplicate"
        conflicts += outcome == "conflict"
    affected = sum(bool(row["differences"]) for row in events)
    report = {
        "schema_version": "fluxlake-replay-v1",
        "status": "differences"
        if affected or any(row["differences"] for row in run_reports)
        else "consistent",
        "scope": "Selected retained GitHub acquisitions; publication reconstruction, not source CDC",
        "ordering": "Event timestamp ascending, then numeric event identity; not source delivery order",
        "counts": {
            "retained_events": len(bronze),
            "silver_rows": len(silver),
            "affected_events": affected,
            "observed_duplicate_count": sum(row["duplicates"] for row in runs),
            "conflicting_identity_receipts": sum(
                row["classification"] == "conflicting_identity_receipt" for row in rejected
            ),
        },
        "runs": run_reports,
        "events": events,
        "quarantine": rejected,
        "controlled_redelivery": {
            "label": "Controlled in-memory second pass; not observed source deliveries",
            "accepted_first_pass": len(replay_state),
            "duplicates_second_pass": duplicates,
            "conflicts": conflicts,
            "state_unchanged": before == _sha(replay_state),
        },
        "limitations": LIMITATIONS,
    }
    report["evidence_sha256"] = _sha(report)
    return report
