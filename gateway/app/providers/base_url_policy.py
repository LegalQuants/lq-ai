"""Egress policy for LLM provider ``base_url``s (#288, GW-04).

The tool path (:mod:`app.providers.tool.egress`) enforces a strict
https-only, host-allowlisted, public-IP egress guard. The LLM provider path
needs a slightly looser but still-safe rule: public providers (Anthropic,
OpenAI, Azure, Vertex, Bedrock) MUST use ``https``, but local providers
(Ollama, vLLM) legitimately speak plaintext ``http`` to a loopback address
or a compose service name (``http://ollama:11434``, ``http://vllm:8000/v1``).

Before this guard ``ProviderConfig.base_url`` was validated only as
``min_length=1``, so a misconfiguration or config tampering could point the
crown-jewel prompt-egress path at ``http://attacker.example`` or an internal
address in cleartext — the asymmetry the audit flagged versus the hardened
tool path. This guard is applied at adapter build time so a bad ``base_url``
fails fast at startup.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class ProviderEgressRefused(Exception):
    """Raised when a provider ``base_url`` violates LLM egress policy."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _is_local_host(host: str) -> bool:
    """True when plaintext ``http`` egress to ``host`` is acceptable.

    Acceptable local targets: a loopback/private/link-local/CGNAT IP literal,
    ``localhost``, or a single-label hostname (no dot) — i.e. a container /
    compose service name such as ``ollama`` or ``vllm`` that is not a routable
    public host. A dotted FQDN (``api.openai.com``) is treated as public.
    """
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP literal: a single-label name is a private service name;
        # a dotted (or IPv6-bracketed) name is a public FQDN.
        return "." not in host and ":" not in host
    return not ip.is_global


def validate_llm_base_url(base_url: str) -> None:
    """Validate an LLM provider ``base_url`` against egress policy.

    ``https`` is always allowed; ``http`` is allowed only to a local host
    (Ollama/vLLM). Any other scheme, a missing host, or plaintext ``http`` to
    a public host raises :class:`ProviderEgressRefused`.
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
        raise ProviderEgressRefused(
            "plaintext http base_url is only permitted for local providers "
            f"(loopback/private/service name); public host {host!r} must use https"
        )
