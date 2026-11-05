import pytest
from fastapi.testclient import TestClient

from fluxlake.api import create_app


CANONICAL = "rohith-fluxlake.vercel.app"
DEPLOYMENT = "fluxlake-build123-rohiths-projects.vercel.app"


def public_client(tmp_path, monkeypatch, deployment=DEPLOYMENT):
    monkeypatch.setenv("FLUXLAKE_PUBLIC_DEMO", "true")
    monkeypatch.setenv("FLUXLAKE_ALLOWED_HOSTS", CANONICAL)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_URL", deployment)
    return TestClient(create_app(tmp_path))


def test_vercel_deployment_is_an_exact_additional_host(tmp_path, monkeypatch):
    client = public_client(tmp_path, monkeypatch)
    for host in (CANONICAL, DEPLOYMENT, "localhost", "127.0.0.1"):
        assert client.get("/health", headers={"Host": host}).status_code == 200
    for host in (
        "sibling-build.vercel.app",
        "child." + DEPLOYMENT,
        DEPLOYMENT + ".attacker.invalid",
        "testserver",
        "untrusted.invalid",
    ):
        assert client.get("/health", headers={"Host": host}).status_code == 400
    assert (
        client.get(
            "/health",
            headers={"Host": "untrusted.invalid", "X-Forwarded-Host": DEPLOYMENT},
        ).status_code
        == 400
    )


@pytest.mark.parametrize("platform", ["", "0", "true"])
def test_deployment_host_requires_exact_vercel_platform_flag(tmp_path, monkeypatch, platform):
    public_client(tmp_path, monkeypatch)
    monkeypatch.setenv("VERCEL", platform)
    client = TestClient(create_app(tmp_path))
    assert client.get("/health", headers={"Host": DEPLOYMENT}).status_code == 400
    assert client.get("/health", headers={"Host": CANONICAL}).status_code == 200


@pytest.mark.parametrize(
    "deployment",
    [
        "",
        "*.vercel.app",
        "vercel.app",
        ".vercel.app",
        "-bad.vercel.app",
        "bad-.vercel.app",
        "bad_name.vercel.app",
        "a" * 64 + ".vercel.app",
        "https://" + DEPLOYMENT,
        DEPLOYMENT + ":443",
        DEPLOYMENT + "/",
        DEPLOYMENT + ".",
        DEPLOYMENT + ".attacker.invalid",
        " " + DEPLOYMENT,
        "user@" + DEPLOYMENT,
        DEPLOYMENT + ",sibling.vercel.app",
    ],
)
def test_malformed_platform_host_does_not_expand_allowlist(tmp_path, monkeypatch, deployment):
    client = public_client(tmp_path, monkeypatch, deployment)
    assert client.get("/health", headers={"Host": DEPLOYMENT}).status_code == 400
    assert client.get("/health", headers={"Host": "sibling.vercel.app"}).status_code == 400
    assert client.get("/health", headers={"Host": CANONICAL}).status_code == 200


def test_platform_host_cannot_replace_required_explicit_canonical(tmp_path, monkeypatch):
    monkeypatch.setenv("FLUXLAKE_PUBLIC_DEMO", "true")
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_URL", DEPLOYMENT)
    monkeypatch.delenv("FLUXLAKE_ALLOWED_HOSTS", raising=False)
    with pytest.raises(RuntimeError, match="exact allowed hostnames"):
        create_app(tmp_path)


def test_local_testserver_remains_available_without_public_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("FLUXLAKE_PUBLIC_DEMO", raising=False)
    monkeypatch.delenv("FLUXLAKE_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    assert TestClient(create_app(tmp_path)).get("/health").status_code == 200
