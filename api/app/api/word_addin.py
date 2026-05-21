"""Word add-in admin surface (M3-B1).

Surface (current):

* ``GET /api/v1/admin/word-addin/manifest`` — admin-only; returns a
  rendered Office Add-in manifest XML with the operator's deployment URL
  + a freshly generated GUID substituted into the template. Operators
  use the rendered file to sideload the add-in via Microsoft 365 Admin
  Center (per `word-addin/README.md`).

Future M3 Phase B surfaces (M3-B2 OAuth, M3-B8 version handshake) land
in this module as separate route handlers under the same router.

Template loading: the manifest template lives at ``api/app/data/word_addin_
manifest.xml``. The source-of-truth lives in the sibling ``word-addin/
manifest.xml`` directory; a sync test in :mod:`api.tests.test_word_addin
_endpoints` asserts the two files match byte-for-byte so any change to
the add-in's manifest flows into the api package.

Per [PRD §9 DE-287](docs/PRD.md), the user-facing feature tabs inside
the add-in are descoped to M4 / community contribution; this M3 plumbing
ships the install-and-authenticate surface only.
"""

from __future__ import annotations

import re
import uuid as _uuid_mod
from importlib import resources
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import Response

from app.api.dependencies import AdminUser

router = APIRouter(prefix="/admin/word-addin", tags=["admin"])


# Default values for manifest tokens. Operators can override per-request
# via query params; the defaults match the project's open-source identity.
DEFAULT_DISPLAY_NAME = "LQ.AI"
DEFAULT_PROVIDER_NAME = "LegalQuants"

# Token names in the manifest XML. Tokens render as ``{{ TOKEN_NAME }}``
# with single spaces; the regex below tolerates extra whitespace inside
# the braces but treats the token name as case-sensitive.
_TOKEN_PATTERN = re.compile(r"\{\{\s*(?P<name>[A-Z_]+)\s*\}\}")


def _load_manifest_template() -> str:
    """Load the bundled Office Add-in manifest template.

    Lives at ``api/app/data/word_addin_manifest.xml``; bundled into the
    api image at COPY time via the Dockerfile. The function is module-
    level (rather than a constant computed at import) so tests can patch
    the resource path if they need to exercise a different template.
    """
    return (
        resources.files("app.data").joinpath("word_addin_manifest.xml").read_text(encoding="utf-8")
    )


def render_manifest(
    *,
    deployment_origin: str,
    display_name: str = DEFAULT_DISPLAY_NAME,
    provider_name: str = DEFAULT_PROVIDER_NAME,
    addin_id: str | None = None,
) -> str:
    """Render the manifest template with the operator's deployment values.

    Pure function: separated from the FastAPI handler so unit tests can
    exercise every token-substitution path without spinning up the app.

    Args:
        deployment_origin: The operator's deployment URL with no trailing
            slash (e.g. ``https://lq.acme.example``). Validation happens
            upstream in the request handler.
        display_name: Branded name surfaced inside Word's ribbon and the
            task pane GetStarted message. Defaults to ``LQ.AI``.
        provider_name: ``ProviderName`` value the manifest surfaces to
            Microsoft 365 Admin Center. Defaults to ``LegalQuants``.
        addin_id: Lowercase hyphenated GUID; freshly generated per
            invocation when omitted so each install is uniquely
            addressable in the M365 catalog.

    Returns:
        Rendered manifest XML.

    Raises:
        ValueError: when the template contains a token that has no
            substitution value supplied by this function (catches
            template drift early).
    """
    if addin_id is None:
        addin_id = str(_uuid_mod.uuid4())

    substitutions = {
        "ADDIN_ID": addin_id,
        "DEPLOYMENT_ORIGIN": deployment_origin.rstrip("/"),
        "DEPLOYMENT_DISPLAY_NAME": display_name,
        "PROVIDER_NAME": provider_name,
    }

    template = _load_manifest_template()

    def _substitute(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in substitutions:
            raise ValueError(
                f"manifest template references unknown token {name!r}; "
                f"known tokens: {sorted(substitutions)}"
            )
        return substitutions[name]

    return _TOKEN_PATTERN.sub(_substitute, template)


def _resolve_deployment_origin(
    request: Request,
    override: str | None,
) -> str:
    """Derive the deployment origin for the rendered manifest.

    Preference order:
        1. Explicit ``deployment_origin`` query param when provided —
           lets an operator generate a manifest for a different
           deployment from the one serving the admin UI (rare but
           valid when a single ops team manages many deployments).
        2. The ``X-Forwarded-Proto`` + ``Host`` headers — these are
           what the reverse proxy reports, and match what the operator's
           users see in their browser address bar.
        3. The request URL's scheme + netloc as a final fallback for
           single-process dev setups.
    """
    if override is not None:
        return override.rstrip("/")

    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        return f"{scheme}://{host}".rstrip("/")

    return str(request.base_url).rstrip("/")


@router.get(
    "/manifest",
    response_class=Response,
    summary="Render the Word add-in manifest XML for sideload (M3-B1).",
    responses={
        200: {
            "description": "Rendered Office Add-in XML manifest.",
            "content": {"application/xml": {}},
        },
        403: {"description": "Caller is not an admin user."},
    },
)
async def get_manifest(
    request: Request,
    _admin: AdminUser,
    deployment_origin: Annotated[
        str | None,
        Query(
            description=(
                "Override the deployment origin embedded in the manifest. "
                "Defaults to the request's effective origin (reverse-proxy "
                "aware). No trailing slash."
            ),
            examples=["https://lq.acme.example"],
        ),
    ] = None,
    display_name: Annotated[
        str,
        Query(
            description=(
                "Branded name surfaced inside Word's ribbon and the task pane GetStarted message."
            ),
            max_length=64,
        ),
    ] = DEFAULT_DISPLAY_NAME,
    provider_name: Annotated[
        str,
        Query(
            description=(
                "ProviderName value the manifest surfaces to Microsoft 365 "
                "Admin Center; typically the operator org's name."
            ),
            max_length=64,
        ),
    ] = DEFAULT_PROVIDER_NAME,
) -> Response:
    """Render and return the Office Add-in manifest XML for sideload.

    The endpoint is admin-only (``AdminUser`` dep at router level via
    ``api_router``). Returns ``application/xml`` with a
    ``Content-Disposition: attachment`` header so the browser downloads
    the file rather than rendering it as XML in the tab.
    """
    origin = _resolve_deployment_origin(request, deployment_origin)
    rendered = render_manifest(
        deployment_origin=origin,
        display_name=display_name,
        provider_name=provider_name,
    )

    return Response(
        content=rendered,
        media_type="application/xml",
        status_code=status.HTTP_200_OK,
        headers={
            "Content-Disposition": ('attachment; filename="lq-ai-word-addin-manifest.xml"'),
            "Cache-Control": "no-store",
        },
    )
