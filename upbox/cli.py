"""upbox CLI.

Day 2 wires ``init`` and ``status``. Other commands stay stubbed until their day.
See ``PLAN.md`` for the 14-day build schedule.
"""

from __future__ import annotations

import platform

import typer

from upbox import ca

app = typer.Typer(
    name="upbox",
    help="See, audit, and control what your AI tools send to the cloud.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def init(
    uninstall: bool = typer.Option(
        False,
        "--uninstall",
        help="Remove the upbox CA from every trust store it was installed into.",
    ),
) -> None:
    """Generate and install the local CA into platform trust stores.

    On Linux, installs to system trust (``update-ca-certificates``), NSS
    (``certutil`` if available), and prints ``NODE_EXTRA_CA_CERTS`` hints for
    known Electron apps. On macOS, installs to the System keychain.
    """
    if uninstall:
        ca.uninstall_all()
        return
    ca.install_all()


@app.command()
def start(
    proxy_port: int = typer.Option(8888, help="Proxy port to listen on."),
    dashboard_port: int = typer.Option(8800, help="Dashboard port to listen on."),
) -> None:
    """Start the proxy and dashboard together (supervisor). Blocks until Ctrl+C."""
    from upbox import supervisor

    rc = supervisor.run(proxy_port=proxy_port, dashboard_port=dashboard_port)
    raise typer.Exit(code=rc)


@app.command()
def proxy(
    host: str = typer.Option("127.0.0.1", help="Proxy bind host."),
    port: int = typer.Option(8888, help="Proxy port to listen on."),
) -> None:
    """Run the upbox proxy (mitmproxy + capture addon). Blocks until Ctrl+C."""
    from upbox import proxy as proxy_module

    proxy_module.run(host=host, port=port)


@app.command()
def dashboard(
    host: str = typer.Option("127.0.0.1", help="Dashboard bind host (loopback only)."),
    port: int = typer.Option(8800, help="Dashboard port to listen on."),
) -> None:
    """Run the upbox dashboard (FastAPI on 127.0.0.1). Blocks until Ctrl+C."""
    from upbox.dashboard import app as dashboard_app

    dashboard_app.run(host=host, port=port)


@app.command()
def stop() -> None:
    """Stop the running proxy and dashboard."""
    typer.echo("Not implemented yet.")
    raise typer.Exit(code=1)


@app.command()
def status() -> None:
    """Report CA trust per layer, plus proxy and dashboard liveness.

    Day 2 covers CA layers; proxy and dashboard checks fill in on Days 3 and 5.
    """
    s = ca.get_status()
    system = platform.system()

    typer.echo("CA trust status:")
    typer.echo(f"  Cert generated:        {_yn(s.cert_exists)} ({s.cert_path})")

    if system == "Darwin":
        typer.echo(f"  macOS System keychain: {_yn(s.in_macos_keychain)}")
    elif system == "Linux":
        typer.echo(f"  Linux system trust:    {_yn(s.in_linux_system_trust)}")
        if s.nss_certutil_available is False:
            typer.echo("  Linux NSS:             SKIPPED (install libnss3-tools or nss-tools)")
        else:
            typer.echo(f"  Linux NSS:             {_yn(s.in_linux_nss)}")
    else:
        typer.echo(f"  Platform '{system}' has no automated trust-store check.")

    typer.echo("")
    typer.echo("Proxy + dashboard liveness: coming Days 3 and 5.")

    if s.cert_exists:
        typer.echo("")
        typer.echo(ca.electron_app_hint())


def _yn(value: bool | None) -> str:
    if value is None:
        return "N/A"
    return "YES" if value else "NO"


@app.command()
def export(
    fmt: str = typer.Option("jsonl", "--format", help="jsonl or csv."),
    output: str = typer.Option("-", "-o", help="Output path; - for stdout."),
    since: str = typer.Option("", help="Only rows with ts >= this ISO timestamp."),
    until: str = typer.Option("", help="Only rows with ts <= this ISO timestamp."),
    tool: str = typer.Option("", help="Only rows for this tool name."),
) -> None:
    """Export the audit log to JSON Lines or CSV."""
    import sqlite3
    import sys
    from collections.abc import Iterable
    from pathlib import Path
    from typing import IO

    from upbox.db.store import Store

    if fmt not in {"jsonl", "csv"}:
        typer.echo(f"unknown format: {fmt!r} (expected jsonl or csv)", err=True)
        raise typer.Exit(code=2)

    def _write(sink: IO[str], rows: Iterable[sqlite3.Row]) -> int:
        if fmt == "jsonl":
            return store.export_jsonl(sink, rows)
        return store.export_csv(sink, rows)

    with Store() as store:
        rows = store.query_filtered(
            since=since or None,
            until=until or None,
            tool=tool or None,
        )
        if output == "-":
            written = _write(sys.stdout, rows)
        else:
            with Path(output).open("w", encoding="utf-8") as sink:
                written = _write(sink, rows)
            typer.echo(f"wrote {written} rows to {output}")
