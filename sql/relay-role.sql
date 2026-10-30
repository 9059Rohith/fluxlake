-- Administrator-applied capability role. It has no login/password and no DDL or source-write rights.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fluxlake_relay') THEN
        CREATE ROLE fluxlake_relay NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO fluxlake_relay;
GRANT SELECT, UPDATE(processed_at) ON TABLE public.transaction_outbox TO fluxlake_relay;
-- Separately grant this role to a dedicated LOGIN identity held in the hosting secret store:
-- GRANT fluxlake_relay TO your_private_relay_login;
-- Never grant the migration/database-owner identity to the public API.
