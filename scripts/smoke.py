"""Acceptance test for the running Compose stack; needs DATABASE_URL and API token."""

import json
import http.client
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg

base = os.getenv("FLUXLAKE_URL", "http://127.0.0.1:18082")


def get(path):
    request = urllib.request.Request(
        base + path, headers={"Authorization": "Bearer " + os.environ["FLUXLAKE_API_TOKEN"]}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def wait(predicate):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise AssertionError("Source change did not reach silver within 40 seconds")


def main():
    assert get("/health")["status"] == "ok"
    assert get("/ready")["status"] == "ready"
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                base + "/events", data=b"[]", headers={"Content-Type": "application/json"}
            ),
            timeout=10,
        )
        raise AssertionError("Unauthenticated write unexpectedly accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    request = urllib.request.Request(
        base + "/events",
        data=b"[]",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ["FLUXLAKE_API_TOKEN"],
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert json.load(response)["applied"] == 0
    endpoint = urlsplit(base)
    connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=10)
    connection.request(
        "POST",
        "/events",
        body=b"[]",
        headers={"Content-Type": "application/json", "Authorization": b"Bearer \xff\xfe"},
    )
    response = connection.getresponse()
    assert response.status == 401
    response.read()
    connection.close()
    unicode_key = "unicode-probe-" + uuid.uuid4().hex
    invalid = [
        {
            "event_id": unicode_key,
            "key": unicode_key,
            "version": 1,
            "op": "insert",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "data": {"amount_minor": 1, "currency": "USD", "status": "settled", "region": "\ud800"},
        }
    ]
    request = urllib.request.Request(
        base + "/events",
        data=json.dumps(invalid).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ["FLUXLAKE_API_TOKEN"],
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert json.load(response)["quarantined"] == 1
    assert all(row["key"] != unicode_key for row in get("/transactions"))
    key = "smoke-" + uuid.uuid4().hex
    durations = {}
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        server_version = conn.execute("SHOW server_version").fetchone()[0]
        before = time.perf_counter()
        conn.execute(
            "INSERT INTO transactions(id,amount_minor,currency,status) VALUES (%s,333,'USD','settled')",
            (key,),
        )
        wait(
            lambda: any(r["key"] == key and r["amount_minor"] == 333 for r in get("/transactions"))
        )
        durations["insert"] = (time.perf_counter() - before) * 1000
        before = time.perf_counter()
        conn.execute("UPDATE transactions SET amount_minor=555 WHERE id=%s", (key,))
        wait(
            lambda: any(r["key"] == key and r["amount_minor"] == 555 for r in get("/transactions"))
        )
        durations["update"] = (time.perf_counter() - before) * 1000
        before = time.perf_counter()
        conn.execute("DELETE FROM transactions WHERE id=%s", (key,))
        wait(lambda: all(r["key"] != key for r in get("/transactions")))
        durations["delete"] = (time.perf_counter() - before) * 1000
        expected = [
            {"currency": row[0], "transaction_count": row[1], "total_minor": int(row[2])}
            for row in conn.execute(
                "SELECT currency,count(*),sum(amount_minor) FROM transactions WHERE status='settled' GROUP BY currency ORDER BY currency"
            )
        ]
        wait(lambda: get("/gold") == expected)
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "scope": "actual HTTP API + automatic relay + PostgreSQL + Parquet/DuckDB",
        "postgres_version": server_version,
        "source_operations": ["insert", "update", "delete"],
        "observed_ms": durations,
        "gold": get("/gold"),
        "pipeline": get("/pipeline"),
        "auth": "missing token rejected; configured bearer accepted",
        "edge_cases": "non-ASCII authorization returned 401; surrogate JSON quarantined without silver mutation",
    }
    Path("evidence/compose-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
