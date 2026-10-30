from fastapi.testclient import TestClient

from fluxlake.api import create_app
from test_lake import event


def test_write_auth_fails_closed_and_readiness(tmp_path, monkeypatch):
    monkeypatch.delenv("FLUXLAKE_API_TOKEN", raising=False)
    client = TestClient(create_app(tmp_path))
    assert client.post("/events", json=[event()]).status_code == 503
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").status_code == 200
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "test-token")
    assert client.post("/events", json=[event()]).status_code == 401
    assert (
        client.post(
            "/events", headers={"Authorization": "Bearer wrong"}, json=[event()]
        ).status_code
        == 401
    )
    response = client.post(
        "/events", headers={"Authorization": "Bearer test-token"}, json=[event()]
    )
    assert response.status_code == 200
    assert response.json()["applied"] == 1
    assert client.get("/transactions").json()[0]["key"] == "tx1"
    assert client.get("/gold").json()[0]["total_minor"] == 12500
    assert "fluxlake_events_total" in client.get("/metrics").text


def test_oversized_batches_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "test-token")
    client = TestClient(create_app(tmp_path))
    assert (
        client.post(
            "/events", headers={"Authorization": "Bearer test-token"}, json=[{}] * 1001
        ).status_code
        == 413
    )


def test_body_bound_and_quarantine_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "test-token")
    client = TestClient(create_app(tmp_path))
    assert client.get("/quarantine").status_code == 401
    assert client.post("/events", content=b"[" + b" " * 2_000_001 + b"]").status_code == 413
    assert client.get("/pipeline").json()["status"] == "unknown"


def test_nonfinite_json_is_rejected_without_server_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "test-token")
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    response = client.post(
        "/events",
        content='[{"value":NaN}]',
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_non_ascii_authorization_is_unauthorized_not_server_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "test-token")
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    response = client.post("/events", json=[], headers=[(b"authorization", b"Bearer \xff\xfe")])
    assert response.status_code == 401


def test_whitespace_only_token_disables_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "  \t  ")
    client = TestClient(create_app(tmp_path))
    assert client.post("/events", json=[]).status_code == 503
