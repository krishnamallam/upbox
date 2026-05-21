"""Smoke tests for the upbox CLI."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from upbox import proxy as proxy_module
from upbox.cli import app


def test_cli_help_succeeds() -> None:
    """``upbox --help`` exits with code 0."""
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0


def test_start_capture_spec_and_capture_all_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing both --capture-spec and --capture-all exits with code 2."""

    def fake_run(**_kwargs: Any) -> int:
        raise AssertionError("supervisor.run should not be called on conflict")

    monkeypatch.setattr("upbox.supervisor.run", fake_run)

    result = CliRunner().invoke(
        app,
        ["start", "--capture-spec", "claude", "--capture-all"],
    )

    assert result.exit_code == 2


def test_start_defaults_to_curated_ai_tool_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """No flags → supervisor receives the curated AI-tool process list."""
    received: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> int:
        received.update(kwargs)
        return 0

    monkeypatch.setattr("upbox.supervisor.run", fake_run)

    result = CliRunner().invoke(app, ["start"])

    assert result.exit_code == 0
    assert received["capture_spec"] == proxy_module.default_capture_spec()


def test_start_capture_all_passes_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    """--capture-all forwards the capture-everything sentinel to the supervisor."""
    received: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> int:
        received.update(kwargs)
        return 0

    monkeypatch.setattr("upbox.supervisor.run", fake_run)

    result = CliRunner().invoke(app, ["start", "--capture-all"])

    assert result.exit_code == 0
    assert received["capture_spec"] == proxy_module.CAPTURE_ALL_SENTINEL


def test_start_custom_capture_spec_overrides_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--capture-spec replaces the curated default verbatim."""
    received: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> int:
        received.update(kwargs)
        return 0

    monkeypatch.setattr("upbox.supervisor.run", fake_run)

    result = CliRunner().invoke(app, ["start", "--capture-spec", "claude,cursor"])

    assert result.exit_code == 0
    assert received["capture_spec"] == "claude,cursor"


def test_default_capture_spec_excludes_vpn_processes() -> None:
    """The curated default must never include common VPN client process names."""
    spec = proxy_module.default_capture_spec().split(",")
    vpn_names = {
        "openvpn",
        "wg-quick",
        "wireguard",
        "tailscaled",
        "nordvpnd",
        "nordvpn",
        "mullvad-daemon",
        "mullvad",
        "protonvpn",
        "protonvpn-cli",
    }

    assert not vpn_names.intersection(spec)


def test_default_capture_spec_includes_core_ai_tools() -> None:
    """Sanity check: the curated default covers the headline AI tools."""
    spec = proxy_module.default_capture_spec().split(",")

    for name in ("Claude", "Cursor", "ChatGPT", "claude", "codex"):
        assert name in spec
