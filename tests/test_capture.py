"""Tests for upbox/addons/capture.py.

Critical assertion (per eng-review): an exception inside the hook does NOT
propagate. mitmproxy must keep processing the next flow. We prove this by
forcing the hook's record builder to raise and confirming (a) no exception
escapes and (b) no row was persisted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from mitmproxy.test import tflow, tutils

from upbox.addons.capture import HEADER_REDACTION_MARKER, CaptureAddon
from upbox.db.store import BODY_EXCERPT_MAX, Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def _flow(
    method: str = "POST",
    host: str = "api.anthropic.com",
    path: str = "/v1/messages",
    req_body: bytes = b'{"prompt": "hi"}',
    status: int = 200,
    resp_body: bytes = b'{"ok": true}',
) -> Any:
    """Build a real mitmproxy HTTPFlow for the addon to consume.

    Sets ``client_conn.sni`` to ``host`` by default to mirror a well-
    behaved HTTPS client. Tests that want to exercise the SNI-absent or
    SNI-different paths override it after construction.
    """
    req = tutils.treq(method=method.encode(), host=host, path=path.encode(), content=req_body)
    resp = tutils.tresp(status_code=status, content=resp_body)
    flow = tflow.tflow(req=req, resp=resp)
    flow.client_conn.sni = host
    return flow


def test_capture_addon_persists_one_flow(store: Store) -> None:
    addon = CaptureAddon(store)

    addon.response(_flow())

    assert len(store.query_recent()) == 1


def test_capture_addon_records_method_and_host(store: Store) -> None:
    addon = CaptureAddon(store)

    addon.response(_flow(method="POST", host="api.openai.com"))
    row = store.query_recent()[0]

    assert (row["method"], row["host"]) == ("POST", "api.openai.com")


def test_capture_addon_prefers_sni_over_request_host(store: Store) -> None:
    # In LocalMode, flow.request.host is often the raw destination IP.
    # The hostname is in flow.client_conn.sni for HTTPS. We must record
    # the SNI so the dashboard shows "api.anthropic.com", not "1.2.3.4",
    # and so tool fingerprinting (which matches on hostname) works.
    addon = CaptureAddon(store)
    flow = _flow(host="1.2.3.4")
    flow.client_conn.sni = "api.anthropic.com"

    addon.response(flow)
    row = store.query_recent()[0]

    assert row["host"] == "api.anthropic.com"


def test_capture_addon_falls_back_to_ip_without_sni(store: Store) -> None:
    addon = CaptureAddon(store)
    flow = _flow(host="1.2.3.4")
    flow.client_conn.sni = None
    # Force pretty_host to also return the IP — simulates no Host header.
    flow.request.host_header = None

    addon.response(flow)
    row = store.query_recent()[0]

    assert row["host"] == "1.2.3.4"


def test_capture_addon_swallows_exceptions(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per CLAUDE.md: addon failures must not crash the proxy."""
    addon = CaptureAddon(store)

    def boom(_flow: Any) -> None:
        raise RuntimeError("synthetic capture failure")

    monkeypatch.setattr(addon, "_record_from_flow", boom)

    addon.response(_flow())  # Must not raise.

    assert len(store.query_recent()) == 0


def test_capture_addon_continues_after_exception(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a failed flow, the next one is still persisted."""
    addon = CaptureAddon(store)
    real_builder = addon._record_from_flow
    calls = {"n": 0}

    def first_call_raises(flow: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic capture failure")
        return real_builder(flow)

    monkeypatch.setattr(addon, "_record_from_flow", first_call_raises)

    addon.response(_flow())  # fails silently
    addon.response(_flow())  # should persist

    assert len(store.query_recent()) == 1


def test_capture_addon_truncates_body_excerpt(store: Store) -> None:
    addon = CaptureAddon(store)
    big_body = b"x" * (BODY_EXCERPT_MAX + 10_000)

    addon.response(_flow(req_body=big_body))
    row = store.query_recent()[0]

    assert row["body_excerpt"] is not None
    assert len(row["body_excerpt"].encode("utf-8")) == BODY_EXCERPT_MAX


def _stored_headers(store: Store, name: str, value: str) -> dict[str, str]:
    """Capture one flow carrying ``name: value`` and return the stored headers."""
    flow = _flow()
    flow.request.headers[name] = value
    CaptureAddon(store).response(flow)
    return cast("dict[str, str]", json.loads(store.query_recent()[0]["headers_json"]))


def test_capture_redacts_authorization_header(store: Store) -> None:
    headers = _stored_headers(store, "Authorization", "Bearer sk-ant-api03-secret")

    assert headers["Authorization"] == HEADER_REDACTION_MARKER


def test_capture_never_stores_the_credential_itself(store: Store) -> None:
    _stored_headers(store, "Authorization", "Bearer sk-ant-api03-secret")

    assert "sk-ant-api03-secret" not in store.query_recent()[0]["headers_json"]


def test_capture_redacts_auth_header_whatever_its_casing(store: Store) -> None:
    headers = _stored_headers(store, "AUTHORIZATION", "Bearer secret")

    assert headers["AUTHORIZATION"] == HEADER_REDACTION_MARKER


def test_capture_redacts_cookie_header(store: Store) -> None:
    headers = _stored_headers(store, "Cookie", "session=abc123")

    assert headers["Cookie"] == HEADER_REDACTION_MARKER


def test_capture_redacts_x_api_key_header(store: Store) -> None:
    headers = _stored_headers(store, "x-api-key", "sk-ant-api03-secret")

    assert headers["x-api-key"] == HEADER_REDACTION_MARKER


def test_capture_keeps_ordinary_header_values(store: Store) -> None:
    headers = _stored_headers(store, "Content-Type", "application/json")

    assert headers["Content-Type"] == "application/json"


def test_capture_keeps_the_redacted_header_name(store: Store) -> None:
    headers = _stored_headers(store, "Authorization", "Bearer secret")

    assert "Authorization" in headers


def test_header_redaction_is_not_reported_as_a_body_redaction(store: Store) -> None:
    """Header values are still forwarded. Only storage changes, so claiming a
    redaction fired would imply the credential never left the machine."""
    _stored_headers(store, "Authorization", "Bearer secret")

    assert store.query_recent()[0]["redactions_applied_json"] is None
