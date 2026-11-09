# Portable replay evidence

Replay audit can now export the inputs needed to reproduce its publication checks. In **Replay audit**, select one or two acquisitions and choose **Download replay bundle**. The existing report download remains available. The bundle route is an anonymous read-only GET:

```text
/api/workspace/replay/bundle?run=<retained-acquisition-uuid>
```

Omit `run` to use the newest acquisition. Repeated, unknown or more than two selected identities are rejected. An empty store returns 404. This change is implemented and verified locally; the evidence below does not assert that the new route is deployed.

Each `fluxlake-replay-bundle-v1` object contains the actual retained Bronze JSON, Silver fields, acquisition and quarantine receipts, a snapshot identity and observation time, and the reconstructed report. The inputs come from the existing repeatable-read, read-only database transaction. No source fetch, model inference, migration or publication occurs during export. The existing 200-row-per-layer, 4 MiB canonical source and 64 KiB individual source limits apply; the complete canonical export is additionally limited to 4 MiB. The stricter total limit bounds the downloadable response as well as the raw input; oversized selections fail closed with 503. Raw objects must remain explicitly public. Rejected and duplicate delivery bodies are unavailable and are not invented.

## Reproduce the checks offline

From an installed FluxLake checkout, run:

```powershell
.venv/Scripts/python -m fluxlake.replay_bundle fluxlake-replay-bundle.json
```

The verifier reads at most 4 MiB plus one overflow byte. It rejects duplicate JSON keys, non-finite numbers, unknown versions, invalid identities and excessive row or source budgets. It checks the bundle fingerprint, then reruns the normalization, canonical source hashes and byte counts, typed publication comparison and receipt reconciliation from the exported inputs. It requires the entire reconstructed report to equal the included report. It does not connect to PostgreSQL, GitHub or a model provider.

| Exit | Meaning |
|---|---|
| 0 | Report reproduced and retained publication checks are consistent |
| 1 | Report reproduced and identifies publication differences |
| 2 | Invalid, oversized, modified or unreproducible evidence |

The `bundle_sha256` covers canonical sorted-key JSON for every top-level field except itself, including the snapshot. It consequently changes between new observations. The separate `evidence_sha256` retains the existing report fingerprint, excluding the observation snapshot. To compare an export against a fingerprint received through a separately trusted channel:

```powershell
.venv/Scripts/python -m fluxlake.replay_bundle fluxlake-replay-bundle.json --expected-sha256 <trusted-bundle-sha256>
```

A hash bundled with the same file does not authenticate its publisher. Rehashing edited inputs alone fails report reconstruction, but an author who replaces the inputs and recomputes the entire report and manifest can produce another self-consistent bundle. A separately trusted pin can detect that replacement. The verifier uses the same checked-in normalization contract as the application; it is an offline reproduction, not a second independent implementation of that contract. Neither this export nor its hashes prove source completeness, original HTTP bytes, source delivery order, cryptographic GitHub authenticity or exactly-once delivery.

## Real-source verification

The reproducible harness validates the previously pinned historical GH Archive object and publishes its first 200 eligible unique public events into a newly initialized disposable PostgreSQL cluster. It downloads the two selected acquisitions through the real application route, verifies the downloaded bundle in a separate offline CLI process, and checks that the complete publisher inventory is unchanged. A controlled alteration of one stored Silver actor produces exactly one reproducible publication difference. Editing the downloaded evidence without updating its manifest is rejected. These fault probes affect only the disposable cluster.

```powershell
.venv/Scripts/python scripts/verify_replay_bundle.py .downloads/2025-01-01-15.json.gz --postgres-bin 'C:/Program Files/PostgreSQL/18/bin'
```

The harness then runs the complete pytest suite against that disposable cluster and removes it. Its retained source sample is [the downloadable portable bundle](../evidence/replay-bundle-archive.json). The dated observations and exact counts are in [verification evidence](../evidence/replay-bundle-verification.json), [full test report](../evidence/replay-bundle-junit.xml) and [execution log](../evidence/replay-bundle-local.log). Test-first failures before implementation are retained in [the red run](../evidence/replay-bundle-red.log).

The final run on 9 November 2026 passed **280 tests, zero failures and zero skips**. Two upstream deprecation warnings concern Starlette's current `httpx` TestClient and AnyIO alias. An earlier run exposed an incorrect new-test assumption that changing an actor preserves the distinct-actor aggregate; [that failure](../evidence/replay-bundle-first-suite.log) is retained. A second run hit a pre-existing inspection test that searched for `999` across the entire stringified response: a random Parquet filename contained those digits. Its assertion now checks the exact diagnostic fields for payload omission. [Original random-filename failure](../evidence/replay-bundle-flaky-inspection.log). Whole-file overflow rejection was separately observed red before tightening the total budget. [Budget red run](../evidence/replay-bundle-budget-red.log)

Local Playwright checks at 1440 × 1050 and 390 × 844 exercised selecting a second acquisition, reconstructing the report and downloading all 200 events. Both had no console errors or document overflow; the screenshots were visually inspected. The Browser plugin was unavailable, so the checks used the already installed Playwright and Chromium. [Browser observations](../evidence/replay-bundle-browser.json). The locked runtime dependency audit found no known vulnerabilities. [Audit output](../evidence/replay-bundle-dependency-audit.log). Full-repository Ruff lint and formatting, JavaScript syntax, five client tests and `pip check` passed. Two older files received formatting-only corrections to satisfy the existing release gate.
