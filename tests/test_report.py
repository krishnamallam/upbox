"""Tests for the subject-transparency report builder and its renderers."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from upbox.addons.capture import CapturePolicy
from upbox.db.store import EraseSelection, RequestRecord, Store
from upbox.report import TransparencyReport, build_report, render_json, render_markdown
from upbox.retention import RetentionPolicy

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
FULL = CapturePolicy()
META = CapturePolicy(bodies=False, headers=False)
RETENTION = RetentionPolicy(body_days=7, record_days=None)


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def _record(ts: datetime = NOW, **overrides: object) -> RequestRecord:
    base: dict[str, object] = {
        "ts": ts.isoformat(),
        "tool": "Cursor",
        "method": "POST",
        "scheme": "https",
        "host": "api.cursor.sh",
        "path": "/v1/chat",
        "req_bytes": 40,
        "resp_bytes": 100,
        "status": 200,
        "headers_json": "{}",
        "body_excerpt": '{"prompt": "hi"}',
        "body_hash": "deadbeef",
        "redactions_applied_json": None,
        "enforcement": None,
    }
    base.update(overrides)
    return RequestRecord(**base)  # type: ignore[arg-type]


def _build(
    store: Store, capture: CapturePolicy = FULL, retention: RetentionPolicy = RETENTION
) -> TransparencyReport:
    return build_report(store, capture_policy=capture, retention_policy=retention)


def test_recipients_are_grouped_per_tool_and_host(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.insert_request(_record())
    tmp_store.insert_request(_record(tool="Claude Code", host="api.anthropic.com"))

    assert len(_build(tmp_store).recipients) == 2


def test_recipient_counts_its_requests(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.insert_request(_record())

    assert _build(tmp_store).recipients[0].requests == 2


def test_recipient_sums_its_bytes(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(req_bytes=40))
    tmp_store.insert_request(_record(req_bytes=60))

    assert _build(tmp_store).recipients[0].req_bytes == 100


def test_recipients_exclude_erased_rows(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.erase(EraseSelection(ids=(1,)), "request", now=NOW)

    assert _build(tmp_store).recipients == ()


def test_total_rows_excludes_tombstones(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.insert_request(_record())
    tmp_store.erase(EraseSelection(ids=(1,)), "request", now=NOW)

    assert _build(tmp_store).total_rows == 1


def test_capture_flags_reflect_the_policy(tmp_store: Store) -> None:
    report = _build(tmp_store, capture=META)

    assert (report.capture_bodies, report.capture_headers) == (False, False)


def test_omitted_row_count_is_reported(tmp_store: Store) -> None:
    tmp_store.insert_request(
        _record(
            body_excerpt=None, headers_json=None, omitted_fields='["body_excerpt", "headers_json"]'
        )
    )

    assert _build(tmp_store).rows_with_omitted_content == 1


def test_retention_fields_reflect_the_policy(tmp_store: Store) -> None:
    report = _build(tmp_store, retention=RetentionPolicy(body_days=3, record_days=90))

    assert (report.body_days, report.record_days) == (3, 90)


def test_pruned_row_count_is_reported(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(NOW - timedelta(days=30)))
    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert _build(tmp_store).rows_with_pruned_content == 1


def test_deleted_entry_count_comes_from_the_gap_records(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(NOW - timedelta(days=30)))
    tmp_store.insert_request(_record(NOW - timedelta(days=29)))
    tmp_store.insert_request(_record(NOW))
    tmp_store.prune(RetentionPolicy(body_days=None, record_days=10), now=NOW)

    assert _build(tmp_store).entries_deleted_by_retention == 2


def test_legal_hold_count_is_reported(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.set_legal_hold()

    assert _build(tmp_store).rows_under_legal_hold == 1


def test_erasures_are_listed_with_their_reason(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.erase(EraseSelection(ids=(1,)), "asked on 2026-09-04", now=NOW)

    assert _build(tmp_store).erasures[0].reason == "asked on 2026-09-04"


def test_no_erasures_is_an_empty_tuple(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _build(tmp_store).erasures == ()


def test_chain_status_is_reported(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _build(tmp_store).chain_status == "ok"


def test_chain_erasure_count_is_reported(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.erase(EraseSelection(ids=(1,)), "request", now=NOW)

    assert _build(tmp_store).chain_entries_erased == 1


def test_last_checkpoint_is_none_before_any_seal(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _build(tmp_store).last_checkpoint is None


def test_last_checkpoint_reflects_the_latest_seal(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.write_checkpoint("manual")
    tmp_store.insert_request(_record())
    tmp_store.write_checkpoint("manual")

    assert _build(tmp_store).last_checkpoint.seq_end == 2


def test_hostname_is_never_empty(tmp_store: Store) -> None:
    assert _build(tmp_store).hostname != ""


def test_markdown_has_nine_sections(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert render_markdown(_build(tmp_store)).count("\n## ") == 9


def test_markdown_contains_no_em_dash(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.erase(EraseSelection(ids=(1,)), "request", now=NOW)

    assert "\u2014" not in render_markdown(_build(tmp_store, capture=META))


def test_markdown_says_when_bodies_are_not_stored(tmp_store: Store) -> None:
    assert "not stored (capture policy)" in render_markdown(_build(tmp_store, capture=META))


def test_markdown_names_each_recipient_host(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(host="api.anthropic.com"))

    assert "api.anthropic.com" in render_markdown(_build(tmp_store))


def test_markdown_lists_erasure_reasons(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.erase(EraseSelection(ids=(1,)), "asked on 2026-09-04", now=NOW)

    assert "asked on 2026-09-04" in render_markdown(_build(tmp_store))


def test_markdown_asks_the_deployer_to_name_the_controller(tmp_store: Store) -> None:
    assert "Controller and contact" in render_markdown(_build(tmp_store))


def test_json_round_trips(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    report = _build(tmp_store)

    assert json.loads(render_json(report))["total_rows"] == report.total_rows
