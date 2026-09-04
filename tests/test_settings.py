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


def test_write_leaves_no_temp_file_in_dir(tmp_rules_dir: Path) -> None:
    settings.validate_and_write("redact", '- name: t\n  pattern: "X"\n  replace: "Y"\n')

    assert [p.name for p in tmp_rules_dir.iterdir()] == ["redact.yaml"]


def test_invalid_write_after_valid_keeps_prior_content(tmp_rules_dir: Path) -> None:
    good = '- name: t\n  pattern: "X"\n  replace: "Y"\n'
    settings.validate_and_write("redact", good)

    settings.validate_and_write("redact", "not: valid: yaml: [")

    assert (tmp_rules_dir / "redact.yaml").read_text() == good


def test_success_message_notes_automatic_apply(tmp_rules_dir: Path) -> None:
    ok, msg = settings.validate_and_write("redact", '- name: t\n  pattern: "X"\n  replace: "Y"\n')

    assert ok and "automatically" in msg


def test_write_cleans_up_temp_file_when_replace_fails(
    tmp_rules_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(settings.os, "replace", boom)

    with pytest.raises(OSError):
        settings.validate_and_write("redact", '- name: t\n  pattern: "X"\n  replace: "Y"\n')

    assert list(tmp_rules_dir.iterdir()) == []


def test_read_current_capture_falls_back_to_bundled_default(tmp_rules_dir: Path) -> None:
    assert "bodies: true" in settings.read_current("capture")


def test_validate_and_write_accepts_capture_yaml(tmp_rules_dir: Path) -> None:
    ok, _ = settings.validate_and_write("capture", "bodies: false\nheaders: true\n")

    assert ok


def test_validate_and_write_rejects_non_boolean_capture_value(tmp_rules_dir: Path) -> None:
    ok, _ = settings.validate_and_write("capture", "bodies: sometimes\n")

    assert not ok


def test_validate_and_write_rejects_unknown_capture_key(tmp_rules_dir: Path) -> None:
    ok, _ = settings.validate_and_write("capture", "responses: true\n")

    assert not ok
