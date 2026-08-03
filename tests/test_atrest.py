"""Tests for at-rest hardening.

upbox ships no in-app encryption, so what it does ship (owner-only permissions
and an honest encryption report) has to actually work. The reporting tests pin
the property that matters most: an unknown answer stays unknown rather than
being smoothed into a reassuring one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from upbox.atrest import (
    DIR_MODE,
    FILE_MODE,
    harden_path_permissions,
    path_mode,
    volume_encryption_status,
)
from upbox.db.store import Store

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX file modes do not apply on Windows"
)


@posix_only
def test_store_open_restricts_the_database_file(tmp_path: Path) -> None:
    db = tmp_path / "sub" / "upbox.db"

    Store(db).close()

    assert path_mode(db) == f"{FILE_MODE:04o}"


@posix_only
def test_store_open_restricts_the_containing_directory(tmp_path: Path) -> None:
    db = tmp_path / "sub" / "upbox.db"

    Store(db).close()

    assert path_mode(db.parent) == f"{DIR_MODE:04o}"


@posix_only
def test_hardening_tightens_a_world_readable_database(tmp_path: Path) -> None:
    db = tmp_path / "upbox.db"
    db.write_text("")
    db.chmod(0o644)

    harden_path_permissions(db)

    assert path_mode(db) == f"{FILE_MODE:04o}"


@posix_only
def test_wal_sidecar_is_restricted_too(tmp_path: Path) -> None:
    """-wal holds recently written rows and needs the same mode as the DB."""
    db = tmp_path / "upbox.db"
    wal = tmp_path / "upbox.db-wal"
    db.write_text("")
    wal.write_text("")
    wal.chmod(0o644)

    harden_path_permissions(db)

    assert path_mode(wal) == f"{FILE_MODE:04o}"


def test_hardening_a_missing_path_does_not_raise(tmp_path: Path) -> None:
    harden_path_permissions(tmp_path / "absent.db")


def test_path_mode_reports_unreadable_rather_than_guessing(tmp_path: Path) -> None:
    assert "unreadable" in path_mode(tmp_path / "absent.db")


def test_encryption_state_is_one_of_the_three_known_values(tmp_path: Path) -> None:
    assert volume_encryption_status(tmp_path).state in {"encrypted", "not_encrypted", "unknown"}


def test_encryption_status_always_explains_itself(tmp_path: Path) -> None:
    assert volume_encryption_status(tmp_path).detail


def test_unknown_encryption_is_not_reported_as_encrypted(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable probe must never resolve to a reassuring answer."""
    monkeypatch.setattr("upbox.atrest._run", lambda command: None)

    assert volume_encryption_status(Path("/tmp")).is_encrypted is None


def test_unrecognised_probe_output_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("upbox.atrest._run", lambda command: "something unexpected")
    monkeypatch.setattr("upbox.atrest.platform.system", lambda: "Darwin")

    assert volume_encryption_status(Path("/tmp")).state == "unknown"


def test_filevault_on_is_reported_as_encrypted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("upbox.atrest._run", lambda command: "FileVault is On.")
    monkeypatch.setattr("upbox.atrest.platform.system", lambda: "Darwin")

    assert volume_encryption_status(Path("/tmp")).is_encrypted is True


def test_filevault_off_is_reported_as_not_encrypted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("upbox.atrest._run", lambda command: "FileVault is Off.")
    monkeypatch.setattr("upbox.atrest.platform.system", lambda: "Darwin")

    assert volume_encryption_status(Path("/tmp")).is_encrypted is False


def test_unsupported_platform_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("upbox.atrest.platform.system", lambda: "Plan9")

    assert volume_encryption_status(Path("/tmp")).state == "unknown"
