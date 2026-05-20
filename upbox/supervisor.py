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
IS_WINDOWS = sys.platform == "win32"
SPAWN_MODULE = "upbox"


def run(
    proxy_port: int = 8888,
    dashboard_port: int = 8800,
    capture_spec: str | None = None,
) -> int:
    """Spawn proxy + dashboard, wait until either dies. Returns the dead child's rc.

    ``capture_spec`` is forwarded to ``upbox proxy`` as mitmproxy's LocalMode
    intercept spec. If ``None``, the proxy boots in standard explicit-proxy
    mode (no OS-level capture).
    """
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    proxy_args = ["proxy", "--port", str(proxy_port)]
    if capture_spec is not None:
        proxy_args.extend(["--capture-spec", capture_spec])

    try:
        proxy_proc = _spawn(proxy_args)
        dashboard_proc = _spawn(["dashboard", "--port", str(dashboard_port)])
    except Exception:
        PID_FILE.unlink(missing_ok=True)
        raise

    children = {"proxy": proxy_proc, "dashboard": dashboard_proc}

    def _forward_signal(signum: int, _frame: object) -> None:
        log.info("supervisor: caught signal %d, forwarding to children", signum)
        _stop_all(children)

    signal.signal(signal.SIGINT, _forward_signal)
    if not IS_WINDOWS:
        # SIGTERM only exists on POSIX. Windows uses Ctrl+C / Ctrl+Break,
        # both of which raise SIGINT in Python, which is already handled.
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
    # `-m upbox` (via `upbox/__main__.py`) actually invokes the typer app.
    # `-m upbox.cli` would just import the module and exit rc=0, because
    # cli.py has no `if __name__ == "__main__"` block.
    return subprocess.Popen([sys.executable, "-m", SPAWN_MODULE, *args])


def _stop_all(procs: dict[str, subprocess.Popen[bytes]]) -> None:
    for proc in procs.values():
        if proc.poll() is None:
            # `terminate()` is cross-platform: SIGTERM on POSIX,
            # TerminateProcess on Windows.
            proc.terminate()
    for proc in procs.values():
        try:
            proc.wait(timeout=TERMINATE_GRACE)
        except subprocess.TimeoutExpired:
            proc.kill()
