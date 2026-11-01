"""Persistent, atomic public inference budgets. No client IP is retained."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from fastapi import HTTPException, Request

POLICY = {
    "per_client": {"requests": 3, "seconds": 600},
    "shared_minute": {"requests": 2, "seconds": 60},
    "shared_day": {"requests": 30, "seconds": 86400},
}


class DemoLimitExceeded(RuntimeError):
    def __init__(self, retry_after):
        self.retry_after = max(1, int(retry_after))
        super().__init__(
            "The free public analyst is cooling down. Please retry after the indicated interval."
        )


class DemoBudgetUnavailable(RuntimeError):
    pass


def client_digest(ip, secret):
    if not 32 <= len(secret.encode("utf-8")) <= 4096:
        raise DemoBudgetUnavailable("Public analyst identity protection is unavailable")
    return hmac.new(secret.encode("utf-8"), ip.encode("ascii"), hashlib.sha256).hexdigest()


def request_identity(request: Request):
    # Vercel overwrites this header at its edge. Everywhere else it is untrusted.
    candidate = request.client.host if request.client else ""
    if os.getenv("VERCEL") == "1" and request.headers.get("x-forwarded-for"):
        candidate = request.headers["x-forwarded-for"].strip()
    try:
        if "," in candidate or "%" in candidate:
            raise ValueError()
        ip = str(ipaddress.ip_address(candidate))
    except ValueError:
        raise HTTPException(400, "A single valid client address is required") from None
    try:
        return client_digest(ip, os.getenv("FLUXLAKE_API_TOKEN", "").strip())
    except (UnicodeError, DemoBudgetUnavailable):
        raise HTTPException(503, "Public analyst identity protection is unavailable") from None


def check_origin(request: Request):
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(403, "Cross-origin public analyst requests are not allowed")
    origin = request.headers.get("origin")
    if origin is None:
        return  # Non-browser JSON clients can use the same bounded public API.
    expected = f"{request.url.scheme}://{request.url.netloc}"
    # Container proxy scheme can be HTTP while the exact public hostname is HTTPS.
    # Host validation is still enforced by TrustedHostMiddleware before this handler.
    canonical = {"https://rohith-fluxlake.vercel.app", "https://fluxlake.vercel.app"}
    try:
        parts = urlsplit(origin)
        valid = origin == expected or (origin in canonical and parts.netloc == request.url.netloc)
        if (
            not valid
            or parts.username
            or parts.password
            or parts.path
            or parts.query
            or parts.fragment
        ):
            raise ValueError()
    except ValueError:
        raise HTTPException(403, "Cross-origin public analyst requests are not allowed") from None


class PersistentDemoLimiter:
    def __init__(self, database_url, *, sqlite_path=None, clock=time.time):
        self.database_url = database_url
        self.sqlite_path = Path(sqlite_path) if sqlite_path else None
        self.clock = clock
        if self.sqlite_path:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.sqlite_path) as conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS flux_public_demo_limits (
                    bucket_key TEXT PRIMARY KEY, window_start INTEGER NOT NULL,
                    attempts INTEGER NOT NULL, expires_at INTEGER NOT NULL)""")

    def _decide(self, identity, now, rows):
        buckets = [
            ("client:" + identity, 3, 600),
            ("shared:minute", 2, 60),
            ("shared:day", 30, 86400),
        ]
        updates, waits, remaining = [], [], {}
        for key, limit, duration in buckets:
            start = now // duration * duration
            previous = rows.get(key)
            used = previous[1] if previous and previous[0] == start else 0
            if used >= limit:
                waits.append(start + duration - now)
            updates.append((key, start, used + 1, start + duration))
            remaining[
                "per_client" if key.startswith("client:") else key.replace("shared:", "shared_")
            ] = max(0, limit - used - 1)
        if waits:
            raise DemoLimitExceeded(max(waits))
        return updates, {
            "policy": POLICY,
            "remaining": remaining,
            "shared_minute_reset_seconds": 60 - now % 60,
        }

    def reserve(self, identity):
        if (
            not isinstance(identity, str)
            or len(identity) != 64
            or any(c not in "0123456789abcdef" for c in identity)
        ):
            raise DemoBudgetUnavailable("Public analyst identity protection is unavailable")
        try:
            if self.sqlite_path:
                # Explicit local/test backend only. Hosted requests never fall back
                # to disposable instance files when PostgreSQL is unavailable.
                with sqlite3.connect(self.sqlite_path, timeout=3) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    now = math.floor(self.clock())
                    keys = ("client:" + identity, "shared:minute", "shared:day")
                    rows = {
                        key: (start, used)
                        for key, start, used in conn.execute(
                            "SELECT bucket_key,window_start,attempts FROM flux_public_demo_limits WHERE bucket_key IN (?,?,?)",
                            keys,
                        )
                    }
                    updates, result = self._decide(identity, now, rows)
                    conn.executemany(
                        "INSERT INTO flux_public_demo_limits VALUES(?,?,?,?) ON CONFLICT(bucket_key) DO UPDATE SET window_start=excluded.window_start,attempts=excluded.attempts,expires_at=excluded.expires_at",
                        updates,
                    )
                    conn.execute("DELETE FROM flux_public_demo_limits WHERE expires_at < ?", (now,))
                return result
            if not self.database_url:
                raise DemoBudgetUnavailable("Persistent public analyst limits are unavailable")
            with psycopg.connect(self.database_url, connect_timeout=5) as conn:
                conn.execute("SET LOCAL statement_timeout='5s'")
                conn.execute("SET LOCAL lock_timeout='2s'")
                # One transaction lock coordinates all three budgets across workers
                # and instances, including buckets that do not exist yet.
                conn.execute("SELECT pg_advisory_xact_lock(704686193)")
                now = conn.execute(
                    "SELECT floor(extract(epoch FROM clock_timestamp()))::bigint"
                ).fetchone()[0]
                keys = ["client:" + identity, "shared:minute", "shared:day"]
                rows = {
                    key: (start, used)
                    for key, start, used in conn.execute(
                        "SELECT bucket_key,window_start,attempts FROM public.flux_public_demo_limits WHERE bucket_key=ANY(%s) FOR UPDATE",
                        (keys,),
                    )
                }
                updates, result = self._decide(identity, now, rows)
                with conn.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO public.flux_public_demo_limits VALUES(%s,%s,%s,%s) ON CONFLICT(bucket_key) DO UPDATE SET window_start=excluded.window_start,attempts=excluded.attempts,expires_at=excluded.expires_at",
                        updates,
                    )
                conn.execute(
                    "DELETE FROM public.flux_public_demo_limits WHERE expires_at < %s", (now,)
                )
            return result
        except (DemoLimitExceeded, DemoBudgetUnavailable):
            raise
        except Exception:
            raise DemoBudgetUnavailable(
                "Persistent public analyst limits are unavailable; no provider request was made"
            ) from None
