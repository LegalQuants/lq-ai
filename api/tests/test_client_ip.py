"""Tests for trusted-proxy-aware client IP resolution.

Pen-test 2026-09-25 finding deploy (HIGH): behind the reverse proxy, every
audit/session row recorded the proxy's IP. ``resolve_client_ip`` reads the real
client IP from ``CF-Connecting-IP`` only when the immediate peer is a configured
trusted proxy, and never trusts the spoofable ``X-Forwarded-For``.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.security.client_ip import parse_trusted_proxies, resolve_client_ip


def _request(peer: str | None, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()
    ]
    scope: dict = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (peer, 12345) if peer is not None else None,
    }
    return Request(scope)


@pytest.mark.unit
def test_no_trusted_proxies_returns_peer_and_ignores_header() -> None:
    req = _request("10.0.0.5", {"CF-Connecting-IP": "203.0.113.9"})
    assert resolve_client_ip(req, "") == "10.0.0.5"


@pytest.mark.unit
def test_trusted_peer_uses_cf_connecting_ip() -> None:
    req = _request("172.20.0.3", {"CF-Connecting-IP": "203.0.113.9"})
    assert resolve_client_ip(req, "172.20.0.0/16") == "203.0.113.9"


@pytest.mark.unit
def test_trusted_peer_without_forwarded_header_returns_peer() -> None:
    req = _request("172.20.0.3", {})
    assert resolve_client_ip(req, "172.20.0.0/16") == "172.20.0.3"


@pytest.mark.unit
def test_trusted_peer_with_invalid_forwarded_header_returns_peer() -> None:
    req = _request("172.20.0.3", {"CF-Connecting-IP": "not-an-ip"})
    assert resolve_client_ip(req, "172.20.0.0/16") == "172.20.0.3"


@pytest.mark.unit
def test_untrusted_peer_ignores_forwarded_header() -> None:
    # Peer not in the trusted range: a client-supplied CF-Connecting-IP must
    # NOT be honored (spoofing guard).
    req = _request("198.51.100.7", {"CF-Connecting-IP": "203.0.113.9"})
    assert resolve_client_ip(req, "172.20.0.0/16") == "198.51.100.7"


@pytest.mark.unit
def test_bare_ip_trusted_proxy_entry() -> None:
    req = _request("172.20.0.3", {"CF-Connecting-IP": "203.0.113.9"})
    assert resolve_client_ip(req, "172.20.0.3") == "203.0.113.9"


@pytest.mark.unit
def test_no_client_returns_none() -> None:
    req = _request(None, {"CF-Connecting-IP": "203.0.113.9"})
    assert resolve_client_ip(req, "172.20.0.0/16") is None


@pytest.mark.unit
def test_parse_trusted_proxies_skips_blank_and_invalid() -> None:
    nets = parse_trusted_proxies("172.20.0.0/16, , not-a-cidr, 10.0.0.1")
    # Two valid entries survive; blanks and garbage are dropped.
    assert len(nets) == 2
