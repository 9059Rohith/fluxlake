import io
import json
from urllib.error import HTTPError

import pytest

from fluxlake.workspace_agent import (
    AgentQuotaExceeded,
    call_provider,
    provider_status,
    retry_interval,
    run_agent,
)


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-private-key")
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.delenv("FLUXLAKE_AI_MODEL", raising=False)


def test_gemini_status_never_exposes_key(gemini):
    status = provider_status()
    assert status["configured"] is True
    assert status["provider"] == "Google Gemini"
    assert status["model"] == "gemini-3.5-flash-lite"
    assert "test-only-private-key" not in json.dumps(status)


def test_explicit_provider_does_not_fall_back_to_another_account(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("FLUXLAKE_AI_KEY", "test-only-other-account")
    monkeypatch.setenv("FLUXLAKE_AI_MODEL", "test-model")
    assert provider_status()["configured"] is False
    monkeypatch.setenv("AI_PROVIDER", "arbitrary-endpoint")
    assert provider_status()["configured"] is False


def test_fixed_gemini_endpoint_and_server_side_authorization(gemini, monkeypatch):
    captured = []

    class Reply(io.BytesIO):
        pass

    class Opener:
        def open(self, request, timeout):
            captured.append(request)
            return Reply(
                json.dumps(
                    {"choices": [{"message": {"role": "assistant", "content": "test-only"}}]}
                ).encode()
            )

    monkeypatch.setattr("fluxlake.workspace_agent.build_opener", lambda *_: Opener())
    assert call_provider([], []) == {"role": "assistant", "content": "test-only"}
    request = captured[0]
    assert (
        request.full_url
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert request.get_header("Authorization") == "Bearer test-only-private-key"
    assert json.loads(request.data)["model"] == "gemini-3.5-flash-lite"


def test_gemini_opaque_signatures_survive_tool_round_trip_but_not_user_trace(gemini):
    assistant = {
        "role": "assistant",
        "content": None,
        "extra_content": {"google": {"test_metadata": True}},
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "lake_overview", "arguments": "{}"},
                "extra_content": {"google": {"thought_signature": "test-only-opaque-signature"}},
            }
        ],
    }
    seen = []

    class Store:
        def overview(self):
            return {"counts": {"events": 10}}

    def provider(messages, tools, choice):
        seen.append(choice)
        if len(seen) == 1:
            return assistant
        assert messages[-2] is assistant
        assert (
            messages[-2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"]
            == "test-only-opaque-signature"
        )
        assert json.loads(messages[-1]["content"])["counts"]["events"] == 10
        assert json.loads(messages[-1]["content"])["source_api"] == "/api/workspace/overview"
        return {"role": "assistant", "content": "The test store contains ten events."}

    result = run_agent(Store(), "Count the retained events", provider=provider)
    assert result["provider"] == "Google Gemini"
    assert result["tool_calls"] == 1
    assert "thought_signature" not in json.dumps(result)
    assert "test-only-opaque-signature" not in json.dumps(result)


def test_quota_retries_once_when_short_and_honors_long_retry_after(gemini, monkeypatch):
    calls, sleeps = [], []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            raise HTTPError(
                request.full_url,
                429,
                "quota",
                {"Retry-After": "2"},
                io.BytesIO(b"private provider error"),
            )

    monkeypatch.setattr("fluxlake.workspace_agent.build_opener", lambda *_: Opener())
    monkeypatch.setattr("fluxlake.workspace_agent.time.sleep", sleeps.append)
    with pytest.raises(AgentQuotaExceeded) as exc:
        call_provider([], [])
    assert len(calls) == 2 and sleeps == [2]
    assert exc.value.retry_after == 2
    assert "private provider error" not in str(exc.value)

    class LongQuota:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 429, "quota", {"Retry-After": "90"}, io.BytesIO())

    monkeypatch.setattr("fluxlake.workspace_agent.build_opener", lambda *_: LongQuota())
    with pytest.raises(AgentQuotaExceeded) as exc:
        call_provider([], [])
    assert exc.value.retry_after == 90 and sleeps == [2]
    assert retry_interval("nonsense") == 1
    assert retry_interval("NaN") == 60


def test_authenticated_quota_response_preserves_retry_header(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from fluxlake.api import create_app

    token = "test-only-quota-token-01234567890123456789"
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", token)

    def limited(*_):
        raise AgentQuotaExceeded(90)

    monkeypatch.setattr("fluxlake.workspace_web.run_agent", limited)
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/workspace/agent",
        json={"question": "Inspect the retained sample"},
        headers={"Authorization": "Bearer " + token},
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "90"
    assert response.headers["Cache-Control"] == "no-store"
    assert (
        client.post("/api/workspace/agent", json={"question": "Inspect the sample"}).status_code
        == 401
    )
