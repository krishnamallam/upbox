"""Smoke tests for the upbox CLI."""

from __future__ import annotations

from typer.testing import CliRunner

from upbox.cli import app


def test_cli_help_succeeds() -> None:
    """``upbox --help`` exits with code 0."""
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
