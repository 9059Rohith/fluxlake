# Deployment host boundary

Public mode still requires explicit `FLUXLAKE_ALLOWED_HOSTS`; a platform variable cannot satisfy that requirement. When `VERCEL=1`, the app additionally permits the exact `VERCEL_URL` if it is one lowercase DNS label (1–63 characters, alphanumeric ends, internal hyphens allowed) followed by `.vercel.app`. Invalid or missing platform values add no host. No wildcard is allowed, and request headers do not configure this list. Localhost and the existing non-public test-server behavior are preserved.

Vercel documents `VERCEL_URL` as a scheme-less generated deployment domain available at build and runtime, and `VERCEL=1` as the platform system-variable indicator: [official system environment variables](https://vercel.com/docs/environment-variables/system-environment-variables#vercel_url).

The deployment-host regression first reproduced HTTP 400 for a valid platform deployment hostname. After the fix, the targeted suite passed **64 tests**, with no skips and two existing dependency deprecation warnings:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_deployment_host.py tests/test_api.py tests/test_public_analyst.py tests/test_workspace_connections.py -q
.venv/Scripts/python.exe -m ruff check src/fluxlake/api.py tests/test_deployment_host.py
```

Coverage includes canonical/deployment acceptance, sibling and child deployment rejection, forged forwarded-host rejection, malformed platform values, platform-flag gating, required canonical configuration, private-route authentication and unchanged connection retry boundaries. The actual staged deployment is verified separately during rollout; these tests do not claim production verification.
