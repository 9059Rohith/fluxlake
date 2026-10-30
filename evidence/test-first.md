# Test-first evidence

The first dependency-free behavioral smoke test (`python tests/red_smoke.py`) was run before `src/fluxlake/lake.py` existed and failed with `ModuleNotFoundError: No module named 'fluxlake.lake'`. Its event then becomes a durable readable Parquet row once implemented.

Initial full-suite attempts during installation failed collection because dependencies were still downloading; these are environment failures and are not counted as passing tests or as behavioral red evidence.

The main behavioral tests were authored before implementation. Additional adversarial tests were added during review for source acknowledgement failures, commit-order gaps, competing local writers, and reserved attribute collisions. Final suite and regression results are recorded separately in verification.md.

Independent review regressions were reproduced before fixes: an unpaired surrogate attribute raised UnicodeEncodeError after state commit; invalid surrogate keys/ignored envelope fields were accepted; non-ASCII Authorization returned 500; whitespace-only configuration returned 401 instead of disabled 503. Four Unicode regressions, two authorization regressions and two directory-sync fault regressions were observed failing, fixed, and included in the final 39-test suite. A positive multibyte-string round trip prevents overrestricting legitimate UTF-8.
