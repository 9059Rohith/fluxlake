# Development workflow

Use an isolated Python 3.12 virtual environment. Install `requirements-dev.lock`, then `pip install --no-deps -e .`. Update direct pins in `pyproject.toml`, install the changed environment, run `python scripts/lock.py`, and review both exact-version lock files. The locks do not include wheel hashes; use an approved package mirror/hash-locking policy for higher supply-chain assurance.

Behavior changes need a focused failing test before the implementation. Run the whole suite, `ruff check .`, `ruff format --check .`, runtime `pip-audit`, Docker build, and Terraform validation before claiming the change verified. Set `TEST_DATABASE_URL` for actual PostgreSQL tests; a skipped integration suite is not an integration pass.

Keep generated runtime data, credentials, `.env`, Terraform state and plans out of commits. Git branches use `codex/` by default. Describe validation scope honestly in pull requests, especially managed Glue behavior that cannot be exercised without AWS.

Integration tests mutate/ack outbox records into temporary sink directories. Run them against a disposable dedicated database (`fluxlake_test`), never against a source serving an existing lake. Reusing the demo database for tests would leave source acknowledgements pointing at discarded test sinks.
