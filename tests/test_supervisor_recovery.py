"""Day 13: supervisor crash-recovery test.

Validates Issue 1 (process-isolation) under real failure. The simpler
test_supervisor.py uses FakeProcs; this one uses real subprocesses.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from upbox import supervisor


def _spawn_sleeper(seconds: int = 30) -> subprocess.Popen[bytes]:
    """A real subprocess that just sleeps. Stands in for proxy / dashboard."""
    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])


def test_supervisor_terminates_sibling_when_one_real_subprocess_dies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a child dies, the sibling is SIGTERMed and the supervisor exits."""
    monkeypatch.setattr(supervisor, "PID_FILE", tmp_path / "supervisor.pid")
    monkeypatch.setattr(supervisor, "POLL_INTERVAL", 0.05)
    monkeypatch.setattr(supervisor, "TERMINATE_GRACE", 2.0)

    children: list[subprocess.Popen[bytes]] = []

    def fake_spawn(_args: list[str]) -> subprocess.Popen[bytes]:
        proc = _spawn_sleeper(60)
        children.append(proc)
        return proc

    monkeypatch.setattr(supervisor, "_spawn", fake_spawn)

    import threading

    def kill_first_after_delay() -> None:
        time.sleep(0.3)
        children[0].send_signal(signal.SIGKILL)

    threading.Thread(target=kill_first_after_delay, daemon=True).start()

    rc = supervisor.run()

    # Both children should be reaped.
    for proc in children:
        assert proc.poll() is not None
    # Supervisor returns the rc of the dead child (SIGKILL → -9 on POSIX).
    assert rc != 0
