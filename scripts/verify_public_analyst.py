"""Public hosted proof. Each phase makes at most one inference-capable request.

Run `first`, wait for a clean browser to complete the second investigation, then run `limited`
within that minute. No Authorization header or operator token is sent.
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["first", "limited"])
    args = parser.parse_args()
    origin = "https://rohith-fluxlake.vercel.app"
    endpoint = origin + "/api/workspace/agent/demo"
    path = Path("evidence/public-analyst-live.json")
    question = "Use lake_overview and aggregate_events grouped by event_type. Report exact retained event counts with source API paths and sample limitations."
    headers = {"Origin": origin}
    if args.phase == "first":
        status = httpx.get(origin + "/api/workspace/agent/status", timeout=45).json()
        assert (
            status["configured"]
            and status["public_demo_configured"]
            and status["vercel_runtime"] is True
        )
        assert status["client_identity_source"] == "vercel-overwritten-x-forwarded-for"
        controls = []
        for payload, extra_headers, expected in [
            ({"question": "Count public events"}, {"Origin": "https://attacker.example"}, 403),
            ({"question": "x" * 601}, headers, 422),
            ({"question": "Count events", "model": "arbitrary"}, headers, 422),
        ]:
            response = httpx.post(endpoint, json=payload, headers=extra_headers, timeout=30)
            assert response.status_code == expected
            controls.append(
                {
                    "status": expected,
                    "case": "cross-origin" if expected == 403 else "invalid bounded request",
                }
            )
        assert httpx.post(origin + "/api/workspace/ingest", timeout=30).status_code == 401
        assert (
            httpx.post(
                origin + "/api/workspace/agent", json={"question": question}, timeout=30
            ).status_code
            == 401
        )
        # Leave enough of a fresh shared minute for the independent browser proof.
        elapsed = time.time() % 60
        if elapsed > 20:
            time.sleep(60 - elapsed + 1)
        response = httpx.post(endpoint, json={"question": question}, headers=headers, timeout=120)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["demo"] is True and result["read_only"] is True and result["tool_calls"] >= 1
        assert result["demo_budget"]["remaining"]["shared_minute"] == 1
        assert "200" in result["answer"]
        assert "/api/workspace/" in result["answer"]
        assert "thought_signature" not in json.dumps(result)
        evidence = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "origin": origin,
            "endpoint": "/api/workspace/agent/demo",
            "authorization_sent": False,
            "status": status,
            "controls": controls,
            "http_status": 200,
            "question": question,
            "result": result,
        }
        path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": 200,
                    "anonymous": True,
                    "tool_calls": result["tool_calls"],
                    "shared_minute_remaining": 1,
                    "reset_seconds_at_reservation": result["demo_budget"][
                        "shared_minute_reset_seconds"
                    ],
                }
            )
        )
    else:
        evidence = json.loads(path.read_text(encoding="utf-8"))
        first_time = datetime.fromisoformat(evidence["checked_at"]).timestamp()
        if int(time.time() // 60) != int(first_time // 60):
            raise SystemExit(
                "The first reservation window expired. Do not spend another model call; use the recorded browser cooldown proof."
            )
        response = httpx.post(endpoint, json={"question": question}, headers=headers, timeout=120)
        assert response.status_code == 429, (
            f"Expected a full shared window; received HTTP {response.status_code}. Do not repeat inference probes."
        )
        retry = int(response.headers["Retry-After"])
        assert retry > 0
        evidence = json.loads(path.read_text(encoding="utf-8"))
        evidence["rate_limit_proof"] = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "http_status": 429,
            "retry_after": retry,
            "authorization_sent": False,
            "detail": response.json()["detail"],
        }
        path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence["rate_limit_proof"]))


if __name__ == "__main__":
    main()
