"""Trusted-proxy-aware client IP resolution.

Behind a reverse proxy (Cloudflare tunnel → cloudflared → Caddy → uvicorn),
``request.client.host`` is the *proxy's* address, not the end user's. Recording
that in audit/session rows makes the actor+IP forensics story void, and any
per-IP control collapses to a single global bucket.

We honor a forwarded client IP **only** when the immediate peer is a configured
trusted proxy, and we read it from ``CF-Connecting-IP`` — the header Cloudflare
sets and overwrites, so a client cannot spoof it. ``X-Forwarded-For`` is
deliberately *not* trusted: its left-most entry is client-supplied and
spoofable. When no trusted proxy is configured (the default), behavior is
unchanged: the immediate peer address.

Pen-test 2026-09-25 finding deploy (HIGH): client IP was always the proxy IP.
"""

from __future__ import annotations

import ipaddress

from starlette.requests import Request

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_trusted_proxies(raw: str) -> list[_Network]:
    """Parse a comma-separated list of trusted-proxy IPs/CIDRs.

    Bare IPs are accepted (treated as /32 or /128). Blank and unparseable
    entries are skipped rather than raising, so a typo degrades to
    "don't trust" rather than a boot failure.
    """

    networks: list[_Network] = []
    for item in (raw or "").split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            continue
    return networks


def _peer_is_trusted(peer: str, networks: list[_Network]) -> bool:
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(peer_ip in network for network in networks)


def resolve_client_ip(request: Request, trusted_proxies_raw: str) -> str | None:
    """Return the best-known client IP for ``request``.

    If the immediate peer is a configured trusted proxy and a valid
    ``CF-Connecting-IP`` header is present, return that; otherwise return the
    immediate peer address (``request.client.host``), or ``None`` when the
    peer is unknown.
    """

    peer = request.client.host if request.client else None
    networks = parse_trusted_proxies(trusted_proxies_raw)
    if peer is not None and networks and _peer_is_trusted(peer, networks):
        forwarded = request.headers.get("cf-connecting-ip")
        if forwarded:
            forwarded = forwarded.strip()
            try:
                ipaddress.ip_address(forwarded)
            except ValueError:
                return peer
            return forwarded
    return peer


__all__ = ["parse_trusted_proxies", "resolve_client_ip"]
