"""Smoke tests for the dashboard FastAPI app."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from upbox.dashboard.app import create_app
from upbox.db.store import RequestRecord, Store


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    with Store(db) as s:
        s.insert_request(
            RequestRecord(
                ts="2026-05-15T09:00:00",
                tool="Cursor",
                method="POST",
                scheme="https",
                host="api.cursor.sh",
                path="/v1/chat",
                req_bytes=42,
                resp_bytes=100,
                status=200,
                headers_json='{"user-agent": "Cursor/0.42"}',
                body_excerpt='{"prompt": "hi"}',
                body_hash="deadbeef",
                redactions_applied_json=None,
                blocked=0,
            )
        )
    return db


@pytest.fixture
def client(populated_db: Path):
    with TestClient(create_app(populated_db)) as c:
        yield c


def test_index_returns_200(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200


def test_index_renders_tool_tile(client: TestClient) -> None:
    response = client.get("/")

    assert "Cursor" in response.text


def test_recent_partial_returns_html(client: TestClient) -> None:
    response = client.get("/requests/recent")

    assert response.status_code == 200
    # Feed partial renders rows with the tool's color dot + host/path.
    # The full tool name lives in the sidebar partial.
    assert "api.cursor.sh" in response.text


def test_detail_returns_404_for_missing_id(client: TestClient) -> None:
    response = client.get("/requests/9999")

    assert response.status_code == 404


def test_detail_renders_request_metadata(client: TestClient) -> None:
    response = client.get("/requests/1")

    assert response.status_code == 200
    assert "api.cursor.sh" in response.text


def test_run_rejects_non_loopback_host() -> None:
    from upbox.dashboard.app import run

    with pytest.raises(ValueError, match="loopback"):
        run(host="0.0.0.0", port=8800)


def test_sidebar_partial_includes_tool_with_icon(client: TestClient) -> None:
    response = client.get("/sidebar")

    assert response.status_code == 200
    # Tool name + the Cursor color dot class.
    assert "Cursor" in response.text
    assert "tool-icon-cs" in response.text


def test_stats_partial_reports_total_count(client: TestClient) -> None:
    response = client.get("/stats")

    assert response.status_code == 200
    assert "Requests" in response.text


def test_index_filters_by_tool_query_param(populated_db: Path) -> None:
    with TestClient(create_app(populated_db)) as c:
        response = c.get("/?tool=NonExistent")

    assert "No requests captured for" in response.text


@pytest.fixture
def mixed_db(tmp_path: Path) -> Path:
    """One forwarded row, one redacted row, one blocked row — for filter tests."""
    db = tmp_path / "mixed.db"
    with Store(db) as s:
        s.insert_request(
            RequestRecord(
                ts="2026-05-20T09:00:00",
                tool="Cursor",
                method="POST",
                scheme="https",
                host="api.cursor.sh",
                path="/v1/chat",
                req_bytes=100,
                resp_bytes=200,
                status=200,
                headers_json="{}",
                body_excerpt=None,
                body_hash="aaaa",
                redactions_applied_json=None,
                blocked=0,
            )
        )
        s.insert_request(
            RequestRecord(
                ts="2026-05-20T09:00:01",
                tool="Claude Code",
                method="POST",
                scheme="https",
                host="api.anthropic.com",
                path="/v1/messages",
                req_bytes=200,
                resp_bytes=200,
                status=200,
                headers_json="{}",
                body_excerpt=None,
                body_hash="bbbb",
                redactions_applied_json='[{"rule":"anthropic-key","count":1}]',
                blocked=0,
            )
        )
        s.insert_request(
            RequestRecord(
                ts="2026-05-20T09:00:02",
                tool="Codeium",
                method="POST",
                scheme="https",
                host="unknown.host",
                path="/track",
                req_bytes=50,
                resp_bytes=None,
                status=0,
                headers_json="{}",
                body_excerpt=None,
                body_hash=None,
                redactions_applied_json=None,
                blocked=1,
            )
        )
    return db


def test_index_status_blocked_shows_only_blocked(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/?status=blocked")

    assert "unknown.host" in response.text
    assert "api.cursor.sh" not in response.text
    assert "api.anthropic.com" not in response.text


def test_index_status_redacted_shows_only_redacted(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/?status=redacted")

    assert "api.anthropic.com" in response.text
    assert "api.cursor.sh" not in response.text


def test_index_search_filters_by_host(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/?q=cursor")

    assert "api.cursor.sh" in response.text
    assert "api.anthropic.com" not in response.text


def test_filter_bar_renders_segments(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/")

    assert 'role="group" aria-label="Time range"' in response.text
    assert 'role="group" aria-label="Status"' in response.text


def test_filter_bar_shows_active_filter_chip(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/?status=blocked")

    assert 'class="af af-status"' in response.text
    assert "Clear all" in response.text


def test_detail_default_tab_is_body(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/requests/1")

    assert response.status_code == 200
    assert 'data-tab="body"' in response.text
    # The body tab partial includes this heading; other tabs don't.
    assert "Request body" in response.text


def test_detail_renders_headers_tab(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/requests/1?tab=headers")

    assert response.status_code == 200
    assert "Request headers" in response.text
    assert "Request body" not in response.text


def test_detail_renders_redactions_tab(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        # Row 2 in mixed_db is the redacted Claude Code row.
        response = c.get("/requests/2?tab=redactions")

    assert response.status_code == 200
    assert "anthropic-key" in response.text


def test_detail_redactions_tab_is_empty_when_no_redactions(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/requests/1?tab=redactions")

    assert response.status_code == 200
    assert "No redactions applied" in response.text


def test_detail_renders_allowlist_tab(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/requests/3?tab=allow")  # blocked row

    assert response.status_code == 200
    assert "Blocked" in response.text
    assert "is not on" in response.text  # part of "is not on the … allowlist"


def test_detail_renders_export_tab(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/requests/1?tab=export")

    assert response.status_code == 200
    # Replay-as-curl block + "Export from CLI" block are both present.
    assert "Replay as curl" in response.text
    assert "Export from CLI" in response.text
    assert "http://127.0.0.1:8888" in response.text  # proxy URL in curl recipe


def test_detail_invalid_tab_falls_back_to_body(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/requests/1?tab=../../etc/passwd")

    assert response.status_code == 200
    assert "Request body" in response.text


def test_detail_body_wraps_redaction_markers(tmp_path: Path) -> None:
    db = tmp_path / "redacted.db"
    with Store(db) as s:
        s.insert_request(
            RequestRecord(
                ts="2026-05-20T09:00:00",
                tool="Cursor",
                method="POST",
                scheme="https",
                host="api.cursor.sh",
                path="/v1/chat",
                req_bytes=42,
                resp_bytes=100,
                status=200,
                headers_json="{}",
                body_excerpt="AWS=[REDACTED:aws-access-key] OAI=[REDACTED:openai-key]",
                body_hash="abc",
                redactions_applied_json='[{"rule":"aws-access-key","count":1}]',
                blocked=0,
            )
        )
    with TestClient(create_app(db)) as c:
        response = c.get("/requests/1?tab=body")

    assert response.status_code == 200
    assert '<span class="red">[REDACTED:aws-access-key]</span>' in response.text
    assert '<span class="red">[REDACTED:openai-key]</span>' in response.text


def test_detail_body_escapes_html_in_excerpt(tmp_path: Path) -> None:
    db = tmp_path / "xss.db"
    with Store(db) as s:
        s.insert_request(
            RequestRecord(
                ts="2026-05-20T09:00:00",
                tool="Cursor",
                method="POST",
                scheme="https",
                host="api.cursor.sh",
                path="/v1/chat",
                req_bytes=42,
                resp_bytes=100,
                status=200,
                headers_json="{}",
                body_excerpt="<script>alert(1)</script>",
                body_hash="abc",
                redactions_applied_json=None,
                blocked=0,
            )
        )
    with TestClient(create_app(db)) as c:
        response = c.get("/requests/1?tab=body")

    assert response.status_code == 200
    # The literal script tag must not survive into the rendered HTML.
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


def test_export_streams_filtered_jsonl(mixed_db: Path) -> None:
    with TestClient(create_app(mixed_db)) as c:
        response = c.get("/export?status=blocked")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = [line for line in response.text.splitlines() if line]
    assert len(lines) == 1
    import json as _json

    assert _json.loads(lines[0])["host"] == "unknown.host"
