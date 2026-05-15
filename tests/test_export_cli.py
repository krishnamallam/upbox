"""Tests for the `upbox export` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from upbox import cli as cli_module
from upbox.db.store import RequestRecord, Store


@pytest.fixture
def populated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test.db"
    monkeypatch.setattr("upbox.db.store.DEFAULT_DB_PATH", db)
    with Store(db) as s:
        s.insert_request(_record(ts="2026-05-01T00:00:00", tool="Cursor", host="api.cursor.sh"))
        s.insert_request(
            _record(ts="2026-05-15T00:00:00", tool="Claude Code", host="api.anthropic.com")
        )
        s.insert_request(_record(ts="2026-06-01T00:00:00", tool="Cursor", host="api.cursor.sh"))
    return db


def _record(**overrides) -> RequestRecord:
    base = {
        "ts": "2026-05-15T00:00:00",
        "tool": "Cursor",
        "method": "POST",
        "scheme": "https",
        "host": "api.cursor.sh",
        "path": "/v1/chat",
        "req_bytes": 42,
        "resp_bytes": 100,
        "status": 200,
        "headers_json": "{}",
        "body_excerpt": None,
        "body_hash": None,
        "redactions_applied_json": None,
        "blocked": 0,
    }
    base.update(overrides)
    return RequestRecord(**base)


def test_export_jsonl_writes_one_line_per_row(populated_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"

    result = CliRunner().invoke(cli_module.app, ["export", "--format", "jsonl", "-o", str(out)])

    assert result.exit_code == 0
    assert len(out.read_text().strip().splitlines()) == 3


def test_export_csv_writes_header_plus_rows(populated_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.csv"

    result = CliRunner().invoke(cli_module.app, ["export", "--format", "csv", "-o", str(out)])

    assert result.exit_code == 0
    assert len(out.read_text().strip().splitlines()) == 4  # 1 header + 3 rows


def test_export_filters_by_tool(populated_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"

    CliRunner().invoke(
        cli_module.app, ["export", "--format", "jsonl", "--tool", "Cursor", "-o", str(out)]
    )
    rows = [json.loads(line) for line in out.read_text().strip().splitlines()]

    assert {r["tool"] for r in rows} == {"Cursor"}


def test_export_filters_by_time_range(populated_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"

    CliRunner().invoke(
        cli_module.app,
        [
            "export",
            "--format",
            "jsonl",
            "--since",
            "2026-05-10T00:00:00",
            "--until",
            "2026-05-20T00:00:00",
            "-o",
            str(out),
        ],
    )
    rows = [json.loads(line) for line in out.read_text().strip().splitlines()]

    assert len(rows) == 1


def test_export_rejects_unknown_format(populated_db: Path) -> None:
    result = CliRunner().invoke(cli_module.app, ["export", "--format", "xml"])

    assert result.exit_code == 2
