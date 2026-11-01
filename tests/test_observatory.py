from fastapi.testclient import TestClient

from fluxlake.api import create_app


def test_observatory_assets_keep_same_origin_security_and_real_font(tmp_path):
    client = TestClient(create_app(tmp_path))
    font = client.get("/assets/inter.woff2")
    assert font.status_code == 200 and font.content[:4] == b"wOF2"
    assert font.headers["content-type"].startswith("font/woff2")
    assert "font-src 'self'" in font.headers["content-security-policy"]
    assert "unsafe-inline" not in font.headers["content-security-policy"]
    icons = client.get("/assets/icons.svg")
    assert icons.status_code == 200 and "<symbol" in icons.text
    assert "<script" not in icons.text and "https://" not in icons.text
    helpers = client.get("/assets/observatory.js")
    assert helpers.status_code == 200
    assert helpers.headers["content-type"].startswith("text/javascript")
