"""Egress policy for LLM provider ``base_url``s (#288, GW-04).

The tool path (:mod:`app.providers.tool.egress`) enforces a strict
https-only, host-allowlisted, public-IP egress guard. The LLM provider path
needs a slightly looser but still-safe rule: public providers (Anthropic,
OpenAI, Azure, Vertex, Bedrock) MUST use ``https``, but local providers
(Ollama, vLLM) legitimately speak plaintext ``http`` to a loopback address,
a private network, or one of a few named local targets
(``http://ollama:11434``, ``http://host.docker.internal:11434``).

The named hosts and networks are spelled out as explicit module constants
below rather than derived from :attr:`ipaddress.ip_address.is_global`, so an
operator can see exactly what plaintext egress is permitted without leaving
this file.

Before this guard ``ProviderConfig.base_url`` was validated only as
``min_length=1``, so a misconfiguration or config tampering could point the
crown-jewel prompt-egress path at ``http://attacker.example`` or an internal
address in cleartext — the asymmetry the audit flagged versus the hardened
tool path. This guard is applied at adapter build time so a bad ``base_url``
fails fast at startup.
"""

from __future__ import annotations

import ipaddress
from typing import ClassVar
from urllib.parse import urlparse

from fastapi import status

from app.errors import CODE_PROVIDER_UNAVAILABLE, LQAIError


class ProviderEgressRefused(LQAIError):
    """Raised when a provider ``base_url`` violates LLM egress policy.

    Typed per CONTRIBUTING (subsystem errors derive from :class:`LQAIError`,
    not bare ``Exception``) so a refusal reaching a request path renders the
    canonical envelope instead of an unhandled 500. It reuses the existing
    ``provider_unavailable`` code rather than introducing a new wire code:
    from a caller's point of view a provider whose ``base_url`` is refused has
    no usable adapter, which is exactly what that code already means.

    Startup behaviour is unchanged — ``lifespan`` runs outside the exception
    handler, so a refusal there still aborts the gateway, which is the
    intended fail-closed posture.
    """

    code: ClassVar[str] = CODE_PROVIDER_UNAVAILABLE
    http_status: ClassVar[int] = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Hostnames permitted as plaintext ``http`` targets. Every local-inference
# host the project documents is here: ``ollama`` is the Compose service
# (docker-compose.yml), ``vllm`` is the disabled-by-default service in
# gateway.yaml.example, and ``host.docker.internal`` is the host bridge that
# .env.example ships as the default OLLAMA_BASE_URL (the release Compose file
# has no ollama service, so that is the release path). Add a name here rather
# than loosening the rule.
_LOCAL_HOSTS = frozenset({"localhost", "host.docker.internal", "ollama", "vllm"})

# Networks permitted as plaintext ``http`` targets: loopback, RFC1918 private
# space, and IPv6 unique-local. Deliberately narrower than "not is_global" —
# link-local (169.254.0.0/16, which carries the cloud metadata endpoint),
# CGNAT (100.64.0.0/10) and 0.0.0.0 are NOT local inference targets and must
# not receive prompts in cleartext.
_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",
        "::1/128",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",
    )
)


def _is_local_host(host: str) -> bool:
    """True when plaintext ``http`` egress to ``host`` is acceptable.

    Acceptable local targets: a name in :data:`_LOCAL_HOSTS`, or an IP literal
    inside one of :data:`_LOCAL_NETWORKS`. Anything else — a public FQDN such
    as ``api.openai.com``, an unlisted service name, or a routable IP — is
    treated as public and must use ``https``.
    """
    if host.lower() in _LOCAL_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP literal and not an allowlisted name.
        return False
    # A v4 address is never "in" a v6 network (and vice versa); CPython returns
    # False on a version mismatch rather than raising, so no version guard.
    return any(ip in network for network in _LOCAL_NETWORKS)


def validate_llm_base_url(base_url: str) -> None:
    """Validate an LLM provider ``base_url`` against egress policy.

    ``https`` is always allowed; ``http`` is allowed only to a host in
    :data:`_LOCAL_HOSTS` or an IP inside :data:`_LOCAL_NETWORKS`. Any other
    scheme, a missing host, or plaintext ``http`` to a public host raises
    :class:`ProviderEgressRefused`.
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise ProviderEgressRefused(
            f"provider base_url must use http or https, got scheme {parsed.scheme!r}"
        )
    host = parsed.hostname
    if not host:
        raise ProviderEgressRefused("provider base_url has no host")
    if parsed.scheme == "http" and not _is_local_host(host):
        allowed = ", ".join(sorted(_LOCAL_HOSTS))
        raise ProviderEgressRefused(
            f"plaintext http base_url is only permitted for local providers ({allowed}, "
            f"or a loopback/private IP); host {host!r} must use https"
        )
