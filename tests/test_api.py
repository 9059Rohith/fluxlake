from fastapi.testclient import TestClient

from fluxlake.api import create_app
from test_lake import event


def test_write_auth_fails_closed_and_readiness(tmp_path, monkeypatch):
    monkeypatch.delenv("FLUXLAKE_API_TOKEN", raising=False)
    client = TestClient(create_app(tmp_path))
    assert client.post("/events", json=[event()]).status_code == 503
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").status_code == 200
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "test-only-fluxlake-token-0123456789")
    assert client.post("/events", json=[event()]).status_code == 401
    assert (
        client.post(
            "/events", headers={"Authorization": "Bearer wrong"}, json=[event()]
        ).status_code
        == 401
    )
    response = client.post(
        "/events",
        headers={"Authorization": "Bearer test-only-fluxlake-token-0123456789"},
        json=[event()],
    )
    assert response.status_code == 200
    assert response.json()["applied"] == 1
    assert client.get("/transactions", headers=AUTH).json()[0]["key"] == "tx1"
    assert client.get("/gold", headers=AUTH).json()[0]["total_minor"] == 12500
    assert "fluxlake_events_total" in client.get("/metrics", headers=AUTH).text


def test_oversized_batches_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "test-only-fluxlake-token-0123456789")
    client = TestClient(create_app(tmp_path))
    assert (
        client.post(
            "/events",
            headers={"Authorization": "Bearer test-only-fluxlake-token-0123456789"},
            json=[{}] * 1001,
        ).status_code
        == 413
    )


def test_body_bound_and_quarantine_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "test-only-fluxlake-token-0123456789")
    client = TestClient(create_app(tmp_path))
    assert client.get("/quarantine").status_code == 401
    assert (
        client.post("/events", headers=AUTH, content=b"[" + b" " * 2_000_001 + b"]").status_code
        == 413
    )
    assert client.get("/pipeline", headers=AUTH).json()["status"] == "unknown"


def test_nonfinite_json_is_rejected_without_server_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "test-only-fluxlake-token-0123456789")
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    response = client.post(
        "/events",
        content='[{"value":NaN}]',
        headers={
            "Authorization": "Bearer test-only-fluxlake-token-0123456789",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 422


def test_non_ascii_authorization_is_unauthorized_not_server_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "test-only-fluxlake-token-0123456789")
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    response = client.post("/events", json=[], headers=[(b"authorization", b"Bearer \xff\xfe")])
    assert response.status_code == 401


def test_whitespace_only_token_disables_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "  \t  ")
    client = TestClient(create_app(tmp_path))
    assert client.post("/events", json=[]).status_code == 503


TOKEN = "test-only-fluxlake-token-0123456789"
AUTH = {"Authorization": "Bearer " + TOKEN}


def test_operational_reads_require_authentication(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    client = TestClient(create_app(tmp_path))
    for path in (
        "/transactions",
        "/gold",
        "/schema",
        "/pipeline",
        "/metrics",
        "/quarantine",
        "/openapi.json",
    ):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=AUTH).status_code == 200


def test_public_demo_exposes_only_explicit_synthetic_aggregates(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    monkeypatch.setenv("FLUXLAKE_PUBLIC_DEMO", "true")
    monkeypatch.setenv("FLUXLAKE_ALLOWED_HOSTS", "testserver")
    client = TestClient(create_app(tmp_path))
    assert (
        client.post(
            "/events",
            headers=AUTH,
            json=[
                event("private", key="private-account", amount_minor=999999),
                event("synthetic", key="demo-id", synthetic=True, region="hidden-region"),
                event("not-demo", key="not-demo", synthetic=False),
            ],
        ).status_code
        == 200
    )
    response = client.get("/demo/summary")
    assert response.status_code == 200
    summary = response.json()
    assert summary["synthetic"] is True
    assert summary["gold"] == [{"currency": "USD", "transaction_count": 1, "total_minor": 12500}]
    assert summary["source_status"] == "unknown"
    assert "private-account" not in response.text
    assert "hidden-region" not in response.text
    assert "synthetic" in client.get("/").text.lower()
    assert client.get("/transactions").status_code == 401


def test_public_demo_disabled_without_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("FLUXLAKE_PUBLIC_DEMO", raising=False)
    client = TestClient(create_app(tmp_path))
    assert client.get("/demo/summary").status_code == 404


def test_deep_and_large_leaf_inputs_rejected_before_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    assert (
        client.post("/events", headers=AUTH, content=b"[" * 40 + b"0" + b"]" * 40).status_code
        == 413
    )
    assert client.post("/events", headers=AUTH, json=[event(region="x" * 5000)]).status_code == 413
    assert client.post("/events", headers=AUTH, json=[{"padding": [0] * 25000}]).status_code == 413
    assert client.get("/transactions", headers=AUTH).json() == []
    assert list((tmp_path / "bronze").glob("*.json")) == []


def test_auth_is_checked_before_parsing_untrusted_bodies(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    assert client.post("/events", content=b"[" * 10000).status_code == 401


def test_private_rows_are_bounded_and_paginated(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", TOKEN)
    client = TestClient(create_app(tmp_path))
    client.post("/events", headers=AUTH, json=[event("one", key="a"), event("two", key="b")])
    assert [
        r["key"] for r in client.get("/transactions?limit=1&offset=1", headers=AUTH).json()
    ] == ["b"]
    assert client.get("/transactions?limit=501", headers=AUTH).status_code == 422


def test_responses_have_security_headers_and_no_cache(tmp_path):
    response = TestClient(create_app(tmp_path)).get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]


def test_weak_token_configuration_disables_protected_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_API_TOKEN", "short")
    client = TestClient(create_app(tmp_path))
    assert (
        client.post("/events", headers={"Authorization": "Bearer short"}, json=[]).status_code
        == 503
    )


def test_public_mode_requires_explicit_exact_hostnames(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setenv("FLUXLAKE_PUBLIC_DEMO", "true")
    monkeypatch.delenv("FLUXLAKE_ALLOWED_HOSTS", raising=False)
    with pytest.raises(RuntimeError, match="host"):
        create_app(tmp_path)
    monkeypatch.setenv("FLUXLAKE_ALLOWED_HOSTS", "*")
    with pytest.raises(RuntimeError, match="host"):
        create_app(tmp_path)


def test_unknown_host_is_rejected(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.get("/health", headers={"Host": "untrusted.invalid"}).status_code == 400


def test_request_source_failure_is_closed_and_does_not_leak_credentials(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("FLUXLAKE_SOURCE_SYNC", "request")
    monkeypatch.setenv("FLUXLAKE_PUBLIC_DEMO", "true")
    monkeypatch.setenv("FLUXLAKE_ALLOWED_HOSTS", "testserver")
    marker = "do-not-expose-test-secret"
    monkeypatch.setenv("DATABASE_URL", f"postgresql://private_user:{marker}@127.0.0.1:1/private_db")
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 503
    summary = client.get("/demo/summary")
    assert summary.status_code == 503
    assert marker not in ready.text + summary.text + caplog.text
    assert "private_db" not in summary.text
