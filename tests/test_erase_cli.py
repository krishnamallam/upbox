"""Tests for the `upbox erase` command and the erasure line in `upbox verify`."""

from __future__ import annotations

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
        s.insert_request(_record("2026-09-01T09:00:00+00:00", "a.example"))
        s.insert_request(_record("2026-09-02T09:00:00+00:00", "b.example"))
    return db


def _record(ts: str, host: str) -> RequestRecord:
    return RequestRecord(
        ts=ts,
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


def _host_of(db: Path, row_id: int) -> str | None:
    with Store(db) as s:
        row = s.query_by_id(row_id)
    return None if row is None else row["host"]


def _erased_at(db: Path, row_id: int) -> str | None:
    with Store(db) as s:
        row = s.query_by_id(row_id)
    return None if row is None else row["erased_at"]


def test_erase_requires_a_reason(populated_db: Path) -> None:
    result = CliRunner().invoke(app, ["erase", "--id", "1"])

    assert result.exit_code == 2


def test_erase_requires_a_selector(populated_db: Path) -> None:
    result = CliRunner().invoke(app, ["erase", "--reason", "request"])

    assert result.exit_code == 2


def test_erase_by_id_tombstones_the_row(populated_db: Path) -> None:
    CliRunner().invoke(app, ["erase", "--id", "1", "--reason", "request"])

    assert _erased_at(populated_db, 1) is not None


def test_erase_leaves_other_rows_alone(populated_db: Path) -> None:
    CliRunner().invoke(app, ["erase", "--id", "1", "--reason", "request"])

    assert _host_of(populated_db, 2) == "b.example"


def test_dry_run_leaves_the_row_intact(populated_db: Path) -> None:
    CliRunner().invoke(app, ["erase", "--id", "1", "--reason", "request", "--dry-run"])

    assert _host_of(populated_db, 1) == "a.example"


def test_dry_run_says_what_it_would_do(populated_db: Path) -> None:
    result = CliRunner().invoke(app, ["erase", "--id", "1", "--reason", "request", "--dry-run"])

    assert "Would erase 1 row(s)" in result.stdout


def test_held_row_exits_with_code_one(populated_db: Path) -> None:
    with Store(populated_db) as s:
        s.set_legal_hold(since="2026-09-01T00:00:00", until="2026-09-01T23:59:59")

    result = CliRunner().invoke(app, ["erase", "--id", "1", "--reason", "request"])

    assert result.exit_code == 1


def test_held_row_is_left_intact(populated_db: Path) -> None:
    with Store(populated_db) as s:
        s.set_legal_hold(since="2026-09-01T00:00:00", until="2026-09-01T23:59:59")

    CliRunner().invoke(app, ["erase", "--id", "1", "--reason", "request"])

    assert _host_of(populated_db, 1) == "a.example"


def test_bare_date_bound_covers_the_whole_day(populated_db: Path) -> None:
    CliRunner().invoke(app, ["erase", "--since", "2026-09-02", "--reason", "request"])

    assert _erased_at(populated_db, 2) is not None


def test_nothing_matching_exits_cleanly(populated_db: Path) -> None:
    result = CliRunner().invoke(app, ["erase", "--host", "nobody.example", "--reason", "request"])

    assert result.exit_code == 0


def test_verify_reports_erased_entries(populated_db: Path) -> None:
    CliRunner().invoke(app, ["erase", "--id", "1", "--reason", "request"])

    result = CliRunner().invoke(app, ["verify"])

    assert "erased" in result.stdout
