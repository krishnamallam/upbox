"""Entry point for ``python -m upbox``."""

from __future__ import annotations

from upbox.cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
