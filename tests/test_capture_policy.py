"""Tests for the capture policy (capture.yaml) and how CaptureAddon applies it.

The load-bearing property: a user file that exists but cannot be trusted must
fall back to storing less, never more.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mitmproxy.test import tflow, tutils

from upbox.addons import capture
from upbox.addons.capture import CaptureAddon, CapturePolicy, load_policy
from upbox.db.store import Store


@pytest.fixture
def rules_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "rules" / "capture.yaml"
    monkeypatch.setattr(capture, "USER_RULES_PATH", path)
    return path


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def _flow(req_body: bytes = b'{"prompt": "hi"}') -> Any:
    req = tutils.treq(
        method=b"POST", host="api.anthropic.com", path=b"/v1/messages", content=req_body
    )
    resp = tutils.tresp(status_code=200, content=b'{"ok": true}')
    flow = tflow.tflow(req=req, resp=resp)
    flow.client_conn.sni = "api.anthropic.com"
    return flow


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# --- loading ---------------------------------------------------------------


def test_bundled_default_stores_everything(rules_path: Path) -> None:
    assert load_policy() == CapturePolicy(bodies=True, headers=True)


def test_user_file_can_turn_bodies_off(rules_path: Path) -> None:
    _write(rules_path, "bodies: false\n")

    assert load_policy().bodies is False


def test_user_file_missing_key_keeps_the_default(rules_path: Path) -> None:
    _write(rules_path, "bodies: false\n")

    assert load_policy().headers is True


def test_malformed_user_file_falls_back_to_metadata_only(rules_path: Path) -> None:
    _write(rules_path, "bodies: [not: valid\n")

    assert load_policy().is_metadata_only


def test_non_boolean_value_falls_back_to_metadata_only(rules_path: Path) -> None:
    _write(rules_path, "bodies: sometimes\n")

    assert load_policy().is_metadata_only


def test_non_mapping_user_file_falls_back_to_metadata_only(rules_path: Path) -> None:
    _write(rules_path, "- bodies\n")

    assert load_policy().is_metadata_only


def test_unknown_key_is_ignored(rules_path: Path) -> None:
    _write(rules_path, "bodies: false\nresponses: true\n")

    assert load_policy() == CapturePolicy(bodies=False, headers=True)


def test_omitted_columns_names_what_is_withheld() -> None:
    assert CapturePolicy(bodies=False, headers=True).omitted_columns() == ("body_excerpt",)


# --- applying --------------------------------------------------------------


def test_bodies_off_stores_no_excerpt(store: Store) -> None:
    CaptureAddon(store, CapturePolicy(bodies=False)).response(_flow())

    assert store.query_recent()[0]["body_excerpt"] is None


def test_bodies_off_still_records_the_body_hash(store: Store) -> None:
    CaptureAddon(store, CapturePolicy(bodies=False)).response(_flow())

    assert store.query_recent()[0]["body_hash"] is not None


def test_bodies_off_still_records_the_true_size(store: Store) -> None:
    CaptureAddon(store, CapturePolicy(bodies=False)).response(_flow(req_body=b"x" * 42))

    assert store.query_recent()[0]["req_bytes"] == 42


def test_headers_off_stores_no_headers(store: Store) -> None:
    CaptureAddon(store, CapturePolicy(headers=False)).response(_flow())

    assert store.query_recent()[0]["headers_json"] is None


def test_omitted_fields_lists_exactly_what_was_withheld(store: Store) -> None:
    CaptureAddon(store, CapturePolicy(bodies=False, headers=False)).response(_flow())

    assert json.loads(store.query_recent()[0]["omitted_fields"]) == [
        "body_excerpt",
        "headers_json",
    ]


def test_full_capture_leaves_omitted_fields_null(store: Store) -> None:
    CaptureAddon(store, CapturePolicy()).response(_flow())

    assert store.query_recent()[0]["omitted_fields"] is None


def test_metadata_only_rows_still_record_redactions(store: Store) -> None:
    flow = _flow()
    flow.metadata["upbox_redactions"] = ["openai-key"]

    CaptureAddon(store, CapturePolicy(bodies=False, headers=False)).response(flow)

    assert json.loads(store.query_recent()[0]["redactions_applied_json"]) == ["openai-key"]


def test_metadata_only_rows_keep_the_chain_verifying(store: Store) -> None:
    addon = CaptureAddon(store, CapturePolicy(bodies=False, headers=False))

    addon.response(_flow())
    addon.response(_flow())

    assert store.verify_chain().status == "ok"


def test_reload_picks_up_a_changed_file(store: Store, rules_path: Path) -> None:
    addon = CaptureAddon(store, CapturePolicy())
    _write(rules_path, "bodies: false\n")

    addon.reload()

    assert addon.policy.bodies is False


def test_failed_reload_keeps_the_previous_policy(
    store: Store, rules_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    addon = CaptureAddon(store, CapturePolicy(bodies=False))

    def boom() -> CapturePolicy:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(capture, "load_policy", boom)

    addon.reload()

    assert addon.policy == CapturePolicy(bodies=False)


def test_addon_without_explicit_policy_reads_the_file(store: Store, rules_path: Path) -> None:
    _write(rules_path, "headers: false\n")

    assert CaptureAddon(store).policy.headers is False
