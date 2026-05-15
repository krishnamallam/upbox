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
    assert "Cursor" in response.text


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
