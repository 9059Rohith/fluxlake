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
    parser.add_argument("command", choices=["api", "worker", "init-source", "replay", "gold"])
    parser.add_argument("--root", default=os.getenv("FLUXLAKE_ROOT", "data"))
    parser.add_argument("--file", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command == "api":
        from fluxlake.api import create_app

        uvicorn.run(create_app(args.root), host=args.host, port=args.port)
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
