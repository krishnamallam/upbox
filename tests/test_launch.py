"""Tests for the frozen binary's double-click behaviour on Windows."""

from __future__ import annotations

import io

from upbox.launch import DOUBLE_CLICK_MESSAGE, explain_and_wait, launched_by_double_click


def test_windows_with_no_arguments_and_own_console_is_a_double_click() -> None:
    assert launched_by_double_click(["upbox.exe"], "win32", 2) is True


def test_arguments_mean_a_deliberate_command() -> None:
    assert launched_by_double_click(["upbox.exe", "start"], "win32", 2) is False


def test_a_shell_owning_the_console_means_a_terminal_launch() -> None:
    assert launched_by_double_click(["upbox.exe"], "win32", 3) is False


def test_unknown_console_ownership_is_treated_as_a_terminal_launch() -> None:
    assert launched_by_double_click(["upbox.exe"], "win32", None) is False


def test_other_platforms_never_count_as_a_double_click() -> None:
    assert launched_by_double_click(["upbox"], "darwin", 2) is False


def test_explanation_names_the_two_commands() -> None:
    out = io.StringIO()

    explain_and_wait(out, wait=lambda _prompt: "")

    assert "upbox.exe init" in out.getvalue() and "upbox.exe start" in out.getvalue()


def test_explanation_waits_for_the_user() -> None:
    prompts: list[str] = []

    explain_and_wait(io.StringIO(), wait=lambda prompt: prompts.append(prompt) or "")

    assert prompts == ["Press Enter to close this window. "]


def test_closed_stdin_does_not_crash_the_window() -> None:
    def closed(_prompt: str) -> str:
        raise EOFError

    explain_and_wait(io.StringIO(), wait=closed)

    assert DOUBLE_CLICK_MESSAGE.startswith("upbox is a command-line tool")
