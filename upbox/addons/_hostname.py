"""Shared hostname resolution for capture + fingerprint addons.

In LocalMode/transparent mode, ``flow.request.host`` is often the raw
destination IP because there's no upstream ``CONNECT`` carrying the
hostname. Both ``capture`` (which records what shows up in the dashboard)
and ``fingerprint`` (which matches ``tools.yaml`` hostnames to tag the
tool) need the actual hostname, not the IP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mitmproxy import http


def resolve_host(flow: http.HTTPFlow) -> str:
    """Best-effort hostname for a captured flow.

    Order: TLS SNI → HTTP ``Host`` header → raw IP. SNI is the most
    reliable for HTTPS; the Host header covers plain HTTP and well-
    behaved HTTPS clients; the IP is the last-resort fallback so the
    field is never empty.
    """
    sni = getattr(flow.client_conn, "sni", None)
    if sni:
        return str(sni)
    pretty = flow.request.pretty_host
    if pretty and pretty != flow.request.host:
        return pretty
    return flow.request.host
