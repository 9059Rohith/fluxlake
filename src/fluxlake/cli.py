import argparse
import json
import logging
import os
from pathlib import Path

import psycopg
import uvicorn

from fluxlake.lake import Lake
from fluxlake.worker import run


def main():
    parser = argparse.ArgumentParser(description="FluxLake local lakehouse")
    parser.add_argument(
        "command", choices=["api", "worker", "init-source", "replay", "gold", "drift"]
    )
    parser.add_argument("--root", default=os.getenv("FLUXLAKE_ROOT", "data"))
    parser.add_argument("--file", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--baseline", help="Drift baseline inclusive outbox identity START:END")
    parser.add_argument("--candidate", help="Drift candidate inclusive outbox identity START:END")
    parser.add_argument("--url", default=os.getenv("FLUXLAKE_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command == "drift":
        from fluxlake.drift_client import fetch_report, parse_window
        from fluxlake.drift_contracts import CompareRequest

        if not args.baseline or not args.candidate:
            parser.error("drift requires --baseline START:END and --candidate START:END")
        try:
            request = CompareRequest.model_validate(
                {
                    "baseline": parse_window(args.baseline),
                    "candidate": parse_window(args.candidate),
                }
            )
            report = fetch_report(args.url, os.getenv("FLUXLAKE_API_TOKEN", ""), request)
        except (ValueError, RuntimeError):
            parser.error(
                "Drift request invalid or unavailable; verify windows, origin, token and source"
            )
        print(report.model_dump_json(indent=2))
    elif args.command == "api":
        from fluxlake.api import create_app

        uvicorn.run(
            create_app(args.root),
            host=args.host,
            port=args.port,
            limit_concurrency=32,
            backlog=64,
            timeout_keep_alive=5,
            server_header=False,
            forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        )
    elif args.command == "worker":
        run(args.root)
    elif args.command == "init-source":
        sql = args.file or Path("sql/source.sql")
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
            conn.execute(sql.read_text())
    elif args.command == "replay":
        if not args.file:
            parser.error("replay requires --file containing a JSON array")
        print(json.dumps(Lake(args.root).apply(json.loads(args.file.read_text()))))
    else:
        print(json.dumps(Lake(args.root).gold(), indent=2))


if __name__ == "__main__":
    main()
