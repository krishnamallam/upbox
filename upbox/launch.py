"""What the frozen binary does when a user double-clicks it.

upbox is a command-line tool. On Windows, double-clicking the ``.exe`` opens a
console that prints the help and closes in a blink, which reads as "nothing
happened". When the binary owns its console alone and got no arguments, it
explains the two commands that matter and waits for Enter instead.

Only ``packaging/entry.py`` (the PyInstaller entry point) calls this;
``python -m upbox`` and the PyPI install are unaffected.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable
from typing import TextIO

DOUBLE_CLICK_MESSAGE = """upbox is a command-line tool, so double-clicking it does not start
anything.

Open PowerShell in the folder that holds upbox.exe and run:

    .\\upbox.exe init      one-time: install the local CA
    .\\upbox.exe start     proxy + dashboard at http://127.0.0.1:8800

`start` needs an administrator PowerShell (right-click, Run as administrator)
because OS-level capture installs a network driver. Put upbox.exe somewhere on
your PATH to drop the ".\\" prefix.

Docs: https://github.com/krishnamallam/upbox#quick-start

"""

# Explorer gives a double-clicked program a console of its own, so the only
# processes attached to it are PyInstaller's bootloader and the Python child it
# spawns. A shell that ran the command is attached as well, making three.
_OWNERS_WHEN_DOUBLE_CLICKED = 2


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


def explain_and_wait(out: TextIO = sys.stdout, wait: Callable[[str], str] = input) -> None:
    """Print the double-click explanation and hold the window open until Enter."""
    out.write(DOUBLE_CLICK_MESSAGE)
    out.flush()
    with contextlib.suppress(EOFError):
        wait("Press Enter to close this window. ")
