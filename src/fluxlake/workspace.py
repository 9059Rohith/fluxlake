"""Real public GitHub event acquisition and a separate, durable analytical workspace.

Only the fixed GitHub public-events endpoint is fetched. No payment CDC table is
queried here. Migrations and ingestion are explicit operator actions, not GET side effects.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SOURCE_URL = "https://api.github.com/events?per_page=100"
SOURCE_DOCS = "https://docs.github.com/en/rest/activity/events#list-public-events"
MAX_RESPONSE = 2 * 1024 * 1024
EVENT_ID = re.compile(r"[0-9]{1,30}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
ACTOR = re.compile(r"[A-Za-z0-9_\[\].-]{1,100}\Z")


class WorkspaceUnavailable(RuntimeError):
    pass


class IngestionBusy(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fetch_public_events():
    """A bounded fixed-origin request, with no credentials or redirects."""
    request = Request(
        SOURCE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "FluxLake-public-observatory/1.0",
        },
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=15) as response:
            body = response.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE:
                raise ValueError("GitHub response exceeds the acquisition budget")
            rows = json.loads(body)
            if not isinstance(rows, list) or len(rows) > 100:
                raise ValueError("GitHub response is not a bounded event list")
            return rows, {
                "http_status": response.status,
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "rate_remaining": int(response.headers.get("X-RateLimit-Remaining", "0")),
                "poll_seconds": max(60, int(response.headers.get("X-Poll-Interval", "60"))),
            }
    except HTTPError as exc:
        raise WorkspaceUnavailable(
            f"GitHub returned HTTP {exc.code}; retry after its rate window"
        ) from None
    except Exception:
        raise WorkspaceUnavailable(
            "GitHub acquisition failed or exceeded its response budget"
        ) from None


def normalize(event):
    if not isinstance(event, dict) or event.get("public") is not True:
        raise ValueError("Event must be an explicitly public object")
    key = event.get("id", "")
    kind = event.get("type", "")
    repo = event.get("repo", {}).get("name", "") if isinstance(event.get("repo"), dict) else ""
    actor = event.get("actor", {}).get("login", "") if isinstance(event.get("actor"), dict) else ""
    if not isinstance(key, str) or not EVENT_ID.fullmatch(key):
        raise ValueError("Event identity must be a bounded numeric string")
    if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z]{1,60}Event", kind):
        raise ValueError("Event type violates the contract")
    if not isinstance(repo, str) or not REPOSITORY.fullmatch(repo):
        raise ValueError("Repository must be a public owner/name identifier")
    if not isinstance(actor, str) or not ACTOR.fullmatch(actor):
        raise ValueError("Actor violates the identifier contract")
    try:
        occurred = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
        if occurred.tzinfo is None:
            raise ValueError()
        occurred = occurred.astimezone(timezone.utc)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError("Event timestamp must contain a timezone") from None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Payload must be an object")
    action = payload.get("action")
    if action is not None and (not isinstance(action, str) or len(action) > 100):
        raise ValueError("Action must be a bounded string")
    org = event.get("org")
    organization = org.get("login") if isinstance(org, dict) else None
    if organization is not None and (
        not isinstance(organization, str) or not ACTOR.fullmatch(organization)
    ):
        raise ValueError("Organization violates the identifier contract")
    return (key, kind, repo, actor, occurred, action, organization)


def schema_paths(value, prefix="", depth=0):
    """Observe object structure; arrays stay arrays, values never become column names."""
    if depth > 5:
        return []
    result = []
    if isinstance(value, dict):
        for key, item in list(value.items())[:100]:
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,80}", key):
                continue
            path = f"{prefix}.{key}" if prefix else key
            kind = (
                "null"
                if item is None
                else "boolean"
                if isinstance(item, bool)
                else "number"
                if isinstance(item, (int, float))
                else "string"
                if isinstance(item, str)
                else "array"
                if isinstance(item, list)
                else "object"
            )
            result.append((path, kind))
            if isinstance(item, dict):
                result.extend(schema_paths(item, path, depth + 1))
    return result


class PublicWorkspace:
    def __init__(self, database_url=None):
        self.database_url = (
            database_url if database_url is not None else os.getenv("DATABASE_URL", "")
        )

    @contextmanager
    def connection(self, write=False):
        if not self.database_url:
            raise WorkspaceUnavailable("Public data store is not configured")
        try:
            with psycopg.connect(
                self.database_url, connect_timeout=5, row_factory=dict_row
            ) as conn:
                if not write:
                    conn.read_only = True
                    conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                conn.execute("SET LOCAL statement_timeout='8s'")
                conn.execute("SET LOCAL lock_timeout='2s'")
                yield conn
        except (WorkspaceUnavailable, IngestionBusy):
            raise
        except Exception:
            raise WorkspaceUnavailable(
                "Public event store is unavailable; no substitute data is shown"
            ) from None

    def ingest(self, fetcher=fetch_public_events):
        """Serialize ingestion in PostgreSQL; atomically publish bronze + silver + run.

        A failed request gets a durable failed run but does not publish a partial batch.
        Existing event identity with different bytes is quarantined, never overwritten.
        """
        run_id = str(uuid.uuid4())
        began = time.monotonic()
        failure = None
        with self.connection(write=True) as conn:
            if not conn.execute("SELECT pg_try_advisory_xact_lock(704686192) AS held").fetchone()[
                "held"
            ]:
                raise IngestionBusy("An ingestion run is already active")
            last = conn.execute(
                "SELECT started_at,poll_seconds FROM public.flux_public_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if last and (datetime.now(timezone.utc) - last["started_at"]).total_seconds() < max(
                60, last["poll_seconds"] or 60
            ):
                raise IngestionBusy("Respecting GitHub poll interval; wait at least 60 seconds")
            conn.execute(
                "INSERT INTO public.flux_public_runs(id,status,source_url) VALUES(%s,'running',%s)",
                (run_id, SOURCE_URL),
            )
            try:
                events, metadata = fetcher()
            except WorkspaceUnavailable as exc:
                failure = str(exc)
                events, metadata = [], {}
            inserted = duplicate = quarantined = 0
            ids = [
                e.get("id") for e in events if isinstance(e, dict) and isinstance(e.get("id"), str)
            ]
            fingerprints = {
                r["event_id"]: r["sha256"]
                for r in conn.execute(
                    "SELECT event_id,sha256 FROM public.flux_public_bronze WHERE event_id=ANY(%s)",
                    (ids,),
                ).fetchall()
            }
            bronze_rows, silver_rows, rejected_rows = [], [], []
            schema_counts = Counter()
            for event in events:
                body = canonical(event)
                digest = hashlib.sha256(body).hexdigest()
                try:
                    if len(body) > 65536:
                        raise ValueError("Event exceeds 64 KiB per-record budget")
                    normalized = normalize(event)
                    previous = fingerprints.get(normalized[0])
                    if previous:
                        if previous != digest:
                            raise ValueError("Existing event identity has conflicting content")
                        duplicate += 1
                        continue
                except (ValueError, TypeError, RecursionError) as exc:
                    event_id = str(event.get("id", ""))[:30] if isinstance(event, dict) else None
                    rejected_rows.append((run_id, event_id, str(exc)[:200], digest))
                    quarantined += 1
                    continue
                fingerprints[normalized[0]] = digest
                bronze_rows.append((normalized[0], run_id, Jsonb(event), digest, len(body)))
                silver_rows.append((*normalized, run_id))
                schema_counts.update(schema_paths(event))
                inserted += 1
            # Psycopg executemany pipelines each bounded batch, avoiding thousands
            # of network round trips for nested schema observations.
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO public.flux_public_bronze(event_id,run_id,raw,sha256,bytes) VALUES(%s,%s,%s,%s,%s)",
                    bronze_rows,
                )
                cursor.executemany(
                    "INSERT INTO public.flux_public_silver(event_id,event_type,repository,actor,occurred_at,action,organization,run_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    silver_rows,
                )
                cursor.executemany(
                    "INSERT INTO public.flux_public_quarantine(run_id,event_id,reason,sha256) VALUES(%s,%s,%s,%s)",
                    rejected_rows,
                )
                cursor.executemany(
                    "INSERT INTO public.flux_public_schema(path,value_type,observations) VALUES(%s,%s,%s) ON CONFLICT(path,value_type) DO UPDATE SET last_seen=now(),observations=flux_public_schema.observations+excluded.observations",
                    [(path, kind, count) for (path, kind), count in schema_counts.items()],
                )
            row = conn.execute(
                """UPDATE public.flux_public_runs SET finished_at=clock_timestamp(),status=%s,fetched=%s,
                inserted=%s,duplicates=%s,quarantined=%s,response_sha256=%s,http_status=%s,
                rate_remaining=%s,poll_seconds=%s,error=%s,duration_ms=%s WHERE id=%s RETURNING *""",
                (
                    "failed" if failure else "succeeded",
                    len(events),
                    inserted,
                    duplicate,
                    quarantined,
                    metadata.get("response_sha256"),
                    metadata.get("http_status"),
                    metadata.get("rate_remaining"),
                    metadata.get("poll_seconds", 60),
                    failure,
                    round((time.monotonic() - began) * 1000),
                    run_id,
                ),
            ).fetchone()
        if failure:
            raise WorkspaceUnavailable(failure)
        return row

    def overview(self):
        with self.connection() as conn:
            counts = conn.execute(
                """SELECT count(*) events,count(DISTINCT repository) repositories,
                count(DISTINCT actor) actors,count(DISTINCT event_type) event_types,
                min(occurred_at) earliest_event,max(occurred_at) latest_event
                FROM public.flux_public_silver"""
            ).fetchone()
            counts.update(
                conn.execute(
                    "SELECT count(*) bronze_events,coalesce(sum(bytes),0) bronze_bytes FROM public.flux_public_bronze"
                ).fetchone()
            )
            counts["quarantined"] = conn.execute(
                "SELECT count(*) n FROM public.flux_public_quarantine"
            ).fetchone()["n"]
            counts["run_count"] = conn.execute(
                "SELECT count(*) n FROM public.flux_public_runs"
            ).fetchone()["n"]
            latest = conn.execute(
                "SELECT * FROM public.flux_public_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            types = conn.execute(
                "SELECT event_type,count(*) events FROM public.flux_public_silver GROUP BY event_type ORDER BY events DESC,event_type"
            ).fetchall()
            recent = conn.execute(
                "SELECT * FROM public.flux_public_silver ORDER BY occurred_at DESC,event_id DESC LIMIT 8"
            ).fetchall()
        return {
            "counts": counts,
            "latest_run": latest,
            "event_types": types,
            "recent": recent,
            "source_url": SOURCE_URL,
            "source_docs": SOURCE_DOCS,
            "scope": "Sampled public GitHub events; not a complete stream or a realtime feed",
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    def sources(self):
        overview = self.overview()
        return {
            "sources": [
                {
                    "id": "github-public-events",
                    "name": "GitHub public events",
                    "endpoint": SOURCE_URL,
                    "docs": SOURCE_DOCS,
                    "authentication": "Public REST endpoint; no GitHub token",
                    "mode": "Operator-triggered, up to 100 events per acquisition",
                    "latency": "GitHub documents 30 seconds to 6 hours of upstream latency",
                    "storage": "Dedicated PostgreSQL bronze, typed silver and SQL aggregates",
                    "latest_run": overview["latest_run"],
                }
            ],
            "counts": overview["counts"],
        }

    def events(self, layer="silver", q="", event_type="", limit=25, offset=0):
        clauses, args = [], []
        if q:
            clauses.append("(s.repository ILIKE %s OR s.actor ILIKE %s OR s.event_id=%s)")
            args.extend([f"%{q}%", f"%{q}%", q])
        if event_type:
            clauses.append("s.event_type=%s")
            args.append(event_type)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        selected = "s.*,b.ingested_at,b.sha256,b.bytes" if layer == "bronze" else "s.*"
        with self.connection() as conn:
            total = conn.execute(
                "SELECT count(*) n FROM public.flux_public_silver s" + where, args
            ).fetchone()["n"]
            rows = conn.execute(
                "SELECT "
                + selected
                + " FROM public.flux_public_silver s JOIN public.flux_public_bronze b USING(event_id)"
                + where
                + " ORDER BY s.occurred_at DESC,s.event_id DESC LIMIT %s OFFSET %s",
                [*args, limit, offset],
            ).fetchall()
        return {"rows": rows, "total": total, "limit": limit, "offset": offset}

    def event(self, event_id):
        with self.connection() as conn:
            return conn.execute(
                "SELECT s.*,b.raw,b.sha256,b.bytes,b.ingested_at FROM public.flux_public_silver s JOIN public.flux_public_bronze b USING(event_id) WHERE event_id=%s",
                (event_id,),
            ).fetchone()

    def gold(self, group="repository"):
        # Column identifiers are fixed enum values, never supplied SQL.
        column = {"repository": "repository", "actor": "actor", "event_type": "event_type"}[group]
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT {column} dimension,count(*) events,count(DISTINCT actor) actors,count(DISTINCT repository) repositories,min(occurred_at) first_event,max(occurred_at) last_event FROM public.flux_public_silver GROUP BY {column} ORDER BY events DESC,dimension LIMIT 50"
            ).fetchall()
        return {
            "group": group,
            "rows": rows,
            "scope": "Retained sample only; no global ranking claim",
        }

    def schema(self):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT *,count(*) OVER(PARTITION BY path) types_observed FROM public.flux_public_schema ORDER BY path,value_type LIMIT 500"
            ).fetchall()
        return {
            "rows": rows,
            "contract": [
                {"field": "id", "rule": "1–30 digit string; immutable identity and SHA-256"},
                {"field": "public", "rule": "Must be the JSON boolean true"},
                {"field": "repo.name", "rule": "Bounded owner/repository identifier"},
                {"field": "actor.login", "rule": "Bounded GitHub actor identifier"},
                {"field": "created_at", "rule": "Timezone-aware ISO timestamp, normalized to UTC"},
                {"field": "payload", "rule": "Object; raw record at most 64 KiB"},
            ],
        }

    def runs(self):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM public.flux_public_runs ORDER BY started_at DESC LIMIT 100"
            ).fetchall()
        return {"rows": rows}

    def replay(self, run_ids=None):
        """One read-only snapshot; never refresh, acquire, publish or acknowledge."""
        from fluxlake.replay import MAX_BYTES, MAX_EVENTS, audit_publication

        if run_ids is not None and (
            not 1 <= len(run_ids) <= 2 or len(set(run_ids)) != len(run_ids)
        ):
            raise ValueError("Select one or two distinct acquisitions")
        with self.connection() as conn:
            if run_ids:
                runs = conn.execute(
                    "SELECT * FROM public.flux_public_runs WHERE id=ANY(%s::uuid[]) ORDER BY started_at,id",
                    (run_ids,),
                ).fetchall()
                if len(runs) != len(run_ids):
                    return None
            else:
                runs = conn.execute(
                    "SELECT * FROM public.flux_public_runs ORDER BY started_at DESC,id DESC LIMIT 1"
                ).fetchall()
            if not runs:
                return {
                    "status": "no_acquisitions",
                    "runs": [],
                    "events": [],
                    "reason": "No retained acquisition exists. No evidence is fabricated.",
                }
            ids = [row["id"] for row in runs]
            snapshot = conn.execute(
                "SELECT pg_current_snapshot()::text AS id, statement_timestamp() AS captured_at"
            ).fetchone()
            # Include either layer's provenance to expose missing/misattributed rows.
            selection = """(b.run_id=ANY(%s::uuid[]) OR b.event_id IN
                (SELECT event_id FROM public.flux_public_silver WHERE run_id=ANY(%s::uuid[])))"""
            budget = conn.execute(
                """SELECT count(*) events,coalesce(sum(octet_length(b.raw::text)),0) total_bytes,
                coalesce(max(octet_length(b.raw::text)),0) largest
                FROM public.flux_public_bronze b WHERE """
                + selection,
                (ids, ids),
            ).fetchone()
            if (
                budget["events"] > MAX_EVENTS
                or budget["total_bytes"] > MAX_BYTES
                or budget["largest"] > 131072
            ):
                raise WorkspaceUnavailable("Replay evidence exceeds bounded capacity")
            bronze = conn.execute(
                "SELECT b.* FROM public.flux_public_bronze b WHERE "
                + selection
                + " ORDER BY b.event_id LIMIT 201",
                (ids, ids),
            ).fetchall()
            silver = conn.execute(
                """SELECT * FROM public.flux_public_silver WHERE run_id=ANY(%s::uuid[])
                OR event_id=ANY(%s::text[]) ORDER BY event_id LIMIT 201""",
                (ids, [row["event_id"] for row in bronze]),
            ).fetchall()
            quarantine = conn.execute(
                """SELECT * FROM public.flux_public_quarantine WHERE run_id=ANY(%s::uuid[])
                ORDER BY id LIMIT 201""",
                (ids,),
            ).fetchall()
            try:
                report = audit_publication(runs, bronze, silver, quarantine)
            except (ValueError, TypeError, RecursionError):
                raise WorkspaceUnavailable(
                    "Replay evidence exceeds bounded capacity or contract"
                ) from None
        # Snapshot identity changes per observation; exclude it from deterministic evidence hash.
        return {**report, "source_snapshot": snapshot}

    def quarantine(self):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM public.flux_public_quarantine ORDER BY observed_at DESC LIMIT 100"
            ).fetchall()
        return {
            "rows": rows,
            "policy": "Rejected records never reach silver. Hashes retain evidence without publishing rejected content.",
        }

    def drift(self, baseline=None, candidate=None):
        with self.connection() as conn:
            runs = conn.execute(
                "SELECT id,started_at,inserted FROM public.flux_public_runs WHERE status='succeeded' AND inserted>0 ORDER BY started_at DESC LIMIT 100"
            ).fetchall()
            if len(runs) < 2:
                return {
                    "status": "insufficient_runs",
                    "runs": runs,
                    "reason": "Two successful runs with new events are required; no distribution is fabricated.",
                }
            baseline = baseline or runs[1]["id"]
            candidate = candidate or runs[0]["id"]
            valid = {str(run["id"]) for run in runs}
            if (
                str(baseline) not in valid
                or str(candidate) not in valid
                or str(baseline) == str(candidate)
            ):
                raise ValueError("Choose two different retained runs")
            distributions = []
            for run_id in (baseline, candidate):
                distributions.append(
                    {
                        row["event_type"]: row["n"]
                        for row in conn.execute(
                            "SELECT event_type,count(*) n FROM public.flux_public_silver WHERE run_id=%s GROUP BY event_type",
                            (run_id,),
                        ).fetchall()
                    }
                )
        a, b = distributions
        na, nb = sum(a.values()), sum(b.values())
        cells, divergence = [], 0.0
        for kind in sorted(a.keys() | b.keys()):
            p, q = a.get(kind, 0) / na, b.get(kind, 0) / nb
            m = (p + q) / 2
            divergence += (
                (p * math.log2(p / m) if p else 0) + (q * math.log2(q / m) if q else 0)
            ) / 2
            cells.append(
                {
                    "event_type": kind,
                    "baseline": a.get(kind, 0),
                    "candidate": b.get(kind, 0),
                    "baseline_share": p,
                    "candidate_share": q,
                }
            )
        return {
            "status": "compared" if min(na, nb) >= 30 else "insufficient_samples",
            "runs": runs,
            "baseline": str(baseline),
            "candidate": str(candidate),
            "baseline_n": na,
            "candidate_n": nb,
            "js_bits": divergence,
            "rows": cells,
            "caveat": "Descriptive Jensen–Shannon distance in bits, 0–1. Samples are correlated and incomplete; no significance or global-change claim.",
        }

    def export(self, q="", event_type=""):
        rows = self.events(q=q, event_type=event_type, limit=1000)["rows"]
        buffer = io.StringIO(newline="")
        fields = [
            "event_id",
            "event_type",
            "repository",
            "actor",
            "occurred_at",
            "action",
            "run_id",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        # Prevent formula execution when CSV is opened in spreadsheets.
        for row in rows:
            writer.writerow(
                {
                    key: "'" + str(value)
                    if isinstance(value, str) and value.startswith(("=", "+", "-", "@"))
                    else value
                    for key, value in row.items()
                }
            )
        return buffer.getvalue()
