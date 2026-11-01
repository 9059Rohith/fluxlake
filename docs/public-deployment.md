# Public deployment

[Open FluxLake](https://rohith-fluxlake.vercel.app) · [Real evidence API](https://rohith-fluxlake.vercel.app/api/workspace/overview) · [Current release verification](workspace-release.md)

The public experience is a 13-page GitHub public-event analytical workspace. Dedicated PostgreSQL tables retain actual API acquisitions, original JSON/SHA-256 evidence, typed silver, schema observations, quarantine evidence and run receipts. Public APIs never query private payment CDC tables. The synthetic public summary is permanently retired with HTTP 410.

Vercel runs the existing pinned nonroot Python Docker/OCI image. Neon PostgreSQL is durable; public data is not stored in disposable container files. The private request-replay CDC profile remains separate. Synthetic bootstrap is disabled in production.

Public pages and public-source reads are anonymous. Schema initialization, source ingestion, the separate operator analyst endpoint and all legacy operational routes require the private bearer token. The recruiter-facing analyst uses the separate anonymous `/api/workspace/agent/demo` endpoint with persistent client and shared free-capacity limits. Exact host allowlisting, CSP, no-store responses, bounded bodies and security headers remain.

The analyst is configured for Google Gemini 3.5 Flash Lite with a server-only key from a billing-disabled Google project. Its operator-authenticated tool loop uses only public GitHub evidence and exposes explicit free-quota errors without a paid fallback. See [Gemini verification](gemini-release.md) for actual provider/tool/answer evidence. See the current release and machine-readable evidence for exact verification and limitations. Older public/review evidence describes earlier, separately dated releases.
