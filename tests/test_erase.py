"""Tests for per-record erasure (GDPR Article 17) as chain-preserving tombstones.

The load-bearing properties: a tombstone keeps nothing about the person except
that a request existed at a time, the chain still verifies through it, and an
erasure is disclosed rather than hidden.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from upbox.audit_export import write_audit_v1
from upbox.db.store import EraseSelection, LegalHoldError, RequestRecord, Store
from upbox.retention import RetentionPolicy

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
REASON = "access request 2026-09-04"


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def _record(ts: datetime = NOW, **overrides: object) -> RequestRecord:
    base: dict[str, object] = {
        "ts": ts.isoformat(),
        "tool": "cursor",
        "method": "POST",
        "scheme": "https",
        "host": "api.cursor.sh",
        "path": "/v1/chat",
        "req_bytes": 42,
        "resp_bytes": 100,
        "status": 200,
        "headers_json": '{"content-type": "application/json"}',
        "body_excerpt": '{"prompt": "my address is 12 Via Roma"}',
        "body_hash": "deadbeef",
        "redactions_applied_json": '["dotenv"]',
        "enforcement": "flagged",
    }
    base.update(overrides)
    return RequestRecord(**base)  # type: ignore[arg-type]


def _three_rows(store: Store) -> None:
    store.insert_request(_record(NOW - timedelta(days=2), host="a.example"))
    store.insert_request(_record(NOW - timedelta(days=1), host="b.example"))
    store.insert_request(_record(NOW, host="c.example"))


def _erase_middle(store: Store) -> None:
    store.erase(EraseSelection(ids=(2,)), REASON, now=NOW)


def _erased_ids(store: Store) -> list[int]:
    return [
        int(row["id"])
        for row in store.query_filtered(include_erased=True)
        if row["erased_at"] is not None
    ]


# --- what a tombstone keeps and drops --------------------------------------


def test_tombstone_clears_the_request_line(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    row = tmp_store.query_by_id(2)
    assert (row["tool"], row["method"], row["scheme"], row["host"], row["path"]) == (None,) * 5


def test_tombstone_clears_sizes_and_status(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    row = tmp_store.query_by_id(2)
    assert (row["req_bytes"], row["resp_bytes"], row["status"]) == (None, None, None)


def test_tombstone_clears_content_and_digests(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    row = tmp_store.query_by_id(2)
    assert (
        row["headers_json"],
        row["body_excerpt"],
        row["body_hash"],
        row["headers_sha256"],
        row["body_excerpt_sha256"],
    ) == (None,) * 5


def test_tombstone_clears_outcomes(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    row = tmp_store.query_by_id(2)
    assert (row["redactions_applied_json"], row["enforcement"]) == (None, None)


def test_tombstone_keeps_the_timestamp(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    assert tmp_store.query_by_id(2)["ts"] == (NOW - timedelta(days=1)).isoformat()


def test_tombstone_keeps_its_chain_position(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    before = tmp_store.query_by_id(2)

    _erase_middle(tmp_store)

    after = tmp_store.query_by_id(2)
    assert (after["seq"], after["prev_hash"], after["entry_hash"]) == (
        before["seq"],
        before["prev_hash"],
        before["entry_hash"],
    )


def test_tombstone_records_when_and_why(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    row = tmp_store.query_by_id(2)
    assert (row["erased_at"], row["erased_reason"]) == (NOW.isoformat(), REASON)


# --- the chain --------------------------------------------------------------


def test_chain_verifies_after_erasing_a_middle_row(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    assert tmp_store.verify_chain().status == "ok"


def test_verification_counts_erased_entries(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    assert tmp_store.verify_chain().entries_erased == 1


def test_verification_checked_count_excludes_tombstones(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    assert tmp_store.verify_chain().checked == 2


def test_verification_still_catches_an_edit_after_an_erasure(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _erase_middle(tmp_store)

    tmp_store._conn.execute("UPDATE requests SET host = 'evil.example' WHERE id = 3")

    assert tmp_store.verify_chain().status == "broken"


def test_tombstone_with_leftover_content_is_tampering(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _erase_middle(tmp_store)

    tmp_store._conn.execute("UPDATE requests SET host = 'still.here' WHERE id = 2")

    assert tmp_store.verify_chain().status == "broken"


def test_leftover_content_names_the_tombstone(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _erase_middle(tmp_store)

    tmp_store._conn.execute("UPDATE requests SET host = 'still.here' WHERE id = 2")

    assert tmp_store.verify_chain().broken_at == 2


# --- selection --------------------------------------------------------------


def test_erase_by_host_matches_only_that_host(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    tmp_store.erase(EraseSelection(host="a.example"), REASON, now=NOW)

    assert _erased_ids(tmp_store) == [1]


def test_erase_by_tool_matches_only_that_tool(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    tmp_store.insert_request(_record(NOW, tool="claude code", host="api.anthropic.com"))

    tmp_store.erase(EraseSelection(tool="claude code"), REASON, now=NOW)

    assert _erased_ids(tmp_store) == [4]


def test_erase_by_time_range_matches_only_rows_inside_it(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    since = (NOW - timedelta(hours=36)).isoformat()
    until = (NOW - timedelta(hours=12)).isoformat()

    tmp_store.erase(EraseSelection(since=since, until=until), REASON, now=NOW)

    assert _erased_ids(tmp_store) == [2]


def test_selectors_combine_with_and(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    tmp_store.erase(EraseSelection(ids=(1, 2, 3), host="c.example"), REASON, now=NOW)

    assert _erased_ids(tmp_store) == [3]


def test_erase_result_counts_tombstones(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    result = tmp_store.erase(EraseSelection(ids=(1, 2)), REASON, now=NOW)

    assert result.erased == 2


def test_erase_result_lists_the_ids(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    result = tmp_store.erase(EraseSelection(ids=(1, 2)), REASON, now=NOW)

    assert result.ids == (1, 2)


def test_preview_lists_matching_rows_without_changing_them(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    tmp_store.preview_erase(EraseSelection(host="a.example"))

    assert tmp_store.query_by_id(1)["host"] == "a.example"


def test_erasing_twice_is_a_no_op(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _erase_middle(tmp_store)

    result = tmp_store.erase(EraseSelection(ids=(2,)), "again", now=NOW)

    assert result.erased == 0


def test_second_erasure_keeps_the_original_reason(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _erase_middle(tmp_store)

    tmp_store.erase(EraseSelection(ids=(2,)), "again", now=NOW)

    assert tmp_store.query_by_id(2)["erased_reason"] == REASON


def test_empty_selection_is_rejected(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    with pytest.raises(ValueError, match="selector"):
        tmp_store.erase(EraseSelection(), REASON, now=NOW)


def test_blank_reason_is_rejected(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    with pytest.raises(ValueError, match="reason"):
        tmp_store.erase(EraseSelection(ids=(1,)), "   ", now=NOW)


# --- legal hold -------------------------------------------------------------


def _hold_row_two(store: Store) -> None:
    ts = (NOW - timedelta(days=1)).isoformat()
    store.set_legal_hold(since=ts, until=ts)


def test_held_row_refuses_the_erasure(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _hold_row_two(tmp_store)

    with pytest.raises(LegalHoldError):
        tmp_store.erase(EraseSelection(ids=(1, 2)), REASON, now=NOW)


def test_refused_erasure_changes_nothing(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _hold_row_two(tmp_store)

    with pytest.raises(LegalHoldError):
        tmp_store.erase(EraseSelection(ids=(1, 2)), REASON, now=NOW)

    assert tmp_store.query_by_id(1)["host"] == "a.example"


def test_legal_hold_error_names_the_held_ids(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _hold_row_two(tmp_store)

    with pytest.raises(LegalHoldError) as excinfo:
        tmp_store.erase(EraseSelection(ids=(1, 2)), REASON, now=NOW)

    assert excinfo.value.held_ids == (2,)


# --- rows that predate the chain ----------------------------------------------


def _legacy_database(path: Path) -> None:
    import sqlite3

    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE requests (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, tool TEXT, "
        "method TEXT, scheme TEXT, host TEXT, path TEXT, req_bytes INTEGER, "
        "resp_bytes INTEGER, status INTEGER, headers_json TEXT, body_excerpt TEXT, "
        "body_hash TEXT, redactions_applied_json TEXT, blocked INTEGER)"
    )
    legacy.execute("INSERT INTO requests (ts, host, blocked) VALUES ('2026-01-01', 'a.example', 0)")
    legacy.commit()
    legacy.close()


def test_unchained_row_is_deleted_outright(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    _legacy_database(path)
    store = Store(path)

    store.erase(EraseSelection(ids=(1,)), REASON, now=NOW)

    assert store.query_by_id(1) is None


def test_unchained_deletion_is_counted_separately(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    _legacy_database(path)
    store = Store(path)

    result = store.erase(EraseSelection(ids=(1,)), REASON, now=NOW)

    assert (result.erased, result.deleted_unchained) == (0, 1)


# --- visibility ---------------------------------------------------------------


def test_erased_rows_leave_the_feed(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    assert len(tmp_store.query_filtered()) == 2


def test_erased_rows_leave_recent(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    assert len(tmp_store.query_recent()) == 2


def test_erased_rows_leave_the_stats(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    assert tmp_store.dashboard_stats()["total"] == 2


def test_erased_rows_leave_the_per_tool_summary(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    assert tmp_store.per_tool_summary()[0]["request_count"] == 2


def test_include_erased_shows_the_tombstone(tmp_store: Store) -> None:
    _three_rows(tmp_store)

    _erase_middle(tmp_store)

    assert len(tmp_store.query_filtered(include_erased=True)) == 3


# --- retention ------------------------------------------------------------------


def test_record_retention_still_deletes_an_aged_tombstone(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    tmp_store.erase(EraseSelection(ids=(1,)), REASON, now=NOW)

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=1), now=NOW - timedelta(hours=12))

    assert tmp_store.query_by_id(1) is None


def test_chain_verifies_after_retention_removes_a_tombstone(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    tmp_store.erase(EraseSelection(ids=(1,)), REASON, now=NOW)

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=1), now=NOW - timedelta(hours=12))

    assert tmp_store.verify_chain().status == "ok"


# --- export -------------------------------------------------------------------


def _export(store: Store) -> list[dict[str, object]]:
    sink = io.StringIO()
    write_audit_v1(store, sink)
    return [json.loads(line) for line in sink.getvalue().splitlines()]


def test_export_includes_the_tombstone(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _erase_middle(tmp_store)

    assert len(_export(tmp_store)) == 5


def test_export_marks_the_tombstone_as_erased(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _erase_middle(tmp_store)

    assert _export(tmp_store)[2]["erased"] == {"at": NOW.isoformat(), "reason": REASON}


def test_export_live_record_reports_no_erasure(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _erase_middle(tmp_store)

    assert _export(tmp_store)[1]["erased"] is None


def test_export_tombstone_has_no_enforcement_meaning(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _erase_middle(tmp_store)

    assert _export(tmp_store)[2]["enforcement_meaning"] is None


def test_export_header_counts_erasures(tmp_store: Store) -> None:
    _three_rows(tmp_store)
    _erase_middle(tmp_store)

    assert _export(tmp_store)[0]["chain"]["entries_erased_on_request"] == 1
