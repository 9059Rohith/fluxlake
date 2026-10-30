from __future__ import annotations

import hmac
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from starlette.middleware.trustedhost import TrustedHostMiddleware

from fluxlake.lake import Lake, canonical
from fluxlake.limits import MAX_EVENT_BYTES, check_json_depth, validate_shape
from fluxlake.projection import ProjectionUnavailable, SourceProjection

CSS = """body{background:#0d1523;color:#ecf5ff;font:16px system-ui;max-width:1000px;margin:60px auto;padding:24px}h1{font-size:48px}small,a{color:#7de0cc}pre{background:#162337;padding:24px;overflow:auto;border-radius:12px}"""
JS = """async function refresh(){const e=document.getElementById('summary');try{const r=await fetch('/demo/summary');if(!r.ok){e.textContent='Public synthetic view is disabled. Operational routes require authentication.';return}e.textContent=JSON.stringify(await r.json(),null,2)}catch(_){e.textContent='Service unavailable'}}refresh();setInterval(refresh,5000);"""
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"


def create_app(root: Path | str | None = None) -> FastAPI:
    lake = Lake(root or os.getenv("FLUXLAKE_ROOT", "data"))
    public_demo = os.getenv("FLUXLAKE_PUBLIC_DEMO", "").lower() == "true"
    sync_mode = os.getenv("FLUXLAKE_SOURCE_SYNC", "poll").lower()
    if sync_mode not in {"poll", "request"}:
        raise RuntimeError("Unknown source synchronization profile")
    projection = (
        SourceProjection(
            lake,
            os.getenv("DATABASE_URL", ""),
            seed_demo=os.getenv("FLUXLAKE_SEED_DEMO", "").lower() == "true",
        )
        if sync_mode == "request"
        else None
    )
    app = FastAPI(
        title="FluxLake",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        description="Authenticated operational lakehouse API. Optional public view contains only explicitly synthetic aggregates.",
    )
    configured_hosts = [
        host.strip() for host in os.getenv("FLUXLAKE_ALLOWED_HOSTS", "").split(",") if host.strip()
    ]
    if (public_demo and not configured_hosts) or any(
        not re.fullmatch(r"[A-Za-z0-9.-]+", host) for host in configured_hosts
    ):
        raise RuntimeError("Public demo requires explicit exact allowed hostnames")
    allowed_hosts = ["localhost", "127.0.0.1", *configured_hosts]
    if not public_demo:
        allowed_hosts.append("testserver")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    cached = {"until": 0.0, "value": None}
    cache_lock = threading.Lock()

    def authorize(authorization: str = Header(default="")):
        try:
            token = os.getenv("FLUXLAKE_API_TOKEN", "").strip().encode("utf-8")
        except UnicodeError:
            token = b""
        if not 32 <= len(token) <= 4096:
            raise HTTPException(503, "Protected routes disabled: configure a strong API token")
        try:
            presented = authorization.encode("utf-8")
        except UnicodeError:
            presented = b""
        if len(presented) > 4103 or not hmac.compare_digest(presented, b"Bearer " + token):
            raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    def available():
        if projection:
            try:
                projection.refresh()
            except ProjectionUnavailable:
                raise HTTPException(
                    503, "Source replay unavailable or beyond bounded demo capacity"
                ) from None

    def read(query):
        try:
            return projection.read(query) if projection else query()
        except ProjectionUnavailable:
            raise HTTPException(
                503, "Source replay unavailable or beyond bounded demo capacity"
            ) from None

    def secure(response, request):
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": CSP,
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            }
        )
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        return JSONResponse(
            {"detail": "Invalid request parameters or event structure"}, status_code=422
        )

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/events":
            try:
                authorize(request.headers.get("authorization", ""))
            except HTTPException as exc:
                return secure(
                    JSONResponse(
                        {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
                    ),
                    request,
                )
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 2_000_000:
                    return secure(
                        JSONResponse({"detail": "Request too large"}, status_code=413), request
                    )
                body.extend(chunk)
            try:
                check_json_depth(body)
            except ValueError:
                return secure(
                    JSONResponse({"detail": "JSON nesting exceeds limits"}, status_code=413),
                    request,
                )
            try:

                def reject_constant(_):
                    raise ValueError("Non-finite JSON")

                payload = json.loads(body, parse_constant=reject_constant)
            except (ValueError, RecursionError, UnicodeError):
                return secure(
                    JSONResponse({"detail": "Invalid finite JSON"}, status_code=422), request
                )
            try:
                validate_shape(payload)
                if isinstance(payload, list) and (
                    len(payload) > 1000
                    or any(len(canonical(item)) > MAX_EVENT_BYTES for item in payload)
                ):
                    raise ValueError("Batch or event limit exceeded")
            except (RecursionError, UnicodeError):
                return secure(
                    JSONResponse({"detail": "Invalid JSON encoding"}, status_code=422), request
                )
            except json.JSONDecodeError:
                return secure(JSONResponse({"detail": "Invalid JSON"}, status_code=422), request)
            except ValueError:
                return secure(
                    JSONResponse(
                        {"detail": "JSON exceeds limits or contains non-finite values"},
                        status_code=413,
                    ),
                    request,
                )
            request._body = bytes(body)
        return secure(await call_next(request), request)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        available()
        try:
            if not lake.ready():
                raise OSError("unavailable")
        except (OSError, ValueError, sqlite3.Error):
            raise HTTPException(503, "Lake unavailable") from None
        return {"status": "ready"}

    def pipeline_value():
        if projection:
            return {
                "status": "request-synchronized" if projection.ready else "unavailable",
                "last_replayed_at": projection.last_success,
                "profile": "request-triggered read-only replay",
            }
        heartbeat = lake.root / "worker-heartbeat.json"
        if not heartbeat.exists():
            return {"status": "unknown", "reason": "No successful source poll observed"}
        try:
            value = json.loads(heartbeat.read_text())
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(value["last_success"])
            ).total_seconds()
        except (OSError, ValueError, KeyError, TypeError):
            return {"status": "unknown", "reason": "Heartbeat unavailable"}
        return {**value, "age_seconds": age, "status": "fresh" if 0 <= age < 60 else "stale"}

    @app.get("/pipeline", dependencies=[Depends(authorize)])
    def pipeline():
        return pipeline_value()

    @app.get("/openapi.json", dependencies=[Depends(authorize)])
    def openapi():
        return app.openapi()

    @app.post("/events", dependencies=[Depends(authorize)])
    def ingest(events: list[dict]):
        if projection:
            raise HTTPException(403, "Fixture writes disabled for source-backed request projection")
        if len(events) > 1000:
            raise HTTPException(413, "Maximum batch is 1000 events")
        try:
            return lake.apply(events)
        except (ValueError, RecursionError):
            raise HTTPException(422, "Events must contain bounded finite JSON values") from None

    @app.get("/transactions", dependencies=[Depends(authorize), Depends(available)])
    def transactions(
        limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0, le=1_000_000)
    ):
        return read(lambda: lake.current(limit=limit, offset=offset))

    @app.get("/gold", dependencies=[Depends(authorize), Depends(available)])
    def gold():
        return read(lake.gold)

    @app.get("/schema", dependencies=[Depends(authorize), Depends(available)])
    def schema():
        return read(lake.schema)

    @app.get("/quarantine", dependencies=[Depends(authorize)])
    def quarantine(
        limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0, le=1_000_000)
    ):
        return lake.quarantine(limit, offset)

    @app.get("/metrics", dependencies=[Depends(authorize), Depends(available)])
    def metrics():
        registry = CollectorRegistry()
        counter = Gauge(
            "fluxlake_events_total",
            "Durable delivery outcomes including replay",
            ["outcome"],
            registry=registry,
        )
        for outcome, count in lake.stats().items():
            counter.labels(outcome=outcome).set(count)
        Gauge(
            "fluxlake_current_transactions", "Live rows in silver snapshot", registry=registry
        ).set(read(lake.row_count))
        return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")

    @app.get("/demo/summary")
    def demo():
        if not public_demo:
            raise HTTPException(404, "Public synthetic demo is disabled")
        available()
        with cache_lock:
            now = time.monotonic()
            if now >= cached["until"] or (
                projection and cached.get("source_sync") != projection.last_success
            ):
                cached["value"] = {
                    "synthetic": True,
                    "label": "Explicitly marked synthetic demonstration data only",
                    "capture": "PostgreSQL outbox request-triggered replay"
                    if projection
                    else "PostgreSQL transactional outbox polling",
                    "gold": read(lake.demo_gold),
                    "source_status": pipeline_value()["status"],
                    "cache_seconds": 5,
                }
                cached["until"] = now + 5
                cached["source_sync"] = projection.last_success if projection else None
            return cached["value"]

    @app.get("/assets/dashboard.css", include_in_schema=False)
    def css():
        return Response(CSS, media_type="text/css")

    @app.get("/assets/dashboard.js", include_in_schema=False)
    def javascript():
        return Response(JS, media_type="text/javascript")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard():
        return """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
        <title>FluxLake synthetic demo</title><link rel=stylesheet href=/assets/dashboard.css>
        <small>TRANSACTION CDC LAKEHOUSE</small><h1>FluxLake</h1>
        <p>PostgreSQL outbox → immutable bronze → Parquet silver → SQL gold</p>
        <p>This public view contains only explicitly marked <strong>synthetic demonstration data</strong>. Operational rows, metrics and administrative actions require authentication.</p>
        <h2>Synthetic settled volume by currency</h2><pre id=summary>Loading actual lake data…</pre>
        <script src=/assets/dashboard.js defer></script></html>"""

    return app
