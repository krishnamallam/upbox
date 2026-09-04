"""What the frozen binary does when a user double-clicks it on Windows.

upbox is a command-line tool, and a console program opened from Explorer
flashes a window that prints the help and closes: "nothing happened". When the
binary owns its console alone and got no arguments, it instead does what a
double-click should: asks Windows for administrator rights (OS-level capture
installs a network driver), asks once before installing the local CA, starts
upbox with the dashboard opening in the browser, and stops when the window is
closed. A declined permission prompt falls back to explaining the two
PowerShell commands.

Only ``packaging/entry.py`` (the PyInstaller entry point) reaches the
double-click path; ``python -m upbox`` and the PyPI install are unaffected.
The hidden ``upbox launch`` command is the elevated half of the flow.
"""

from __future__ import annotations

import contextlib
import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from upbox.ca import CAStatus

DOUBLE_CLICK_MESSAGE = """\
upbox could not start from a double-click because Windows declined, or could
not show, the administrator permission prompt. Run it from PowerShell instead:

    .\\upbox.exe init      one-time: install the local CA
    .\\upbox.exe start     proxy + dashboard at http://127.0.0.1:8800

`start` needs an administrator PowerShell (right-click, Run as administrator)
because OS-level capture installs a network driver. Put upbox.exe somewhere on
your PATH to drop the ".\\" prefix.

Docs: https://github.com/krishnamallam/upbox#quick-start

"""

CA_CONSENT_MESSAGE = """\
upbox needs a local certificate authority (CA) to see what your AI tools send.
The CA is generated on this machine, kept in %USERPROFILE%\\.upbox\\ca, and added
to your own user's Trusted Root store, nowhere else. `upbox init --uninstall`
removes it again.

"""

# Explorer gives a double-clicked program a console of its own, so the only
# processes attached to it are PyInstaller's bootloader and the Python child it
# spawns. A shell that ran the command is attached as well, making three.
_OWNERS_WHEN_DOUBLE_CLICKED = 2
_SW_SHOWNORMAL = 1
# ShellExecuteW returns an HINSTANCE-shaped value: anything above 32 is success.
_SHELLEXECUTE_OK = 32


def launched_by_double_click(argv: list[str], platform: str, console_owners: int | None) -> bool:
    """True when a Windows user opened the binary from Explorer with no arguments.

    ``console_owners`` is the number of processes attached to our console, or
    ``None`` when it could not be read, which never counts as a double-click:
    the safe default is to behave like a normal CLI.
    """
    return (
        platform == "win32"
        and len(argv) <= 1
        and console_owners is not None
        and console_owners <= _OWNERS_WHEN_DOUBLE_CLICKED
    )


def console_owner_count() -> int | None:
    """Processes attached to this console (Windows only), or None if unknown."""
    # Read through a variable: mypy evaluates `sys.platform` comparisons
    # statically and would otherwise flag the Windows branch as unreachable
    # when checking on Linux.
    platform = sys.platform
    if platform != "win32":
        return None
    try:
        import ctypes

        kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009
        buffer = (ctypes.c_uint * 32)()
        count = int(kernel32.GetConsoleProcessList(buffer, 32))
    except Exception:
        return None
    return count if count > 0 else None


def is_admin() -> bool:
    """True when the current process already has administrator rights (Windows only)."""
    platform = sys.platform
    if platform != "win32":
        return False
    try:
        import ctypes

        return bool(getattr(ctypes, "windll").shell32.IsUserAnAdmin())  # noqa: B009
    except Exception:
        return False


def elevate(executable: str, arguments: str) -> bool:
    """Relaunch ``executable`` with administrator rights through the UAC prompt.

    Returns True when Windows accepted the request (the user may still be
    looking at the prompt), False when it was declined or unavailable.
    """
    platform = sys.platform
    if platform != "win32":
        return False
    try:
        import ctypes

        shell32 = getattr(ctypes, "windll").shell32  # noqa: B009
        result = int(
            shell32.ShellExecuteW(None, "runas", executable, arguments, None, _SW_SHOWNORMAL)
        )
    except Exception:
        return False
    return result > _SHELLEXECUTE_OK


def run_double_click_flow(
    executable: str,
    *,
    admin: Callable[[], bool] = is_admin,
    relaunch: Callable[[str, str], bool] = elevate,
    launch: Callable[[], int] | None = None,
    out: TextIO = sys.stdout,
    wait: Callable[[str], str] = input,
    pause: Callable[[float], None] = time.sleep,
) -> int:
    """Entry for a double-clicked exe. Returns the process exit code.

    Already elevated: run the launch flow here. Otherwise ask Windows to start
    a second, elevated copy running ``upbox launch`` and let this window go.
    """
    if admin():
        return (launch or run_launch)()
    if relaunch(executable, "launch"):
        out.write(
            "Windows is asking for administrator permission. upbox continues in the new "
            "window; this one can be closed.\n"
        )
        out.flush()
        pause(4)
        return 0
    explain_and_wait(out, wait)
    return 1


def run_launch(
    *,
    ca_status: Callable[[], CAStatus] | None = None,
    install_ca: Callable[[], None] | None = None,
    start: Callable[[], int] | None = None,
    out: TextIO = sys.stdout,
    wait: Callable[[str], str] = input,
) -> int:
    """The elevated half: consent, CA install if missing, start, dashboard in the browser.

    Installing a root CA is the one step a person must agree to explicitly, so
    it is asked for in words before anything is written to the trust store.
    """
    from upbox import ca as ca_module
    from upbox import proxy as proxy_module
    from upbox import supervisor

    status = (ca_status or ca_module.get_status)()
    if not (status.cert_exists and status.in_windows_trust):
        out.write(CA_CONSENT_MESSAGE)
        out.flush()
        answer = wait("Install the upbox CA now? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            out.write("Not installed. upbox cannot see AI-tool traffic without it.\n")
            explain_and_wait(out, wait)
            return 1
        (install_ca or ca_module.install_all)()

    out.write("Starting upbox. Close this window to stop it.\n")
    out.flush()
    run = start or (
        lambda: supervisor.run(
            capture_spec=proxy_module.default_capture_spec(), open_dashboard=True
        )
    )
    rc = run()
    if rc != 0:
        out.write(f"upbox stopped with exit code {rc}. See the messages above.\n")
        out.flush()
        with contextlib.suppress(EOFError):
            wait("Press Enter to close this window. ")
    return rc


def explain_and_wait(out: TextIO = sys.stdout, wait: Callable[[str], str] = input) -> None:
    """Print the fallback explanation and hold the window open until Enter."""
    out.write(DOUBLE_CLICK_MESSAGE)
    out.flush()
    with contextlib.suppress(EOFError):
        wait("Press Enter to close this window. ")
