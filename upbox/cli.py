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
    capture_spec: str = typer.Option(
        "!__upbox_disabled__",
        "--capture-spec",
        help=(
            "mitmproxy LocalMode intercept spec. Default captures all processes "
            "(via a sentinel exclude). Examples: 'claude.exe,cursor.exe' for "
            "AI tools only; '!firefox,!chrome' to skip browsers. "
            "See mitmproxy local-redirector docs for syntax."
        ),
    ),
    no_allowlist: bool = typer.Option(
        False,
        "--no-allowlist",
        help=(
            "Disable the TLS allowlist (default: ON). Without an allowlist, "
            "every HTTPS host gets MITM'd, which captures more but breaks "
            "pinned-cert apps like Microsoft Login, Teams, and many banks."
        ),
    ),
    allow: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--allow",
        help=(
            "Add a hostname to the TLS allowlist on top of tools.yaml. "
            "Repeatable. Matches the host exactly OR as a subdomain "
            "(e.g., --allow example.com also allows api.example.com)."
        ),
    ),
) -> None:
    """Start the proxy + dashboard with OS-level traffic capture.

    Uses mitmproxy's LocalMode (mitmproxy-rs redirector) to intercept HTTPS
    traffic at the network layer — Wireshark-style. No system-proxy registry
    edits required, no per-app launchers, no "stuck offline" failure mode.

    Requires admin/root on first run (Windows: WinDivert driver install;
    Linux: iptables; macOS: Network Extension approval). After that, the OS
    handles capture transparently and mitmproxy reverts cleanly on exit.
    """
    from upbox import supervisor

    rc = supervisor.run(
        proxy_port=proxy_port,
        dashboard_port=dashboard_port,
        capture_spec=capture_spec,
        use_allowlist=not no_allowlist,
        extra_allow_hosts=tuple(allow or ()),
    )
    raise typer.Exit(code=rc)


@app.command()
def proxy(
    host: str = typer.Option("127.0.0.1", help="Proxy bind host."),
    port: int = typer.Option(8888, help="Proxy port to listen on."),
    capture_spec: str = typer.Option(
        "",
        "--capture-spec",
        help=(
            "mitmproxy LocalMode intercept spec for OS-level capture. Empty "
            "= regular explicit-proxy mode (no OS capture)."
        ),
    ),
    no_allowlist: bool = typer.Option(False, "--no-allowlist"),
    allow: list[str] | None = typer.Option(None, "--allow"),  # noqa: B008
) -> None:
    """Run the upbox proxy (mitmproxy + capture addon). Blocks until Ctrl+C."""
    from upbox import proxy as proxy_module

    proxy_module.run(
        host=host,
        port=port,
        capture_spec=capture_spec or None,
        use_allowlist=not no_allowlist,
        extra_allow_hosts=tuple(allow or ()),
    )


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
