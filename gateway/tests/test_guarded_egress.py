import pytest

from app.providers.tool.egress import EgressRefused, validate_egress_target


@pytest.mark.unit
def test_rejects_non_https() -> None:
    with pytest.raises(EgressRefused, match="https"):
        validate_egress_target("http://example.test/x", allowlist=["example.test"])


@pytest.mark.unit
def test_rejects_host_not_in_allowlist() -> None:
    with pytest.raises(EgressRefused, match="allowlist"):
        validate_egress_target("https://evil.test/x", allowlist=["example.test"])


@pytest.mark.unit
def test_rejects_private_ip_literal_host() -> None:
    with pytest.raises(EgressRefused, match="private"):
        validate_egress_target("https://127.0.0.1/x", allowlist=["127.0.0.1"])


@pytest.mark.unit
def test_rejects_link_local_and_metadata_ip() -> None:
    with pytest.raises(EgressRefused, match="private"):
        validate_egress_target("https://169.254.169.254/latest", allowlist=["169.254.169.254"])


@pytest.mark.unit
def test_allows_public_host_in_allowlist(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips",
        lambda host: ["93.184.216.34"],
    )
    validate_egress_target("https://example.test/x", allowlist=["example.test"])


@pytest.mark.unit
def test_rejects_dns_rebind_to_private(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips",
        lambda host: ["10.0.0.5"],
    )
    with pytest.raises(EgressRefused, match="private"):
        validate_egress_target("https://example.test/x", allowlist=["example.test"])


@pytest.mark.unit
def test_rejects_cgnat_address(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips",
        lambda host: ["100.64.0.1"],  # RFC 6598 CGNAT — not globally routable
    )
    with pytest.raises(EgressRefused, match="private"):
        validate_egress_target("https://example.test/x", allowlist=["example.test"])


@pytest.mark.unit
def test_allowlist_match_is_case_insensitive(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips",
        lambda host: ["93.184.216.34"],
    )
    # Allowlist entry is upper-case; urlparse lowercases the URL host.
    validate_egress_target("https://example.test/x", allowlist=["EXAMPLE.TEST"])  # no raise


@pytest.mark.unit
def test_rejects_host_header_override() -> None:
    from app.providers.tool.egress import validate_outbound_headers

    with pytest.raises(EgressRefused, match="Host"):
        validate_outbound_headers({"Host": "evil.test"})
