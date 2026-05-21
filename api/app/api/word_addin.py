"""Word add-in plumbing surface (M3-B1, M3-B2, M3-B8).

Surfaces (current):

* ``GET /api/v1/admin/word-addin/manifest`` — admin-only; returns a
  rendered Office Add-in manifest XML with the operator's deployment URL
  + a freshly generated GUID substituted into the template (M3-B1).
* ``GET /api/v1/word-addin/version`` — **unauthenticated**; returns the
  deployment's version + the compatible add-in version range + the
  task-pane bundle URL. The task pane consults this on mount before
  the user even sees the sign-in screen, so an out-of-date add-in
  surfaces an "Update needed" overlay without the operator getting
  stuck at a broken OAuth handshake (M3-B8).

OAuth (M3-B2) reuses ``/api/v1/auth/login`` + ``/auth/refresh`` from the
existing auth surface — no Word-add-in-specific endpoint required.

Template loading: the manifest template lives at ``api/app/data/word_addin_
manifest.xml``. The source-of-truth lives in the sibling ``word-addin/
manifest.xml`` directory; a sync test in :mod:`api.tests.test_word_addin
_endpoints` asserts the two files match byte-for-byte so any change to
the add-in's manifest flows into the api package.

Per [PRD §9 DE-287](docs/PRD.md), the user-facing feature tabs inside
the add-in are descoped to M4 / community contribution; this M3 plumbing
ships the install-authenticate-version-check surface only.
"""

from __future__ import annotations

import re
import uuid as _uuid_mod
from importlib import resources
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import __version__ as _api_version
from app.api.dependencies import AdminUser

admin_router = APIRouter(prefix="/admin/word-addin", tags=["admin"])
"""Admin-only routes (manifest generation). Mounted under the standard
``AdminUser`` gate in :mod:`app.api.__init__`."""

public_router = APIRouter(prefix="/word-addin", tags=["word-addin"])
"""Unauthenticated routes (version handshake). The task pane consults
the version endpoint before the user has signed in, so the gate must
not require an auth token. Mounted without the ``ActiveUser`` dependency
in :mod:`app.api.__init__` (same pattern as ``bootstrap.router``)."""

# Back-compat alias for callers that imported ``router`` directly before
# M3-B8 introduced the split. New code should reference ``admin_router``
# or ``public_router`` explicitly so the auth posture is clear at the
# import site.
router = admin_router


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


@admin_router.get(
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


# ---------------------------------------------------------------------------
# M3-B8 — Version handshake. The task pane calls this on mount BEFORE the
# user signs in, so the endpoint is unauthenticated and mounted on the
# ``public_router`` (no ``ActiveUser`` gate).
# ---------------------------------------------------------------------------


# The earliest add-in version that this deployment can talk to. Bump when a
# breaking change (e.g., a new required request field, an API rename) lands
# in the task-pane bundle; bumping forces operators to redistribute the
# manifest before the deployment will accept the older add-in.
ADDIN_MIN_COMPATIBLE_VERSION = "0.3.0"

# Upper bound on add-in versions this deployment recognizes. The default
# accepts every 0.3.x patch so operators don't have to bump the deployment
# for cosmetic add-in fixes; raise to ``0.4.99`` when M4 features ship.
ADDIN_MAX_COMPATIBLE_VERSION = "0.3.99"


class WordAddinVersionResponse(BaseModel):
    """Wire shape for the version handshake (M3-B8)."""

    deployment_version: str = Field(
        description=(
            "LQ.AI deployment version (api package ``__version__``). "
            "Informational — the add-in doesn't use this for "
            "compatibility decisions; it surfaces the value in the "
            "'Update needed' overlay so the user can quote it to "
            "support."
        )
    )
    addin_min_compatible_version: str = Field(
        description=(
            "Lowest add-in version (semver string) this deployment "
            "accepts. The task pane refuses to render features when "
            "its bundled version is lower."
        )
    )
    addin_max_compatible_version: str = Field(
        description=(
            "Highest add-in version this deployment recognizes. Task "
            "pane bundles newer than this should still load (forward "
            "compatibility is best-effort) but the add-in surfaces a "
            "soft warning so the operator knows to update the "
            "deployment."
        )
    )
    taskpane_bundle_url: str = Field(
        description=(
            "Canonical URL of the task-pane bundle's HTML entry point. "
            "The task pane reaches this from its `window.location` "
            "today; the value exists in the handshake so a future "
            "deployment can serve the bundle from a CDN or operator-"
            "chosen path without changing the manifest."
        )
    )
    taskpane_bundle_hash: str | None = Field(
        default=None,
        description=(
            "Optional SHA-256 hash of the deployed task-pane bundle "
            "JS. When present, the add-in can verify it loaded the "
            "bundle the deployment expects (catches Office's "
            "occasional stale-cache behavior). M3-B8 ships with this "
            "field nullable; M3-B7 / signing CI populates the value "
            "from the build manifest. Null means 'don't enforce' — "
            "not an error condition."
        ),
    )


@public_router.get(
    "/version",
    response_model=WordAddinVersionResponse,
    summary="Version handshake for the Word add-in task pane (M3-B8).",
    description=(
        "Unauthenticated endpoint the task pane consults on mount. "
        "Returns the deployment's version + the add-in version range "
        "this deployment is compatible with. The task pane compares "
        "its bundled version (baked in by webpack at build time) to "
        "the range; out-of-range bundles surface an 'Update needed' "
        "overlay rather than getting stuck against a breaking-change "
        "API call."
    ),
)
async def get_version(request: Request) -> WordAddinVersionResponse:
    origin = _resolve_deployment_origin(request, override=None)
    return WordAddinVersionResponse(
        deployment_version=_api_version,
        addin_min_compatible_version=ADDIN_MIN_COMPATIBLE_VERSION,
        addin_max_compatible_version=ADDIN_MAX_COMPATIBLE_VERSION,
        taskpane_bundle_url=f"{origin}/word-addin/taskpane.html",
        taskpane_bundle_hash=None,
    )
