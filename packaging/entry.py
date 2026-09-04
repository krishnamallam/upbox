"""PyInstaller entry point for the one-file upbox binary.

PyInstaller wants a script, not a module, so this is the smallest one that
runs the Typer app. Everything else comes from the ``upbox`` package exactly
as the PyPI install ships it.
"""

from __future__ import annotations

from upbox.cli import app

if __name__ == "__main__":
    app()
