# Replay audit release — 2 November 2026

[Open Replay audit](https://rohith-fluxlake.vercel.app/workspace/replay).
Runtime commit `0b39db8` is Ready in deployment `dpl_DWAhTFF6W248CEjt8qZ8jRbTiqdG`,
[unique deployment](https://fluxlake-ikwtqfzmb-rohiths-projects-5e14931b.vercel.app).
Vercel CLI inspection confirmed the canonical `rohith-fluxlake.vercel.app` alias.

The fourteenth workspace page reconstructs one or two actual retained GitHub acquisitions.
It checks canonical hashes and bytes, normalized fields, missing layers and acquisition
provenance, then reconciles bronze/silver/quarantine counts with receipts. Readers can sort
the event timeline, filter differences, inspect exact expected/observed values, open original
evidence and download the fingerprinted report. Existing navy/violet components and CSP are
preserved. No schema changes, dependencies, provider calls or public-source writes were added.

## Fresh verification

- Complete PostgreSQL-enabled Python suite: **191 passed, zero skips/failures**. A disposable
  local database was created and dropped; production was never used for test fixtures.
  [JUnit evidence](../evidence/replay-postgres-junit.xml). The 15 new replay cases cover exact
  damage, real SQL read-only behavior and duplicate/conflict ingestion receipts, stable
  evidence ordering, large IDs, missing rows, failed/empty runs and bounded bytes/rows.
- TDD began with seven cases failing on the absent replay module, then API/source cases
  failing on the absent store method, followed by implementation and green verification.
- Ruff check and format check passed across all 48 Python files. Both JavaScript files passed
  Node syntax checks; the five existing client safety/rendering tests passed.
- Production dependency audit: no known vulnerabilities. No dependency versions changed.
- Existing production smoke: **39 HTTP checks / all 14 pages** passed, including original
  hashes, filters, CSV, drift, source provenance and anonymous private-route denials.
  [HTTP evidence](../evidence/replay-workspace-http.json).
- Real Replay API: both retained acquisitions reconstruct **200 bronze and 200 silver rows**,
  with zero event differences. Three observations and the download have the same SHA-256:
  `e00c837536cb024c38b6685a619c9d275e68d6835b01e91e010b588b14324db2`.
  Source counts are unchanged. Malformed, repeated, excessive and missing selections produce
  422/404 responses; private mutations remain anonymous 401. [Replay evidence](../evidence/replay-verification.json).

The controlled local CPU benchmark uses 200 generated test-only records / 3,632,890 canonical
bytes, never persisted or deployed: median 59.8 ms, maximum 91.6 ms over ten runs. Actual
public API observations over the retained 200 events have median 894.8 ms, maximum 1,046.8 ms
over three requests. Those HTTP measurements include network and database work; they are
observations on this run, not a service-level guarantee or a source-stream throughput claim.

The implementation agent did not use the shared browser. The coordinator performs actual
rendered desktop/mobile interaction verification separately; HTTP success is not presented
as browser verification.

## Evidence limits

First accepted JSON is retained; duplicate bodies and original HTTP response bytes are not.
Quarantine retains hashes/reasons, so rejected field differences cannot be reconstructed.
Timestamp ordering does not establish delivery or database commit order. No stale-delivery,
complete-history or exactly-once claim is made. The separate second pass repeats retained
identities only in memory. Report hashes exclude the per-observation source snapshot and
are fingerprints rather than authentication. See [design and primary-source research](replay-audit.md).

The existing Gemini 3.5 Flash Lite/free-project configuration, private authentication and
persistent public limits remain unchanged: 3/client/600 seconds, shared 2/60 seconds and
30/UTC day. Verification made no model calls or allowance-counter resets.
