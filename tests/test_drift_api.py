import json

import pytest
from fastapi.testclient import TestClient

from fluxlake.api import create_app

TOKEN = "test-only-fluxlake-drift-token-0123456789"
AUTH = {"Authorization": "Bearer " + TOKEN}
PAYLOAD = {"baseline": {"start": 1, "end": 100}, "candidate": {"start": 101, "end": 200}}


def test_drift_api_auth_bounds_and_error_redaction(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    marker = "private-drift-never-echo"
    monkeypatch.setenv("DATABASE_URL", f"postgresql://user:{marker}@127.0.0.1:1/private")
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    assert client.post("/drift/compare", json=PAYLOAD).status_code == 401
    assert client.post("/drift/compare", content=b"x" * 5000).status_code == 401
    assert client.post("/drift/compare", content=b"x" * 4097, headers=AUTH).status_code == 413
    for body in (
        {**PAYLOAD, "private": marker},
        {**PAYLOAD, "baseline": {"start": "1", "end": 100}},
        {**PAYLOAD, "candidate": {"start": 50, "end": 200}},
        {**PAYLOAD, "policy": {"ks_threshold": float("nan")}},
    ):
        response = client.post(
            "/drift/compare",
            content=json.dumps(body),
            headers={**AUTH, "Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert marker not in response.text
    response = client.post("/drift/compare", json=PAYLOAD, headers=AUTH)
    assert response.status_code == 503
    assert marker not in response.text + caplog.text
    assert response.headers["cache-control"] == "no-store"


def test_drift_rejects_duplicate_json_and_nested_body(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    client = TestClient(create_app(tmp_path))
    body = '{"baseline":{"start":1,"start":2,"end":100},"candidate":{"start":101,"end":200}}'
    assert client.post("/drift/compare", content=body, headers=AUTH).status_code == 422
    body = "[" * 40 + "0" + "]" * 40
    assert client.post("/drift/compare", content=body, headers=AUTH).status_code == 413


def test_drift_cli_rejects_unsafe_remote_plaintext_and_missing_token(monkeypatch, capsys):
    from fluxlake.drift_client import fetch_report
    from fluxlake.drift_contracts import CompareRequest

    req = CompareRequest.model_validate(PAYLOAD)
    with pytest.raises(ValueError):
        fetch_report("http://example.com", TOKEN, req)
    with pytest.raises(ValueError):
        fetch_report("https://user:pass@example.com", TOKEN, req)
    with pytest.raises(ValueError):
        fetch_report("http://127.0.0.1:8000", "", req)


def test_drift_cli_parses_explicit_windows_and_calls_authenticated_http(monkeypatch, capsys):
    import sys
    from fluxlake.cli import main
    from fluxlake.drift import compare_events
    from fluxlake.drift_contracts import CompareRequest
    from test_drift import record

    def fetch(url, token, request):
        assert url == "http://127.0.0.1:9099"
        assert token == TOKEN
        assert request == CompareRequest.model_validate(PAYLOAD)
        return compare_events(request, [record(1)], [record(101)])

    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    monkeypatch.setattr("fluxlake.drift_client.fetch_report", fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fluxlake",
            "drift",
            "--baseline",
            "1:100",
            "--candidate",
            "101:200",
            "--url",
            "http://127.0.0.1:9099",
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out)["scope"] == "retained_outbox_event_index_windows"


def test_drift_body_read_has_deadline_and_redacts_partial_input(tmp_path, monkeypatch):
    import asyncio
    import httpx

    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    monkeypatch.setattr("fluxlake.api.DRIFT_BODY_TIMEOUT", 0.02, raising=False)

    async def slow_body():
        yield b'{"private":"never-echo-partial-body'
        await asyncio.sleep(0.2)
        yield b'"}'

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)), base_url="http://testserver"
        ) as client:
            return await client.post("/drift/compare", content=slow_body(), headers=AUTH)

    response = asyncio.run(send())
    assert response.status_code == 408
    assert "never-echo" not in response.text
