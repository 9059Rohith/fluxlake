"""Explicit once-only initialization of a dedicated empty synthetic-demo database."""

from pathlib import Path

import psycopg


def initialize_synthetic_source(database_url: str) -> None:
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout='5s'")
            conn.execute("SET LOCAL lock_timeout='2s'")
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('fluxlake/synthetic-bootstrap/v1',0))"
            )
            marker = conn.execute(
                "SELECT to_regclass('public.fluxlake_demo_bootstrap')"
            ).fetchone()[0]
            if (
                marker
                and conn.execute(
                    "SELECT EXISTS(SELECT 1 FROM public.fluxlake_demo_bootstrap WHERE id=1)"
                ).fetchone()[0]
            ):
                return
            existing = conn.execute("SELECT to_regclass('public.transactions')").fetchone()[0]
            if existing:
                conn.execute("LOCK TABLE public.transactions IN EXCLUSIVE MODE")
                if conn.execute("SELECT EXISTS(SELECT 1 FROM public.transactions)").fetchone()[0]:
                    raise ValueError("Synthetic initialization requires a dedicated empty source")
            conn.execute(Path("sql/source.sql").read_text(encoding="utf-8"))
            if conn.execute("SELECT EXISTS(SELECT 1 FROM public.transaction_outbox)").fetchone()[0]:
                raise ValueError("Synthetic initialization requires empty retained history")
            conn.execute("""INSERT INTO public.transactions(id,amount_minor,currency,status,attributes)
                SELECT 'synthetic-bootstrap-v1-' || lpad(i::text,2,'0'), 10000+125*i,
                       CASE WHEN i%2=0 THEN 'INR' ELSE 'USD' END, 'settled',
                       '{"synthetic":true,"region":"demo","channel":"bootstrap"}'::jsonb
                FROM generate_series(0,19) AS i""")
            conn.execute(
                "UPDATE public.transactions SET amount_minor=25000 WHERE id='synthetic-bootstrap-v1-00'"
            )
            conn.execute("DELETE FROM public.transactions WHERE id='synthetic-bootstrap-v1-01'")
            conn.execute("""CREATE TABLE public.fluxlake_demo_bootstrap (
                id integer PRIMARY KEY CHECK(id=1), initialized_at timestamptz NOT NULL DEFAULT clock_timestamp())""")
            conn.execute("INSERT INTO public.fluxlake_demo_bootstrap(id) VALUES(1)")
