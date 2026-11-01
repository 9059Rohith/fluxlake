"""Boundary and tool-loop tests. Fixtures are test-only; never public application data."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from fluxlake.api import create_app
from fluxlake.workspace import (
    PublicWorkspace,
    WorkspaceUnavailable,
    canonical,
    normalize,
    schema_paths,
)
from fluxlake.workspace_agent import AgentUnavailable, execute_tool, run_agent
from fluxlake.workspace_web import PAGES

TOKEN = "workspace-test-token-012345678901234567890"
AUTH = {"Authorization": "Bearer " + TOKEN}


def public_event():
    return {
        "id": "123456789",
        "type": "PushEvent",
        "public": True,
        "created_at": "2026-11-01T00:00:00Z",
        "actor": {"login": "test-actor"},
        "repo": {"name": "test-owner/test-repo"},
        "payload": {"ref": "refs/heads/main"},
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FLUXLAKE_AI_KEY", raising=False)
    monkeypatch.delenv("FLUXLAKE_AI_MODEL", raising=False)
    return TestClient(create_app(tmp_path))


def test_all_distinct_workspace_pages_and_assets_are_served(client):
    assert len(PAGES) >= 10
    titles = set()
    for page in PAGES:
        response = client.get("/workspace/" + page)
        assert response.status_code == 200
        assert f'data-page="{page}"' in response.text
        assert "unsafe-inline" not in response.headers["content-security-policy"]
        titles.add(response.text.split("<title>")[1].split("</title>")[0])
    assert len(titles) == len(PAGES)
    assert client.get("/workspace/not-a-page").status_code == 404
    assert client.get("/assets/workspace.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/assets/workspace.css").headers["content-type"].startswith("text/css")


def test_public_workspace_never_reads_private_projection(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Private CDC access from public route")

    monkeypatch.setattr("fluxlake.api.SourceProjection.refresh", forbidden)
    response = client.get("/api/workspace/overview")
    assert response.status_code == 503
    assert response.json()["detail"] == "Public data store is not configured"
    assert client.get("/demo/summary").status_code == 410
    assert client.get("/transactions").status_code == 401


def test_mutations_authenticate_before_body_parsing(client):
    for path in ("/api/workspace/ingest", "/api/workspace/agent", "/api/workspace/migrate"):
        assert client.post(path, content="[" * 10000).status_code == 401
        assert client.post(path, content="x" * 4097, headers=AUTH).status_code == 413
    assert (
        client.post(
            "/api/workspace/agent", json={"question": "short", "extra": True}, headers=AUTH
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/workspace/agent", json={"question": "Inspect the sample"}, headers=AUTH
        ).status_code
        == 503
    )


def test_provider_status_is_honest_and_no_secret_is_returned(client, monkeypatch):
    response = client.get("/api/workspace/agent/status")
    assert response.json()["configured"] is False
    monkeypatch.setenv("FLUXLAKE_AI_KEY", "private-test-secret")
    monkeypatch.setenv("FLUXLAKE_AI_MODEL", "test-model")
    response = client.get("/api/workspace/agent/status")
    assert response.json()["configured"] is True
    assert "private-test-secret" not in response.text


def test_api_filters_pagination_and_identifiers_are_bounded(client):
    for suffix in ("limit=101", "offset=-1", "q=" + "x" * 101):
        assert client.get("/api/workspace/silver?" + suffix).status_code == 422
    assert client.get("/api/workspace/gold?group=sql").status_code == 422
    assert client.get("/api/workspace/events/abc").status_code == 422
    assert client.get("/api/workspace/events/" + "1" * 31).status_code == 422
    assert client.get("/api/workspace/unknown").status_code == 422


def test_normalization_and_canonical_fingerprint():
    event = public_event()
    row = normalize(event)
    assert row[:4] == ("123456789", "PushEvent", "test-owner/test-repo", "test-actor")
    assert row[4].isoformat() == "2026-11-01T00:00:00+00:00"
    assert (
        hashlib.sha256(canonical(event)).hexdigest()
        == hashlib.sha256(canonical(dict(reversed(list(event.items()))))).hexdigest()
    )
    event["public"] = "true"
    with pytest.raises(ValueError, match="explicitly public"):
        normalize(event)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 123),
        ("id", "1;drop table"),
        ("type", "<script>"),
        ("repo", {"name": "https://private.internal/"}),
        ("actor", {"login": "<script>"}),
        ("created_at", "2026-11-01T00:00:00"),
        ("payload", []),
    ],
)
def test_invalid_public_events_do_not_reach_silver(field, value):
    event = public_event()
    event[field] = value
    with pytest.raises(ValueError):
        normalize(event)


def test_schema_observation_reports_types_not_values():
    paths = schema_paths(
        {"actor": {"login": "secret-value"}, "public": True, "payload": [1, 2], "optional": None}
    )
    assert ("actor.login", "string") in paths
    assert ("public", "boolean") in paths
    assert ("payload", "array") in paths
    assert ("optional", "null") in paths
    assert "secret-value" not in str(paths)


class EvidenceStore:
    def overview(self):
        return {"counts": {"events": 42}, "scope": "test-only retained sample"}

    def events(self, q="", limit=25):
        return {"rows": [], "total": 0, "query": q, "limit": limit}


def test_agent_requires_provider_and_does_not_fabricate(monkeypatch):
    monkeypatch.delenv("FLUXLAKE_AI_KEY", raising=False)
    with pytest.raises(AgentUnavailable, match="not configured"):
        run_agent(
            EvidenceStore(),
            "What is retained?",
            provider=lambda *_: pytest.fail("No provider call permitted"),
        )


def test_real_tool_loop_protocol_records_evidence_and_requires_a_tool(monkeypatch):
    monkeypatch.setenv("FLUXLAKE_AI_KEY", "test-only")
    monkeypatch.setenv("FLUXLAKE_AI_MODEL", "test-only")
    calls = []

    def protocol_fixture(messages, tools, choice):
        calls.append(choice)
        if len(calls) == 1:
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call1",
                        "type": "function",
                        "function": {"name": "lake_overview", "arguments": "{}"},
                    }
                ],
            }
        assert json.loads(messages[-1]["content"])["counts"]["events"] == 42
        return {"role": "assistant", "content": "The test-only retained sample contains 42 events."}

    result = run_agent(EvidenceStore(), "How many events?", provider=protocol_fixture)
    assert calls == ["required", "auto"]
    assert result["tool_calls"] == 1
    assert result["trace"][0]["source"] == "/api/workspace/overview"
    assert result["read_only"] is True
    with pytest.raises(AgentUnavailable, match="evidence-backed"):
        run_agent(
            EvidenceStore(), "How many?", provider=lambda *_: {"content": "Unsupported assertion"}
        )


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("execute_sql", {"sql": "DELETE"}),
        ("find_events", {"query": "x" * 101}),
        ("lake_overview", {"write": True}),
    ],
)
def test_agent_rejects_unknown_or_unbounded_tools(name, arguments):
    with pytest.raises(ValueError):
        execute_tool(EvidenceStore(), name, arguments)


def test_agent_excessive_tool_calls_stop_without_a_conclusion(monkeypatch):
    monkeypatch.setenv("FLUXLAKE_AI_KEY", "test-only")
    monkeypatch.setenv("FLUXLAKE_AI_MODEL", "test-only")
    tool = {
        "id": "test",
        "type": "function",
        "function": {"name": "lake_overview", "arguments": "{}"},
    }
    with pytest.raises(AgentUnavailable, match="six-tool"):
        run_agent(EvidenceStore(), "Inspect", provider=lambda *_: {"tool_calls": [tool] * 7})


def test_missing_store_is_explicit_and_never_returns_fixtures():
    with pytest.raises(WorkspaceUnavailable, match="not configured"):
        PublicWorkspace("").overview()
