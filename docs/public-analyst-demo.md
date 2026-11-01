# Recruiter-ready public analyst

The analyst at `/workspace/agent` uses a separate anonymous `POST /api/workspace/agent/demo` endpoint. No account, operator token or credential entry is needed. The original `/api/workspace/agent` endpoint remains authenticated, as do ingestion, schema initialization and every private CDC operation.

## A finite free allowance

Three fixed-window budgets are reserved together before inference: **3 attempts per client per 600 seconds**, **2 shared attempts per 60 seconds**, and **30 shared attempts per UTC day**. A reservation consumes a slot even if the provider later fails. Invalid input and rejected origins consume no slot. Denied requests never call the model. HTTP 429 responses include `Retry-After`, and the UI displays the cooldown and disables submission until it expires. Provider quota errors remain explicit; there is no paid fallback.

PostgreSQL is the durable quota authority in production. An advisory transaction lock coordinates all three budgets across workers and instances, including newly created buckets; checks and increments commit atomically. Database failures return 503 before inference. Expired records are removed, and denied identities are not inserted, bounding storage growth. An explicitly configured SQLite backend exists only for local tests; hosted requests never fall back to ephemeral files after a database failure.

## Identity and request boundary

The limiter stores only a server-secret HMAC of the canonical client address, fixed-window timestamps, counts and expiration. Raw IP addresses and the HMAC secret are not written into quota records or returned to clients. The existing private API token supplies the server secret. Rotating it changes client identities while shared budgets remain intact.

Forwarded addresses are ignored outside the trusted Vercel runtime. Only `VERCEL=1` enables the platform-overwritten `x-forwarded-for` header, and the header must contain exactly one valid IP. Invalid or multi-address headers are rejected. Otherwise the socket peer supplies the address. The status API exposes the nonsensitive configured identity source so deployment checks can verify this boundary.

Browser origins must exactly match the current origin or its exact canonical HTTPS origin. Cross-site and `Origin: null` requests are rejected. Non-browser JSON clients without an Origin header may use the same bounded public endpoint. The only accepted body field is a meaningful question of **5–600 characters**, with a **4,096-byte body limit**, nesting bound and body deadline. Model, provider, URL, SQL and execution controls cannot be supplied by callers.

## Real evidence and preserved permissions

The public workflow uses the existing actual Gemini tool loop, fixed provider endpoint and real retained GitHub evidence. It can read overview, bounded public event search, fixed aggregates and latest-run drift only. Its maximum remains six tool calls across four model turns, with bounded provider responses and escaped output. No private CDC rows, uploads, credentials, writes or generated SQL are exposed to the public model tools.

The UI shows free capacity and public-data restrictions and submits no Authorization header to the demo endpoint. Private operator workflows retain their existing bearer boundary. Unit security fixtures use a controlled provider only inside tests; shipped application responses always come from the actual configured model or an honest error.

## Verification

Regression coverage includes anonymous real tool-loop control flow, client and shared quotas, no provider call after rejection, restart persistence, concurrent reservations, daily capacity, spoofed forwarded headers, trusted-header parsing, origin rejection, oversized/unknown inputs, fail-closed storage and unchanged private-route authentication. Dedicated actual PostgreSQL tests exercise concurrency across independent instances and persisted client/day budgets. Tests use disposable local databases rather than production data.

The live check is coordinated to preserve capacity: one anonymous HTTP investigation, a separate anonymous browser investigation, then an expected shared-capacity 429. Sanitized results contain public answers, tool traces, statuses and retry intervals, never credentials or raw client addresses.

The final complete suite passed **174 tests with zero failures and zero skips** in 83.38 seconds, including actual PostgreSQL concurrency and all existing fault/replay tests. Two existing deprecation warnings remain. Ruff, formatting, JavaScript syntax and installed-dependency checks passed. Dedicated local test databases were removed, and Docker Desktop was returned to its initially stopped state after validation. Production identity metadata confirmed `VERCEL=1` and the trusted platform-overwritten forwarded-address source. No explicit proxy-trust override was needed.

## Verified anonymous release

Application commit `f5c2bde` is deployed as `dpl_Fc29GHan3uju137WxNBDhmC3FeVt` on both production aliases. The authenticated idempotent migration initialized the quota table successfully. An anonymous same-origin HTTP investigation returned 200, made two actual Gemini-selected database tool calls and reported the 200 retained GitHub events with exact source citations. Private analyst and ingestion requests without authorization remained 401; cross-origin and invalid public requests were rejected before inference.

The coordinator used a fresh anonymous built-in browser session. It observed an actual 429 with a two-second displayed cooldown, retried after the cooldown, and received a real 200 answer with two tools in 2,319 ms. Counts were PushEvent 157, CreateEvent 22, DeleteEvent 15 and PullRequestEvent 6, with API citations and sample limits. Browser logs showed zero warnings/errors. The cooldown display is recorded as browser evidence; no unobserved Retry-After header value is claimed. No further model probes were made after the successful browser check.

Sanitized proof: `evidence/public-analyst-live.json`, `evidence/public-analyst-junit.xml`, `evidence/public-demo-browser.png`, `evidence/public-demo-browser.txt` and `evidence/public-demo-browser-cooldown.png`. The evidence contains no credentials, raw client addresses or opaque model signatures.
