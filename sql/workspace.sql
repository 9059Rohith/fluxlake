-- Explicit migration: the public workspace never reads the private payment tables.
CREATE TABLE IF NOT EXISTS public.flux_public_runs (
  id uuid PRIMARY KEY, started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz, status text NOT NULL CHECK(status IN ('running','succeeded','failed')),
  source_url text NOT NULL, fetched integer NOT NULL DEFAULT 0,
  inserted integer NOT NULL DEFAULT 0, duplicates integer NOT NULL DEFAULT 0,
  quarantined integer NOT NULL DEFAULT 0, response_sha256 text,
  http_status integer, rate_remaining integer, poll_seconds integer,
  error text, duration_ms integer
);
CREATE TABLE IF NOT EXISTS public.flux_public_bronze (
  event_id text PRIMARY KEY, run_id uuid NOT NULL REFERENCES public.flux_public_runs(id),
  ingested_at timestamptz NOT NULL DEFAULT now(), raw jsonb NOT NULL,
  sha256 text NOT NULL, bytes integer NOT NULL
);
CREATE TABLE IF NOT EXISTS public.flux_public_silver (
  event_id text PRIMARY KEY REFERENCES public.flux_public_bronze(event_id),
  event_type text NOT NULL, repository text NOT NULL, actor text NOT NULL,
  occurred_at timestamptz NOT NULL, action text, organization text,
  run_id uuid NOT NULL REFERENCES public.flux_public_runs(id)
);
CREATE INDEX IF NOT EXISTS flux_public_silver_time ON public.flux_public_silver(occurred_at DESC);
CREATE INDEX IF NOT EXISTS flux_public_silver_run ON public.flux_public_silver(run_id);
CREATE TABLE IF NOT EXISTS public.flux_public_quarantine (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES public.flux_public_runs(id),
  event_id text, reason text NOT NULL, sha256 text NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.flux_public_schema (
  path text NOT NULL, value_type text NOT NULL, first_seen timestamptz NOT NULL DEFAULT now(),
  last_seen timestamptz NOT NULL DEFAULT now(), observations integer NOT NULL DEFAULT 1,
  PRIMARY KEY(path,value_type)
);
CREATE TABLE IF NOT EXISTS public.flux_public_demo_limits (
  bucket_key text PRIMARY KEY,
  window_start bigint NOT NULL,
  attempts integer NOT NULL CHECK (attempts >= 0),
  expires_at bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS flux_public_demo_expiry ON public.flux_public_demo_limits(expires_at);
