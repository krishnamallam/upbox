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
        req = flow.request
        ua = req.headers.get("user-agent", "")
        host = req.host or ""
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
