# Public deployment

[Open FluxLake](https://rohith-fluxlake.vercel.app) · [Real evidence API](https://rohith-fluxlake.vercel.app/api/workspace/overview) · [Current release verification](workspace-release.md)

The public experience is a 13-page GitHub public-event analytical workspace. Dedicated PostgreSQL tables retain actual API acquisitions, original JSON/SHA-256 evidence, typed silver, schema observations, quarantine evidence and run receipts. Public APIs never query private payment CDC tables. The synthetic public summary is permanently retired with HTTP 410.

Vercel runs the existing pinned nonroot Python Docker/OCI image. Neon PostgreSQL is durable; public data is not stored in disposable container files. The private request-replay CDC profile remains separate. Synthetic bootstrap is disabled in production.

Public pages and public-source reads are anonymous. Schema initialization, source ingestion, provider-backed AI and all legacy operational routes require the private bearer token. Exact host allowlisting, CSP, no-store responses, bounded bodies and security headers remain.

No provider key/model is configured. The actual AI tool loop is implemented, but its UI/status API explicitly expose unavailable state, never simulated answers. See the current release and machine-readable evidence for exact verification and limitations. Older public/review evidence describes earlier, separately dated releases.
