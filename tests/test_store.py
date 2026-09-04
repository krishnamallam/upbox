"""Tests for upbox/db/store.py.

The eng-review pinned three Day-3 assertions: WAL mode is actually on,
body excerpt is capped at ``BODY_EXCERPT_MAX`` when input is larger, and
addon exceptions don't bring down the proxy. The third is in test_capture.py;
the first two live here, plus basic insert/query behaviour.
"""

from __future__ import annotations

import io
import json
import sqlite3
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
        "enforcement": None,
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


def test_truncate_body_excerpt_caps_at_max() -> None:
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


def test_query_filtered_status_blocked_excludes_flagged(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record(enforcement="blocked"))
    tmp_store.insert_request(_make_record(enforcement="flagged"))

    rows = tmp_store.query_filtered(status="blocked")

    assert len(rows) == 1
    assert rows[0]["enforcement"] == "blocked"


def test_query_filtered_status_flagged_excludes_blocked(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record(enforcement="flagged"))
    tmp_store.insert_request(_make_record(enforcement="blocked"))

    rows = tmp_store.query_filtered(status="flagged")

    assert len(rows) == 1
    assert rows[0]["enforcement"] == "flagged"


def test_query_filtered_status_redacted(tmp_store: Store) -> None:
    redaction_a = json.dumps([{"rule": "a"}])
    tmp_store.insert_request(_make_record(enforcement=None, redactions_applied_json=None))
    tmp_store.insert_request(_make_record(enforcement=None, redactions_applied_json=redaction_a))

    rows = tmp_store.query_filtered(status="redacted")

    assert len(rows) == 1
    assert rows[0]["redactions_applied_json"] is not None


def test_query_filtered_status_forwarded_excludes_flagged(tmp_store: Store) -> None:
    redaction = json.dumps([{"rule": "a"}])
    tmp_store.insert_request(_make_record(enforcement=None, redactions_applied_json=None))
    tmp_store.insert_request(_make_record(enforcement=None, redactions_applied_json=redaction))
    tmp_store.insert_request(_make_record(enforcement="flagged"))

    rows = tmp_store.query_filtered(status="forwarded")

    assert len(rows) == 1
    assert rows[0]["enforcement"] is None
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


def test_dashboard_stats_counts_flagged_separately_from_blocked(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record(enforcement="flagged"))
    tmp_store.insert_request(_make_record(enforcement="flagged"))
    tmp_store.insert_request(_make_record(enforcement="blocked"))

    stats = tmp_store.dashboard_stats()

    assert stats["flagged"] == 2
    assert stats["blocked"] == 1


def test_migrated_db_backfills_old_blocked_rows_as_flagged(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    legacy = sqlite3.connect(db)
    legacy.execute(
        "CREATE TABLE requests ("
        "id INTEGER PRIMARY KEY, ts TEXT NOT NULL, tool TEXT, method TEXT, "
        "scheme TEXT, host TEXT, path TEXT, req_bytes INTEGER, resp_bytes INTEGER, "
        "status INTEGER, headers_json TEXT, body_excerpt TEXT, body_hash TEXT, "
        "redactions_applied_json TEXT, blocked INTEGER NOT NULL DEFAULT 0)"
    )
    legacy.execute("INSERT INTO requests (ts, blocked) VALUES ('2026-05-20T00:00:00', 1)")
    legacy.commit()
    legacy.close()

    store = Store(db)
    try:
        rows = store.query_filtered(status="flagged")
    finally:
        store.close()

    assert len(rows) == 1
    assert rows[0]["enforcement"] == "flagged"


def test_insert_request_stores_omitted_fields(tmp_store: Store) -> None:
    tmp_store.insert_request(
        RequestRecord(
            ts="2026-09-04T09:00:00+00:00",
            tool="Cursor",
            method="POST",
            scheme="https",
            host="api.cursor.sh",
            path="/v1/chat",
            req_bytes=42,
            resp_bytes=100,
            status=200,
            headers_json=None,
            body_excerpt=None,
            body_hash="deadbeef",
            redactions_applied_json=None,
            enforcement=None,
            omitted_fields='["body_excerpt", "headers_json"]',
        )
    )

    assert tmp_store.query_recent()[0]["omitted_fields"] == '["body_excerpt", "headers_json"]'
