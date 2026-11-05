import logging

import psycopg
import pytest
from fastapi.testclient import TestClient

from fluxlake.api import create_app
from fluxlake.workspace import PublicWorkspace, WorkspaceUnavailable


class Connection:
    def __init__(self, setup_error=None, commit_error=None):
        self.setup_error = setup_error
        self.commit_error = commit_error
        self.closed = False
        self.commits = 0
        self.rollbacks = 0
        self.read_only = False
        self.isolation_level = None

    def execute(self, _query):
        if self.setup_error:
            raise self.setup_error

    def __enter__(self):
        return self

    def __exit__(self, error_type, _error, _trace):
        try:
            if error_type:
                self.rollbacks += 1
            else:
                self.commits += 1
                if self.commit_error:
                    raise self.commit_error
        finally:
            self.close()

    def close(self):
        self.closed = True


def connector(monkeypatch, outcomes):
    calls, sleeps = [], []

    def connect(_dsn, **settings):
        calls.append(settings)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("fluxlake.workspace.psycopg.connect", connect)
    monkeypatch.setattr("fluxlake.workspace.time.sleep", sleeps.append)
    return calls, sleeps


def test_transient_connect_retry_enters_body_once(monkeypatch):
    connection = Connection()
    calls, sleeps = connector(
        monkeypatch, [psycopg.OperationalError("private connection value"), connection]
    )
    entered = []
    with PublicWorkspace("private-dsn").connection(write=True) as current:
        entered.append(current)
    assert entered == [connection]
    assert len(calls) == 2 and len(sleeps) == 1
    assert all(call["connect_timeout"] == 5 for call in calls)
    assert connection.commits == 1 and connection.closed


def test_transient_setup_retry_closes_failed_connection_before_body(monkeypatch):
    failed = Connection(setup_error=psycopg.errors.ConnectionFailure("private setup value"))
    healthy = Connection()
    calls, sleeps = connector(monkeypatch, [failed, healthy])
    with PublicWorkspace("private-dsn").connection() as current:
        assert current is healthy and failed.closed
        assert current.read_only
        assert current.isolation_level == psycopg.IsolationLevel.REPEATABLE_READ
    assert len(calls) == 2 and len(sleeps) == 1


def test_exhausted_connect_retries_emit_only_safe_diagnostics(monkeypatch, caplog):
    calls, sleeps = connector(monkeypatch, [psycopg.OperationalError("secret-dsn-value")] * 3)
    caplog.set_level(logging.WARNING)
    with pytest.raises(WorkspaceUnavailable) as error:
        with PublicWorkspace("secret-dsn-value").connection():
            pytest.fail("Unavailable connections must not enter the body")
    assert len(calls) == 3 and len(sleeps) == 2
    assert error.value.diagnostic == {
        "phase": "connect",
        "exception_type": "OperationalError",
        "sqlstate": None,
        "attempt": 3,
        "retrying": False,
    }
    assert "phase=connect" in caplog.text and "type=OperationalError" in caplog.text
    assert "sqlstate=none" in caplog.text and "attempt=3" in caplog.text
    assert "secret-dsn-value" not in caplog.text + str(error.value)


@pytest.mark.parametrize(
    "failure",
    [
        psycopg.errors.InvalidPassword("private"),
        psycopg.errors.InvalidCatalogName("private"),
        psycopg.errors.SyntaxError("private"),
        psycopg.errors.InsufficientPrivilege("private"),
        psycopg.errors.QueryCanceled("private"),
        ValueError("private"),
    ],
)
def test_permanent_setup_failure_is_not_retried(monkeypatch, failure):
    connection = Connection(setup_error=failure)
    calls, sleeps = connector(monkeypatch, [connection])
    with pytest.raises(WorkspaceUnavailable) as error:
        with PublicWorkspace("private-dsn").connection():
            pytest.fail("Invalid sessions must not enter the body")
    assert len(calls) == 1 and not sleeps and connection.closed
    assert error.value.diagnostic["phase"] == "session_setup"


def test_body_failure_never_replays_the_yielded_operation(monkeypatch):
    connection = Connection()
    calls, sleeps = connector(monkeypatch, [connection])
    operations = []
    with pytest.raises(WorkspaceUnavailable) as error:
        with PublicWorkspace("private-dsn").connection(write=True):
            operations.append("write")
            raise psycopg.errors.ConnectionFailure("secret statement")
    assert operations == ["write"] and len(calls) == 1 and not sleeps
    assert connection.rollbacks == 1
    assert error.value.diagnostic["phase"] == "body"
    assert error.value.diagnostic["sqlstate"] == "08006"


def test_ambiguous_commit_never_replays_the_body(monkeypatch):
    connection = Connection(commit_error=psycopg.OperationalError("secret commit value"))
    calls, sleeps = connector(monkeypatch, [connection])
    operations = []
    with pytest.raises(WorkspaceUnavailable) as error:
        with PublicWorkspace("private-dsn").connection(write=True):
            operations.append("write")
    assert operations == ["write"] and len(calls) == 1 and not sleeps
    assert connection.commits == 1 and connection.closed
    assert error.value.diagnostic["phase"] == "commit"


@pytest.mark.parametrize(
    "failure",
    [
        psycopg.ProgrammingError('invalid connection option "private"'),
        psycopg.OperationalError('FATAL: password authentication failed for user "private"'),
        psycopg.OperationalError('FATAL: database "private" does not exist'),
        psycopg.OperationalError('root certificate file "private" does not exist'),
    ],
)
def test_known_connect_configuration_errors_fail_fast(monkeypatch, failure):
    calls, sleeps = connector(monkeypatch, [failure])
    with pytest.raises(WorkspaceUnavailable) as error:
        with PublicWorkspace("private-dsn").connection():
            pytest.fail("Invalid configuration must not enter the body")
    assert len(calls) == 1 and not sleeps
    assert error.value.diagnostic["phase"] == "connect"


def test_public_response_and_default_log_text_do_not_expose_driver_details(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.setenv("DATABASE_URL", "private-dsn-value")
    connector(monkeypatch, [psycopg.ProgrammingError("private-driver-message")])
    client = TestClient(create_app(tmp_path))
    response = client.get("/api/workspace/overview")
    assert response.status_code == 503
    assert "Public event store is unavailable" in response.json()["detail"]
    assert (
        "phase=connect type=ProgrammingError sqlstate=none attempt=1 retrying=False" in caplog.text
    )
    for secret in ("private-dsn-value", "private-driver-message"):
        assert secret not in response.text + caplog.text
