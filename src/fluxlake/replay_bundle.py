"""Portable retained-evidence replay. No network, database, model calls or writes."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
from pathlib import Path

from fluxlake.replay import MAX_EVENTS, _plain, audit_publication
from fluxlake.workspace import EVENT_ID, canonical

VERSION = "fluxlake-replay-bundle-v1"
MAX_BUNDLE_BYTES = 4 * 1024 * 1024
TABLES = {"runs", "bronze", "silver", "quarantine"}
BOUNDARY = (
    "Reproduces the exported retained evidence using FluxLake's versioned normalization contract. "
    "Fingerprints detect changes against a trusted pin; they do not authenticate GitHub or prove "
    "source completeness. Original HTTP bodies and duplicate/rejected bodies are not retained."
)


def _fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def create_bundle(runs, bronze, silver, quarantine, snapshot):
    """Export exactly the inputs and report from one bounded database snapshot."""
    # Do not publish rows that no longer meet the explicit public-data boundary.
    if any(
        not isinstance(row.get("raw"), dict) or row["raw"].get("public") is not True
        for row in bronze
    ):
        raise ValueError("Bundle contains evidence outside the public contract")
    report = audit_publication(runs, bronze, silver, quarantine)
    result = _plain(
        {
            "schema_version": VERSION,
            "boundary": BOUNDARY,
            "source_snapshot": snapshot,
            "evidence": dict(
                zip(
                    ("runs", "bronze", "silver", "quarantine"),
                    (runs, bronze, silver, quarantine),
                    strict=True,
                )
            ),
            "report": report,
        }
    )
    result["bundle_sha256"] = _fingerprint(result)
    if len(canonical(result)) > MAX_BUNDLE_BYTES:
        raise ValueError("Bundle exceeds bounded capacity")
    return result


def verify_bundle(bundle, expected_sha256=None):
    """Check a portable manifest, then recompute the report from its retained inputs.

    A matching manifest alone is insufficient: an attacker can rehash edited rows.
    The optional pin must be obtained through a separately trusted channel.
    """
    try:
        if (
            not isinstance(bundle, dict)
            or set(bundle)
            != {
                "schema_version",
                "boundary",
                "source_snapshot",
                "evidence",
                "report",
                "bundle_sha256",
            }
            or bundle["schema_version"] != VERSION
        ):
            raise ValueError("Unsupported replay bundle schema")
        if len(canonical(bundle)) > MAX_BUNDLE_BYTES:
            raise ValueError("Bundle exceeds bounded capacity")
        digest = bundle["bundle_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid bundle fingerprint")
        computed = _fingerprint({k: v for k, v in bundle.items() if k != "bundle_sha256"})
        if not hmac.compare_digest(computed, digest):
            raise ValueError("Bundle fingerprint differs from exported content")
        if expected_sha256 is not None and (
            not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or not hmac.compare_digest(digest, expected_sha256)
        ):
            raise ValueError("Bundle differs from expected fingerprint")
        data = bundle["evidence"]
        if not isinstance(data, dict) or set(data) != TABLES:
            raise ValueError("Invalid retained evidence tables")
        for table, rows in data.items():
            if not isinstance(rows, list) or len(rows) > (2 if table == "runs" else MAX_EVENTS):
                raise ValueError("Evidence exceeds bounded row capacity")
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError("Invalid retained evidence row")
        for row in data["bronze"] + data["silver"]:
            if not isinstance(row.get("event_id"), str) or not EVENT_ID.fullmatch(row["event_id"]):
                raise ValueError("Invalid retained event identity")
        if any(
            not isinstance(row.get("raw"), dict) or row["raw"].get("public") is not True
            for row in data["bronze"]
        ):
            raise ValueError("Bundle contains evidence outside the public contract")
        reconstructed = audit_publication(
            *(data[name] for name in ("runs", "bronze", "silver", "quarantine"))
        )
        if canonical(reconstructed) != canonical(bundle["report"]):
            raise ValueError("Report reconstruction differs from exported report")
        return {
            "verification": "reproduced",
            "publication_status": reconstructed["status"],
            "counts": reconstructed["counts"],
            "bundle_sha256": digest,
            "evidence_sha256": reconstructed["evidence_sha256"],
            "boundary": BOUNDARY,
        }
    except (KeyError, TypeError, RecursionError, OverflowError, AttributeError):
        raise ValueError("Malformed or excessive replay evidence") from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Non-finite JSON numbers are not supported")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reproduce a FluxLake public replay bundle offline"
    )
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--expected-sha256", help="Canonical bundle fingerprint from a trusted channel"
    )
    args = parser.parse_args(argv)
    try:
        with args.file.open("rb") as source:
            body = source.read(MAX_BUNDLE_BYTES + 1)
        if len(body) > MAX_BUNDLE_BYTES:
            raise ValueError("Bundle exceeds bounded capacity")
        bundle = json.loads(
            body, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
        result = verify_bundle(bundle, args.expected_sha256)
    except (OSError, UnicodeError, ValueError, RecursionError):
        # A local untrusted file must not emit raw payloads, paths or tracebacks.
        print(json.dumps({"verification": "invalid", "reason": "Bundle failed verification"}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["publication_status"] == "consistent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
