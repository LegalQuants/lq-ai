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


@pytest.mark.unit
def test_trusted_peer_rejects_ipv6_zone_id_header() -> None:
    # Postgres INET cannot store a zone ID; honoring one would 500 the
    # session/audit insert. Fall back to the peer instead.
    req = _request("172.20.0.3", {"CF-Connecting-IP": "fe80::1%eth0"})
    assert resolve_client_ip(req, "172.20.0.0/16") == "172.20.0.3"


@pytest.mark.unit
def test_ipv4_mapped_header_is_unwrapped() -> None:
    req = _request("172.20.0.3", {"CF-Connecting-IP": "::ffff:203.0.113.9"})
    assert resolve_client_ip(req, "172.20.0.0/16") == "203.0.113.9"


@pytest.mark.unit
def test_ipv4_mapped_peer_matches_ipv4_trust_entry() -> None:
    # Dual-stack listeners report IPv4 peers as ::ffff:a.b.c.d.
    req = _request("::ffff:172.20.0.3", {"CF-Connecting-IP": "203.0.113.9"})
    assert resolve_client_ip(req, "172.20.0.0/16") == "203.0.113.9"


@pytest.mark.unit
def test_catch_all_trust_entry_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    parse_trusted_proxies.cache_clear()
    with caplog.at_level("WARNING", logger="app.security.client_ip"):
        nets = parse_trusted_proxies("0.0.0.0/0")
    assert len(nets) == 1
    assert "trusts every peer" in caplog.text


@pytest.mark.unit
@pytest.mark.parametrize(
    ("module_name", "ip_index"),
    [
        ("app.api.auth", 1),  # (user_agent, ip_address)
        ("app.audit", 0),  # (ip_address, user_agent, request_id)
    ],
)
def test_client_metadata_helpers_use_trusted_proxy_resolution(
    module_name: str, ip_index: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guards the wiring: both session-row and audit-row metadata helpers must
    # resolve through the trusted-proxy config, not request.client.host.
    import importlib

    from app.config import get_settings

    module = importlib.import_module(module_name)
    monkeypatch.setenv("LQ_AI_TRUSTED_PROXIES", "172.20.0.0/16")
    get_settings.cache_clear()
    try:
        req = _request("172.20.0.3", {"CF-Connecting-IP": "203.0.113.9"})
        metadata = module._client_metadata(req)
        assert metadata[ip_index] == "203.0.113.9"
    finally:
        monkeypatch.delenv("LQ_AI_TRUSTED_PROXIES")
        get_settings.cache_clear()
