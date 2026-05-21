"""`upbox proxy` entry point — runs mitmproxy as the main process.

Per ``PLAN.md``'s process architecture this is one of two cooperating
processes. The dashboard ships separately on Day 5; the supervisor that
spawns both lands on Day 5 too. For Day 3, ``upbox proxy`` runs standalone
and writes to ``~/.upbox/upbox.db``; the dashboard reads from the same
file.
"""

from __future__ import annotations

import asyncio
import logging

from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from upbox import ca
from upbox.addons.capture import CaptureAddon
from upbox.addons.enforce import EnforceAddon
from upbox.addons.fingerprint import FingerprintAddon
from upbox.addons.redact import RedactAddon
from upbox.db.store import Store

# Curated AI-tool process list for `upbox start`'s default LocalMode spec.
# Captures only the binaries that produce AI traffic so unrelated processes —
# especially VPN clients (openvpn, wg-quick, tailscaled, nordvpnd, mullvad,
# protonvpn) — are not redirected through mitmproxy. Names are matched as
# exe basenames, so per-OS variants are listed explicitly.
#
# To capture everything (the pre-fix behavior) use `upbox start --capture-all`.
# To override with your own list use `upbox start --capture-spec "..."`.
DEFAULT_CAPTURE_PROCESSES: tuple[str, ...] = (
    # Desktop AI clients
    "Claude",
    "Claude.exe",
    "ChatGPT",
    "ChatGPT.exe",
    # AI-first editors
    "Cursor",
    "Cursor.exe",
    "Windsurf",
    "Windsurf.exe",
    # CLI AI tools
    "claude",
    "claude.cmd",
    "codex",
    "codex.cmd",
    "ollama",
    "ollama.exe",
    "gh",
    "gh.exe",
    # General-purpose editors that host AI extensions (Copilot, Cody, Continue)
    "code",
    "code.exe",
    "Code.exe",
    "code-insiders",
    # Browsers — needed for web AI (chatgpt.com, claude.ai, gemini.google.com).
    # The TLS allowlist from tools.yaml means non-AI sites pass through as a
    # CONNECT tunnel without decryption, so banking and work apps stay intact.
    "firefox",
    "Firefox",
    "firefox.exe",
    "chrome",
    "chrome.exe",
    "chromium",
    "Chromium",
    "chromium.exe",
    "brave",
    "brave.exe",
    "msedge",
    "msedge.exe",
    "Safari",
    "Arc",
)

# Sentinel handed to mitmproxy when the user passes --capture-all. The name
# never matches a real process, so the "exclude" rule is a no-op and every
# other process gets captured.
CAPTURE_ALL_SENTINEL = "!__upbox_disabled__"


def default_capture_spec() -> str:
    """Return the mitmproxy LocalMode spec for the curated AI-tool process list."""
    return ",".join(DEFAULT_CAPTURE_PROCESSES)


def run(
    host: str = "127.0.0.1",
    port: int = 8888,
    capture_spec: str | None = None,
    use_allowlist: bool = True,
    extra_allow_hosts: tuple[str, ...] = (),
) -> None:
    """Boot the proxy. Blocks until interrupted (Ctrl+C).

    If ``capture_spec`` is set, mitmproxy runs in LocalMode (the OS-level
    traffic redirector from ``mitmproxy-rs``). The spec is a comma-
    separated process filter — e.g. ``"!firefox"`` to capture everything
    except Firefox, or ``"claude.exe,cursor.exe"`` to only capture those.
    The sentinel value ``"!__upbox_disabled__"`` captures all processes
    (sentinel name never matches a real process, so the "exclude" rule
    becomes a no-op and everything else flows through).

    LocalMode requires admin/root: WinDivert driver on Windows, iptables
    on Linux, Network Extension approval on macOS. If ``capture_spec`` is
    ``None``, the proxy runs in regular explicit-proxy mode (clients must
    set HTTPS_PROXY themselves).
    """
    # mitmproxy logs startup ("HTTP(S) proxy listening at ...") through the
    # standard logging tree, but Python's root logger defaults to WARNING,
    # which filters those records out before they reach mitmproxy's TermLog
    # handler. Without this, `upbox proxy` looks completely dead on Windows
    # until a request flows through.
    logging.getLogger().setLevel(logging.INFO)

    # Immediate ack so the user sees something during CA generation, which
    # on a fresh install takes a second or two.
    print(f"upbox proxy starting on {host}:{port} (Ctrl+C to stop)", flush=True)
    asyncio.run(_run(host, port, capture_spec, use_allowlist, extra_allow_hosts))


async def _run(
    host: str,
    port: int,
    capture_spec: str | None,
    use_allowlist: bool = True,
    extra_allow_hosts: tuple[str, ...] = (),
) -> None:
    # Ensure the upbox CA exists, then materialise it in mitmproxy's expected
    # confdir/mitmproxy-ca.pem combined-PEM format so the proxy generates leaf
    # certs that the user's tools (which trust upbox-ca) will accept.
    ca.generate_ca()
    confdir = ca.write_mitmproxy_bundle()

    if capture_spec:
        _check_local_mode_available()
        mode = [f"local:{capture_spec}"]
    else:
        mode = ["regular"]

    opt_kwargs: dict[str, object] = {
        "listen_host": host,
        "listen_port": port,
        "confdir": str(confdir),
        "mode": mode,
    }
    if use_allowlist:
        # Derive the TLS allowlist from tools.yaml. Pinned-cert apps
        # (login.live.com, Teams, banking) and OS noise pass through
        # untouched; only AI-tool traffic gets intercepted + audited.
        from upbox.addons.fingerprint import load_allowed_host_patterns

        patterns = load_allowed_host_patterns(extra_allow_hosts)
        if patterns:
            opt_kwargs["allow_hosts"] = patterns
            print(
                f"upbox: TLS allowlist active ({len(patterns)} host patterns from "
                "tools.yaml). Non-AI traffic passes through without inspection.",
                flush=True,
            )

    opts = Options(**opt_kwargs)
    master = DumpMaster(opts)

    store = Store()
    # Order matters: fingerprint tags the tool, enforce checks the destination
    # (and may short-circuit with a 403), redact rewrites the body, then
    # capture (response hook) persists the final state including
    # block/redaction metadata.
    master.addons.add(  # type: ignore[no-untyped-call]
        FingerprintAddon(),
        EnforceAddon(),
        RedactAddon(),
        CaptureAddon(store),
    )

    try:
        await master.run()
    finally:
        store.close()


def _check_local_mode_available() -> None:
    """Fail fast with a useful message if LocalMode isn't usable here."""
    from mitmproxy_rs.local import LocalRedirector

    reason = LocalRedirector.unavailable_reason()
    if reason:
        raise RuntimeError(
            f"OS-level capture (LocalMode) is unavailable: {reason}. "
            "Re-run `upbox start` with admin/root, or pass --capture-spec '' "
            "to fall back to regular explicit-proxy mode."
        )


if __name__ == "__main__":
    run()
