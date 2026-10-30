from __future__ import annotations

import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from fluxlake.lake import Lake


def create_app(root: Path | str | None = None) -> FastAPI:
    lake = Lake(root or os.getenv("FLUXLAKE_ROOT", "data"))
    app = FastAPI(
        title="FluxLake",
        version="0.1.0",
        description="Transactional outbox → Parquet → gold SQL. Write routes require a bearer token.",
    )

    def authorize(authorization: str = Header(default="")):
        try:
            token = os.getenv("FLUXLAKE_API_TOKEN", "").strip().encode("utf-8")
        except UnicodeError:
            token = b""
        if not token or len(token) > 4096:
            raise HTTPException(503, "Write access disabled: token is not configured")
        try:
            presented = authorization.encode("utf-8")
        except UnicodeError:
            presented = b""
        if len(presented) > 4103 or not hmac.compare_digest(presented, b"Bearer " + token):
            raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    @app.middleware("http")
    async def bound_request(request: Request, call_next):
        # Stream with a bound even when Content-Length is absent or forged.
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    return Response("Request too large", status_code=413)
            request._body = bytes(body)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        try:
            if not lake.ready():
                raise OSError("lake is not ready")
        except (OSError, ValueError):
            raise HTTPException(503, "Lake unavailable") from None
        return {"status": "ready", "scope": "local storage; source freshness is /pipeline"}

    @app.get("/pipeline")
    def pipeline():
        heartbeat = lake.root / "worker-heartbeat.json"
        if not heartbeat.exists():
            return {"status": "unknown", "reason": "No successful source poll observed"}
        value = json.loads(heartbeat.read_text())
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(value["last_success"])
        ).total_seconds()
        return {**value, "age_seconds": age, "status": "fresh" if age < 60 else "stale"}

    @app.post("/events", dependencies=[Depends(authorize)])
    def ingest(events: list[dict]):
        if len(events) > 1000:
            raise HTTPException(413, "Maximum batch is 1000 events")
        try:
            return lake.apply(events)
        except ValueError:
            raise HTTPException(422, "Events must contain finite JSON values") from None

    @app.get("/transactions")
    def transactions():
        return lake.current()

    @app.get("/gold")
    def gold():
        return lake.gold()

    @app.get("/schema")
    def schema():
        return lake.schema()

    @app.get("/quarantine", dependencies=[Depends(authorize)])
    def quarantine():
        return lake.quarantine()

    @app.get("/metrics")
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
        ).set(len(lake.current()))
        return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return """<!doctype html><html lang=en><meta charset=utf-8>
        <meta name=viewport content='width=device-width,initial-scale=1'><title>FluxLake</title>
        <style>body{background:#0d1523;color:#ecf5ff;font:16px system-ui;max-width:1000px;margin:60px auto;padding:24px}h1{font-size:48px}small{color:#7de0cc}pre{background:#162337;padding:24px;overflow:auto;border-radius:12px}a{color:#7de0cc}</style>
        <small>TRANSACTION CDC LAKEHOUSE</small><h1>FluxLake</h1>
        <p>PostgreSQL outbox → immutable bronze → Parquet silver → SQL gold</p>
        <p><a href=/docs>API documentation</a> · <a href=/metrics>Prometheus metrics</a></p>
        <h2>Gold: settled volume by currency</h2><pre id=gold>Loading…</pre>
        <h2>Source worker freshness</h2><pre id=pipeline>Loading…</pre>
        <script>async function refresh(){for(const p of ['gold','pipeline']){
        try{document.getElementById(p).textContent=JSON.stringify(await(await fetch('/'+p)).json(),null,2)}
        catch(e){document.getElementById(p).textContent='Unavailable'}}}refresh();setInterval(refresh,5000)</script></html>"""

    return app
