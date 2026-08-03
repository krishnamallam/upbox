"""Tests for the TLS-interception exclusion list.

This list is a proportionality control for workplace deployments, so the
behaviour that matters is that it fails closed: a broken or empty user file
falls back to the shipped defaults rather than to decrypting everything.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from upbox.no_intercept import load_no_intercept_patterns


@pytest.fixture
def user_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "no_intercept.yaml"
    monkeypatch.setattr("upbox.no_intercept.USER_RULES_PATH", path)
    return path


def test_defaults_load_when_no_user_file_exists(user_rules: Path) -> None:
    assert load_no_intercept_patterns()


def test_every_default_pattern_compiles(user_rules: Path) -> None:
    assert all(re.compile(pattern) for pattern in load_no_intercept_patterns())


def test_defaults_cover_banking(user_rules: Path) -> None:
    patterns = load_no_intercept_patterns()

    assert any(re.search(p, "www.paypal.com:443") for p in patterns)


def test_defaults_cover_private_webmail(user_rules: Path) -> None:
    patterns = load_no_intercept_patterns()

    assert any(re.search(p, "mail.proton.me:443") for p in patterns)


def test_defaults_cover_health(user_rules: Path) -> None:
    patterns = load_no_intercept_patterns()

    assert any(re.search(p, "www.nhs.uk:443") for p in patterns)


def test_defaults_do_not_exclude_ai_hosts(user_rules: Path) -> None:
    """Excluding an AI host would silently blind the tool's actual purpose."""
    patterns = load_no_intercept_patterns()

    assert not any(re.search(p, "api.anthropic.com:443") for p in patterns)


def test_user_file_replaces_the_defaults(user_rules: Path) -> None:
    user_rules.write_text('- "(^|\\\\.)example\\\\.com:"\n')

    assert load_no_intercept_patterns() == ["(^|\\.)example\\.com:"]


def test_empty_user_file_falls_back_to_defaults(user_rules: Path) -> None:
    """Failing open here would start decrypting banking traffic."""
    user_rules.write_text("[]\n")

    assert len(load_no_intercept_patterns()) > 1


def test_malformed_user_file_falls_back_to_defaults(user_rules: Path) -> None:
    user_rules.write_text("{not: [a, list\n")

    assert len(load_no_intercept_patterns()) > 1


def test_uncompilable_pattern_is_dropped_not_fatal(user_rules: Path) -> None:
    user_rules.write_text('- "(unclosed"\n- "(^|\\\\.)example\\\\.com:"\n')

    assert load_no_intercept_patterns() == ["(^|\\.)example\\.com:"]


def test_non_string_entry_is_dropped(user_rules: Path) -> None:
    user_rules.write_text('- 42\n- "(^|\\\\.)example\\\\.com:"\n')

    assert load_no_intercept_patterns() == ["(^|\\.)example\\.com:"]
