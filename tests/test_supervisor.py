"""Unit tests for the supervisor.

Full crash-recovery / signal-forwarding round-trips are exercised on Day 13
with real subprocesses. Here we mock subprocess.Popen so the supervisor logic
is testable without spawning processes.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from upbox import supervisor


class FakeProc:
    """Minimal Popen stand-in for the supervisor poll loop."""

    def __init__(self) -> None:
        self.pid = 12345
        self._exit_code: int | None = None
        self.terminate_calls = 0
        self.killed = False

    def poll(self) -> int | None:
        return self._exit_code

    def terminate(self) -> None:
        self.terminate_calls += 1
        self._exit_code = 143  # SIGTERM convention

    def kill(self) -> None:
        self.killed = True
        self._exit_code = -9

    def wait(self, timeout: float | None = None) -> int:
        return self._exit_code or 0

    def set_exited(self, rc: int) -> None:
        self._exit_code = rc


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep supervisor tests off the real ~/.upbox.

    ``run()`` initialises the audit database before spawning children. That is
    filesystem work these tests do not exercise, and leaving it live both wrote
    to the developer's home directory and made the spawn slow enough to lose the
    races below.
    """
    monkeypatch.setattr(supervisor, "_initialise_database", lambda: None)


def _exit_when_spawned(spawned: list[FakeProc], index: int, rc: int) -> threading.Thread:
    """Mark a child exited as soon as it has actually been spawned.

    A fixed sleep here used to race ``run()``: on a slow runner the timer fired
    before ``_spawn`` had appended anything, ``spawned[index]`` raised
    IndexError in the thread, no child ever looked dead, and the supervisor
    polled until CI killed the job six hours later.
    """

    def wait_then_exit() -> None:
        deadline = time.monotonic() + 30
        while len(spawned) <= index:
            if time.monotonic() > deadline:  # pragma: no cover - guards a hang
                raise AssertionError(f"child {index} was never spawned")
            time.sleep(0.005)
        spawned[index].set_exited(rc)

    thread = threading.Thread(target=wait_then_exit, daemon=True)
    thread.start()
    return thread


def test_supervisor_exits_when_child_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If a child returns non-zero, supervisor returns that rc and stops the other."""
    monkeypatch.setattr(supervisor, "PID_FILE", tmp_path / "supervisor.pid")
    monkeypatch.setattr(supervisor, "POLL_INTERVAL", 0.01)

    procs = [FakeProc(), FakeProc()]
    spawned: list[FakeProc] = []

    def fake_spawn(_args: list[str]) -> Any:
        proc = procs.pop(0)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(supervisor, "_spawn", fake_spawn)

    _exit_when_spawned(spawned, 0, 7)

    rc = supervisor.run()

    assert rc == 7


def test_supervisor_terminates_sibling_when_one_child_dies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supervisor, "PID_FILE", tmp_path / "supervisor.pid")
    monkeypatch.setattr(supervisor, "POLL_INTERVAL", 0.01)

    procs = [FakeProc(), FakeProc()]
    spawned: list[FakeProc] = []

    def fake_spawn(_args: list[str]) -> Any:
        proc = procs.pop(0)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(supervisor, "_spawn", fake_spawn)

    _exit_when_spawned(spawned, 0, 0)
    supervisor.run()

    assert spawned[1].terminate_calls >= 1


def test_run_initialises_the_database_before_spawning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard opens read-only and will not migrate, so a writer must
    have created and migrated the database before either child starts."""
    monkeypatch.setattr(supervisor, "PID_FILE", tmp_path / "supervisor.pid")
    monkeypatch.setattr(supervisor, "POLL_INTERVAL", 0.01)

    order: list[str] = []
    spawned: list[FakeProc] = []
    monkeypatch.setattr(supervisor, "_initialise_database", lambda: order.append("db"))

    def fake_spawn(_args: list[str]) -> Any:
        order.append("spawn")
        proc = FakeProc()
        spawned.append(proc)
        return proc

    monkeypatch.setattr(supervisor, "_spawn", fake_spawn)

    _exit_when_spawned(spawned, 0, 0)
    supervisor.run()

    assert order[0] == "db"


def test_spawn_module_invokes_typer_app() -> None:
    # `python -m upbox.cli` exits rc=0 silently because cli.py has no main
    # block, which made `upbox start` look like the proxy crashed cleanly.
    # `python -m upbox` routes through __main__.py and actually runs the app.
    result = subprocess.run(
        [sys.executable, "-m", supervisor.SPAWN_MODULE, "proxy", "--help"],
        capture_output=True,
        timeout=15,
    )

    assert b"Run the upbox proxy" in result.stdout


def test_run_forwards_capture_spec_to_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supervisor, "PID_FILE", tmp_path / "supervisor.pid")
    monkeypatch.setattr(supervisor, "POLL_INTERVAL", 0.01)

    spawned_args: list[list[str]] = []
    spawned_procs: list[FakeProc] = []

    def fake_spawn(args: list[str]) -> Any:
        spawned_args.append(list(args))
        proc = FakeProc()
        spawned_procs.append(proc)
        return proc

    monkeypatch.setattr(supervisor, "_spawn", fake_spawn)

    _exit_when_spawned(spawned_procs, 0, 0)
    supervisor.run(capture_spec="claude.exe,cursor.exe")

    assert spawned_args[0] == [
        "proxy",
        "--port",
        "8888",
        "--capture-spec",
        "claude.exe,cursor.exe",
    ]


def test_run_forwards_no_allowlist_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "PID_FILE", tmp_path / "supervisor.pid")
    monkeypatch.setattr(supervisor, "POLL_INTERVAL", 0.01)

    spawned_args: list[list[str]] = []
    spawned_procs: list[FakeProc] = []

    def fake_spawn(args: list[str]) -> Any:
        spawned_args.append(list(args))
        proc = FakeProc()
        spawned_procs.append(proc)
        return proc

    monkeypatch.setattr(supervisor, "_spawn", fake_spawn)

    _exit_when_spawned(spawned_procs, 0, 0)
    supervisor.run(use_allowlist=False, extra_allow_hosts=("custom.ai",))

    assert "--no-allowlist" in spawned_args[0]
    assert spawned_args[0][-2:] == ["--allow", "custom.ai"]
