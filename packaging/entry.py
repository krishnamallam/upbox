"""PyInstaller entry point for the one-file upbox binary.

PyInstaller wants a script, not a module, so this is the smallest one that
runs the Typer app. Everything else comes from the ``upbox`` package exactly
as the PyPI install ships it. The one addition: a Windows user who
double-clicks the .exe gets upbox started (administrator prompt, CA consent,
dashboard in the browser) instead of a console that flashes and closes.
"""

from __future__ import annotations

import sys

from upbox.cli import app
from upbox.launch import console_owner_count, launched_by_double_click, run_double_click_flow

if __name__ == "__main__":
    if launched_by_double_click(sys.argv, sys.platform, console_owner_count()):
        sys.exit(run_double_click_flow(sys.executable))
    app()
