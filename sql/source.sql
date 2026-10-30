-- Development source schema. Run once via Compose init or `fluxlake init-source`.
CREATE TABLE IF NOT EXISTS public.transactions (
    id text PRIMARY KEY CHECK (id ~ '^[A-Za-z0-9_-]{1,128}$'),
    amount_minor bigint NOT NULL CHECK (amount_minor >= 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    status text NOT NULL CHECK (status IN ('pending','settled','failed')),
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb
);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname='transaction_attributes_safe'
                     AND conrelid='public.transactions'::regclass) THEN
        ALTER TABLE public.transactions ADD CONSTRAINT transaction_attributes_safe CHECK (
            jsonb_typeof(attributes)='object' AND NOT attributes ?| ARRAY[
                'id','amount_minor','currency','status','key','version',
                'occurred_at','attributes','event_id','op'
            ]
        ) NOT VALID;
    END IF;
END $$;
-- Separate durable revision ledger prevents a delete/reinsert from resetting version.
CREATE TABLE IF NOT EXISTS public.transaction_versions (
    aggregate_id text PRIMARY KEY,
    version bigint NOT NULL
);
CREATE TABLE IF NOT EXISTS public.transaction_outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    aggregate_id text NOT NULL,
    version bigint NOT NULL,
    operation text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    data jsonb NOT NULL,
    processed_at timestamptz,
    UNIQUE(aggregate_id, version)
);
CREATE INDEX IF NOT EXISTS transaction_outbox_pending ON public.transaction_outbox(id)
    WHERE processed_at IS NULL;
CREATE OR REPLACE FUNCTION public.capture_transaction() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE row_data jsonb; entity_key text; revision bigint;
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.id <> NEW.id THEN
        RAISE EXCEPTION 'transaction id is immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        row_data := to_jsonb(OLD); entity_key := OLD.id;
    ELSE
        row_data := to_jsonb(NEW); entity_key := NEW.id;
    END IF;
    INSERT INTO public.transaction_versions(aggregate_id, version) VALUES(entity_key, 1)
      ON CONFLICT (aggregate_id) DO UPDATE SET version=transaction_versions.version+1
      RETURNING version INTO revision;
    INSERT INTO public.transaction_outbox(aggregate_id,version,operation,data)
      VALUES(entity_key,revision,lower(TG_OP),
        (row_data - 'id' - 'attributes') || COALESCE(row_data->'attributes','{}'::jsonb));
    RETURN NULL;
END;
$$;
DROP TRIGGER IF EXISTS transactions_outbox ON public.transactions;
CREATE TRIGGER transactions_outbox AFTER INSERT OR UPDATE OR DELETE ON public.transactions
    FOR EACH ROW EXECUTE FUNCTION public.capture_transaction();
