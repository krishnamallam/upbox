"""Tests for upbox/addons/fingerprint.py."""

from __future__ import annotations

import pytest
from mitmproxy.test import tflow, tutils

from upbox.addons.fingerprint import FingerprintAddon, ToolRule, _parse_rules


def _flow(host: str = "api.example.com", ua: str = "", extra_headers: dict[str, str] | None = None):
    headers = [(b"user-agent", ua.encode())] if ua else []
    for k, v in (extra_headers or {}).items():
        headers.append((k.encode(), v.encode()))
    req = tutils.treq(host=host, headers=headers)
    flow = tflow.tflow(req=req)
    # Mirror SNI to host so the well-behaved-HTTPS path runs in tests.
    # Tests that want to exercise IP-only LocalMode flows override this.
    flow.client_conn.sni = host
    return flow


def _rule(name: str, **kwargs) -> ToolRule:
    return ToolRule(
        name=name,
        ua_contains=tuple(kwargs.get("ua_contains", [])),
        hosts=tuple(kwargs.get("hosts", [])),
        header_matches=tuple(kwargs.get("header_matches", [])),
    )


def test_classify_returns_none_when_no_rule_matches() -> None:
    addon = FingerprintAddon(rules=[_rule("Cursor", hosts=["api.cursor.sh"])])

    addon.request(_flow(host="api.example.com"))
    flow = _flow(host="api.example.com")
    addon.request(flow)

    assert flow.metadata["upbox_tool"] is None


def test_classify_matches_by_host() -> None:
    addon = FingerprintAddon(rules=[_rule("Cursor", hosts=["api.cursor.sh"])])
    flow = _flow(host="api.cursor.sh")

    addon.request(flow)

    assert flow.metadata["upbox_tool"] == "Cursor"


def test_classify_matches_by_sni_when_host_is_ip() -> None:
    # LocalMode: client connects to the resolved IP; SNI carries the
    # hostname. Without SNI fallback this rule would never match.
    addon = FingerprintAddon(rules=[_rule("Cursor", hosts=["api.cursor.sh"])])
    flow = _flow(host="44.196.46.125")
    flow.client_conn.sni = "api.cursor.sh"

    addon.request(flow)

    assert flow.metadata["upbox_tool"] == "Cursor"


def test_load_allowed_host_patterns_includes_known_ai_hosts() -> None:
    from upbox.addons.fingerprint import load_allowed_host_patterns

    patterns = load_allowed_host_patterns()

    # The bundled tools.yaml lists api.anthropic.com.
    assert any("api\\.anthropic\\.com" in p for p in patterns)


def test_allow_pattern_matches_host_and_subdomain() -> None:
    import re

    from upbox.addons.fingerprint import _host_to_pattern

    pattern = re.compile(_host_to_pattern("api.cursor.sh"))

    assert pattern.match("api.cursor.sh")
    assert pattern.match("internal.api.cursor.sh")
    assert not pattern.match("attacker.com")
    # The host name appearing as a substring of an unrelated domain
    # MUST NOT match — anchoring guards against this.
    assert not pattern.match("api.cursor.sh.attacker.tld")


def test_allow_pattern_includes_extra_hosts() -> None:
    from upbox.addons.fingerprint import load_allowed_host_patterns

    patterns = load_allowed_host_patterns(extra=("custom.ai.example.com",))

    assert any("custom\\.ai\\.example\\.com" in p for p in patterns)


def test_classify_matches_subdomain() -> None:
    addon = FingerprintAddon(rules=[_rule("Cursor", hosts=["cursor.sh"])])
    flow = _flow(host="api2.cursor.sh")

    addon.request(flow)

    assert flow.metadata["upbox_tool"] == "Cursor"


def test_classify_requires_all_conditions() -> None:
    """A rule with both ua_contains and hosts requires BOTH to match."""
    addon = FingerprintAddon(
        rules=[_rule("Cursor", ua_contains=["Cursor/"], hosts=["api.cursor.sh"])]
    )
    flow = _flow(host="api.cursor.sh", ua="not-cursor")

    addon.request(flow)

    assert flow.metadata["upbox_tool"] is None


def test_classify_disambiguates_via_header() -> None:
    """Claude Desktop and Claude Code share api.anthropic.com; header decides."""
    addon = FingerprintAddon(
        rules=[
            _rule(
                "Claude Desktop",
                hosts=["api.anthropic.com"],
                header_matches=[("x-app", "claude-desktop")],
            ),
            _rule("Claude Code", ua_contains=["anthropic-ai/sdk"], hosts=["api.anthropic.com"]),
        ]
    )
    flow = _flow(host="api.anthropic.com", extra_headers={"x-app": "claude-desktop"})

    addon.request(flow)

    assert flow.metadata["upbox_tool"] == "Claude Desktop"


def test_classify_first_match_wins() -> None:
    addon = FingerprintAddon(
        rules=[
            _rule("A", hosts=["api.example.com"]),
            _rule("B", hosts=["api.example.com"]),
        ]
    )
    flow = _flow(host="api.example.com")

    addon.request(flow)

    assert flow.metadata["upbox_tool"] == "A"


def test_classify_empty_rule_matches_nothing() -> None:
    addon = FingerprintAddon(rules=[_rule("Empty")])
    flow = _flow(host="api.example.com")

    addon.request(flow)

    assert flow.metadata["upbox_tool"] is None


def test_addon_swallows_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per CLAUDE.md: addon failures must not crash the proxy."""
    addon = FingerprintAddon(rules=[])
    flow = _flow()

    def boom(_flow):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(addon, "_classify", boom)

    addon.request(flow)  # must not raise

    assert "upbox_tool" not in flow.metadata


def test_parse_rules_extracts_header_match_pair() -> None:
    raw = [
        {
            "name": "Claude Desktop",
            "match": {"hosts": ["api.anthropic.com"], "headers": ["x-app: claude-desktop"]},
        }
    ]

    rules = _parse_rules(raw)

    assert rules[0].header_matches == (("x-app", "claude-desktop"),)


def test_bundled_rules_load_successfully() -> None:
    """Smoke test: the shipped tools.yaml parses without error."""
    from upbox.addons.fingerprint import load_rules

    rules = load_rules()

    assert any(r.name == "Cursor" for r in rules)
