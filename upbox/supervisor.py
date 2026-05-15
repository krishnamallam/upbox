"""``upbox start`` supervisor — spawns ``upbox proxy`` + ``upbox dashboard``.

Per ``PLAN.md``'s process architecture: each component runs as its own
process. The supervisor wires them together:

- Spawn both via ``subprocess.Popen``.
- Forward ``SIGINT`` / ``SIGTERM`` to both children.
- Poll every 500 ms; if either child dies, kill the other and exit with
  the dead child's exit status.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

PID_FILE = Path.home() / ".upbox" / "supervisor.pid"
POLL_INTERVAL = 0.5
TERMINATE_GRACE = 5.0


def run(proxy_port: int = 8888, dashboard_port: int = 8800) -> int:
    """Spawn proxy + dashboard, wait until either dies. Returns the dead child's rc."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    try:
        proxy_proc = _spawn(["proxy", "--port", str(proxy_port)])
        dashboard_proc = _spawn(["dashboard", "--port", str(dashboard_port)])
    except Exception:
        PID_FILE.unlink(missing_ok=True)
        raise

    children = {"proxy": proxy_proc, "dashboard": dashboard_proc}

    def _forward_signal(signum: int, _frame: object) -> None:
        log.info("supervisor: caught signal %d, forwarding to children", signum)
        _stop_all(children)

    signal.signal(signal.SIGINT, _forward_signal)
    signal.signal(signal.SIGTERM, _forward_signal)

    print(f"upbox: proxy=127.0.0.1:{proxy_port}  dashboard=http://127.0.0.1:{dashboard_port}")

    try:
        while True:
            for name, proc in children.items():
                rc = proc.poll()
                if rc is not None:
                    log.warning("supervisor: %s exited with rc=%d", name, rc)
                    _stop_all({n: p for n, p in children.items() if n != name})
                    return rc
            time.sleep(POLL_INTERVAL)
    finally:
        PID_FILE.unlink(missing_ok=True)


def _spawn(args: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-m", "upbox.cli", *args])


def _stop_all(procs: dict[str, subprocess.Popen[bytes]]) -> None:
    for proc in procs.values():
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
    for proc in procs.values():
        try:
            proc.wait(timeout=TERMINATE_GRACE)
        except subprocess.TimeoutExpired:
            proc.kill()
