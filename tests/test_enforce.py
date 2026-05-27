"""Tests for upbox/addons/enforce.py.

The CRITICAL test from the eng-review: a blocked flow still produces a row
(audit trail preserved). That's actually exercised in tests/test_capture.py
by checking metadata flow-through. Here we test the policy decisions
themselves.
"""

from __future__ import annotations

from mitmproxy.test import tflow, tutils

from upbox.addons.enforce import EnforceAddon, ToolPolicy


def _flow(host: str = "api.example.com", tool: str | None = None):
    req = tutils.treq(host=host)
    flow = tflow.tflow(req=req)
    if tool is not None:
        flow.metadata["upbox_tool"] = tool
    return flow


def test_allowed_host_for_tool_is_not_flagged() -> None:
    addon = EnforceAddon(
        policies={"Cursor": ToolPolicy(allow=("api.cursor.sh",), block_unknown="warn")}
    )
    flow = _flow(host="api.cursor.sh", tool="Cursor")

    addon.request(flow)

    assert "upbox_enforcement" not in flow.metadata


def test_unknown_host_under_warn_is_flagged_but_forwarded() -> None:
    addon = EnforceAddon(
        policies={"Cursor": ToolPolicy(allow=("api.cursor.sh",), block_unknown="warn")}
    )
    flow = _flow(host="api.evil.example", tool="Cursor")

    addon.request(flow)

    assert flow.metadata["upbox_enforcement"] == "flagged"
    assert flow.response is None


def test_unknown_host_under_block_short_circuits_with_403() -> None:
    addon = EnforceAddon(
        policies={"Cursor": ToolPolicy(allow=("api.cursor.sh",), block_unknown="block")}
    )
    flow = _flow(host="api.evil.example", tool="Cursor")

    addon.request(flow)

    assert flow.metadata["upbox_enforcement"] == "blocked"
    assert flow.response is not None
    assert flow.response.status_code == 403


def test_default_policy_applies_when_tool_not_listed() -> None:
    addon = EnforceAddon(
        policies={
            "default": ToolPolicy(allow=(), block_unknown="warn"),
        }
    )
    flow = _flow(host="api.example.com", tool=None)

    addon.request(flow)

    assert flow.metadata["upbox_enforcement"] == "flagged"


def test_subdomain_match_is_allowed() -> None:
    addon = EnforceAddon(
        policies={"Cursor": ToolPolicy(allow=("cursor.sh",), block_unknown="block")}
    )
    flow = _flow(host="api2.cursor.sh", tool="Cursor")

    addon.request(flow)

    assert flow.response is None


def test_no_policy_for_tool_and_no_default_skips_check() -> None:
    addon = EnforceAddon(policies={})
    flow = _flow(host="api.example.com", tool="Cursor")

    addon.request(flow)

    assert "upbox_enforcement" not in flow.metadata


def test_bundled_allowlist_yaml_parses() -> None:
    from upbox.addons.enforce import load_policies

    policies = load_policies()

    assert "default" in policies
