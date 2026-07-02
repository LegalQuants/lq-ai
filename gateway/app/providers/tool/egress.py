"""SSRF-guarded outbound egress primitive (ADR 0014 D2).

The gateway-native equivalent of MikeOSS's ``validateRemoteMcpUrl`` /
``guardedFetch``. Every tool-provider adapter MUST validate its outbound URL
through :func:`validate_egress_target` before issuing a request. Enforces:
HTTPS-only; host in the per-provider allowlist; resolved IPs are public
(blocks private/loopback/link-local/CGNAT, defeating DNS-rebind)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class EgressRefused(Exception):
    """Raised when an outbound target violates egress policy."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _resolve_ips(host: str) -> list[str]:
    """Resolve ``host`` to its IP addresses. Wrapped so tests can stub it."""
    infos = socket.getaddrinfo(host, None)
    return [str(info[4][0]) for info in infos]


def _is_public_ip(ip: str) -> bool:
    """True only if ``ip`` is a globally-routable public address. Fails closed:
    private, loopback, link-local, CGNAT (100.64/10), reserved, multicast, and
    unspecified addresses all return False."""
    return ipaddress.ip_address(ip).is_global


def validate_egress_target(url: str, *, allowlist: list[str]) -> None:
    """Validate ``url`` against egress policy. Raise :class:`EgressRefused`.

    Checks, in order: scheme is https; host present; host is in ``allowlist``;
    every resolved IP for the host is public (blocks IP-literal private hosts
    and DNS-rebind of an allowlisted name to a private address)."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise EgressRefused(f"egress must use https, got scheme {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise EgressRefused("egress target has no host")
    if host not in {entry.lower() for entry in allowlist}:
        raise EgressRefused(f"host {host!r} not in provider allowlist")
    for ip in _resolve_ips(host):
        if not _is_public_ip(ip):
            raise EgressRefused(f"host {host!r} resolves to private/blocked address {ip}")


# Headers a caller may never override on an outbound tool request.
_FORBIDDEN_OUTBOUND_HEADERS = frozenset({"host", "x-lq-ai-gateway-key"})


def validate_outbound_headers(headers: dict[str, str]) -> None:
    """Reject caller-supplied Host overrides and smuggled gateway auth."""
    for name in headers:
        if name.lower() in _FORBIDDEN_OUTBOUND_HEADERS:
            raise EgressRefused(f"outbound header {name!r} is not allowed")
