"""Trusted-proxy-aware client IP resolution.

Behind a reverse proxy (Cloudflare tunnel → cloudflared → Caddy → uvicorn),
``request.client.host`` is the *proxy's* address, not the end user's. Recording
that in audit/session rows makes the actor+IP forensics story void, and any
per-IP control collapses to a single global bucket.

We honor a forwarded client IP **only** when the immediate peer is a configured
trusted proxy, and we read it from ``CF-Connecting-IP`` — the header Cloudflare
sets and overwrites. That guarantee only holds when every request reaching the
trusted proxy came through Cloudflare; behind any other proxy the header is
client-controlled, so ``LQ_AI_TRUSTED_PROXIES`` must stay empty (the repo's
non-Cloudflare proxy recipes also strip the header). ``X-Forwarded-For`` is
deliberately *not* trusted: its left-most entry is client-supplied.
When no trusted proxy is configured (the default), behavior is unchanged: the
immediate peer address.

Pen-test 2026-09-25 finding deploy (HIGH): client IP was always the proxy IP.
"""

from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache

from starlette.requests import Request

log = logging.getLogger(__name__)

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network
_Address = ipaddress.IPv4Address | ipaddress.IPv6Address


@lru_cache(maxsize=8)
def parse_trusted_proxies(raw: str) -> tuple[_Network, ...]:
    """Parse a comma-separated list of trusted-proxy IPs/CIDRs.

    Bare IPs are accepted (treated as /32 or /128). Unparseable entries are
    skipped with a warning rather than raising, so a typo degrades to "don't
    trust" rather than a boot failure. A catch-all network (``0.0.0.0/0`` or
    ``::/0``) is accepted but warned about: it lets any peer set the client IP.
    Cached, since the setting is read on every request.
    """

    networks: list[_Network] = []
    for item in (raw or "").split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            network = ipaddress.ip_network(candidate, strict=False)
        except ValueError:
            log.warning("LQ_AI_TRUSTED_PROXIES: ignoring unparseable entry %r", candidate)
            continue
        if network.prefixlen == 0:
            log.warning(
                "LQ_AI_TRUSTED_PROXIES: %s trusts every peer; any client can set its own IP",
                network,
            )
        networks.append(network)
    return tuple(networks)


def _parse_address(value: str) -> _Address | None:
    """Parse an IP address for use as a client IP; ``None`` if unusable.

    IPv6 zone IDs (``fe80::1%eth0``) are rejected: Postgres ``INET`` cannot
    store them, so accepting one from a header would turn the session/audit
    insert into a 500. IPv4-mapped IPv6 (``::ffff:10.0.0.1``) is unwrapped to
    plain IPv4 so it matches IPv4 trust entries and stores canonically.
    """

    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        if address.scope_id is not None:
            return None
        if address.ipv4_mapped is not None:
            return address.ipv4_mapped
    return address


def resolve_client_ip(request: Request, trusted_proxies_raw: str) -> str | None:
    """Return the best-known client IP for ``request``.

    If the immediate peer is a configured trusted proxy and a valid
    ``CF-Connecting-IP`` header is present, return that (normalized);
    otherwise return the immediate peer address (``request.client.host``), or
    ``None`` when the peer is unknown.
    """

    peer = request.client.host if request.client else None
    if peer is None:
        return None
    networks = parse_trusted_proxies(trusted_proxies_raw or "")
    peer_address = _parse_address(peer)
    if networks and peer_address is not None and any(peer_address in n for n in networks):
        forwarded = request.headers.get("cf-connecting-ip")
        if forwarded:
            forwarded_address = _parse_address(forwarded)
            if forwarded_address is not None:
                return str(forwarded_address)
    return peer


__all__ = ["parse_trusted_proxies", "resolve_client_ip"]
