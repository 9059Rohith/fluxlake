"""HTTP-only CLI client; bearer authentication follows the API boundary."""

from __future__ import annotations

import ipaddress
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from fluxlake.drift_contracts import CompareRequest, DriftReport

MAX_RESPONSE_BYTES = 256 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an operational bearer token through redirects.
        return None


def fetch_report(url: str, token: str, request: CompareRequest) -> DriftReport:
    parts = urlsplit(url)
    try:
        local = parts.hostname == "localhost" or ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        local = False
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
        or (parts.scheme == "http" and not local)
    ):
        raise ValueError("Use an HTTPS origin or local loopback HTTP origin without credentials")
    if not 32 <= len(token.encode("utf-8")) <= 4096 or any(c in token for c in "\r\n"):
        raise ValueError("Configure FLUXLAKE_API_TOKEN with a strong bearer token")
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/drift/compare",
            data=request.model_dump_json().encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method="POST",
        )
        # No environment proxy should receive loopback operational credentials.
        handlers = [_NoRedirect()]
        if local:
            handlers.append(urllib.request.ProxyHandler({}))
        with urllib.request.build_opener(*handlers).open(req, timeout=20) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("Report exceeds response budget")
            return DriftReport.model_validate_json(body)
    except Exception:
        raise RuntimeError(
            "Drift API request failed; verify origin, token and source availability"
        ) from None


def parse_window(value: str) -> dict[str, int]:
    try:
        pieces = value.split(":")
        if len(pieces) != 2 or any(
            not piece.isascii() or not piece.isdecimal() for piece in pieces
        ):
            raise ValueError
        return {"start": int(pieces[0]), "end": int(pieces[1])}
    except (ValueError, OverflowError):
        raise ValueError("Windows require inclusive START:END identity indices") from None
