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
        "",
        "--capture-spec",
        help=(
            "Override the curated AI-tool process list with a custom "
            "mitmproxy LocalMode intercept spec. Examples: "
            "'claude.exe,cursor.exe' for those processes only; "
            "'!firefox,!chrome' to skip browsers. "
            "See mitmproxy local-redirector docs for syntax. "
            "Mutually exclusive with --capture-all."
        ),
    ),
    capture_all: bool = typer.Option(
        False,
        "--capture-all",
        help=(
            "Capture every process system-wide. WARNING: this redirects "
            "all TCP traffic — including VPN clients (openvpn, wg-quick, "
            "tailscaled, nordvpnd, mullvad-daemon, protonvpn). Most VPN "
            "tunnels will drop. Use only if you know what you're doing."
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

    By default, captures the curated list of AI-tool processes in
    ``upbox.proxy.DEFAULT_CAPTURE_PROCESSES`` (Claude, Cursor, ChatGPT,
    common browsers for web AI, etc.). VPN clients and unrelated apps
    are not redirected, so tunnels stay up.

    Uses mitmproxy's LocalMode (mitmproxy-rs redirector) to intercept
    HTTPS traffic at the network layer — Wireshark-style. Requires
    admin/root on first run (Windows: WinDivert driver install; Linux:
    iptables; macOS: Network Extension approval). After that, the OS
    handles capture transparently and mitmproxy reverts cleanly on exit.

    Use ``--capture-spec`` to override the default list, or
    ``--capture-all`` to capture every process (the pre-v0.1.1 default,
    which can disconnect VPNs).
    """
    from upbox import proxy as proxy_module
    from upbox import supervisor

    if capture_spec and capture_all:
        typer.echo(
            "error: --capture-spec and --capture-all are mutually exclusive.",
            err=True,
        )
        raise typer.Exit(code=2)

    if capture_all:
        spec = proxy_module.CAPTURE_ALL_SENTINEL
    elif capture_spec:
        spec = capture_spec
    else:
        spec = proxy_module.default_capture_spec()

    rc = supervisor.run(
        proxy_port=proxy_port,
        dashboard_port=dashboard_port,
        capture_spec=spec,
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
def verify() -> None:
    """Recompute the audit-log hash chain and report whether it holds.

    Exit code 0 if the chain verifies (or is empty), 1 if it is broken.
    """
    from upbox.db.store import Store

    with Store() as store:
        result = store.verify_chain()

    if result.status == "empty":
        typer.echo("Chain is empty: no requests captured since the chain was introduced.")
    elif result.status == "ok":
        typer.echo(f"Chain OK: {result.checked} entries, seq {result.first_seq}-{result.last_seq}.")
    else:
        where = f" at seq {result.broken_at}" if result.broken_at is not None else ""
        typer.echo(f"Chain BROKEN{where}: {result.detail}", err=True)
        typer.echo(f"Verified {result.checked} entries before the break.", err=True)

    if result.unchained:
        typer.echo(
            f"{result.unchained} row(s) predate the chain and are not covered by it. "
            "They were never backfilled on purpose."
        )
    if result.entries_deleted:
        typer.echo(
            f"{result.entries_deleted} entry/entries were deleted by retention. The chain "
            "resumes across the recorded gap, but says nothing about what was removed."
        )
    if result.content_unavailable:
        typer.echo(
            f"{result.content_unavailable} stored body/header value(s) were cleared by "
            "retention. Their digests still verify; the content cannot be re-checked."
        )

    typer.echo(f"Head: {result.head_hash}")
    if result.status != "broken":
        typer.echo(
            "This proves the log is internally consistent, not that it is complete. "
            "Record the head hash somewhere off this machine so truncation is detectable."
        )
        return
    raise typer.Exit(code=1)


@app.command()
def doctor() -> None:
    """Report at-rest protection for the audit database, and chain health.

    upbox does not encrypt its own database. This tells you whether the thing
    that actually protects it, full-disk encryption, is switched on.
    """
    from upbox.atrest import (
        DIR_MODE,
        FILE_MODE,
        harden_path_permissions,
        path_mode,
        volume_encryption_status,
    )
    from upbox.db.store import DEFAULT_DB_PATH, Store

    db = DEFAULT_DB_PATH
    typer.echo(f"Database: {db}")
    typer.echo(f"  Exists:               {_yn(db.exists())}")

    # Tighten before reporting, or the report shows modes it is about to fix
    # itself when it opens the store below.
    harden_path_permissions(db)
    dir_mode = path_mode(db.parent)
    file_mode = path_mode(db) if db.exists() else "n/a"
    typer.echo(f"  Directory mode:       {dir_mode} (want {DIR_MODE:04o})")
    typer.echo(f"  Database mode:        {file_mode} (want {FILE_MODE:04o})")

    encryption = volume_encryption_status(db.parent)
    typer.echo("")
    typer.echo("At rest:")
    typer.echo(f"  Volume encryption:    {encryption.state.upper()} ({encryption.detail})")
    typer.echo("  upbox in-app crypto:  NONE, by design (see the At rest section of the README)")
    if encryption.is_encrypted is False:
        typer.echo(
            "  ACTION: the audit log contains prompt bodies. Turn on full-disk encryption.",
        )

    if db.exists():
        with Store(db, read_only=True) as store:
            result = store.verify_chain()
        typer.echo("")
        typer.echo("Audit log:")
        typer.echo(f"  Chain:                {result.status.upper()}")
        typer.echo(f"  Entries verified:     {result.checked}")
        typer.echo(f"  Head:                 {result.head_hash}")


@app.command()
def prune(
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would go, change nothing."),
) -> None:
    """Apply the retention policy from ~/.upbox/rules/retention.yaml."""
    from upbox.db.store import Store
    from upbox.retention import load_policy

    policy = load_policy()
    typer.echo(
        f"Policy: body_days={policy.body_days}, record_days={policy.record_days}"
        f" (min_record_days={policy.min_record_days})"
    )
    for note in policy.warnings():
        typer.echo(f"warning: {note}", err=True)

    if dry_run:
        with Store() as store:
            preview = store.preview_prune(policy)
        typer.echo(f"Would clear bodies on {preview.bodies_cleared} row(s).")
        if preview.records_deleted:
            typer.echo(
                f"Would delete {preview.records_deleted} row(s)"
                + (
                    f", chained seq {preview.gap_seq_start}-{preview.gap_seq_end}"
                    if preview.gap_seq_start is not None
                    else ""
                )
                + "."
            )
        typer.echo("--dry-run: nothing was changed.")
        return

    with Store() as store:
        result = store.prune(policy)
        typer.echo(f"Cleared bodies on {result.bodies_cleared} row(s).")
        if result.records_deleted:
            typer.echo(
                f"Deleted {result.records_deleted} row(s), seq "
                f"{result.gap_seq_start}-{result.gap_seq_end}. Recorded as a chain gap so "
                "verification reports it as a retention deletion, not tampering."
            )
        row = store.write_checkpoint("prune")
        typer.echo(f"Head after prune: {row['head_hash']}")


@app.command()
def hold(
    since: str = typer.Option("", help="Hold rows with ts >= this ISO timestamp."),
    until: str = typer.Option("", help="Hold rows with ts <= this ISO timestamp."),
    release: bool = typer.Option(False, "--release", help="Lift the hold instead of setting it."),
) -> None:
    """Exempt a time range from retention, for a live dispute or investigation."""
    from upbox.db.store import Store

    # Bounds are compared as strings against stored ISO timestamps, so a
    # date-only bound like "2026-07-01" silently excludes every row from that
    # same day (their "2026-07-01T09:00:00" sorts after it). Normalise instead
    # of holding the wrong rows in a dispute.
    since_ts = _normalise_bound(since, end_of_day=False)
    until_ts = _normalise_bound(until, end_of_day=True)

    with Store() as store:
        affected = store.set_legal_hold(since_ts, until_ts, held=not release)
    verb = "released" if release else "held"
    typer.echo(f"{verb} {affected} row(s).")


def _normalise_bound(value: str, *, end_of_day: bool) -> str | None:
    """Validate an ISO timestamp bound, widening a bare date to cover the day."""
    if not value:
        return None
    from datetime import date, datetime

    try:
        datetime.fromisoformat(value)
    except ValueError:
        try:
            date.fromisoformat(value)
        except ValueError:
            typer.echo(f"not an ISO date or timestamp: {value!r}", err=True)
            raise typer.Exit(code=2) from None
        return f"{value}T23:59:59.999999" if end_of_day else f"{value}T00:00:00"
    return value


@app.command()
def checkpoint(
    reason: str = typer.Option("manual", help="Why this checkpoint was taken."),
    output: str = typer.Option("", "-o", help="Also write the head hash to this file."),
) -> None:
    """Seal the current chain head so later truncation becomes detectable."""
    from pathlib import Path

    from upbox.db.store import Store

    with Store() as store:
        row = store.write_checkpoint(reason)

    typer.echo(f"Checkpoint {row['id']} at seq {row['seq_end']} ({row['entry_count']} entries)")
    typer.echo(f"Head: {row['head_hash']}")
    if output:
        Path(output).write_text(f"{row['ts']} seq={row['seq_end']} {row['head_hash']}\n")
        typer.echo(f"wrote {output}")
    typer.echo(
        "A checkpoint only proves anything once this hash has left the machine. "
        "Mail it to yourself, commit it, or have it timestamped."
    )


@app.command()
def export(
    fmt: str = typer.Option("jsonl", "--format", help="audit, jsonl, or csv."),
    output: str = typer.Option("-", "-o", help="Output path; - for stdout."),
    since: str = typer.Option("", help="Only rows with ts >= this ISO timestamp."),
    until: str = typer.Option("", help="Only rows with ts <= this ISO timestamp."),
    tool: str = typer.Option("", help="Only rows for this tool name."),
) -> None:
    """Export the audit log.

    ``audit`` writes upbox.audit.v1: newline-delimited JSON carrying the ruleset
    digests, the hash-chain verification result, and an explicit coverage
    statement, so the file stands on its own. ``jsonl`` and ``csv`` are the flat
    v0.1 dumps, kept for spreadsheets and existing scripts.
    """
    import sqlite3
    import sys
    from collections.abc import Iterable
    from pathlib import Path
    from typing import IO

    from upbox.audit_export import write_audit_v1
    from upbox.db.store import Store

    if fmt not in {"audit", "jsonl", "csv"}:
        typer.echo(f"unknown format: {fmt!r} (expected audit, jsonl, or csv)", err=True)
        raise typer.Exit(code=2)

    def _write(sink: IO[str], rows: Iterable[sqlite3.Row]) -> int:
        if fmt == "audit":
            return write_audit_v1(
                store, sink, since=since or None, until=until or None, tool=tool or None
            )
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
