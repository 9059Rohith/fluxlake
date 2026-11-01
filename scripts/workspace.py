"""Explicit public workspace migration/acquisition. Uses DATABASE_URL, never prints it."""

import argparse
import json
from pathlib import Path

import psycopg

from fluxlake.workspace import PublicWorkspace


def main():
    parser = argparse.ArgumentParser(description="Manage the real public GitHub event workspace")
    parser.add_argument("command", choices=["migrate", "ingest", "overview"])
    args = parser.parse_args()
    store = PublicWorkspace()
    if args.command == "migrate":
        with psycopg.connect(store.database_url, connect_timeout=5) as conn:
            conn.execute(Path("sql/workspace.sql").read_text())
        print("Public workspace schema initialized; private CDC tables untouched")
    elif args.command == "ingest":
        print(json.dumps(store.ingest(), default=str, indent=2))
    else:
        print(json.dumps(store.overview(), default=str, indent=2))


if __name__ == "__main__":
    main()
