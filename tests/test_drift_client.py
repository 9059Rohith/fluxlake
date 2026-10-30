import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from fluxlake.drift_client import fetch_report, parse_window
from fluxlake.drift_contracts import CompareRequest
from test_drift_api import PAYLOAD, TOKEN


@contextmanager
def server(status, body, location=None):
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed.append(
                (
                    self.path,
                    self.headers.get("Authorization"),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (ConnectionResetError, BrokenPipeError):
                pass

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", observed
    finally:
        httpd.shutdown()
        worker.join(timeout=2)
        httpd.server_close()


def test_client_sends_exact_authenticated_request_and_validates_report():
    from fluxlake.drift import compare_events

    req = CompareRequest.model_validate(PAYLOAD)
    report = compare_events(req, [], [])
    with server(200, report.model_dump_json().encode()) as (url, observed):
        assert fetch_report(url, TOKEN, req).fingerprint == report.fingerprint
    assert observed == [("/drift/compare", "Bearer " + TOKEN, req.model_dump())]


@pytest.mark.parametrize(
    "status,body",
    [(500, b"PRIVATE-DATABASE-ERROR"), (200, b"x" * 262145), (200, b'{"private":"secret"}')],
    ids=["server_error", "response_budget", "invalid_contract"],
)
def test_client_response_failures_and_budget_are_sanitized(status, body):
    req = CompareRequest.model_validate(PAYLOAD)
    with server(status, body) as (url, _):
        with pytest.raises(RuntimeError) as error:
            fetch_report(url, TOKEN, req)
    assert "PRIVATE" not in str(error.value) and "secret" not in str(error.value)


def test_client_does_not_forward_token_on_redirect():
    req = CompareRequest.model_validate(PAYLOAD)
    with server(200, b"{}") as (destination, observed):
        with server(307, b"", location=destination) as (origin, _):
            with pytest.raises(RuntimeError):
                fetch_report(origin, TOKEN, req)
    assert observed == []


@pytest.mark.parametrize("value", ["1", "1:2:3", "-1:2", "1.0:2", "١:٢", ":2", "1:"])
def test_cli_windows_reject_ambiguous_or_non_ascii_indices(value):
    with pytest.raises(ValueError):
        parse_window(value)
