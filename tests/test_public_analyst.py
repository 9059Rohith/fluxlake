"""Public-demo security and persistent-budget regressions; provider fixtures are test only."""

import hashlib
import hmac
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from fluxlake.api import create_app
from fluxlake.public_demo import DemoLimitExceeded, PersistentDemoLimiter, client_digest

TOKEN = "public-demo-test-secret-01234567890123456789"


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("FLUXLAKE_DEMO_RATE_SQLITE", str(tmp_path / "rate.sqlite"))
    monkeypatch.setenv("FLUXLAKE_AI_KEY", "test-only-provider")
    monkeypatch.setenv("FLUXLAKE_AI_MODEL", "test-only-model")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-free-provider")
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    app = create_app(tmp_path / "lake")
    calls = []

    def provider(messages, tools, choice):
        calls.append(choice)
        if choice == "required":
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "test-call",
                        "type": "function",
                        "function": {"name": "lake_overview", "arguments": "{}"},
                    }
                ],
            }
        assert __import__("json").loads(messages[-1]["content"])["counts"]["events"] == 17
        return {
            "role": "assistant",
            "content": "The retained public sample contains 17 events. Source: /api/workspace/overview.",
        }

    monkeypatch.setattr("fluxlake.workspace_agent.call_provider", provider)
    monkeypatch.setattr(app.state.public_workspace, "overview", lambda: {"counts": {"events": 17}})
    return app, TestClient(app, client=("192.0.2.9", 12345)), calls


def post(client, **kwargs):
    return client.post(
        "/api/workspace/agent/demo",
        json={"question": "Count the retained public event sample"},
        **kwargs,
    )


def test_anonymous_demo_uses_actual_tool_loop_and_shared_limits(demo):
    app, client, calls = demo
    first, second = post(client), post(client)
    assert first.status_code == second.status_code == 200
    assert (
        first.json()["tool_calls"] == 1
        and first.json()["trace"][0]["result"]["counts"]["events"] == 17
    )
    assert first.json()["demo"] is True
    assert calls == ["required", "auto", "required", "auto"]
    third = post(client)
    assert third.status_code == 429 and int(third.headers["Retry-After"]) > 0
    assert len(calls) == 4
    assert third.headers["Cache-Control"] == "no-store"
    assert client.post("/api/workspace/ingest").status_code == 401
    assert client.post("/api/workspace/agent", json={"question": "Count events"}).status_code == 401


def test_public_input_and_origin_fail_before_provider(demo):
    _, client, calls = demo
    assert post(client, headers={"Origin": "https://attacker.example"}).status_code == 403
    assert post(client, headers={"Origin": "null"}).status_code == 403
    assert post(client, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    for body in (
        {"question": "x" * 601},
        {"question": "Count events", "model": "other"},
        {"question": "      "},
    ):
        assert client.post("/api/workspace/agent/demo", json=body).status_code == 422
    assert client.post("/api/workspace/agent/demo", content="x" * 4097).status_code == 413
    assert not calls
    assert post(client, headers={"Origin": "http://testserver"}).status_code == 200


def test_public_never_uses_paid_legacy_adapter_but_private_adapter_still_works(demo, monkeypatch):
    app, client, calls = demo
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    response = post(client)
    assert response.status_code == 503
    assert not calls
    with sqlite3.connect(app.state.public_demo_limiter.sqlite_path) as conn:
        assert conn.execute("SELECT count(*) FROM flux_public_demo_limits").fetchone()[0] == 0
    private = client.post(
        "/api/workspace/agent",
        json={"question": "Count the retained public sample"},
        headers={"Authorization": "Bearer " + TOKEN},
    )
    assert private.status_code == 200 and private.json()["provider"] == "OpenAI"
    assert calls == ["required", "auto"]


def test_forwarded_headers_are_trusted_only_on_vercel(demo, monkeypatch):
    app, client, calls = demo
    assert post(client, headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 200
    assert post(client, headers={"X-Forwarded-For": "198.51.100.8"}).status_code == 200
    assert post(client, headers={"X-Forwarded-For": "198.51.100.9"}).status_code == 429
    with sqlite3.connect(app.state.public_demo_limiter.sqlite_path) as conn:
        keys = conn.execute(
            "SELECT bucket_key FROM flux_public_demo_limits WHERE bucket_key LIKE 'client:%'"
        ).fetchall()
    assert keys == [("client:" + client_digest("192.0.2.9", TOKEN),)]
    monkeypatch.setenv("VERCEL", "1")
    assert (
        post(client, headers={"X-Forwarded-For": "198.51.100.1, 198.51.100.2"}).status_code == 400
    )
    assert post(client, headers={"X-Forwarded-For": "not-an-ip"}).status_code == 400
    assert len(calls) == 4


def test_hash_identity_has_no_raw_ip_or_credential():
    value = client_digest("192.0.2.9", TOKEN)
    assert len(value) == 64 and "192.0.2.9" not in value
    assert value == hmac.new(TOKEN.encode(), b"192.0.2.9", hashlib.sha256).hexdigest()


def test_trusted_vercel_identity_uses_one_valid_overwritten_address(monkeypatch):
    from starlette.requests import Request
    from fluxlake.public_demo import request_identity

    request = Request(
        {
            "type": "http",
            "client": ("192.0.2.9", 1234),
            "headers": [(b"x-forwarded-for", b"198.51.100.7")],
        }
    )
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    monkeypatch.delenv("VERCEL", raising=False)
    assert request_identity(request) == client_digest("192.0.2.9", TOKEN)
    monkeypatch.setenv("VERCEL", "1")
    assert request_identity(request) == client_digest("198.51.100.7", TOKEN)


def test_persistent_budgets_survive_restart_and_separate_client_from_global(tmp_path):
    now = [1800000005]
    path = tmp_path / "rates.sqlite"
    limiter = PersistentDemoLimiter("", sqlite_path=path, clock=lambda: now[0])
    limiter.reserve("a" * 64)
    limiter.reserve("b" * 64)
    restarted = PersistentDemoLimiter("", sqlite_path=path, clock=lambda: now[0])
    with pytest.raises(DemoLimitExceeded):
        restarted.reserve("c" * 64)
    now[0] += 60
    restarted.reserve("a" * 64)
    restarted.reserve("a" * 64)
    now[0] += 60
    with pytest.raises(DemoLimitExceeded) as exc:
        restarted.reserve("a" * 64)
    assert exc.value.retry_after > 60
    with sqlite3.connect(path) as conn:
        assert all(
            "192.0.2.9" not in str(row)
            for row in conn.execute("SELECT * FROM flux_public_demo_limits")
        )


def test_atomic_concurrent_reservations_never_exceed_shared_budget(tmp_path):
    path = tmp_path / "concurrent.sqlite"
    limiter = PersistentDemoLimiter("", sqlite_path=path, clock=lambda: 1800000005)

    def attempt(index):
        try:
            limiter.reserve(hashlib.sha256(str(index).encode()).hexdigest())
            return True
        except DemoLimitExceeded:
            return False

    with ThreadPoolExecutor(max_workers=12) as executor:
        assert sum(executor.map(attempt, range(24))) == 2


def test_global_daily_budget_and_database_failure_fail_closed(tmp_path, monkeypatch):
    now = [1800000005]
    limiter = PersistentDemoLimiter("", sqlite_path=tmp_path / "daily.sqlite", clock=lambda: now[0])
    for index in range(30):
        if index and index % 2 == 0:
            now[0] += 60
        limiter.reserve(hashlib.sha256(str(index).encode()).hexdigest())
    now[0] += 60
    with pytest.raises(DemoLimitExceeded) as exc:
        limiter.reserve("f" * 64)
    assert exc.value.retry_after > 600
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FLUXLAKE_DEMO_RATE_SQLITE", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-free-provider")
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setattr(
        "fluxlake.workspace_web.run_agent",
        lambda *_: pytest.fail("Provider must not run when budget storage is unavailable"),
    )
    app = create_app(tmp_path / "unconfigured")
    client = TestClient(app, client=("192.0.2.9", 12345))
    assert post(client).status_code == 503
