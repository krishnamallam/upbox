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
            path=req.path,
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
