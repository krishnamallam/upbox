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
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable
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
    use_allowlist: bool = True,
    extra_allow_hosts: tuple[str, ...] = (),
    open_dashboard: bool = False,
) -> int:
    """Spawn proxy + dashboard, wait until either dies. Returns the dead child's rc.

    ``capture_spec`` is forwarded to ``upbox proxy`` as mitmproxy's LocalMode
    intercept spec. ``use_allowlist`` and ``extra_allow_hosts`` control the
    TLS allowlist derived from ``tools.yaml``. ``open_dashboard`` opens the
    dashboard in the default browser once it answers.
    """
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    proxy_args = ["proxy", "--port", str(proxy_port)]
    if capture_spec is not None:
        proxy_args.extend(["--capture-spec", capture_spec])
    if not use_allowlist:
        proxy_args.append("--no-allowlist")
    for h in extra_allow_hosts:
        proxy_args.extend(["--allow", h])

    # Create and migrate the database here, before either child exists. The
    # dashboard opens it read-only and will not migrate it, so leaving this to
    # the proxy would race: on an existing v0.1 database the dashboard could
    # open first and fail every query until the proxy caught up.
    _initialise_database()

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
    if open_dashboard:
        threading.Thread(
            target=open_dashboard_when_ready,
            args=(f"http://127.0.0.1:{dashboard_port}/",),
            daemon=True,
            name="upbox-open-dashboard",
        ).start()

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


def wait_until_ready(
    url: str,
    probe: Callable[[str], bool],
    attempts: int = 60,
    delay: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Poll ``probe(url)`` until it answers true or ``attempts`` run out."""
    for _ in range(attempts):
        if probe(url):
            return True
        sleep(delay)
    return False


def _http_answers(url: str) -> bool:
    # Loopback only: the dashboard binds 127.0.0.1, so this is not an outbound call.
    try:
        with urllib.request.urlopen(url, timeout=1):
            return True
    except Exception:
        return False


def open_dashboard_when_ready(
    url: str,
    probe: Callable[[str], bool] = _http_answers,
    opener: Callable[[str], bool] = webbrowser.open,
    attempts: int = 60,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Open ``url`` in the default browser once the dashboard answers; give up after ~30 s."""
    if wait_until_ready(url, probe, attempts=attempts, sleep=sleep):
        opener(url)
        return True
    log.warning("dashboard did not answer at %s; not opening a browser", url)
    return False


def _initialise_database() -> None:
    """Open the store once as a writer so the schema exists and is current."""
    from upbox.db.store import Store

    Store().close()


def _child_command(args: list[str]) -> list[str]:
    """Argv for a child process, whether we run from source or from a frozen binary.

    A PyInstaller one-file build has ``sys.executable`` pointing at the binary
    itself, which already runs the Typer app, so ``-m upbox`` would reach it as
    unknown options. From source, ``-m upbox`` (via ``upbox/__main__.py``) is
    what invokes the app; ``-m upbox.cli`` would import the module and exit.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", SPAWN_MODULE, *args]


def _spawn(args: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(_child_command(args))


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
