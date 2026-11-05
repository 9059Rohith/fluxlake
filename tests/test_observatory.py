from fastapi.testclient import TestClient

from fluxlake.api import create_app
from fluxlake.field_atlas import ASSETS, CHAPTERS, ROUTE_ART


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


def test_field_atlas_uses_local_decorative_images_and_an_exact_asset_allowlist(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert len(ASSETS) == 21
    for page, image in ROUTE_ART.items():
        response = client.get(f"/workspace/{page}")
        assert response.status_code == 200
        assert f'/assets/atlas/{image}" alt=""' in response.text

    overview = client.get("/").text
    assert (
        'rel="canonical" href="https://rohith-fluxlake.vercel.app/workspace/overview"' in overview
    )
    assert 'aria-label="Search the observatory"' in overview
    assert 'aria-label="GitHub public events documentation"' in overview
    for _, _, _, image in CHAPTERS:
        assert f'/assets/atlas/{image}" alt="" width="900" height="420" loading="lazy"' in overview

    for filename in ASSETS:
        response = client.get(f"/assets/atlas/{filename}")
        assert response.status_code == 200
        if filename.endswith(".svg"):
            assert response.headers["content-type"] == "image/svg+xml"
            assert b"<script" not in response.content
        else:
            assert response.headers["content-type"] == "image/webp"
            assert response.content[:4] == b"RIFF" and response.content[8:12] == b"WEBP"

    assert client.get("/assets/atlas/inter-latin.woff2").status_code == 404
    font = client.get("/assets/inter-latin.woff2")
    assert font.content.startswith(b"wOF2")
    assert font.headers["content-type"] == "font/woff2"
