"""Outbound TLS must not trust eMudhra's emSign ECC Root CA - G3.

In October 2026 the private keys of eight eMudhra intermediate CAs under that
root proved recoverable from their public certificates, so anyone could mint
certificates that chain to it. The gateway's provider, MCP and tool clients
verify with httpx's default context, which loads certifi's bundle; certifi
2026.10.19 removed the root. This fails if a lock brings an older bundle back.
"""

from __future__ import annotations

import ssl

import httpx

DISTRUSTED_ROOT = "emSign ECC Root CA - G3"


def _common_names(context: ssl.SSLContext) -> set[str]:
    names: set[str] = set()
    for cert in context.get_ca_certs():
        subject = cert.get("subject", ())
        if not isinstance(subject, tuple):
            continue
        for rdn in subject:
            for attribute in rdn:
                if isinstance(attribute, tuple) and attribute[0] == "commonName":
                    names.add(str(attribute[1]))
    return names


def test_default_client_trust_excludes_emudhra_root() -> None:
    names = _common_names(httpx.create_ssl_context())
    assert names, "the default context loaded no CA certificates"
    assert DISTRUSTED_ROOT not in names
