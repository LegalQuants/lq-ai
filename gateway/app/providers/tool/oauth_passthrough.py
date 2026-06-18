"""Egress-guarded OAuth passthrough primitives (PR4c, ADR-0014-pure D-c6).

100% of third-party OAuth egress stays at the one audited gateway boundary.
The api drives the OAuth flow but does NOT make the discovery / token HTTP
calls itself — it asks the gateway to make them. These two coroutines are the
only place the gateway speaks to an MCP server's OAuth discovery surface and
its authorization-server ``token_endpoint``.

Security invariants (mirror ``app.providers.tool.mcp``):

* EVERY outbound URL passes :func:`validate_egress_target` BEFORE the request
  (https-only + host-in-allowlist + public-IP anti-SSRF/DNS-rebind). The AS
  host is discovered at runtime and may differ from the MCP server host, so
  the operator must have allowlisted it; an un-allowlisted host is refused.
* NO credential ever appears in a raised exception message. The token form
  carries the user's ``code`` / ``refresh_token`` / ``code_verifier`` /
  ``client_id``; the AS response carries ``access_token`` / ``refresh_token``.
  None of these is echoed into an error, a log line, or an audit row.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.providers.tool.egress import validate_egress_target

# Discovery metadata documents are tiny; a short timeout keeps a hung AS from
# pinning a gateway worker. The token exchange gets a little more headroom.
_DISCOVER_TIMEOUT = httpx.Timeout(10.0)
_TOKEN_TIMEOUT = httpx.Timeout(15.0)

_PRM_SUFFIX = "/.well-known/oauth-protected-resource"
_AS_METADATA_SUFFIX = "/.well-known/oauth-authorization-server"
_OIDC_METADATA_SUFFIX = "/.well-known/openid-configuration"


class OAuthPassthroughError(Exception):
    """A discovery / token egress failed for a non-policy reason.

    Network failure, non-2xx discovery response, or an unparseable body. The
    message is deliberately generic — it NEVER carries the request form, the
    AS response body, or any token value, so it is safe to surface in an HTTP
    error envelope and safe to log.
    """


def _base(url: str) -> str:
    """Right-strip a single trailing slash so suffix joins don't double up."""
    return url.rstrip("/")


async def discover_oauth_metadata(*, server_url: str, allowlist: list[str]) -> dict[str, Any]:
    """Perform MCP OAuth discovery and return the merged metadata.

    RFC 9728 (protected-resource-metadata) → RFC 8414
    (authorization-server-metadata) with an OIDC ``openid-configuration``
    fallback. Each GET is preceded by :func:`validate_egress_target`.

    Returns a dict with ``authorization_endpoint``, ``token_endpoint``,
    ``issuer``, ``resource``, ``scopes_supported`` and
    ``authorization_response_iss_parameter_supported``. Lets
    :class:`~app.providers.tool.egress.EgressRefused` propagate on a guard
    failure; raises :class:`OAuthPassthroughError` (no creds) otherwise.
    """
    prm_url = _base(server_url) + _PRM_SUFFIX
    validate_egress_target(prm_url, allowlist=allowlist)

    async with httpx.AsyncClient(timeout=_DISCOVER_TIMEOUT) as client:
        prm = await _get_json(client, prm_url, what="protected-resource metadata")

        authorization_servers = prm.get("authorization_servers")
        if not isinstance(authorization_servers, list) or not authorization_servers:
            raise OAuthPassthroughError("protected-resource metadata missing authorization_servers")
        as_issuer = authorization_servers[0]
        if not isinstance(as_issuer, str) or not as_issuer:
            raise OAuthPassthroughError(
                "protected-resource metadata authorization_servers[0] is not a string"
            )

        resource = prm.get("resource")
        prm_scopes = prm.get("scopes_supported")

        as_base = _base(as_issuer)
        as_metadata_url = as_base + _AS_METADATA_SUFFIX
        validate_egress_target(as_metadata_url, allowlist=allowlist)
        as_meta = await _get_json_allow_404(
            client,
            as_metadata_url,
            what="authorization-server metadata",
        )
        if as_meta is None:
            # RFC 8414 404 → OIDC fallback.
            oidc_url = as_base + _OIDC_METADATA_SUFFIX
            validate_egress_target(oidc_url, allowlist=allowlist)
            as_meta = await _get_json(client, oidc_url, what="openid-configuration")

    authorization_endpoint = as_meta.get("authorization_endpoint")
    token_endpoint = as_meta.get("token_endpoint")
    if not isinstance(authorization_endpoint, str) or not authorization_endpoint:
        raise OAuthPassthroughError("authorization-server metadata missing authorization_endpoint")
    if not isinstance(token_endpoint, str) or not token_endpoint:
        raise OAuthPassthroughError("authorization-server metadata missing token_endpoint")

    issuer = as_meta.get("issuer", as_issuer)
    scopes_supported = as_meta.get("scopes_supported", prm_scopes)
    iss_param_supported = bool(as_meta.get("authorization_response_iss_parameter_supported", False))

    return {
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "issuer": issuer,
        "resource": resource,
        "scopes_supported": scopes_supported,
        "authorization_response_iss_parameter_supported": iss_param_supported,
    }


async def exchange_oauth_token(
    *, token_endpoint: str, form: dict[str, str], allowlist: list[str]
) -> tuple[int, dict[str, Any]]:
    """POST ``form`` to the AS ``token_endpoint`` and relay its response.

    Used for BOTH the ``authorization_code`` and ``refresh_token`` grants. The
    URL passes :func:`validate_egress_target` first. The AS status and JSON
    body are returned VERBATIM for any HTTP status (a 2xx token response OR a
    4xx OAuth error like ``invalid_grant`` — the api/authlib parses both).

    Lets :class:`~app.providers.tool.egress.EgressRefused` propagate on a guard
    failure; raises :class:`OAuthPassthroughError` (no form contents in the
    message) if the AS is unreachable or returns a non-JSON body.
    """
    validate_egress_target(token_endpoint, allowlist=allowlist)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT) as client:
            response = await client.post(token_endpoint, data=form, headers=headers)
    except httpx.HTTPError as exc:
        # Surface the failure CLASS only — never the form or the AS reply.
        raise OAuthPassthroughError(f"token endpoint unreachable: {type(exc).__name__}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise OAuthPassthroughError("token endpoint returned a non-JSON response") from exc
    if not isinstance(body, dict):
        raise OAuthPassthroughError("token endpoint returned a non-object JSON response")

    return response.status_code, body


async def _get_json_allow_404(
    client: httpx.AsyncClient, url: str, *, what: str
) -> dict[str, Any] | None:
    """As :func:`_get_json`, but a 404 returns ``None`` (OIDC fallback signal)."""
    response = await _get(client, url, what=what)
    if response.status_code == 404:
        return None
    return _parse_json_object(response, what=what)


async def _get_json(client: httpx.AsyncClient, url: str, *, what: str) -> dict[str, Any]:
    """GET ``url`` and parse a JSON object. ``what`` is a safe label for errors.

    Raises :class:`OAuthPassthroughError` (no creds) on a network failure, any
    non-2xx status, or a non-object body. The response body is NEVER placed in
    the error message — discovery documents are non-secret but the discipline
    is uniform.
    """
    response = await _get(client, url, what=what)
    return _parse_json_object(response, what=what)


async def _get(client: httpx.AsyncClient, url: str, *, what: str) -> httpx.Response:
    """GET with a generic (no-creds) network-error wrapper."""
    try:
        return await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OAuthPassthroughError(f"{what} request failed: {type(exc).__name__}") from exc


def _parse_json_object(response: httpx.Response, *, what: str) -> dict[str, Any]:
    """Require a 2xx JSON-object response; raise a generic error otherwise."""
    if response.status_code >= 400:
        raise OAuthPassthroughError(f"{what} request returned HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise OAuthPassthroughError(f"{what} response was not JSON") from exc
    if not isinstance(body, dict):
        raise OAuthPassthroughError(f"{what} response was not a JSON object")
    return body
