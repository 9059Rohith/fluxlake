# Workspace connection recovery

`PublicWorkspace.connection()` now retries transient connection and session-setup failures before entering the caller body. It makes at most three attempts, with waits of 0.25 and 0.75 seconds. Each connection keeps the existing 5-second connect timeout, 8-second statement timeout and 2-second lock timeout. Session setup establishes the existing read-only repeatable-read behavior or the write transaction settings.

The retry loop ends before the single yielded body. A read, publication, source fetch, body failure or commit acknowledgement failure is never replayed by this mechanism. PostgreSQL retains responsibility for commit and rollback. A client error after commit requires reconciliation through retained identities and receipts before an operator decides what to do next.

Transient connection SQLSTATE values cover connection loss, server restart/startup and connection capacity. The connection error family can lack SQLSTATE during libpq startup. Recognized authentication, missing database/role, invalid option and certificate/key configuration failures fail fast. Other SQL, permission, statement-cancellation and Python errors fail through the safe unavailable response.

## Diagnostics

The default emitted log text includes phase, exception type, SQLSTATE, attempt and whether a retry follows. It also carries the same fields as structured logging metadata. `WorkspaceUnavailable.diagnostic` exposes this fixed dictionary to an operator harness. The public HTTP response retains the safe unavailable message. The error message and DSN are excluded from emitted diagnostics.

The native recovery observation emitted fields such as `phase=connect type=ConnectionTimeout sqlstate=none attempt=1 retrying=True`. The deliberately lost commit acknowledgement emitted `phase=commit type=OperationalError sqlstate=none attempt=1 retrying=False`.

Both archive and incremental-model benchmark commands retain database diagnostics on success. A failed run writes a separate `.failure.json` with safe terminal fields and preserves an existing successful output file. The benchmark CLI exits unsuccessfully after saving the diagnostic artifact.

The older independent `WorkspaceUnavailable` failure remains unconfirmed because its underlying exception and disposable server log were not retained. This release does not attribute a cause to that historical observation. [Earlier failure and rerun record](incremental-hourly-model.md#independent-attempt-and-bounded-rerun)

## Reproduce the local fault observation

```powershell
.venv/Scripts/python.exe scripts/verify_workspace_connection_recovery.py .downloads/2025-01-01-15.json.gz --postgres-bin 'C:/Program Files/PostgreSQL/18/bin'
```

The script uses a disposable PostgreSQL cluster and the first 200 admitted records from the checksum-verified archive. It stops its own server, observes failed connection attempts, starts the server, and verifies that one source-body call produces 100 persisted events and one receipt. It then commits the second real batch and deliberately raises a client acknowledgement error after that real commit. Independent SQL verifies 200 total events and two receipts, with one connection and one source-body call for the uncertain commit. This acknowledgement loss is controlled in the client wrapper. The wrong-password check uses actual PostgreSQL authentication and fails after one attempt. [Native fault evidence](../evidence/workspace-connection-recovery.json)

The full PostgreSQL-enabled regression suite passed 208 cases. The 16 new cases began with failing regressions and verify retry limits, failed-session cleanup, fail-fast permanent errors, emitted metadata and public redaction, body execution once and uncertain commit behavior. [JUnit evidence](../evidence/workspace-connectivity-junit.xml)
