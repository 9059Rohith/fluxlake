from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from filelock import FileLock

IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ATTRIBUTE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
BASE = pa.schema(
    [
        ("key", pa.string()),
        ("version", pa.int64()),
        ("amount_minor", pa.int64()),
        ("currency", pa.string()),
        ("status", pa.string()),
        ("occurred_at", pa.string()),
        ("attributes_json", pa.string()),
    ]
)
GOLD_SQL = """SELECT currency, count(*) AS transaction_count,
                     sum(amount_minor) AS total_minor
              FROM read_parquet(?) WHERE status = 'settled'
              GROUP BY currency ORDER BY currency"""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def validate_utf8(value: Any) -> None:
    """JSON escape syntax can carry unpaired surrogates that Arrow cannot store."""
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ValueError("JSON strings must encode as strict UTF-8") from None
    elif isinstance(value, dict):
        for key, item in value.items():
            validate_utf8(key)
            validate_utf8(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            validate_utf8(item)


def fsync_directory(path: Path) -> None:
    """Persist POSIX directory entries, including newly renamed immutable objects."""
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_directory(path: Path) -> None:
    missing = []
    candidate = path
    while not candidate.exists():
        missing.append(candidate)
        candidate = candidate.parent
    path.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing):
        fsync_directory(created.parent)


def durable_write(path: Path, data: bytes, *, immutable: bool = False) -> None:
    """Atomic replacement for pointers; content-addressed exclusive creation for raw records."""
    if immutable:
        if path.exists():
            if path.read_bytes() != data:
                raise OSError("immutable object content mismatch")
            fsync_directory(path.parent)
            return
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


class Lake:
    """One local filesystem, multiple serialized writers, immutable reader snapshots.

    SQLite commits receipts and current state together. Publishing follows commit; startup
    republishes committed state after an interrupted write. Source ack happens only after
    apply returns, so a crash between sink commit and source ack becomes a harmless replay.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        for part in ("bronze", "silver"):
            ensure_directory(self.root / part)
        self.lock = FileLock(str(self.root / ".writer.lock"), timeout=60)
        self.db_path = self.root / "state.sqlite3"
        with self.lock, self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY, version INTEGER NOT NULL, deleted INTEGER NOT NULL,
                    payload TEXT NOT NULL, event_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts (
                    event_id TEXT PRIMARY KEY, event_hash TEXT NOT NULL, outcome TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quarantine (
                    event_hash TEXT PRIMARY KEY, reason TEXT NOT NULL, raw TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attributes (name TEXT PRIMARY KEY, type TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS counters (outcome TEXT PRIMARY KEY, count INTEGER NOT NULL);
            """)
            self._publish()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=60)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _validate(event: Any) -> tuple[dict, dict]:
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        validate_utf8(event)
        for name in ("event_id", "key"):
            if not isinstance(event.get(name), str) or not IDENTIFIER.fullmatch(event[name]):
                raise ValueError(f"{name} must be a bounded safe identifier")
        version = event.get("version")
        if type(version) is not int or not 0 < version <= 2**63 - 1:
            raise ValueError("version must be a positive int64")
        if event.get("op") not in ("insert", "update", "delete"):
            raise ValueError("unsupported operation")
        occurred = datetime.fromisoformat(event.get("occurred_at", ""))
        if occurred.tzinfo is None:
            raise ValueError("occurred_at requires timezone")
        data = event.get("data")
        if not isinstance(data, dict):
            raise ValueError("data must be an object, including for tombstones")
        if event["op"] != "delete":
            amount = data.get("amount_minor")
            if type(amount) is not int or not 0 <= amount <= 2**63 - 1:
                raise ValueError("amount_minor must be nonnegative int64")
            if not isinstance(data.get("currency"), str) or not re.fullmatch(
                r"[A-Z]{3}", data["currency"]
            ):
                raise ValueError("currency must be three uppercase letters")
            if data.get("status") not in ("pending", "settled", "failed"):
                raise ValueError("invalid transaction status")
        attrs = {k: v for k, v in data.items() if k not in ("amount_minor", "currency", "status")}
        for key, value in attrs.items():
            if key in {"key", "version", "occurred_at", "attributes", "event_id", "op"}:
                raise ValueError("attribute name collides with envelope")
            if not ATTRIBUTE.fullmatch(key) or type(value) not in (str, int, bool, float):
                raise ValueError("attributes must have safe names and non-null scalar values")
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and not -(2**63) <= value < 2**63
            ):
                raise ValueError("attribute integer exceeds int64")
        return data, attrs

    def apply(self, events: list[Any]) -> dict[str, int]:
        counts = dict.fromkeys(("applied", "duplicate", "stale", "quarantined"), 0)
        with self.lock:
            with self._connect() as db:
                for event in events:
                    raw = canonical(event)
                    digest = hashlib.sha256(raw).hexdigest()
                    durable_write(self.root / "bronze" / f"{digest}.json", raw, immutable=True)
                    outcome = "quarantined"
                    try:
                        data, attrs = self._validate(event)
                        previous = db.execute(
                            "SELECT * FROM receipts WHERE event_id=?", (event["event_id"],)
                        ).fetchone()
                        if previous:
                            if previous["event_hash"] != digest:
                                raise ValueError("event_id reused with different content")
                            outcome = "duplicate"
                        else:
                            state = db.execute(
                                "SELECT * FROM state WHERE key=?", (event["key"],)
                            ).fetchone()
                            if state and state["version"] == event["version"]:
                                raise ValueError("same key/version carries a different event")
                            if state and state["version"] > event["version"]:
                                outcome = "stale"
                            else:
                                for name, value in attrs.items():
                                    typename = type(value).__name__
                                    registered = db.execute(
                                        "SELECT type FROM attributes WHERE name=?", (name,)
                                    ).fetchone()
                                    if registered and registered[0] != typename:
                                        raise ValueError(f"attribute type changed: {name}")
                                for name, value in attrs.items():
                                    db.execute(
                                        "INSERT OR IGNORE INTO attributes VALUES (?,?)",
                                        (name, type(value).__name__),
                                    )
                                payload = {
                                    "key": event["key"],
                                    "version": event["version"],
                                    "occurred_at": event["occurred_at"],
                                    **data,
                                    "attributes": attrs,
                                }
                                db.execute(
                                    "INSERT OR REPLACE INTO state VALUES (?,?,?,?,?)",
                                    (
                                        event["key"],
                                        event["version"],
                                        event["op"] == "delete",
                                        canonical(payload).decode(),
                                        digest,
                                    ),
                                )
                                outcome = "applied"
                            db.execute(
                                "INSERT INTO receipts VALUES (?,?,?)",
                                (event["event_id"], digest, outcome),
                            )
                    except (ValueError, TypeError, OverflowError) as exc:
                        db.execute(
                            "INSERT OR IGNORE INTO quarantine VALUES (?,?,?)",
                            (digest, str(exc), raw.decode()),
                        )
                    counts[outcome] += 1
                    db.execute(
                        "INSERT INTO counters VALUES (?,1) ON CONFLICT(outcome) DO UPDATE SET count=count+1",
                        (outcome,),
                    )
            # Commit before publish. A failed publish must propagate so PostgreSQL does not ack.
            self._publish()
        return counts

    def _publish(self) -> None:
        with self._connect() as db:
            rows = [
                json.loads(row[0])
                for row in db.execute("SELECT payload FROM state WHERE deleted=0 ORDER BY key")
            ]
            attributes = dict(db.execute("SELECT name,type FROM attributes ORDER BY name"))
        type_map = {
            "str": pa.string(),
            "int": pa.int64(),
            "bool": pa.bool_(),
            "float": pa.float64(),
        }
        schema = pa.schema(
            list(BASE) + [pa.field("attr_" + k, type_map[v]) for k, v in attributes.items()]
        )
        records = []
        for row in rows:
            record = {name: row.get(name) for name in BASE.names}
            record["attributes_json"] = canonical(row["attributes"]).decode()
            record.update({"attr_" + name: row["attributes"].get(name) for name in attributes})
            records.append(record)
        snapshot = "snapshot-" + uuid.uuid4().hex + ".parquet"
        destination = self.root / "silver" / snapshot
        pq.write_table(
            pa.Table.from_pylist(records, schema=schema), destination, compression="zstd"
        )
        with destination.open("r+b") as handle:
            os.fsync(handle.fileno())
        # The target name must persist before a manifest can refer to it.
        fsync_directory(destination.parent)
        durable_write(
            self.root / "silver" / "manifest.json",
            canonical({"file": snapshot, "rows": len(rows), "attributes": attributes}),
        )

    def _snapshot(self) -> Path:
        manifest = json.loads((self.root / "silver" / "manifest.json").read_text())
        name = manifest["file"]
        if not re.fullmatch(r"snapshot-[a-f0-9]{32}\.parquet", name):
            raise ValueError("invalid snapshot pointer")
        return self.root / "silver" / name

    def current(self) -> list[dict]:
        rows = pq.read_table(self._snapshot()).to_pylist()
        for row in rows:
            row["attributes"] = json.loads(row.pop("attributes_json"))
            for name in list(row):
                if name.startswith("attr_"):
                    del row[name]
        return rows

    def gold(self) -> list[dict]:
        with duckdb.connect() as db:
            cursor = db.execute(GOLD_SQL, [str(self._snapshot())])
            names = [col[0] for col in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

    def schema(self) -> dict:
        with self._connect() as db:
            return {
                "attributes": dict(db.execute("SELECT name,type FROM attributes ORDER BY name"))
            }

    def quarantine(self) -> list[dict]:
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT event_hash,reason FROM quarantine ORDER BY event_hash"
                )
            ]

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            return dict(db.execute("SELECT outcome,count FROM counters"))

    def ready(self) -> bool:
        with self._connect() as db:
            return (
                db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                and self._snapshot().is_file()
            )
