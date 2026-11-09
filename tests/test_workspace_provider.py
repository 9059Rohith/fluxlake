import io
import json
from urllib.error import HTTPError, URLError

import pytest

from fluxlake.workspace_agent import (
    AgentQuotaExceeded,
    AgentUnavailable,
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
    client = TestClient(create_app(tmp_path), client=("192.0.2.9", 12345))
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


@pytest.fixture
def transport(monkeypatch):
    """Replace only external HTTP and time; exercise the real provider/tool loop."""
    now, requests, sleeps, outcomes = [100.0], [], [], []

    class Opener:
        def open(self, request, timeout):
            requests.append((request, timeout))
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return io.BytesIO(json.dumps({"choices": [{"message": outcome}]}).encode())

    def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    monkeypatch.setattr("fluxlake.workspace_agent.build_opener", lambda *_: Opener())
    monkeypatch.setattr("fluxlake.workspace_agent.time.monotonic", lambda: now[0])
    monkeypatch.setattr("fluxlake.workspace_agent.time.sleep", sleep)
    return outcomes, requests, sleeps, now


def provider_error(status=503, retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return HTTPError(
        "https://provider.invalid/private-url",
        status,
        "private-message",
        headers,
        io.BytesIO(b"private-provider-body"),
    )


@pytest.mark.parametrize("failure", [500, 502, 503, 504, "network", "timeout"])
def test_transient_provider_failure_recovers_without_fabricating(gemini, transport, failure):
    outcomes, requests, sleeps, _ = transport
    failure = (
        URLError("private-network-detail")
        if failure == "network"
        else TimeoutError("private-timeout-detail")
        if failure == "timeout"
        else provider_error(failure)
    )
    outcomes.extend([failure, {"role": "assistant", "content": "provider-generated"}])
    assert call_provider([], [])["content"] == "provider-generated"
    assert len(requests) == 2 and sleeps == [1]
    assert all(
        request.full_url.startswith("https://generativelanguage.googleapis.com/")
        for request, _ in requests
    )


def test_persistent_transient_failure_has_bounded_redacted_logs(gemini, transport, caplog):
    outcomes, requests, sleeps, _ = transport
    outcomes.extend([provider_error()] * 4)
    with pytest.raises(AgentUnavailable) as error:
        call_provider([{"role": "user", "content": "private-question"}], [])
    assert len(requests) == 3 and sleeps == [1, 2]
    assert "status=503" in caplog.text and "HTTPError" in caplog.text
    for private in (
        "private-question",
        "private-provider-body",
        "private-message",
        "private-url",
        "test-only-private-key",
    ):
        assert private not in caplog.text + str(error.value)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_provider_failure_is_not_retried(gemini, transport, status):
    outcomes, requests, sleeps, _ = transport
    outcomes.append(provider_error(status))
    with pytest.raises(AgentUnavailable):
        call_provider([], [])
    assert len(requests) == 1 and not sleeps


@pytest.mark.parametrize("delay", ["90", "7200"])
def test_transient_retry_after_is_never_shortened(gemini, transport, delay):
    outcomes, requests, sleeps, _ = transport
    outcomes.append(provider_error(503, delay))
    with pytest.raises(AgentUnavailable) as error:
        call_provider([], [])
    assert getattr(error.value, "retry_after", None) == int(delay)
    assert len(requests) == 1 and not sleeps
    assert retry_interval(delay) == int(delay)


TOOL_MESSAGE = {
    "role": "assistant",
    "tool_calls": [
        {
            "id": "call-overview",
            "type": "function",
            "function": {"name": "lake_overview", "arguments": "{}"},
        }
    ],
}


class RecoveryStore:
    def overview(self):
        return {"counts": {"events": 17}}


def test_recovery_resumes_real_tool_loop_without_replaying_tools(gemini, transport):
    outcomes, requests, _, _ = transport
    outcomes.extend(
        [
            provider_error(),
            TOOL_MESSAGE,
            provider_error(502),
            {"role": "assistant", "content": "17 retained events."},
        ]
    )
    result = run_agent(RecoveryStore(), "Count retained events")
    assert result["answer"] == "17 retained events."
    assert result["tool_calls"] == 1 and len(result["trace"]) == 1
    assert len(requests) == 4
    assert json.loads(requests[-1][0].data)["messages"][-1]["role"] == "tool"


def test_retry_budget_is_shared_across_model_turns(gemini, transport):
    outcomes, requests, sleeps, _ = transport
    outcomes.extend(
        [
            provider_error(),
            TOOL_MESSAGE,
            provider_error(),
            TOOL_MESSAGE,
            provider_error(),
            {"role": "assistant", "content": "must not arrive"},
        ]
    )
    with pytest.raises(AgentUnavailable):
        run_agent(RecoveryStore(), "Count retained events")
    assert len(requests) == 5 and len(sleeps) == 2


@pytest.mark.parametrize("second_failure", [503, "network"])
def test_default_backoff_increases_across_model_turns(gemini, transport, second_failure):
    outcomes, requests, sleeps, _ = transport
    failure = (
        URLError("private-network-detail")
        if second_failure == "network"
        else provider_error(second_failure)
    )
    outcomes.extend(
        [
            provider_error(),
            TOOL_MESSAGE,
            failure,
            {"role": "assistant", "content": "17 retained events."},
        ]
    )
    result = run_agent(RecoveryStore(), "Count retained events")
    assert result["answer"] == "17 retained events."
    assert len(requests) == 4 and sleeps == [1, 2]


def test_deadline_caps_next_request_and_rejects_late_answer(gemini, transport):
    outcomes, requests, _, now = transport
    outcomes.extend([TOOL_MESSAGE, {"role": "assistant", "content": "too late"}])

    class SlowStore(RecoveryStore):
        def overview(self):
            now[0] += 45
            return super().overview()

    # The second request has five seconds left; even a late successful response
    # cannot be returned as though the investigation was within its deadline.
    original_json_loads = json.loads

    def receive(payload):
        message = original_json_loads(payload)
        if message.get("choices", [{}])[0].get("message", {}).get("content") == "too late":
            now[0] += 6
        return message

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("fluxlake.workspace_agent.json.loads", receive)
        with pytest.raises(AgentUnavailable, match="time budget"):
            run_agent(SlowStore(), "Count retained events")
    assert [timeout for _, timeout in requests] == [18, 5]


@pytest.mark.parametrize("public", [False, True])
def test_unavailable_retry_after_reaches_both_endpoints(tmp_path, monkeypatch, gemini, public):
    from fastapi.testclient import TestClient

    from fluxlake.api import create_app

    token = "test-only-recovery-token-01234567890123456789"
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", token)
    monkeypatch.setenv("FLUXLAKE_DEMO_RATE_SQLITE", str(tmp_path / "rate.sqlite"))

    def unavailable(*_):
        error = AgentUnavailable("Provider cooling down")
        error.retry_after = 90
        raise error

    monkeypatch.setattr("fluxlake.workspace_web.run_agent", unavailable)
    client = TestClient(create_app(tmp_path), client=("192.0.2.9", 12345))
    response = client.post(
        "/api/workspace/agent/demo" if public else "/api/workspace/agent",
        json={"question": "Inspect the retained sample"},
        headers={} if public else {"Authorization": "Bearer " + token},
    )
    assert response.status_code == 503
    assert response.headers.get("Retry-After") == "90"
    assert response.headers["Cache-Control"] == "no-store"
