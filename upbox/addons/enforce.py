"""Domain-allowlist enforcement addon.

Per-tool policy: which destinations a tool is allowed to call. Anything
outside the allowlist is either flagged (``block_unknown: warn`` — capture
records ``blocked=1`` but the request still goes through) or short-
circuited (``block_unknown: block`` — synthesised 403 response, never
reaches upstream).

Either way, the capture addon writes a row, so the audit trail records
every block decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from mitmproxy import http

log = logging.getLogger(__name__)

DEFAULT_RULES_RESOURCE = "allowlist.yaml"
USER_RULES_PATH = Path.home() / ".upbox" / "rules" / "allowlist.yaml"


@dataclass(frozen=True)
class ToolPolicy:
    allow: tuple[str, ...]
    block_unknown: str  # "warn" or "block"


def _parse_policies(raw: dict[str, Any] | None) -> dict[str, ToolPolicy]:
    policies: dict[str, ToolPolicy] = {}
    for tool, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            continue
        allow_raw = entry.get("allow") or []
        if not isinstance(allow_raw, list):
            allow_raw = []
        block = str(entry.get("block_unknown", "warn"))
        if block not in {"warn", "block"}:
            block = "warn"
        policies[str(tool)] = ToolPolicy(
            allow=tuple(str(h) for h in allow_raw),
            block_unknown=block,
        )
    return policies


def load_policies() -> dict[str, ToolPolicy]:
    if USER_RULES_PATH.exists():
        raw = yaml.safe_load(USER_RULES_PATH.read_text())
    else:
        raw = yaml.safe_load(
            resources.files("upbox.rules").joinpath(DEFAULT_RULES_RESOURCE).read_text()
        )
    return _parse_policies(raw)


def _host_allowed(host: str, allow: tuple[str, ...]) -> bool:
    return any(host == h or host.endswith("." + h) for h in allow)


class EnforceAddon:
    """Tags ``flow.metadata['upbox_blocked']`` and short-circuits if needed."""

    def __init__(self, policies: dict[str, ToolPolicy] | None = None) -> None:
        self._policies = policies if policies is not None else load_policies()

    def request(self, flow: http.HTTPFlow) -> None:
        try:
            self._check(flow)
        except Exception:
            log.exception("enforce failed on flow %s", getattr(flow, "id", "<unknown>"))

    def _check(self, flow: http.HTTPFlow) -> None:
        tool = flow.metadata.get("upbox_tool")
        policy = self._policies.get(tool) if tool else None
        if policy is None:
            policy = self._policies.get("default")
        if policy is None:
            return

        host = flow.request.host or ""
        if _host_allowed(host, policy.allow):
            return

        if policy.block_unknown == "block":
            flow.metadata["upbox_blocked"] = "block"
            flow.response = http.Response.make(
                403,
                b"upbox: destination not in allowlist for this tool",
                {"content-type": "text/plain"},
            )
        else:
            flow.metadata["upbox_blocked"] = "warn"
