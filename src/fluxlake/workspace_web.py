"""Public workspace routes and CSP-compatible, code-native analytical UI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from fluxlake.observatory_icons import icon, sprite
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
    public_gemini_configured,
    run_agent,
)

PAGES = {
    "overview": (
        "Overview",
        "Every event. A clearer signal.",
        "A public GitHub sample, from original evidence to analytical insight.",
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
    "replay": (
        "Replay audit",
        "Replay the evidence. Inspect the difference.",
        "Reconstruct retained public event publication, with exact differences and a downloadable audit.",
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
        "Ask the lake. Follow the evidence.",
        "A read-only analyst grounded in the public GitHub sample.",
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
        ("Workspace", ["overview", "sources", "ingestion"]),
        ("Data layers", ["bronze", "silver", "gold"]),
        ("Observability", ["schema", "drift", "replay", "quarantine", "runs", "lineage"]),
        ("Intelligence", ["agent"]),
    ]
    names = {
        "overview": "overview",
        "sources": "database",
        "ingestion": "upload",
        "bronze": "database",
        "silver": "layers",
        "gold": "overview",
        "schema": "file",
        "drift": "activity",
        "replay": "refresh",
        "quarantine": "warning",
        "runs": "clock",
        "lineage": "lineage",
        "agent": "message",
    }
    navigation = ""
    for label, keys in groups:
        navigation += f'<div class="nav-group"><p class="nav-label">{label}</p>'
        for item in keys:
            active = ' aria-current="page"' if item == key else ""
            navigation += f'<a href="/workspace/{item}"{active}>{icon(names[item])}<span>{PAGES[item][0]}</span></a>'
        navigation += "</div>"
    primary = (
        f'<a class="button" href="/workspace/agent">{icon("message")}Ask the lake analyst</a>'
        if key == "overview"
        else ""
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
    <meta name="description" content="A public GitHub sample, from original evidence to analytical insight. Explore real events, provenance and a bounded public analyst.">
    <title>{title} · FluxLake</title><link rel="icon" href="/assets/mark.svg" type="image/svg+xml">
    <link rel="preload" href="/assets/inter.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="stylesheet" href="/assets/workspace.css"><script src="/assets/observatory.js" defer></script><script src="/assets/workspace.js" defer></script></head>
    <body data-page="{key}"><a class="skip" href="#main">Skip to content</a>
    <aside class="sidebar" id="navigation" aria-label="Workspace navigation"><div class="brand-block"><a class="brand" href="/" aria-label="FluxLake overview"><svg class="brand-mark" viewBox="0 0 32 36" aria-hidden="true"><path d="M10 5h17M6 13h17M3 21h17M7 29h12"/></svg><span>FluxLake</span></a><p>Public observatory</p></div><button class="sidebar-close icon-button" id="close-navigation" aria-label="Close navigation">{icon("close")}</button>
    <nav aria-label="Workspace">{navigation}</nav>
    <div class="sidebar-foot"><a href="/workspace/access">{icon("user")}<span>Operator access</span>{icon("chevron")}</a><small>Public source. Inspectable evidence.</small></div></aside>
    <div class="nav-backdrop" id="nav-backdrop"></div>
    <div class="app"><header class="topbar"><button id="menu-toggle" class="menu-toggle icon-button" aria-label="Toggle navigation" aria-controls="navigation" aria-expanded="false">{icon("menu")}</button><div class="breadcrumb"><span>Workspace</span><span class="breadcrumb-separator">/</span><strong>{title}</strong></div><button id="command-trigger" class="command-trigger" aria-haspopup="dialog">{icon("search")}<span>Search the observatory</span><kbd>Ctrl K</kbd></button><a class="top-source" href="https://docs.github.com/en/rest/activity/events#list-public-events" target="_blank" rel="noopener">{icon("github")}<span>GitHub</span>{icon("external")}</a></header>
    <main id="main"><div class="page-heading"><div><h1>{headline}</h1><p>{description}</p></div><div class="heading-actions">{primary}<button id="refresh" class="button secondary" aria-label="Refresh current data">{icon("refresh")}<span>Refresh</span></button></div></div>
    <div id="notice" role="status" aria-live="polite"></div><div id="content" aria-busy="true"><div class="loading"><span class="spinner"></span>Reading actual source evidence…</div></div>
    <footer><span>FluxLake</span><span class="footer-rule"></span><span>Public GitHub sample · PostgreSQL evidence</span><a href="/api/workspace/overview">Source JSON {icon("external")}</a></footer>
    </main></div>
    <dialog id="detail" class="evidence-drawer" aria-labelledby="detail-title"><div class="dialog-head"><div><span class="drawer-context">SOURCE EVIDENCE</span><h2 id="detail-title">Event evidence</h2></div><button class="icon-button" id="close-detail" aria-label="Close details">{icon("close")}</button></div><div id="detail-body"></div></dialog>
    <dialog id="command-palette" class="command-dialog" aria-labelledby="command-title"><div class="command-input-row">{icon("search")}<label class="sr-only" id="command-title" for="command-query">Search pages and retained events</label><input id="command-query" autocomplete="off" maxlength="100" placeholder="Search pages, repositories, actors or event IDs…" role="combobox" aria-autocomplete="list" aria-expanded="true" aria-controls="command-results"><kbd>Esc</kbd><button id="close-command" class="icon-button" aria-label="Close search">{icon("close")}</button></div><div id="command-results" role="listbox" aria-label="Search results"></div><div class="command-footer"><span>Arrow keys to choose · Enter to open</span><span>Real retained evidence</span></div></dialog>
    </body></html>'''


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

    @app.get("/api/workspace/replay")
    def replay(
        response: Response,
        run: list[UUID] | None = Query(None, min_length=1, max_length=2),
        download: bool = False,
    ):
        selected = [str(identity) for identity in run] if run is not None else None
        if selected and len(set(selected)) != len(selected):
            raise HTTPException(422, "Choose one or two distinct acquisitions")
        report = query(lambda: store.replay(selected))
        if report is None:
            raise HTTPException(404, "Selected acquisition is not retained")
        if download:
            response.headers["Content-Disposition"] = (
                'attachment; filename="fluxlake-replay-evidence.json"'
            )
        return report

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
            "public_demo_configured": public_gemini_configured(),
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
        if not public_gemini_configured():
            raise HTTPException(
                503, "The free public Gemini analyst is unavailable. No paid provider is used."
            )
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

    @app.get("/assets/observatory.js", include_in_schema=False)
    def observatory_script():
        return Response(
            (Path(__file__).parent / "web" / "observatory.js").read_text(encoding="utf-8"),
            media_type="text/javascript",
        )

    @app.get("/assets/icons.svg", include_in_schema=False)
    def icons():
        return Response(sprite(), media_type="image/svg+xml")

    @app.get("/assets/inter.woff2", include_in_schema=False)
    def inter_font():
        return Response(
            (Path(__file__).parent / "web" / "inter.woff2").read_bytes(), media_type="font/woff2"
        )

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
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36"><rect width="36" height="36" rx="8" fill="#0d1421"/><path d="M12 7h16M7 15h17M5 23h17M10 30h10" fill="none" stroke="#a38bff" stroke-width="4" stroke-linecap="round"/></svg>',
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
