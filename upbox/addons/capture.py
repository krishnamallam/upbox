"""Capture mitmproxy addon — persists every completed flow to SQLite.

Per CLAUDE.md's error-handling rule, hook bodies are wrapped in try/except
so an exception in capture never crashes the proxy. The next flow still
goes through. Failed captures are logged but otherwise silent.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from upbox.addons._hostname import resolve_host
from upbox.db.store import RequestRecord, Store, truncate_body_excerpt

if TYPE_CHECKING:
    from mitmproxy import http

log = logging.getLogger(__name__)

# Headers whose value authenticates the caller. Their values are replaced with
# a marker before the row is stored.
#
# This is not body redaction and is deliberately kept out of
# ``redactions_applied_json``. The real header value was still forwarded to the
# destination; only what upbox *stores* changes. Conflating the two would let
# the dashboard imply a credential never left the machine when it did.
SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "x-auth-token",
        "x-session-token",
        "x-goog-api-key",
        "openai-organization",
    }
)

HEADER_REDACTION_MARKER = "[REDACTED:header]"

# Query parameters that carry credentials. Google, and plenty of smaller APIs,
# accept the key in the URL, and mitmproxy's ``request.path`` includes the query
# string. Storing it verbatim is the same defect as the header one, and worse in
# one respect: ``path`` is chained directly rather than via a digest, so
# retention cannot clear it later without breaking verification. It has to be
# kept out at capture time or not at all.
SENSITIVE_QUERY_PARAMS = frozenset(
    {
        "key",
        "api_key",
        "apikey",
        "access_token",
        "token",
        "auth",
        "auth_token",
        "session",
        "sig",
        "signature",
        "password",
        "secret",
        "client_secret",
        "refresh_token",
        "id_token",
    }
)

QUERY_REDACTION_MARKER = "[REDACTED:query]"


def redact_query_string(path: str) -> str:
    """Replace credential-bearing query parameter values with a marker.

    Keeps the parameter name and position so the path stays recognisable and an
    auditor can still see that a key was passed in the URL. Anything upbox
    cannot parse is returned unchanged rather than guessed at.
    """
    head, sep, query = path.partition("?")
    if not sep or not query:
        return path
    # Split manually rather than via parse_qsl: that drops empty values,
    # collapses separators, and unquotes, all of which would silently rewrite a
    # path that gets hashed into the chain.
    parts: list[str] = []
    for pair in query.split("&"):
        name, eq, _value = pair.partition("=")
        if eq and name.lower() in SENSITIVE_QUERY_PARAMS:
            parts.append(f"{name}={QUERY_REDACTION_MARKER}")
        else:
            parts.append(pair)
    return f"{head}?{'&'.join(parts)}"


def redact_headers(items: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Replace auth-bearing header values with a marker, keeping the names.

    Names are kept so the audit record still shows the request carried a
    credential, which is itself evidence, without storing the credential.
    Matching is case-insensitive because header casing is not normalised.
    """
    return {
        name: (HEADER_REDACTION_MARKER if name.lower() in SENSITIVE_HEADERS else value)
        for name, value in items
    }


class CaptureAddon:
    """mitmproxy addon: persist every completed flow."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def response(self, flow: http.HTTPFlow) -> None:
        """Called by mitmproxy after a response is received for a flow."""
        try:
            record = self._record_from_flow(flow)
            self._store.insert_request(record)
        except Exception:
            log.exception("capture addon failed on flow %s", getattr(flow, "id", "<unknown>"))

    @staticmethod
    def _record_from_flow(flow: http.HTTPFlow) -> RequestRecord:
        req = flow.request
        resp = flow.response
        body = req.content or b""
        return RequestRecord(
            ts=datetime.now(UTC).isoformat(),
            tool=flow.metadata.get("upbox_tool"),
            method=req.method,
            scheme=req.scheme,
            host=resolve_host(flow),
            path=redact_query_string(req.path),
            req_bytes=len(body),
            resp_bytes=len(resp.content) if resp and resp.content else None,
            status=resp.status_code if resp else None,
            headers_json=json.dumps(redact_headers(req.headers.items())),  # type: ignore[no-untyped-call]
            body_excerpt=truncate_body_excerpt(body),
            body_hash=hashlib.sha256(body).hexdigest() if body else None,
            redactions_applied_json=(
                json.dumps(flow.metadata["upbox_redactions"])
                if "upbox_redactions" in flow.metadata
                else None
            ),
            enforcement=flow.metadata.get("upbox_enforcement"),
        )
