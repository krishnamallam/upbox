"""Tests for upbox/addons/redact.py.

The four CRITICAL tests pinned by the eng-review live here:
1. JSON body parses → redacts → reserialises (output is still valid JSON).
2. gzipped body decompresses → redacts → recompresses (round-trip).
3. Non-JSON binary body is skipped with a logged reason.
4. Malformed JSON falls back gracefully (no exception).
"""

from __future__ import annotations

import gzip
import json
import re

import pytest
from mitmproxy.test import tflow, tutils

from upbox.addons.redact import RedactAddon, RedactPattern


def _patterns() -> list[RedactPattern]:
    return [
        RedactPattern(
            name="openai-key",
            regex=re.compile(r"sk-[A-Za-z0-9]{32,}"),
            replace="[REDACTED:openai-key]",
        )
    ]


def _flow(
    content: bytes, content_type: str = "application/json", content_encoding: str | None = None
):
    headers = [(b"content-type", content_type.encode())]
    if content_encoding:
        headers.append((b"content-encoding", content_encoding.encode()))
    req = tutils.treq(method=b"POST", content=content, headers=headers)
    return tflow.tflow(req=req)


SECRET = "sk-" + "A" * 40


def test_json_body_remains_valid_after_redaction() -> None:
    addon = RedactAddon(patterns=_patterns())
    payload = json.dumps({"prompt": f"my key is {SECRET}"}).encode()
    flow = _flow(payload)

    addon.request(flow)
    reparsed = json.loads(flow.request.content)

    assert "[REDACTED:openai-key]" in reparsed["prompt"]


def test_json_redaction_records_applied_rule_name() -> None:
    addon = RedactAddon(patterns=_patterns())
    payload = json.dumps({"prompt": SECRET}).encode()
    flow = _flow(payload)

    addon.request(flow)

    assert flow.metadata["upbox_redactions"] == {"applied": ["openai-key"]}


def test_gzipped_json_body_round_trips() -> None:
    """CRITICAL: gzipped body decompresses → redacts → recompresses."""
    addon = RedactAddon(patterns=_patterns())
    payload = json.dumps({"prompt": SECRET}).encode()
    gzipped = gzip.compress(payload)
    flow = _flow(gzipped, content_encoding="gzip")

    addon.request(flow)
    # mitmproxy auto-handles Content-Encoding when reading/writing .content.
    decoded = json.loads(flow.request.content)

    assert "[REDACTED:openai-key]" in decoded["prompt"]


def test_binary_body_is_skipped_with_logged_reason() -> None:
    addon = RedactAddon(patterns=_patterns())
    flow = _flow(b"\x89PNG\r\n\x1a\n", content_type="application/octet-stream")

    addon.request(flow)

    assert "skipped" in flow.metadata["upbox_redactions"]


def test_malformed_json_falls_back_gracefully() -> None:
    addon = RedactAddon(patterns=_patterns())
    flow = _flow(b"{not json at all", content_type="application/json")

    addon.request(flow)  # must not raise

    assert flow.metadata["upbox_redactions"] == {"skipped": "malformed JSON"}


def test_no_match_leaves_body_unchanged() -> None:
    addon = RedactAddon(patterns=_patterns())
    payload = json.dumps({"prompt": "nothing to redact here"}).encode()
    flow = _flow(payload)
    original = flow.request.content

    addon.request(flow)

    assert flow.request.content == original


def test_text_plain_body_is_redacted() -> None:
    addon = RedactAddon(patterns=_patterns())
    flow = _flow(f"my key is {SECRET}".encode(), content_type="text/plain")

    addon.request(flow)

    assert b"[REDACTED:openai-key]" in flow.request.content


def test_walk_redacts_nested_strings() -> None:
    addon = RedactAddon(patterns=_patterns())
    payload = json.dumps(
        {"messages": [{"role": "user", "content": SECRET}, {"role": "assistant", "content": "ok"}]}
    ).encode()
    flow = _flow(payload)

    addon.request(flow)
    parsed = json.loads(flow.request.content)

    assert parsed["messages"][0]["content"] == "[REDACTED:openai-key]"


def test_addon_swallows_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    addon = RedactAddon(patterns=_patterns())
    flow = _flow(b'{"prompt": "hi"}')

    def boom(_flow, _content):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(addon, "_redact_json", boom)

    addon.request(flow)  # must not raise


def test_bundled_redact_yaml_compiles() -> None:
    from upbox.addons.redact import load_patterns

    patterns = load_patterns()

    assert any(p.name == "openai-key" for p in patterns)
