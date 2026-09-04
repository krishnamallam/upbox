"""Capture mitmproxy addon: persists every completed flow to SQLite, subject to capture.yaml.

Per CLAUDE.md's error-handling rule, hook bodies are wrapped in try/except
so an exception in capture never crashes the proxy. The next flow still
goes through. Failed captures are logged but otherwise silent.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

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

DEFAULT_RULES_RESOURCE = "capture.yaml"
USER_RULES_PATH = Path.home() / ".upbox" / "rules" / "capture.yaml"
_POLICY_KEYS = ("bodies", "headers")


@dataclass(frozen=True)
class CapturePolicy:
    """Which content columns the proxy stores. Metadata is always stored."""

    bodies: bool = True
    headers: bool = True

    @property
    def is_metadata_only(self) -> bool:
        return not self.bodies and not self.headers

    def omitted_columns(self) -> tuple[str, ...]:
        """The content columns this policy withholds, in schema order."""
        omitted: list[str] = []
        if not self.bodies:
            omitted.append("body_excerpt")
        if not self.headers:
            omitted.append("headers_json")
        return tuple(omitted)


METADATA_ONLY = CapturePolicy(bodies=False, headers=False)


def load_policy() -> CapturePolicy:
    """Read capture.yaml, preferring the user file over the bundled default.

    A user file that exists but is unreadable, not a mapping, or carries a
    non-boolean value yields metadata-only, not the bundled default. Its
    existence signals intent to restrict, and storing prompt bodies that were
    meant to be withheld is the direction that cannot be undone.
    """
    if USER_RULES_PATH.exists():
        try:
            raw = yaml.safe_load(USER_RULES_PATH.read_text())
        except Exception:
            log.exception("capture.yaml is unreadable; storing metadata only until it is fixed")
            return METADATA_ONLY
        policy = _parse_policy(raw)
        if policy is None:
            log.error("capture.yaml is invalid; storing metadata only until it is fixed")
            return METADATA_ONLY
        return policy
    bundled = yaml.safe_load(
        resources.files("upbox.rules").joinpath(DEFAULT_RULES_RESOURCE).read_text()
    )
    return _parse_policy(bundled) or CapturePolicy()


def _parse_policy(raw: object) -> CapturePolicy | None:
    """Turn parsed YAML into a policy, or None when the shape is wrong."""
    if not isinstance(raw, dict):
        return None
    values: dict[str, bool] = {}
    for key in _POLICY_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, bool):
            return None
        values[key] = value
    for key in raw:
        if key not in _POLICY_KEYS:
            log.warning("ignoring unknown capture.yaml key %r", key)
    return CapturePolicy(**values)


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
    """mitmproxy addon: persist every completed flow, subject to the capture policy."""

    def __init__(self, store: Store, policy: CapturePolicy | None = None) -> None:
        self._store = store
        self._policy = policy if policy is not None else load_policy()

    @property
    def policy(self) -> CapturePolicy:
        return self._policy

    def reload(self) -> None:
        """Re-read capture.yaml and swap the policy. Keeps the old one on failure."""
        try:
            new_policy = load_policy()
        except Exception:
            log.exception("capture policy reload failed; keeping previous policy")
            return
        self._policy = new_policy
        log.info(
            "reloaded capture.yaml (bodies=%s, headers=%s)", new_policy.bodies, new_policy.headers
        )

    def response(self, flow: http.HTTPFlow) -> None:
        """Called by mitmproxy after a response is received for a flow."""
        try:
            record = self._record_from_flow(flow)
            self._store.insert_request(record)
        except Exception:
            log.exception("capture addon failed on flow %s", getattr(flow, "id", "<unknown>"))

    def _record_from_flow(self, flow: http.HTTPFlow) -> RequestRecord:
        req = flow.request
        resp = flow.response
        body = req.content or b""
        policy = self._policy
        omitted = policy.omitted_columns()
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
            headers_json=(
                json.dumps(redact_headers(req.headers.items()))  # type: ignore[no-untyped-call]
                if policy.headers
                else None
            ),
            body_excerpt=truncate_body_excerpt(body) if policy.bodies else None,
            body_hash=hashlib.sha256(body).hexdigest() if body else None,
            redactions_applied_json=(
                json.dumps(flow.metadata["upbox_redactions"])
                if "upbox_redactions" in flow.metadata
                else None
            ),
            enforcement=flow.metadata.get("upbox_enforcement"),
            omitted_fields=json.dumps(list(omitted)) if omitted else None,
        )
