"""Tests for the frozen binary's double-click behaviour on Windows."""

from __future__ import annotations

import io
from dataclasses import dataclass

from upbox.launch import (
    CA_CONSENT_MESSAGE,
    DOUBLE_CLICK_MESSAGE,
    explain_and_wait,
    launched_by_double_click,
    run_double_click_flow,
    run_launch,
)


@dataclass
class _Status:
    cert_exists: bool
    in_windows_trust: bool | None


def _quiet(_prompt: str) -> str:
    return ""


def _no_pause(_seconds: float) -> None:
    return None


# --- deciding whether this was a double-click --------------------------------


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


# --- the double-click flow ------------------------------------------------------


def test_admin_double_click_runs_the_launch_directly() -> None:
    calls: list[str] = []

    rc = run_double_click_flow(
        "upbox.exe",
        admin=lambda: True,
        relaunch=lambda _exe, _args: False,
        launch=lambda: calls.append("launch") or 0,
        out=io.StringIO(),
        wait=_quiet,
        pause=_no_pause,
    )

    assert (rc, calls) == (0, ["launch"])


def test_non_admin_double_click_relaunches_elevated_with_the_launch_command() -> None:
    seen: list[tuple[str, str]] = []

    run_double_click_flow(
        "C:\\Tools\\upbox.exe",
        admin=lambda: False,
        relaunch=lambda exe, args: seen.append((exe, args)) or True,
        out=io.StringIO(),
        wait=_quiet,
        pause=_no_pause,
    )

    assert seen == [("C:\\Tools\\upbox.exe", "launch")]


def test_accepted_elevation_says_where_upbox_continues() -> None:
    out = io.StringIO()

    rc = run_double_click_flow(
        "upbox.exe",
        admin=lambda: False,
        relaunch=lambda _exe, _args: True,
        out=out,
        wait=_quiet,
        pause=_no_pause,
    )

    assert (rc, "new window" in out.getvalue()) == (0, True)


def test_declined_elevation_falls_back_to_the_powershell_explanation() -> None:
    out = io.StringIO()

    rc = run_double_click_flow(
        "upbox.exe",
        admin=lambda: False,
        relaunch=lambda _exe, _args: False,
        out=out,
        wait=_quiet,
        pause=_no_pause,
    )

    assert (rc, "upbox.exe start" in out.getvalue()) == (1, True)


# --- the elevated launch ----------------------------------------------------------


def test_launch_installs_the_ca_after_consent() -> None:
    installed: list[bool] = []

    run_launch(
        ca_status=lambda: _Status(False, None),
        install_ca=lambda: installed.append(True),
        start=lambda: 0,
        out=io.StringIO(),
        wait=lambda _prompt: "y",
    )

    assert installed == [True]


def test_enter_alone_counts_as_consent() -> None:
    installed: list[bool] = []

    run_launch(
        ca_status=lambda: _Status(False, False),
        install_ca=lambda: installed.append(True),
        start=lambda: 0,
        out=io.StringIO(),
        wait=_quiet,
    )

    assert installed == [True]


def test_declining_the_ca_does_not_start_upbox() -> None:
    started: list[bool] = []

    rc = run_launch(
        ca_status=lambda: _Status(False, False),
        install_ca=lambda: None,
        start=lambda: started.append(True) or 0,
        out=io.StringIO(),
        wait=lambda _prompt: "n",
    )

    assert (rc, started) == (1, [])


def test_launch_skips_the_ca_prompt_when_already_trusted() -> None:
    out = io.StringIO()

    run_launch(
        ca_status=lambda: _Status(True, True),
        install_ca=lambda: None,
        start=lambda: 0,
        out=out,
        wait=_quiet,
    )

    assert CA_CONSENT_MESSAGE not in out.getvalue()


def test_launch_returns_the_supervisor_exit_code() -> None:
    rc = run_launch(
        ca_status=lambda: _Status(True, True),
        install_ca=lambda: None,
        start=lambda: 3,
        out=io.StringIO(),
        wait=_quiet,
    )

    assert rc == 3


def test_failed_start_holds_the_window_open() -> None:
    prompts: list[str] = []

    run_launch(
        ca_status=lambda: _Status(True, True),
        install_ca=lambda: None,
        start=lambda: 1,
        out=io.StringIO(),
        wait=lambda prompt: prompts.append(prompt) or "",
    )

    assert prompts == ["Press Enter to close this window. "]


# --- the fallback explanation ------------------------------------------------------


def test_explanation_names_the_two_commands() -> None:
    out = io.StringIO()

    explain_and_wait(out, wait=_quiet)

    assert "upbox.exe init" in out.getvalue() and "upbox.exe start" in out.getvalue()


def test_explanation_waits_for_the_user() -> None:
    prompts: list[str] = []

    explain_and_wait(io.StringIO(), wait=lambda prompt: prompts.append(prompt) or "")

    assert prompts == ["Press Enter to close this window. "]


def test_closed_stdin_does_not_crash_the_window() -> None:
    def closed(_prompt: str) -> str:
        raise EOFError

    explain_and_wait(io.StringIO(), wait=closed)

    assert DOUBLE_CLICK_MESSAGE.startswith("upbox could not start from a double-click")
