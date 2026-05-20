"""Unit tests for the supervisor.

Full crash-recovery / signal-forwarding round-trips are exercised on Day 13
with real subprocesses. Here we mock subprocess.Popen so the supervisor logic
is testable without spawning processes.
"""

from __future__ import annotations

import subprocess
import sys
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

    import threading

    def kill_first_after_delay() -> None:
        import time as _t

        _t.sleep(0.05)
        spawned[0].set_exited(7)

    threading.Thread(target=kill_first_after_delay, daemon=True).start()

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

    import threading

    def kill_first() -> None:
        import time as _t

        _t.sleep(0.05)
        spawned[0].set_exited(0)

    threading.Thread(target=kill_first, daemon=True).start()
    supervisor.run()

    assert spawned[1].terminate_calls >= 1


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
    import threading

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

    def exit_proxy_after_delay() -> None:
        import time as _t

        _t.sleep(0.05)
        spawned_procs[0].set_exited(0)

    threading.Thread(target=exit_proxy_after_delay, daemon=True).start()
    supervisor.run(capture_spec="claude.exe,cursor.exe")

    assert spawned_args[0] == [
        "proxy",
        "--port",
        "8888",
        "--capture-spec",
        "claude.exe,cursor.exe",
    ]
