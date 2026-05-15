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
from upbox.addons.fingerprint import FingerprintAddon
from upbox.db.store import Store

log = logging.getLogger(__name__)


def run(host: str = "127.0.0.1", port: int = 8888) -> None:
    """Boot the proxy. Blocks until interrupted (Ctrl+C)."""
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
    # Fingerprint runs on the request hook so capture (response hook) sees the tag.
    master.addons.add(FingerprintAddon(), CaptureAddon(store))  # type: ignore[no-untyped-call]

    log.info("upbox proxy listening on %s:%d", host, port)
    try:
        await master.run()
    finally:
        store.close()


if __name__ == "__main__":
    run()
