# Statistical DriftLab

DriftLab answers a bounded question: how do retained transaction change events in two chosen identity-index ranges differ in their business distributions? It runs directly against the existing PostgreSQL outbox and complements selected-key projection inspection. It does not recompute gold, repair silver, replay source history, acknowledge events or infer source-table population drift.

## Contract

Authenticated `POST /drift/compare` accepts a strict object:

```json
{
  "baseline": {"start": 1, "end": 400},
  "candidate": {"start": 401, "end": 800},
  "policy": {
    "min_samples": 30,
    "bins": 5,
    "smoothing": 0.5,
    "ks_threshold": 0.25,
    "psi_threshold": 0.2,
    "status_js_threshold": 0.1,
    "currency_js_threshold": 0.05
  }
}
```

`policy` and each policy field are optional. Both windows are explicit, inclusive, disjoint and independently bounded to 2000 identity positions; reversed baseline/candidate chronological interpretations are not imposed. Indices are strict positive PostgreSQL bigint integers. Booleans, string coercion, overlap, unknown fields, duplicate JSON fields and nonfinite numbers fail validation. Policy limits: minimum samples 10–1000, requested quantile bins 2–20, pseudocount `(0,10]`, KS/JS thresholds `(0,1]`, PSI threshold `(0,100]`. Effects require a **strictly greater** metric value, not equality.

`fluxlake drift --url http://127.0.0.1:8000 --baseline 1:400 --candidate 401:800` invokes the same authenticated HTTP endpoint. The bearer token comes from `FLUXLAKE_API_TOKEN`; it is never a command argument. Remote origins require HTTPS; loopback HTTP is allowed. Redirects are refused, loopback proxies disabled, responses capped at 256 KiB and HTTP operations use a 20-second timeout. Errors omit remote response bodies and credentials.

The output includes:

- Frozen typed request/report structures and version `fluxlake-drift-v1`.
- One PostgreSQL snapshot ID/time, repeatable-read isolation and read-only status.
- Per-window observed/analyzed row counts, tombstones, repeated-key events, distinct analyzed keys, missing identity positions, observed index/time extents and evidence digest.
- Per-currency sample counts, integer nearest-rank amount summaries, amount metrics/histograms, status counts/divergence and effect flags.
- Currency composition counts/divergence independent of conditional business distributions.
- `effect_detected`, `no_effect_detected` or `insufficient_samples`; partial groups always retain explicit insufficient-sample flags. A detected currency-mix effect can coexist with insufficient within-currency samples.

Reports expose aggregate business statistics to authorized callers. They omit event IDs, entity keys, attribute bodies and source connection information. Raw fingerprints may still be sensitive operational metadata; retain reports in a trusted location.

## Window and snapshot meaning

`transaction_outbox.id` records sequence allocation, which can precede commit. It is **not commit order**, a commit watermark, an event-time interval or a wall-clock cohort. A transaction that allocated a low ID and commits late can appear in the same explicit window on a later comparison. A rollback can leave a gap. Pruning can remove evidence. Missing positions therefore never prove data loss or historical completeness.

Both windows and their size preflight are read within one PostgreSQL `REPEATABLE READ`, `READ ONLY` transaction. All SQL is fixed and parameterized. Retained rows are selected regardless of `processed_at`. Insert/update events contribute their payload at that revision; tombstones are excluded from distributions and counted. A key updated repeatedly contributes repeated event observations, even if that key also appears in the other window. This is event-weighted analysis rather than an independent entity sample.

`occurred_at` extents are descriptive metadata from the retained envelopes, not filters or proof of commit ordering. The source snapshot covers acquisition only. No source-to-Parquet distributed snapshot is claimed; DriftLab does not touch the local projection.

## Mathematics and finite samples

**KS amount distance:** `max_x |F_baseline(x) - F_candidate(x)|` over the union of observed integer amounts. Both ECDFs advance over a tie together. Comparisons and the numerator use integers, preserving adjacent bigint values beyond float precision. The statistic is well-defined for tied finite samples. No continuous-null KS p-value is attached. See [NIST two-sample KS reference](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/ks2samp.htm).

**Baseline-fixed PSI:** nearest-rank baseline quantiles define upper cuts, including the baseline maximum; duplicate cuts collapse. Two additional cells represent values strictly below and strictly above baseline support. Interior cells are right-closed and candidate values use the unchanged baseline cuts. If the baseline is constant, the three cells are below/equal/above that value. Each cell receives pseudocount `a`; normalized frequencies are `p_i=(b_i+a)/(n+a*K)` and `q_i=(c_i+a)/(m+a*K)`. PSI is `sum_i (q_i-p_i)*ln(q_i/p_i)`. Its finite denominators and strictly positive probabilities make empty cells safe. With unequal sample counts, count pseudocount smoothing can produce a small nonzero PSI even for identical observed constant values. Tail cells can make rare outliers operationally visible; policy thresholds need calibration for the workload.

**Categorical JS divergence:** for status or currency frequency vectors, `M=(P+Q)/2`, `JS=(KL_2(P||M)+KL_2(Q||M))/2`, using zero contribution for zero-probability cells. Values lie in `[0,1]` bits. This is divergence, not the square-root Jensen-Shannon distance; [SciPy's distance reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.distance.jensenshannon.html) makes that distinction explicit. New/disappearing categories remain visible in currency counts. Within-currency status and amount effects require both sample counts to meet the minimum; global currency JS uses both overall analyzed counts.

Amount effects flag when KS **or** PSI exceeds its configured threshold; status/currency use their own JS thresholds. These are descriptive operational policies. There are no null hypothesis tests, p-values, claimed family-wise error rates or implied multiple-test correction. Repeated CDC revisions and selected windows need not be IID. The separate controlled experiment measures empirical combined false alarms for its generator, not a statistical guarantee for arbitrary production traffic.

## Provenance and replay

Per-event evidence combines identity index, event UUID, key, revision, operation, UTC occurrence string, analyzed business fields and a SHA-256 of the canonical complete payload. Per-window hashes include all observed events in sorted identity order, including deletes. Thus a changed attribute can change provenance without changing amount/status effects. A report fingerprint includes the algorithm version, explicit ranges, policy, window evidence and analysis result. Acquisition time and PostgreSQL snapshot ID remain in the report but are excluded from this reproducible fingerprint; identical evidence/configuration gives the same fingerprint across observations.

Frozen contracts prevent accidental in-memory edits; hashes identify content. They do not authenticate a privileged source administrator, prove historical completeness, create a signed audit log or stop someone from replacing a saved report. Retained history must be trusted independently.

## Resource and privacy boundary

The API authenticates before consuming the comparison body, limits it to 4096 bytes, applies a 5-second body-read deadline, rejects excessive nesting, and redacts validation inputs. Source preflight checks both windows' payload sizes and metadata lengths before transferring JSON: at most 4000 total rows, 32 analyzed currencies, 64 KiB per payload and 4 MiB combined payload. JSON structure and strict amount/currency/status contracts are validated; any malformed retained event fails the entire request with sanitized 503. This avoids silently dropping invalid evidence.

PostgreSQL uses a 5-second connection timeout, 5-second **per-statement** timeout and 2-second lock timeout. Those are not a single whole-request deadline. Bounds are deliberately suitable for a small diagnostic, not a scalable full-history profiling service. Existing request-projection capacity remains separate. The public synthetic dashboard does not expose this private route.

## Controlled evaluation

Run `python scripts/evaluate_drift.py --seed 20261030 --trials 60 --samples 400 --output evidence/driftlab-evaluation.json`. This does not access PostgreSQL. The generator uses independent seeded lognormal events with USD/INR conditional scales and a shared status law. Scenarios are identical distributions, candidate amount multiplier 2.5, and candidate USD mix reduced from .65 to .15. Every trial invokes the production comparison engine and saves evidence fingerprints plus metric-specific alarms.

The actual Python 3.12 run recorded:

| Scenario | Target metric | Alarms / trials | Observed rate | 95% Wilson trial-rate interval |
|---|---|---:|---:|---|
| No shift | Any alarm (false positive) | 4 / 60 | 6.67% | 2.62–15.93% |
| Amount ×2.5 | At least one conditional amount alarm | 60 / 60 | 100% | 93.98–100% |
| Currency mix .65→.15 USD | Currency-mix alarm | 60 / 60 | 100% | 93.98–100% |

Currency-mix trials also triggered conditional amount alarms in 8/60 trials despite the unchanged conditional law, illustrating finite-sample/pseudocount effects when currency sample sizes change. No-shift false alarms were all amount alarms; no status alarms occurred in this run. Large injected shifts are easy cases, not minimum detectable effects. The small trial count yields wide uncertainty; 60/60 is not evidence of perfect future detection. Wilson intervals quantify this Monte Carlo trial-rate uncertainty only. Raw outcomes, generator description, policy and Python version remain in [the evaluation artifact](../evidence/driftlab-evaluation.json).

For a real PostgreSQL/HTTP check, point a running API at a disposable database ending `_test`, configure `DATABASE_URL`, `FLUXLAKE_URL`, `FLUXLAKE_API_TOKEN`, then run `python scripts/drift_smoke.py --output evidence/driftlab-runtime-smoke.json`. It writes 600 synthetic source rows, compares actual retained windows through HTTP and CLI, checks unchanged event data/acknowledgements, and removes its fixture keys. Optional `--manifest PATH` verifies projection bytes too. This harness writes fixtures; the diagnostic endpoint itself remains read-only.
