"""Tool fingerprinting addon — tags each flow with the originating AI tool.

Runs on mitmproxy's ``request`` hook (before capture's ``response`` hook),
so the capture addon can persist the tool name. Fields:

- ``ua_contains``: substring match against ``User-Agent``.
- ``hosts``: exact host match, plus subdomain match (``host == h`` or
  ``host.endswith("." + h)``).
- ``headers``: exact ``name: value`` match, case-insensitive on the name.

A rule matches when every condition it specifies holds. Rules are tried in
file order; first match wins. Unmatched flows get ``None``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from mitmproxy import http

log = logging.getLogger(__name__)

DEFAULT_RULES_RESOURCE = "tools.yaml"
USER_RULES_PATH = Path.home() / ".upbox" / "rules" / "tools.yaml"


@dataclass(frozen=True)
class ToolRule:
    """One classification rule. All non-empty fields must hold to match."""

    name: str
    ua_contains: tuple[str, ...]
    hosts: tuple[str, ...]
    header_matches: tuple[tuple[str, str], ...]  # (lowercase header name, expected value)


def _parse_rules(raw: list[dict[str, object]] | None) -> list[ToolRule]:
    rules: list[ToolRule] = []
    for entry in raw or []:
        match = entry.get("match", {}) or {}
        if not isinstance(match, dict):
            continue
        header_matches: list[tuple[str, str]] = []
        for header in match.get("headers", []) or []:
            if isinstance(header, str) and ":" in header:
                name, value = header.split(":", 1)
                header_matches.append((name.strip().lower(), value.strip()))
        rules.append(
            ToolRule(
                name=str(entry["name"]),
                ua_contains=tuple(match.get("ua_contains", []) or []),
                hosts=tuple(match.get("hosts", []) or []),
                header_matches=tuple(header_matches),
            )
        )
    return rules


def load_rules() -> list[ToolRule]:
    """Load the user's tools.yaml if present, else the bundled defaults."""
    if USER_RULES_PATH.exists():
        raw = yaml.safe_load(USER_RULES_PATH.read_text())
    else:
        raw = yaml.safe_load(
            resources.files("upbox.rules").joinpath(DEFAULT_RULES_RESOURCE).read_text()
        )
    return _parse_rules(raw)


def load_allowed_host_patterns(extra: tuple[str, ...] = ()) -> list[str]:
    """Build the regex allowlist for mitmproxy's ``allow_hosts`` option.

    Extracts every unique hostname from ``tools.yaml`` and returns one
    anchored regex per host that matches the host exactly OR as a
    subdomain (``host`` itself, or ``*.host``). Any ``extra`` hosts
    (e.g., from a CLI flag) are appended.

    The resulting patterns are passed to ``mitmproxy.options.Options``
    so only AI-tool traffic gets TLS-intercepted — everything else
    (Outlook, banking, OS telemetry, pinned apps that would otherwise
    break under MITM) passes through untouched.
    """
    hosts: set[str] = set()
    for rule in load_rules():
        hosts.update(rule.hosts)
    hosts.update(extra)
    return [_host_to_pattern(h) for h in sorted(hosts) if h]


def _host_to_pattern(host: str) -> str:
    escaped = re.escape(host)
    # `^(?:.*\.)?<host>(?::\d+)?$` matches `host` exactly OR as a subdomain.
    # The optional `:\d+` handles ``host:port`` form that mitmproxy
    # sometimes presents.
    return rf"^(?:.*\.)?{escaped}(?::\d+)?$"


class FingerprintAddon:
    """Tags ``flow.metadata['upbox_tool']`` with the matched tool name (or None)."""

    def __init__(self, rules: list[ToolRule] | None = None) -> None:
        self._rules = rules if rules is not None else load_rules()

    def request(self, flow: http.HTTPFlow) -> None:
        try:
            flow.metadata["upbox_tool"] = self._classify(flow)
        except Exception:
            log.exception(
                "fingerprint addon failed on flow %s",
                getattr(flow, "id", "<unknown>"),
            )

    def _classify(self, flow: http.HTTPFlow) -> str | None:
        from upbox.addons._hostname import resolve_host

        req = flow.request
        ua = req.headers.get("user-agent", "")
        # Use SNI / Host header — req.host is the IP in LocalMode, which
        # would never match the hostname rules in tools.yaml.
        host = resolve_host(flow) or ""
        headers_lower = {
            k.lower(): v
            for k, v in req.headers.items()  # type: ignore[no-untyped-call]
        }
        for rule in self._rules:
            if _matches(rule, ua=ua, host=host, headers=headers_lower):
                return rule.name
        return None


def _matches(rule: ToolRule, *, ua: str, host: str, headers: dict[str, str]) -> bool:
    if rule.ua_contains and not any(s in ua for s in rule.ua_contains):
        return False
    if rule.hosts and not any(host == h or host.endswith("." + h) for h in rule.hosts):
        return False
    if rule.header_matches and not all(
        headers.get(name) == value for name, value in rule.header_matches
    ):
        return False
    # A rule with no conditions matches nothing.
    return bool(rule.ua_contains or rule.hosts or rule.header_matches)
