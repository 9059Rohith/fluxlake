"""Exercise the actual deployed provider and actual public database tools.

FLUXLAKE_API_TOKEN is read from the environment and never saved or printed.
The saved evidence contains only the fixed public question and public results.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    origin = "https://fluxlake.vercel.app"
    status = httpx.get(origin + "/api/workspace/agent/status", timeout=45)
    assert status.status_code == 200
    status = status.json()
    assert status["configured"] is True and status["provider"] == "Google Gemini"
    anonymous = httpx.post(
        origin + "/api/workspace/agent", json={"question": "Count public events"}, timeout=30
    )
    assert anonymous.status_code == 401
    question = "Use lake_overview and aggregate_events grouped by event_type. Report the exact retained event count and event-type counts in digits, with source API paths and sample limitations. Use only the real public data."
    response = httpx.post(
        origin + "/api/workspace/agent",
        json={"question": question},
        headers={"Authorization": "Bearer " + os.environ["FLUXLAKE_API_TOKEN"]},
        timeout=120,
    )
    if response.status_code != 200:
        print(
            json.dumps(
                {
                    "status": response.status_code,
                    "retry_after": response.headers.get("Retry-After"),
                    "detail": response.json().get("detail"),
                }
            )
        )
        raise SystemExit(1)
    result = response.json()
    assert result["read_only"] is True and 1 <= result["tool_calls"] <= 6
    assert result["provider"] == "Google Gemini"
    tool_names = {item["tool"] for item in result["trace"]}
    assert "lake_overview" in tool_names and "aggregate_events" in tool_names
    overview = next(item["result"] for item in result["trace"] if item["tool"] == "lake_overview")
    aggregates = next(
        item["result"] for item in result["trace"] if item["tool"] == "aggregate_events"
    )
    assert overview["counts"]["events"] > 0
    assert sum(row["events"] for row in aggregates["rows"]) == overview["counts"]["events"]
    assert str(overview["counts"]["events"]) in result["answer"]
    assert "/api/workspace/overview" in result["answer"]
    assert "/api/workspace/gold" in result["answer"]
    encoded = json.dumps(result)
    assert "thought_signature" not in encoded and "extra_content" not in encoded
    assert os.environ["FLUXLAKE_API_TOKEN"] not in encoded
    evidence = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "question": question,
        "http_status": response.status_code,
        "anonymous_status": anonymous.status_code,
        "provider_status": status,
        "real_public_events": overview["counts"]["events"],
        "result": result,
        "secret_or_signature_persisted": False,
    }
    Path("evidence/gemini-live.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "http_status": 200,
                "provider": result["provider"],
                "model": result["model"],
                "real_public_events": evidence["real_public_events"],
                "tool_calls": result["tool_calls"],
                "tools": sorted(tool_names),
                "evidence": "evidence/gemini-live.json",
            }
        )
    )


if __name__ == "__main__":
    main()
