"""Capture mitmproxy addon — persists every completed flow to SQLite.

Per CLAUDE.md's error-handling rule, hook bodies are wrapped in try/except
so an exception in capture never crashes the proxy. The next flow still
goes through. Failed captures are logged but otherwise silent.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from upbox.db.store import RequestRecord, Store, truncate_body_excerpt

if TYPE_CHECKING:
    from mitmproxy import http

log = logging.getLogger(__name__)


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
            tool=None,  # Filled in by fingerprint addon on Day 4.
            method=req.method,
            scheme=req.scheme,
            host=req.host,
            path=req.path,
            req_bytes=len(body),
            resp_bytes=len(resp.content) if resp and resp.content else None,
            status=resp.status_code if resp else None,
            headers_json=json.dumps(dict(req.headers.items())),  # type: ignore[no-untyped-call]
            body_excerpt=truncate_body_excerpt(body),
            body_hash=hashlib.sha256(body).hexdigest() if body else None,
            redactions_applied_json=None,  # Filled in by redact addon on Day 7.
            blocked=0,  # Set by enforce addon on Day 8.
        )
