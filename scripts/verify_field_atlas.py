"""Verify deployed field atlas placement, integrity, route behavior and real replay."""

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import httpx


class Images(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = {}

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        source = attrs.get("src" if tag == "img" else "srcset", "")
        if tag in {"img", "source"} and source.startswith("/assets/atlas/"):
            self.assets[source.removeprefix("/assets/atlas/")] = (tag, attrs)


def verify(base_url, manifest):
    placements = {}
    for asset in manifest["assets"]:
        placements.setdefault(asset["route"], []).append(asset)

    with httpx.Client(base_url=base_url, timeout=45) as client:

        def get(path):
            response = client.get(path).raise_for_status()
            assert response.headers["x-content-type-options"] == "nosniff", path
            assert "unsafe-inline" not in response.headers["content-security-policy"], path
            return response

        def page_check(route):
            response = get(route)
            assert response.headers["cache-control"] == "no-store"
            assert 'href="/assets/inter-latin.woff2"' in response.text
            assert 'src="/assets/field-motion.js"' in response.text
            images = Images()
            images.feed(response.text)
            for asset in placements[route]:
                tag, attrs = images.assets[asset["file"]]
                if tag == "img":
                    assert attrs.get("alt") == ""
                    assert "width" in attrs and "height" in attrs
                    if asset["loading"] == "lazy":
                        assert attrs.get("loading") == "lazy"
            assert len(images.assets) == len(placements[route])
            return {"route": route, "status": response.status_code, "images": len(images.assets)}

        def image_check(asset):
            response = get(f"/assets/atlas/{asset['file']}")
            kind = "image/webp" if asset["file"].endswith(".webp") else "image/svg+xml"
            assert response.headers["content-type"].startswith(kind), asset["file"]
            digest = hashlib.sha256(response.content).hexdigest()
            assert digest == asset["sha256"], asset["file"]
            assert len(response.content) == asset["bytes"]
            if kind == "image/svg+xml":
                svg = ElementTree.fromstring(response.content)
                for node in svg.iter():
                    assert node.tag.rsplit("}", 1)[-1] not in {"script", "foreignObject", "image"}
                    assert all(not attr.startswith("on") for attr in node.attrib)
            return digest

        with ThreadPoolExecutor(max_workers=8) as pool:
            pages = list(pool.map(page_check, placements))
            digests = list(pool.map(image_check, manifest["assets"]))

        assert len(set(digests)) == len(digests)
        assert len({asset["composition"] for asset in manifest["assets"]}) == 20
        assert client.get("/assets/atlas/inter-latin.woff2").status_code == 404
        font = get("/assets/inter-latin.woff2")
        assert font.content.startswith(b"wOF2")
        assert font.headers["content-type"] == "font/woff2"
        css = get("/assets/field-atlas.css").text
        assert (
            "prefers-reduced-motion: no-preference" in css and "animation-timeline: scroll" in css
        )

        live = get("/api/workspace/overview").json()
        run = live["latest_run"]["id"]
        replay = get(f"/api/workspace/replay?run={run}").json()
        assert replay["status"] == "consistent" and replay["counts"]["affected_events"] == 0
        benchmark = get("/api/workspace/archive-benchmark").json()
        assert benchmark["unique_events"] == 20_000
        assert benchmark["read_only_audit"]["differences"] == 0
        assert client.post("/api/workspace/ingest", content=b"{").status_code == 401

    return {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "pages": pages,
        "distinct_compositions": 20,
        "image_files": len(digests),
        "image_bytes": manifest["total_bytes"],
        "font_bytes": len(font.content),
        "live_events": live["counts"]["events"],
        "reconstructed_events": replay["counts"]["retained_events"],
        "replay_differences": replay["counts"]["affected_events"],
        "offline_benchmark_events": benchmark["unique_events"],
        "anonymous_ingest_status": 401,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://rohith-fluxlake.vercel.app")
    parser.add_argument("--output", type=Path, default=Path("evidence/field-atlas-http.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "docs/field-atlas-assets.json").read_text(encoding="utf-8"))
    report = verify(args.url, manifest)
    encoded = json.dumps(report, indent=2) + "\n"
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")


if __name__ == "__main__":
    main()
