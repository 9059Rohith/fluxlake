"""Actual PostgreSQL quota reservations; TEST_DATABASE_URL must be disposable."""

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest

from fluxlake.public_demo import DemoLimitExceeded, PersistentDemoLimiter

pytestmark = pytest.mark.postgres


@pytest.fixture
def rate_database():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; actual PostgreSQL required")
    with psycopg.connect(url) as conn:
        conn.execute(Path("sql/workspace.sql").read_text())
        conn.execute("TRUNCATE public.flux_public_demo_limits")
        now = conn.execute(
            "SELECT floor(extract(epoch FROM clock_timestamp()))::bigint"
        ).fetchone()[0]
    # Keep the concurrency assertion inside one fixed window, including on slow CI.
    if 60 - now % 60 < 5:
        time.sleep(60 - now % 60 + 0.1)
    return url


def test_postgres_reservations_are_atomic_across_instances_and_restart(rate_database):
    def attempt(index):
        limiter = PersistentDemoLimiter(rate_database)
        try:
            limiter.reserve(hashlib.sha256(str(index).encode()).hexdigest())
            return True
        except DemoLimitExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(16))) == 2
    with pytest.raises(DemoLimitExceeded):
        PersistentDemoLimiter(rate_database).reserve("f" * 64)
    with psycopg.connect(rate_database) as conn:
        rows = conn.execute(
            "SELECT bucket_key,attempts FROM public.flux_public_demo_limits"
        ).fetchall()
    assert len(rows) == 4
    assert dict(rows)["shared:day"] == dict(rows)["shared:minute"] == 2


def test_postgres_client_cap_and_daily_cap_cannot_be_bypassed(rate_database):
    limiter = PersistentDemoLimiter(rate_database)
    identity = "a" * 64
    limiter.reserve(identity)
    # Test-only direct budget preparation avoids spending real inference or waiting.
    with psycopg.connect(rate_database) as conn:
        conn.execute(
            "UPDATE public.flux_public_demo_limits SET attempts=3 WHERE bucket_key=%s",
            ("client:" + identity,),
        )
    with pytest.raises(DemoLimitExceeded) as exc:
        limiter.reserve(identity)
    assert 1 <= exc.value.retry_after <= 600
    with psycopg.connect(rate_database) as conn:
        conn.execute(
            "UPDATE public.flux_public_demo_limits SET attempts=30 WHERE bucket_key='shared:day'"
        )
    with pytest.raises(DemoLimitExceeded):
        limiter.reserve("b" * 64)
    with psycopg.connect(rate_database) as conn:
        assert (
            conn.execute(
                "SELECT attempts FROM public.flux_public_demo_limits WHERE bucket_key='shared:day'"
            ).fetchone()[0]
            == 30
        )
