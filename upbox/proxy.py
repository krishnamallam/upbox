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


def run(host: str = "127.0.0.1", port: int = 8888) -> None:
    """Boot the proxy. Blocks until interrupted (Ctrl+C)."""
    # mitmproxy logs startup ("HTTP(S) proxy listening at ...") through the
    # standard logging tree, but Python's root logger defaults to WARNING,
    # which filters those records out before they reach mitmproxy's TermLog
    # handler. Without this, `upbox proxy` looks completely dead on Windows
    # until a request flows through.
    logging.getLogger().setLevel(logging.INFO)

    # Immediate ack so the user sees something during CA generation, which
    # on a fresh install takes a second or two.
    print(f"upbox proxy starting on {host}:{port} (Ctrl+C to stop)", flush=True)
    asyncio.run(_run(host, port))


async def _run(host: str, port: int) -> None:
    # Ensure the upbox CA exists, then materialise it in mitmproxy's expected
    # confdir/mitmproxy-ca.pem combined-PEM format so the proxy generates leaf
    # certs that the user's tools (which trust upbox-ca) will accept.
    ca.generate_ca()
    confdir = ca.write_mitmproxy_bundle()

    opts = Options(listen_host=host, listen_port=port, confdir=str(confdir))
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


if __name__ == "__main__":
    run()
