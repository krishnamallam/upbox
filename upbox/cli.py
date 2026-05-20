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
def run(
    tool: str = typer.Argument(
        None,
        help="AI tool to launch (claude, cursor, code, claude-code, chrome).",
    ),
    host: str = typer.Option("127.0.0.1", help="Proxy host the child should target."),
    port: int = typer.Option(8888, help="Proxy port the child should target."),
    dashboard_port: int = typer.Option(8800, help="Dashboard port (auto-started)."),
    list_tools: bool = typer.Option(False, "--list", "-l", help="List known tools and exit."),
    no_start: bool = typer.Option(
        False, "--no-start", help="Skip auto-starting proxy + dashboard."
    ),
) -> None:
    """Launch an AI tool routed through the upbox proxy.

    Boots `upbox start` (proxy + dashboard) in the background if it isn't
    already running, then spawns the tool with HTTPS_PROXY +
    NODE_EXTRA_CA_CERTS set on the child process only. When the tool exits
    (or you Ctrl+C), the auto-started proxy + dashboard get torn down. If
    they were already running from another terminal, they're left alone.
    """
    import subprocess as _subprocess
    import sys as _sys

    from upbox import launchers

    if list_tools:
        for t in launchers.TOOLS:
            aliases = ", ".join(t.aliases)
            typer.echo(f"  {t.name:16s}  aliases: {aliases}")
        return

    if not tool:
        typer.echo("Missing tool argument. Try `upbox run --list`.", err=True)
        raise typer.Exit(code=1)

    selected = launchers.find_tool(tool)
    if selected is None:
        known = ", ".join(t.name for t in launchers.TOOLS)
        typer.echo(f"Unknown tool: {tool}. Known: {known}", err=True)
        raise typer.Exit(code=1)

    sup_proc: _subprocess.Popen[bytes] | None = None
    proxy_was_running = launchers.is_listening(host, port)
    if not proxy_was_running and not no_start:
        typer.echo(f"upbox: starting proxy on {host}:{port} + dashboard on :{dashboard_port}")
        sup_proc = _subprocess.Popen(
            [
                _sys.executable,
                "-m",
                "upbox",
                "start",
                "--proxy-port",
                str(port),
                "--dashboard-port",
                str(dashboard_port),
            ]
        )
        if not launchers.wait_for_listening(host, port, timeout=20, sentinel=sup_proc):
            typer.echo("upbox: proxy did not start in time", err=True)
            sup_proc.terminate()
            raise typer.Exit(code=3)
        typer.echo(f"upbox: dashboard ready at http://127.0.0.1:{dashboard_port}")
    elif proxy_was_running:
        typer.echo(f"upbox: proxy already running on {host}:{port} — reusing it")

    try:
        rc = launchers.launch(selected, proxy_host=host, proxy_port=port)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        if sup_proc is not None:
            sup_proc.terminate()
        raise typer.Exit(code=2) from exc
    finally:
        if sup_proc is not None:
            typer.echo("upbox: tearing down proxy + dashboard")
            sup_proc.terminate()
            try:
                sup_proc.wait(timeout=5)
            except _subprocess.TimeoutExpired:
                sup_proc.kill()
    raise typer.Exit(code=rc)


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
    elif system == "Windows":
        typer.echo(f"  Windows Root store:    {_yn(s.in_windows_trust)}")
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
            # newline="" is required by the csv module to avoid double line
            # endings on Windows (and is harmless for JSONL).
            with Path(output).open("w", encoding="utf-8", newline="") as sink:
                written = _write(sink, rows)
            typer.echo(f"wrote {written} rows to {output}")
