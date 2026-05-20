"""Tests for upbox/db/store.py.

The eng-review pinned three Day-3 assertions: WAL mode is actually on,
body excerpt is exactly the first 4 KB when input is larger, and addon
exceptions don't bring down the proxy. The third is in test_capture.py;
the first two live here, plus basic insert/query behaviour.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from upbox.db.store import (
    BODY_EXCERPT_MAX,
    RequestRecord,
    Store,
    truncate_body_excerpt,
)


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def _make_record(**overrides: object) -> RequestRecord:
    base: dict[str, object] = {
        "ts": "2026-05-15T09:00:00",
        "tool": None,
        "method": "POST",
        "scheme": "https",
        "host": "api.example.com",
        "path": "/v1/messages",
        "req_bytes": 42,
        "resp_bytes": 100,
        "status": 200,
        "headers_json": '{"x-test": "1"}',
        "body_excerpt": '{"prompt": "hi"}',
        "body_hash": "deadbeef",
        "redactions_applied_json": None,
        "blocked": 0,
    }
    base.update(overrides)
    return RequestRecord(**base)  # type: ignore[arg-type]


def test_store_enables_wal_journal_mode(tmp_store: Store) -> None:
    mode = tmp_store._conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert mode.lower() == "wal"


def test_insert_request_writes_one_row(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record())
    count = tmp_store._conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]

    assert count == 1


def test_insert_request_returns_rowid(tmp_store: Store) -> None:
    rowid = tmp_store.insert_request(_make_record())

    assert rowid == 1


def test_truncate_body_excerpt_caps_at_4kb() -> None:
    big = b"x" * (BODY_EXCERPT_MAX + 1024)

    result = truncate_body_excerpt(big)

    assert result is not None
    assert len(result.encode("utf-8")) == BODY_EXCERPT_MAX


def test_truncate_body_excerpt_passes_through_short_bodies() -> None:
    assert truncate_body_excerpt(b"hello") == "hello"


def test_truncate_body_excerpt_handles_none() -> None:
    assert truncate_body_excerpt(None) is None


def test_query_recent_returns_newest_first(tmp_store: Store) -> None:
    for i in range(3):
        tmp_store.insert_request(_make_record(host=f"host{i}.example"))

    rows = tmp_store.query_recent(limit=10)

    assert rows[0]["host"] == "host2.example"


def test_query_recent_respects_limit(tmp_store: Store) -> None:
    for i in range(5):
        tmp_store.insert_request(_make_record(host=f"host{i}.example"))

    rows = tmp_store.query_recent(limit=2)

    assert len(rows) == 2


def test_export_jsonl_writes_one_line_per_row(tmp_store: Store) -> None:
    for i in range(3):
        tmp_store.insert_request(_make_record(host=f"host{i}.example"))

    buf = io.StringIO()
    written = tmp_store.export_jsonl(buf)

    assert written == 3


def test_export_jsonl_rows_are_valid_json(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record(host="api.example.com"))

    buf = io.StringIO()
    tmp_store.export_jsonl(buf)
    decoded = json.loads(buf.getvalue().strip())

    assert decoded["host"] == "api.example.com"


def test_export_csv_writes_header_when_empty(tmp_store: Store) -> None:
    buf = io.StringIO()
    written = tmp_store.export_csv(buf)

    assert written == 0
    assert "ts" in buf.getvalue().splitlines()[0]


def test_query_filtered_status_blocked(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record(blocked=1))
    tmp_store.insert_request(_make_record(blocked=0))

    rows = tmp_store.query_filtered(status="blocked")

    assert len(rows) == 1
    assert rows[0]["blocked"] == 1


def test_query_filtered_status_redacted(tmp_store: Store) -> None:
    redaction_a = json.dumps([{"rule": "a"}])
    redaction_b = json.dumps([{"rule": "b"}])
    tmp_store.insert_request(_make_record(blocked=0, redactions_applied_json=None))
    tmp_store.insert_request(_make_record(blocked=0, redactions_applied_json=redaction_a))
    tmp_store.insert_request(_make_record(blocked=1, redactions_applied_json=redaction_b))

    rows = tmp_store.query_filtered(status="redacted")

    assert len(rows) == 1
    assert rows[0]["redactions_applied_json"] is not None
    assert rows[0]["blocked"] == 0


def test_query_filtered_status_forwarded(tmp_store: Store) -> None:
    redaction = json.dumps([{"rule": "a"}])
    tmp_store.insert_request(_make_record(blocked=0, redactions_applied_json=None))
    tmp_store.insert_request(_make_record(blocked=0, redactions_applied_json=redaction))
    tmp_store.insert_request(_make_record(blocked=1))

    rows = tmp_store.query_filtered(status="forwarded")

    assert len(rows) == 1
    assert rows[0]["blocked"] == 0
    assert rows[0]["redactions_applied_json"] is None


def test_query_filtered_search_matches_host(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record(host="api.cursor.sh"))
    tmp_store.insert_request(_make_record(host="api.anthropic.com"))

    rows = tmp_store.query_filtered(search="cursor")

    assert len(rows) == 1
    assert rows[0]["host"] == "api.cursor.sh"


def test_query_filtered_search_is_case_insensitive(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record(host="API.Cursor.SH"))

    rows = tmp_store.query_filtered(search="cursor")

    assert len(rows) == 1


def test_query_filtered_limit_caps_results(tmp_store: Store) -> None:
    for _ in range(5):
        tmp_store.insert_request(_make_record())

    rows = tmp_store.query_filtered(limit=3)

    assert len(rows) == 3


def test_query_filtered_order_desc_returns_newest_first(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record(host="first.com"))
    tmp_store.insert_request(_make_record(host="second.com"))

    rows = tmp_store.query_filtered(order="DESC")

    assert rows[0]["host"] == "second.com"


def test_dashboard_stats_reports_total_bytes(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record(req_bytes=100))
    tmp_store.insert_request(_make_record(req_bytes=250))

    stats = tmp_store.dashboard_stats()

    assert stats["total_bytes"] == 350
