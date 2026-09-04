"""Tests for the `upbox report` command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from upbox.cli import app
from upbox.db.store import RequestRecord, Store


@pytest.fixture
def populated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test.db"
    monkeypatch.setattr("upbox.db.store.DEFAULT_DB_PATH", db)
    with Store(db) as s:
        s.insert_request(_record("api.cursor.sh"))
        s.insert_request(_record("api.anthropic.com"))
    return db


def _record(host: str) -> RequestRecord:
    return RequestRecord(
        ts="2026-09-01T09:00:00+00:00",
        tool="Cursor",
        method="POST",
        scheme="https",
        host=host,
        path="/v1/chat",
        req_bytes=42,
        resp_bytes=100,
        status=200,
        headers_json="{}",
        body_excerpt='{"prompt": "hi"}',
        body_hash="deadbeef",
        redactions_applied_json=None,
        enforcement=None,
    )


def test_report_writes_markdown_to_stdout_by_default(populated_db: Path) -> None:
    result = CliRunner().invoke(app, ["report"])

    assert result.stdout.startswith("# What upbox holds about this machine's user")


def test_report_writes_the_file(populated_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "report.md"

    CliRunner().invoke(app, ["report", "-o", str(out)])

    assert "## 3. Recipients" in out.read_text(encoding="utf-8")


def test_report_json_format_parses(populated_db: Path) -> None:
    result = CliRunner().invoke(app, ["report", "--format", "json"])

    assert json.loads(result.stdout)["total_rows"] == 2


def test_report_records_writes_an_audit_export(populated_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    records = tmp_path / "records.ndjson"

    CliRunner().invoke(app, ["report", "-o", str(out), "--records", str(records)])

    first_line = records.read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(first_line)["type"] == "upbox.audit.header"


def test_report_rejects_unknown_format(populated_db: Path) -> None:
    result = CliRunner().invoke(app, ["report", "--format", "pdf"])

    assert result.exit_code == 2
