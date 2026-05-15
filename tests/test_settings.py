"""Tests for upbox/settings.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from upbox import settings


@pytest.fixture
def tmp_rules_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    rules = tmp_path / "rules"
    monkeypatch.setattr(settings, "USER_RULES_DIR", rules)
    return rules


def test_read_current_falls_back_to_bundled_defaults(tmp_rules_dir: Path) -> None:
    text = settings.read_current("redact")

    assert "openai-key" in text


def test_validate_and_write_rejects_invalid_yaml(tmp_rules_dir: Path) -> None:
    ok, msg = settings.validate_and_write("redact", "not: valid: yaml: [")

    assert not ok and "parse" in msg.lower()


def test_validate_and_write_rejects_unknown_kind(tmp_rules_dir: Path) -> None:
    ok, msg = settings.validate_and_write("nonsense", "[]")

    assert not ok and "unknown" in msg.lower()


def test_validate_and_write_rejects_wrong_top_level_shape(tmp_rules_dir: Path) -> None:
    """redact.yaml must be a list, not a dict."""
    ok, _ = settings.validate_and_write("redact", "key: value\n")

    assert not ok


def test_validate_and_write_persists_valid_redact_yaml(tmp_rules_dir: Path) -> None:
    text = '- name: test\n  pattern: "X"\n  replace: "Y"\n'

    ok, _ = settings.validate_and_write("redact", text)

    assert ok
    assert (tmp_rules_dir / "redact.yaml").read_text() == text


def test_validate_and_write_persists_valid_allowlist_yaml(tmp_rules_dir: Path) -> None:
    text = "Cursor:\n  allow: [api.cursor.sh]\n  block_unknown: warn\n"

    ok, _ = settings.validate_and_write("allowlist", text)

    assert ok and (tmp_rules_dir / "allowlist.yaml").exists()


def test_validate_and_write_rejects_redact_missing_required_field(tmp_rules_dir: Path) -> None:
    ok, _ = settings.validate_and_write("redact", "- name: missing-pattern\n")

    assert not ok
