"""Public workspace routes and CSP-compatible, code-native analytical UI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from fluxlake.public_demo import (
    POLICY,
    DemoBudgetUnavailable,
    DemoLimitExceeded,
    PersistentDemoLimiter,
    check_origin,
    request_identity,
)

from fluxlake.workspace import IngestionBusy, PublicWorkspace, WorkspaceUnavailable
from fluxlake.workspace_agent import (
    AgentQuotaExceeded,
    AgentUnavailable,
    provider_status,
    run_agent,
)

PAGES = {
    "overview": (
        "Overview",
        "Your data, from source to signal.",
        "Trace a real public event sample through every layer of the lake.",
    ),
    "sources": (
        "Sources",
        "Know where every event begins.",
        "One verified public source, with acquisition boundaries and original provenance.",
    ),
    "ingestion": (
        "Ingestion",
        "Bring the next sample into the lake.",
        "A bounded acquisition writes immutable bronze and typed silver in one database transaction.",
    ),
    "bronze": (
        "Bronze archive",
        "The original event. Preserved.",
        "Inspect canonical JSON, acquisition time and SHA-256 evidence for every retained event.",
    ),
    "silver": (
        "Silver explorer",
        "Find the event behind the number.",
        "Search validated public events by repository, actor or event identity.",
    ),
    "gold": (
        "Gold analytics",
        "Turn retained events into a clear signal.",
        "SQL aggregates across the observed sample. Every total leads back to evidence.",
    ),
    "schema": (
        "Schema registry",
        "Make change visible at the boundary.",
        "Observed JSON field types alongside the explicit silver validation contract.",
    ),
    "drift": (
        "Distribution drift",
        "Compare two acquisitions, precisely.",
        "Inspect event-type mix across two retained runs, with descriptive distance and sample limits.",
    ),
    "quarantine": (
        "Quarantine",
        "Keep invalid data out of the signal.",
        "Rejected records carry a reason, run and evidence hash. Silver stays within contract.",
    ),
    "runs": (
        "Run history",
        "Every acquisition leaves a receipt.",
        "Inspect outcomes, duplicates, upstream status and response fingerprints.",
    ),
    "lineage": (
        "Lineage",
        "Follow one event all the way through.",
        "Look up an identity to connect source evidence, the acquisition run and typed analytics.",
    ),
    "agent": (
        "Lake analyst",
        "Ask a question. Inspect the evidence.",
        "A provider-backed analyst selects bounded read-only tools and shows the results behind its answer.",
    ),
    "access": (
        "Operator access",
        "Connect your operator session.",
        "Public exploration is open. Acquisition and private operating tools require the existing bearer token.",
    ),
}


class AgentQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=5, max_length=1200)


class PublicAgentQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=5, max_length=600)

    @field_validator("question")
    @classmethod
    def meaningful_question(cls, value):
        value = value.strip()
        if len(value) < 5:
            raise ValueError("Ask a question about the retained public sample")
        return value


def page_html(key):
    title, headline, description = PAGES[key]
    groups = [
        ("WORKSPACE", ["overview", "sources", "ingestion"]),
        ("DATA LAYERS", ["bronze", "silver", "gold"]),
        ("OBSERVABILITY", ["schema", "drift", "quarantine", "runs", "lineage"]),
        ("INTELLIGENCE", ["agent"]),
    ]
    navigation = ""
    for label, keys in groups:
        navigation += f'<p class="nav-label">{label}</p>'
        for item in keys:
            active = ' aria-current="page"' if item == key else ""
            navigation += f'<a href="/workspace/{item}"{active}><span class="nav-mark">{ {"overview": "◈", "sources": "↗", "ingestion": "↓", "bronze": "▤", "silver": "▥", "gold": "◫", "schema": "⌘", "drift": "≈", "quarantine": "◇", "runs": "◷", "lineage": "⌁", "agent": "✧"}[item] }</span>{PAGES[item][0]}</a>'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="description" content="Explore a real public GitHub event sample through immutable bronze, validated silver and SQL analytics.">
    <title>{title} · FluxLake</title><link rel="icon" href="/assets/mark.svg" type="image/svg+xml">
    <link rel="stylesheet" href="/assets/workspace.css"><script src="/assets/workspace.js" defer></script></head>
    <body data-page="{key}"><a class="skip" href="#main">Skip to content</a>
    <aside class="sidebar"><a class="brand" href="/"><span class="brand-mark">F</span>FluxLake<span class="brand-dot"></span></a><button class="sidebar-close" id="close-navigation" aria-label="Close navigation">×</button>
    <div class="workspace-switch"><span class="workspace-avatar">G</span><div>Public observatory<small>GitHub events</small></div><span class="switch-arrow">⌄</span></div>
    <nav aria-label="Workspace">{navigation}</nav>
    <div class="sidebar-foot"><div class="source-indicator"><span></span>Public source · real evidence</div><a href="/workspace/access">Operator access <span>↗</span></a><small>Sampled events. Honest boundaries.</small></div></aside>
    <div class="app"><header class="topbar"><button id="menu-toggle" class="menu-toggle" aria-label="Toggle navigation" aria-expanded="false">☰</button><div class="breadcrumb">Workspace <span>/</span> <strong>{title}</strong></div><a class="top-source" href="https://docs.github.com/en/rest/activity/events#list-public-events" target="_blank" rel="noopener">GitHub source ↗</a></header>
    <main id="main"><div class="page-heading"><div><h1>{headline}</h1><p>{description}</p></div><button id="refresh" class="button secondary" aria-label="Refresh current data">↻ <span>Refresh</span></button></div>
    <div id="notice" role="status" aria-live="polite"></div><div id="content"><div class="loading"><span class="spinner"></span>Reading the public event store…</div></div>
    <footer>FluxLake <span>·</span> PostgreSQL evidence → typed events → SQL insight <a href="/api/workspace/overview">View source JSON ↗</a></footer>
    </main></div><dialog id="detail"><div class="dialog-head"><h2 id="detail-title">Event evidence</h2><button class="icon-button" id="close-detail" aria-label="Close details">×</button></div><div id="detail-body"></div></dialog></body></html>'''


def install_workspace(app, authorize):
    store = PublicWorkspace()
    app.state.public_workspace = store
    app.state.public_demo_limiter = PersistentDemoLimiter(
        store.database_url,
        sqlite_path=os.getenv("FLUXLAKE_DEMO_RATE_SQLITE") if os.getenv("VERCEL") != "1" else None,
    )

    def query(operation):
        try:
            return operation()
        except WorkspaceUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except IngestionBusy as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "60"}) from None

    @app.get("/api/workspace/overview")
    def overview():
        return query(store.overview)

    @app.get("/api/workspace/sources")
    def sources():
        return query(store.sources)

    @app.get("/api/workspace/events/{event_id}")
    def event(event_id: str):
        if not event_id.isdigit() or len(event_id) > 30:
            raise HTTPException(422, "A bounded numeric GitHub event identity is required")
        row = query(lambda: store.event(event_id))
        if not row:
            raise HTTPException(404, "Event is not present in the retained public sample")
        return row

    @app.get("/api/workspace/{layer}")
    def layer_rows(
        layer: Literal["bronze", "silver"],
        q: str = Query("", max_length=100),
        event_type: str = Query("", max_length=80),
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100000),
    ):
        return query(lambda: store.events(layer, q, event_type, limit, offset))

    # Specific routes must precede the dynamic layer route in Starlette. Move the
    # dynamic route to the end after defining the remaining exact API paths.
    layer_route = app.router.routes.pop()

    @app.get("/api/workspace/gold")
    def gold(group: Literal["repository", "actor", "event_type"] = "repository"):
        return query(lambda: store.gold(group))

    @app.get("/api/workspace/schema")
    def schema():
        return query(store.schema)

    @app.get("/api/workspace/quarantine")
    def quarantine():
        return query(store.quarantine)

    @app.get("/api/workspace/runs")
    def runs():
        return query(store.runs)

    @app.get("/api/workspace/drift")
    def drift(
        baseline: str | None = Query(None, max_length=36),
        candidate: str | None = Query(None, max_length=36),
    ):
        try:
            return query(lambda: store.drift(baseline, candidate))
        except ValueError:
            raise HTTPException(422, "Choose two different successful nonempty runs") from None

    @app.get("/api/workspace/export.csv")
    def export(q: str = Query("", max_length=100), event_type: str = Query("", max_length=80)):
        return Response(
            query(lambda: store.export(q, event_type)),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="fluxlake-public-events.csv"'},
        )

    @app.get("/api/workspace/agent/status")
    def agent_status():
        return {
            **provider_status(),
            "demo_endpoint": "/api/workspace/agent/demo",
            "demo_limits": POLICY,
            "client_identity_source": "vercel-overwritten-x-forwarded-for"
            if os.getenv("VERCEL") == "1"
            else "socket-peer",
            "vercel_runtime": os.getenv("VERCEL") == "1",
        }

    @app.post("/api/workspace/ingest", dependencies=[Depends(authorize)])
    def ingest():
        return query(store.ingest)

    @app.post("/api/workspace/migrate", dependencies=[Depends(authorize)])
    def migrate():
        # An explicit, authenticated, idempotent schema initialization; never
        # triggered by a public GET or by the model's read-only tool surface.
        def initialize():
            with store.connection(write=True) as conn:
                conn.execute(Path("sql/workspace.sql").read_text())
            return {"status": "initialized", "scope": "public GitHub event workspace only"}

        return query(initialize)

    @app.post("/api/workspace/agent", dependencies=[Depends(authorize)])
    def agent(question: AgentQuestion):
        try:
            return run_agent(store, question.question)
        except AgentQuotaExceeded as exc:
            raise HTTPException(
                429, str(exc), headers={"Retry-After": str(exc.retry_after)}
            ) from None
        except AgentUnavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.post("/api/workspace/agent/demo")
    def public_agent(question: PublicAgentQuestion, request: Request):
        check_origin(request)
        identity = request_identity(request)
        try:
            budget = app.state.public_demo_limiter.reserve(identity)
        except DemoLimitExceeded as exc:
            raise HTTPException(
                429, str(exc), headers={"Retry-After": str(exc.retry_after)}
            ) from None
        except DemoBudgetUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        # Reservation occurs before any model call; failed provider attempts also
        # consume a slot. Public tools and output budgets are the same bounded loop.
        try:
            return {**run_agent(store, question.question), "demo": True, "demo_budget": budget}
        except AgentQuotaExceeded as exc:
            raise HTTPException(
                429, str(exc), headers={"Retry-After": str(exc.retry_after)}
            ) from None
        except AgentUnavailable as exc:
            raise HTTPException(503, str(exc)) from None

    app.router.routes.append(layer_route)

    @app.get("/assets/workspace.css", include_in_schema=False)
    def style():
        return Response(
            (Path(__file__).parent / "web" / "workspace.css").read_text(encoding="utf-8"),
            media_type="text/css",
        )

    @app.get("/assets/workspace.js", include_in_schema=False)
    def script():
        return Response(
            (Path(__file__).parent / "web" / "workspace.js").read_text(encoding="utf-8"),
            media_type="text/javascript",
        )

    @app.get("/assets/mark.svg", include_in_schema=False)
    def mark():
        return Response(
            '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" rx="8" fill="#17a891"/><path d="M10 24V8h14v4H14v3h8v4h-8v5" fill="white"/></svg>',
            media_type="image/svg+xml",
        )

    @app.get("/workspace/{page}", response_class=HTMLResponse, include_in_schema=False)
    def workspace_page(page: str):
        if page not in PAGES:
            raise HTTPException(404, "Workspace page not found")
        return page_html(page)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home():
        return page_html("overview")
