-- Opt-in downstream model for immutable public Silver. Apply after sql/workspace.sql.
CREATE SCHEMA IF NOT EXISTS flux_analytics;

CREATE TABLE IF NOT EXISTS flux_analytics.applied_runs (
  run_id uuid PRIMARY KEY REFERENCES public.flux_public_runs(id),
  source_events integer NOT NULL CHECK (source_events > 0),
  applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS flux_analytics.hourly_event_type (
  utc_hour timestamptz NOT NULL,
  event_type text NOT NULL,
  events bigint NOT NULL CHECK (events > 0),
  first_event timestamptz NOT NULL,
  last_event timestamptz NOT NULL,
  PRIMARY KEY (utc_hour, event_type),
  CHECK (first_event <= last_event)
);

CREATE OR REPLACE VIEW flux_analytics.hourly_mix AS
SELECT utc_hour, event_type, events, first_event, last_event,
       round(events::numeric / sum(events) OVER (PARTITION BY utc_hour), 6) AS share,
       dense_rank() OVER (PARTITION BY utc_hour ORDER BY events DESC) AS type_rank
FROM flux_analytics.hourly_event_type;

CREATE OR REPLACE FUNCTION flux_analytics.refresh_hourly(max_runs integer DEFAULT 32)
RETURNS TABLE(runs_applied bigint, events_applied bigint, buckets_touched bigint)
LANGUAGE plpgsql SET search_path TO pg_catalog AS $$
DECLARE
  receipts_agree boolean;
BEGIN
  IF max_runs IS NULL OR max_runs < 1 OR max_runs > 128 THEN
    RAISE EXCEPTION 'max_runs must be between 1 and 128' USING ERRCODE = '22023';
  END IF;

  -- A separate lock from source acquisition serializes model writers through commit.
  PERFORM pg_advisory_xact_lock(704686193);

  WITH pending AS MATERIALIZED (
    SELECT r.id, r.inserted
    FROM public.flux_public_runs r
    WHERE r.status = 'succeeded' AND r.inserted > 0
      AND NOT EXISTS (SELECT 1 FROM flux_analytics.applied_runs a WHERE a.run_id = r.id)
    ORDER BY r.started_at, r.id
    LIMIT max_runs
  ), delta AS MATERIALIZED (
    SELECT s.run_id, s.event_type, s.occurred_at
    FROM pending p JOIN public.flux_public_silver s ON s.run_id = p.id
  ), per_run AS (
    SELECT run_id, count(*) AS events FROM delta GROUP BY run_id
  ), applied AS (
    INSERT INTO flux_analytics.applied_runs(run_id, source_events)
    SELECT id, inserted FROM pending
    RETURNING run_id
  ), updated AS (
    INSERT INTO flux_analytics.hourly_event_type AS target
      (utc_hour, event_type, events, first_event, last_event)
    SELECT date_trunc('hour', occurred_at, 'UTC'), event_type, count(*),
           min(occurred_at), max(occurred_at)
    FROM delta
    GROUP BY 1, 2
    ON CONFLICT (utc_hour, event_type) DO UPDATE SET
      events = target.events + EXCLUDED.events,
      first_event = least(target.first_event, EXCLUDED.first_event),
      last_event = greatest(target.last_event, EXCLUDED.last_event)
    RETURNING utc_hour
  )
  SELECT (SELECT count(*) FROM applied), (SELECT count(*) FROM delta),
         (SELECT count(*) FROM updated),
         NOT EXISTS (SELECT 1 FROM pending p LEFT JOIN per_run d ON d.run_id = p.id
                     WHERE coalesce(d.events, 0) <> p.inserted)
  INTO runs_applied, events_applied, buckets_touched, receipts_agree;

  IF NOT receipts_agree THEN
    RAISE EXCEPTION 'committed Silver counts disagree with an acquisition receipt';
  END IF;
  RETURN NEXT;
END;
$$;
