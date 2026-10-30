# Statistical DriftLab verification — 2026-10-30

The new private diagnostic compares actual retained PostgreSQL outbox evidence in two explicit identity-index ranges. It is local repository work; no hosted deployment, push, CI execution, AWS provisioning or workflow change is claimed. Existing hosted release, inspection and benchmark artifacts remain separately dated.

## Test-first and review evidence

Initial RED runs observed 22 missing-engine/contract failures, four missing-route/client failures, eight actual-PostgreSQL missing-adapter/route failures, and ten missing-scenario/evaluator failures. Implementation then passed the corresponding tests.

Additional focused regressions were observed RED before their production fixes:

- Combined 4 MiB payload budget was initially checked after `fetchall`; a real PostgreSQL 72-row fixture proved JSON had transferred before rejection. A same-snapshot server-side preflight now rejects before any payload query.
- Oversized retained outbox operation metadata initially transferred before model rejection. Metadata length preflight now rejects before transfer.
- A slow partial request initially returned 422 after reading the whole body; the API now returns sanitized 408 at its bounded body-read deadline.

An independent parent-agent review inspected the engine, source adapter, contracts and client, and found no material blockers. It specifically checked integer-safe ECDF comparisons, explicit allocation-index scope, payload preflight and read-only semantics. Trial-level uncertainty and incidental synthetic alarms were retained explicitly.

## Final executed checks

| Check | Actual result |
|---|---|
| Windows Python 3.12.0, full suite, dedicated actual PostgreSQL 16.6 database | **134 passed**, no skips/failures, 201.47 s; [JUnit](driftlab-junit.xml) |
| Digest-pinned Linux Python 3.15.1 verify target, full suite, separate actual PostgreSQL 16.6 database | **134 passed**, no skips/failures, 118.40 s; [JUnit](driftlab-python315-junit.xml) |
| Ruff lint and format | All checks passed; 30 Python files formatted |
| `python -m pip check` | No broken requirements |
| `docker compose config --quiet`, `git diff --check` | Exit 0 |
| Pinned Docker verify and minimal runtime builds | Both succeeded; tags `fluxlake:driftlab-verify`, `fluxlake:driftlab` |

Both full runs emitted the same two visible upstream Starlette/httpx and AnyIO deprecation warnings. Several local project builds/containers were running concurrently; suite durations are execution evidence, not performance benchmarks. Runtime dependency pins, Python image digests, lockfiles and workflows are unchanged. No new package dependency was introduced.

There are 66 additional tests beyond the prior 68. They cover literal mathematical KS/PSI/JS reference values, ties, adjacent bigint precision, histogram support/tail boundaries, strict types/nonfinite values, frozen reports, policy-sensitive fingerprints, currency leakage, minimum-sample boundaries, status effects, empty/deleted observations, duplicate/out-of-range identities, category limits, authenticated request parsing, duplicate JSON fields, redaction, body deadlines, real HTTP client request/redirect/response budgets and CLI parsing.

Actual PostgreSQL tests cover acknowledged retained rows, tombstones, missing/pruned identities, changed retained payloads, one snapshot across both windows, late lower-ID commits, read-only transaction/isolation flags, unchanged source acknowledgements and unchanged request-mode projection manifest. Corrupt/oversized retained evidence fails the whole diagnostic; tests remove their corruption fixtures before other complete-history replay tests run.

## Minimal image HTTP smoke

[Raw smoke evidence](driftlab-runtime-smoke.json) records an actual running Python 3.15.1 minimal image, configured with a dedicated disposable PostgreSQL database. It ran as `10001:10001`, read-only root filesystem, dropped all capabilities, no-new-privileges and a noexec/nosuid `/tmp` tmpfs. Image identity: `sha256:83bbebfd9ccf04d248849753ac91b19a67c151b74698bd396a8475a7ba79e6e5`.

`scripts/drift_smoke.py` committed 600 explicitly synthetic source transactions in two windows, then called the real authenticated API and the HTTP CLI. Both currency groups reported the injected amount effect; currency mix stayed below its threshold. Repeat HTTP and CLI reports had the same fingerprint. All observed event payloads and `processed_at` values remained byte/value equivalent, and the cold request-mode projection manifest remained unchanged.

Anonymous comparison returned 401, oversized body 413 and invalid private-marker body a redacted 422. The harness removed its own source fixtures; the temporary API container and test database were removed. The script refuses fixture writes unless the configured database name ends in `_test`.

Reproduce against a running API pointed at the same disposable test database:

```powershell
# DATABASE_URL, FLUXLAKE_URL and FLUXLAKE_API_TOKEN must already be configured privately.
.venv\Scripts\python scripts/drift_smoke.py --output evidence/driftlab-runtime-smoke.json
```

The smoke harness writes/removes synthetic fixtures. `POST /drift/compare` itself only reads. A tiny source such as the existing 22-event hosted seed remains `insufficient_samples` at the default 30-event minimum; no statistics are fabricated to fill the gap.

## Controlled evaluation

[Raw evaluation](driftlab-evaluation.json) contains 60 trials per scenario, 400 events per window, seed 20261030 and the actual default policy. No-shift false alarms: **4/60 (6.67%; Wilson 95% 2.62–15.93%)**. Amount ×2.5 detections: **60/60**. Currency-mix detections: **60/60**. Both 60/60 Wilson intervals are 93.98–100%, not a perfect-detection guarantee.

Currency-mix trials also had **8/60 conditional amount alarms** despite the unchanged conditional law. The evaluator exposes these metric-specific alarms and their trial fingerprints. Wilson intervals describe independent synthetic Monte Carlo trials; they do not assume independent CDC events or establish production accuracy. The thresholds make descriptive effect decisions without p-values, hypothesis rejection or family-wise significance claims.

## Scope and retained limits

Identity indices are allocation order, not commit order or temporal windows. Gaps cannot establish retention completeness. Repeated source revisions are event-weighted; distributions describe retained insert/update payloads rather than current distinct entities. Amounts remain isolated by currency; there is no exchange-rate conversion.

The API bounds bodies, shape and read time; source acquisition bounds requested identity positions, payload bytes, metadata lengths and currency cardinality, with per-statement/lock timeouts. These bounds do not make it a full-history scalable profiler or a single total SQL request deadline. Fingerprints identify observed content/configuration; they are not signatures or proof against privileged source edits. [Detailed contract](../docs/driftlab.md).

[Code metrics](driftlab-code-metrics.json): **933 net new production/operational-script code lines**, **574 test code lines**; comments, docstrings, blank lines, documentation and evidence are excluded. Physical line counts are separately reported (1091 production net, 701 tests). These are measurements of the implemented scope, not generated line quotas.
