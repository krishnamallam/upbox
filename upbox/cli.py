"""upbox CLI.

Day 1 ships stubs only — each command exits non-zero with a pointer to the
day it lands. See ``PLAN.md`` for the 14-day build schedule.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="upbox",
    help="See, audit, and control what your AI tools send to the cloud.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def init() -> None:
    """Generate and install the local CA into the system trust store."""
    typer.echo("Not implemented yet — coming in Day 2 (Local CA).")
    raise typer.Exit(code=1)


@app.command()
def start(
    proxy_port: int = typer.Option(8888, help="Proxy port to listen on."),
    dashboard_port: int = typer.Option(8800, help="Dashboard port to listen on."),
) -> None:
    """Start the proxy and dashboard."""
    typer.echo("Not implemented yet — coming in Day 3 (capture) and Day 5 (dashboard).")
    typer.echo(f"  Planned proxy:     http://127.0.0.1:{proxy_port}")
    typer.echo(f"  Planned dashboard: http://127.0.0.1:{dashboard_port}")
    raise typer.Exit(code=1)


@app.command()
def stop() -> None:
    """Stop the running proxy and dashboard."""
    typer.echo("Not implemented yet.")
    raise typer.Exit(code=1)


@app.command()
def status() -> None:
    """Show whether the proxy is running and how many requests it has captured."""
    typer.echo("Not implemented yet.")
    raise typer.Exit(code=1)


@app.command()
def export(
    fmt: str = typer.Option("jsonl", "--format", help="jsonl or csv."),
    output: str = typer.Option("-", "-o", help="Output path (- for stdout)."),
) -> None:
    """Export the audit log to JSON Lines or CSV."""
    typer.echo(f"Not implemented yet — coming in Day 11 (export). format={fmt} output={output}")
    raise typer.Exit(code=1)
