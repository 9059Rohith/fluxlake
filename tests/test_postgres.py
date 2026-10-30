import os
from pathlib import Path
import uuid

import psycopg
import pytest

from fluxlake.lake import Lake
from fluxlake.worker import drain_once

pytestmark = pytest.mark.postgres


@pytest.fixture
def db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; needs actual PostgreSQL")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(Path("sql/source.sql").read_text())
        yield conn


def test_postgres_rollback_update_delete_and_worker_replay(db, tmp_path):
    key = "test-" + uuid.uuid4().hex
    lake = Lake(tmp_path)
    db.execute("BEGIN")
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,100,'USD','settled')",
        (key,),
    )
    db.execute("ROLLBACK")
    assert (
        db.execute(
            "SELECT count(*) FROM transaction_outbox WHERE aggregate_id=%s", (key,)
        ).fetchone()[0]
        == 0
    )
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,100,'USD','settled')",
        (key,),
    )
    db.execute("UPDATE transactions SET amount_minor=200 WHERE id=%s", (key,))
    db.execute("DELETE FROM transactions WHERE id=%s", (key,))
    versions = db.execute(
        "SELECT version FROM transaction_outbox WHERE aggregate_id=%s ORDER BY id", (key,)
    ).fetchall()
    assert versions == [(1,), (2,), (3,)]
    assert drain_once(db, lake, 10000) >= 3
    assert not [row for row in lake.current() if row["key"] == key]
    db.execute("UPDATE transaction_outbox SET processed_at=NULL WHERE aggregate_id=%s", (key,))
    assert drain_once(db, Lake(tmp_path), 10000) == 3
    assert not [row for row in lake.current() if row["key"] == key]
    # Reinsert same key must not reset revision after a delete.
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,300,'USD','settled')",
        (key,),
    )
    drain_once(db, lake, 10000)
    assert [r for r in lake.current() if r["key"] == key][0]["version"] == 4


def test_source_late_lower_sequence_commit_is_not_lost(db, tmp_path):
    # A high-watermark implementation would ack the larger id then skip this
    # late-committing lower identity. Different keys avoid intentional per-key locks.
    url = os.environ["TEST_DATABASE_URL"]
    low, high = "low-" + uuid.uuid4().hex, "high-" + uuid.uuid4().hex
    lake = Lake(tmp_path)
    with psycopg.connect(url, autocommit=True) as slow:
        slow.execute("BEGIN")
        slow.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,1,'USD','settled')",
            (low,),
        )
        db.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,2,'USD','settled')",
            (high,),
        )
        drain_once(db, lake, 10000)
        assert high in [r["key"] for r in lake.current()]
        assert low not in [r["key"] for r in lake.current()]
        slow.execute("COMMIT")
        drain_once(db, lake, 10000)
    assert {low, high}.issubset({r["key"] for r in lake.current()})


def test_sink_failure_does_not_ack_source(db, tmp_path, monkeypatch):
    key = "fail-" + uuid.uuid4().hex
    db.execute(
        "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,5,'USD','settled')",
        (key,),
    )
    lake = Lake(tmp_path)

    def crash():
        raise OSError("disk full")

    monkeypatch.setattr(lake, "_publish", crash)
    with pytest.raises(OSError):
        drain_once(db, lake, 10000)
    assert (
        db.execute(
            "SELECT processed_at FROM transaction_outbox WHERE aggregate_id=%s", (key,)
        ).fetchone()[0]
        is None
    )
    restarted = Lake(tmp_path)
    drain_once(db, restarted, 10000)
    assert [r for r in restarted.current() if r["key"] == key][0]["amount_minor"] == 5


def test_source_attributes_cannot_override_core_amount(db):
    key = "reserved-" + uuid.uuid4().hex
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status,attributes) VALUES (%s,100,'USD','settled','{\"amount_minor\":1}')",
            (key,),
        )


def test_cli_init_uses_explicit_schema_file(db, tmp_path, monkeypatch):
    import sys
    from fluxlake.cli import main

    name = "cli_probe_" + uuid.uuid4().hex
    schema = tmp_path / "probe.sql"
    schema.write_text(f"CREATE TABLE {name} (value integer)")
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setattr(sys, "argv", ["fluxlake", "init-source", "--file", str(schema)])
    main()
    assert db.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] == name
    db.execute(f"DROP TABLE {name}")
