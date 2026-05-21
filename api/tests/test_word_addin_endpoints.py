"""HTTP-level tests for the M3-B1 Word add-in admin surface.

Exercises:

* ``GET /api/v1/admin/word-addin/manifest`` — admin-only manifest
  generation. Validates token substitution, the admin gate, the
  reverse-proxy-aware origin resolution, and that the rendered output
  is well-formed XML.

Plus a structural test that asserts the embedded manifest template at
``api/app/data/word_addin_manifest.xml`` matches the source-of-truth
``word-addin/manifest.xml`` byte-for-byte — drift would surface here
before a stale manifest reached an operator's sideload.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from xml.etree import ElementTree

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.word_addin import (
    DEFAULT_DISPLAY_NAME,
    DEFAULT_PROVIDER_NAME,
    render_manifest,
)
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


async def _make_user(db: AsyncSession, *, is_admin: bool = False) -> User:
    u = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=is_admin,
        role="admin" if is_admin else "member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(u)
    await db.flush()
    return u


def _bearer(user: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token(user.id, user.email, is_admin=user.is_admin)}"
        )
    }


# ---------------------------------------------------------------------------
# Pure-function render_manifest tests — exercise every substitution path
# without touching the HTTP layer.
# ---------------------------------------------------------------------------


def test_render_manifest_substitutes_required_tokens() -> None:
    """Every {{ TOKEN }} in the template gets a value substituted."""
    rendered = render_manifest(
        deployment_origin="https://lq.acme.example",
        display_name="ACME Legal AI",
        provider_name="ACME Inc.",
        addin_id="11111111-2222-3333-4444-555555555555",
    )
    assert "{{" not in rendered, "no template tokens should remain after render"
    assert "}}" not in rendered, "no template tokens should remain after render"

    assert "11111111-2222-3333-4444-555555555555" in rendered
    assert "https://lq.acme.example" in rendered
    assert "ACME Legal AI" in rendered
    assert "ACME Inc." in rendered


def test_render_manifest_strips_trailing_slash_from_origin() -> None:
    """Trailing slash on origin would produce //word-addin/... URLs."""
    rendered = render_manifest(
        deployment_origin="https://lq.acme.example/",
        addin_id="0",
    )
    assert "https://lq.acme.example/word-addin/taskpane.html" in rendered
    assert "https://lq.acme.example//word-addin" not in rendered


def test_render_manifest_generates_fresh_guid_when_omitted() -> None:
    """Calling render twice without addin_id yields distinct GUIDs."""
    a = render_manifest(deployment_origin="https://x")
    b = render_manifest(deployment_origin="https://x")
    # Extract <Id>...</Id> from each
    a_id = a.split("<Id>", 1)[1].split("</Id>", 1)[0]
    b_id = b.split("<Id>", 1)[1].split("</Id>", 1)[0]
    assert a_id != b_id, "each render should generate a fresh GUID"
    # Both should parse as UUIDs.
    uuid.UUID(a_id)
    uuid.UUID(b_id)


def test_render_manifest_defaults_match_module_constants() -> None:
    """Calling render with no display/provider names uses the module defaults."""
    rendered = render_manifest(
        deployment_origin="https://x",
        addin_id="0",
    )
    assert DEFAULT_DISPLAY_NAME in rendered
    assert DEFAULT_PROVIDER_NAME in rendered


def test_render_manifest_output_is_well_formed_xml() -> None:
    """The rendered manifest must parse as XML (Office sideload requires this)."""
    rendered = render_manifest(
        deployment_origin="https://lq.acme.example",
        addin_id="0",
    )
    # ElementTree.fromstring raises on malformed XML.
    root = ElementTree.fromstring(rendered)
    # Sanity-check root element name (namespace-stripped).
    tag = root.tag.split("}", 1)[-1]
    assert tag == "OfficeApp"


# ---------------------------------------------------------------------------
# Template-sync test: api/app/data/ vs word-addin/manifest.xml
# ---------------------------------------------------------------------------


def test_manifest_template_matches_word_addin_source() -> None:
    """The api-side template and the word-addin source-of-truth must match.

    If this test fails, ``cp word-addin/manifest.xml api/app/data/
    word_addin_manifest.xml`` to sync them. The api bundles its own
    copy because the api Dockerfile's build context is ``./api/`` and
    can't reach ``../word-addin/`` at image-build time. This test
    catches drift early.
    """
    repo_root = Path(__file__).resolve().parents[2]
    word_addin_source = repo_root / "word-addin" / "manifest.xml"
    api_bundled = repo_root / "api" / "app" / "data" / "word_addin_manifest.xml"

    if not word_addin_source.exists():
        pytest.skip(
            "word-addin/manifest.xml absent — this test only runs in the "
            "monorepo checkout, not inside the api Docker image where "
            "word-addin/ is not bundled."
        )

    source_bytes = word_addin_source.read_bytes()
    bundled_bytes = api_bundled.read_bytes()
    assert source_bytes == bundled_bytes, (
        "api/app/data/word_addin_manifest.xml has drifted from "
        "word-addin/manifest.xml. Run: "
        "cp word-addin/manifest.xml api/app/data/word_addin_manifest.xml"
    )


# ---------------------------------------------------------------------------
# GET /api/v1/admin/word-addin/manifest — HTTP-level tests
# ---------------------------------------------------------------------------


MANIFEST_PATH = "/api/v1/admin/word-addin/manifest"


@pytest.mark.integration
async def test_get_manifest_requires_authentication(client: AsyncClient) -> None:
    """Unauthenticated requests get 401."""
    response = await client.get(MANIFEST_PATH)
    assert response.status_code == 401


@pytest.mark.integration
async def test_get_manifest_rejects_non_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Authenticated non-admin users get 403."""
    user = await _make_user(db_session, is_admin=False)
    response = await client.get(MANIFEST_PATH, headers=_bearer(user))
    assert response.status_code == 403


@pytest.mark.integration
async def test_get_manifest_returns_xml_for_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Admin sees rendered manifest XML with the request-origin substituted."""
    admin = await _make_user(db_session, is_admin=True)
    response = await client.get(
        MANIFEST_PATH,
        headers={**_bearer(admin), "Host": "lq.example"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/xml")
    # Browser should treat the response as a downloadable file.
    assert "attachment" in response.headers["content-disposition"]
    assert "lq-ai-word-addin-manifest.xml" in response.headers["content-disposition"]

    body = response.text
    assert "{{" not in body, "rendered manifest must have all tokens substituted"
    # No origin override was supplied → derived from request Host header.
    assert "lq.example/word-addin/taskpane.html" in body


@pytest.mark.integration
async def test_get_manifest_accepts_origin_override(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``deployment_origin`` query param overrides the request origin."""
    admin = await _make_user(db_session, is_admin=True)
    response = await client.get(
        f"{MANIFEST_PATH}?deployment_origin=https://lq.acme.example",
        headers=_bearer(admin),
    )
    assert response.status_code == 200, response.text
    body = response.text
    assert "https://lq.acme.example/word-addin/taskpane.html" in body


@pytest.mark.integration
async def test_get_manifest_accepts_display_and_provider_overrides(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``display_name`` + ``provider_name`` query params override defaults."""
    admin = await _make_user(db_session, is_admin=True)
    response = await client.get(
        f"{MANIFEST_PATH}?display_name=ACME%20Legal%20AI&provider_name=ACME%20Inc.",
        headers=_bearer(admin),
    )
    assert response.status_code == 200, response.text
    body = response.text
    assert "ACME Legal AI" in body
    assert "ACME Inc." in body


@pytest.mark.integration
async def test_get_manifest_respects_forwarded_proto_and_host(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """X-Forwarded-Proto + X-Forwarded-Host override the raw URL origin.

    This is the path operators behind a TLS-terminating reverse proxy
    take — without honoring the forwarded headers, the manifest would
    embed the internal ``http://api:8000`` origin instead of the
    operator's public ``https://lq.acme.example``.
    """
    admin = await _make_user(db_session, is_admin=True)
    response = await client.get(
        MANIFEST_PATH,
        headers={
            **_bearer(admin),
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "lq.acme.example",
        },
    )
    assert response.status_code == 200, response.text
    body = response.text
    assert "https://lq.acme.example/word-addin/taskpane.html" in body


@pytest.mark.integration
async def test_get_manifest_each_call_yields_fresh_guid(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Two calls produce different <Id> values so installs are uniquely addressable."""
    admin = await _make_user(db_session, is_admin=True)

    def _extract_id(xml: str) -> str:
        return xml.split("<Id>", 1)[1].split("</Id>", 1)[0]

    r1 = await client.get(MANIFEST_PATH, headers=_bearer(admin))
    r2 = await client.get(MANIFEST_PATH, headers=_bearer(admin))
    assert r1.status_code == 200
    assert r2.status_code == 200
    id1 = _extract_id(r1.text)
    id2 = _extract_id(r2.text)
    assert id1 != id2
    uuid.UUID(id1)
    uuid.UUID(id2)


# ---------------------------------------------------------------------------
# GET /api/v1/word-addin/version — M3-B8 unauthenticated handshake
# ---------------------------------------------------------------------------


VERSION_PATH = "/api/v1/word-addin/version"


@pytest.mark.integration
async def test_get_version_is_unauthenticated(client: AsyncClient) -> None:
    """The task pane consults this BEFORE sign-in; no bearer required."""
    response = await client.get(VERSION_PATH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body.keys()) == {
        "deployment_version",
        "addin_min_compatible_version",
        "addin_max_compatible_version",
        "taskpane_bundle_url",
        "taskpane_bundle_hash",
    }


@pytest.mark.integration
async def test_get_version_returns_module_constants(client: AsyncClient) -> None:
    """The compatibility-range values come from the module-level constants."""
    from app.api.word_addin import (
        ADDIN_MAX_COMPATIBLE_VERSION,
        ADDIN_MIN_COMPATIBLE_VERSION,
    )

    response = await client.get(VERSION_PATH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["addin_min_compatible_version"] == ADDIN_MIN_COMPATIBLE_VERSION
    assert body["addin_max_compatible_version"] == ADDIN_MAX_COMPATIBLE_VERSION
    # Hash is intentionally nullable in M3-B8; signing CI populates it later.
    assert body["taskpane_bundle_hash"] is None


@pytest.mark.integration
async def test_get_version_derives_bundle_url_from_request_origin(
    client: AsyncClient,
) -> None:
    """The bundle URL embeds the request's effective origin (reverse-proxy aware)."""
    response = await client.get(
        VERSION_PATH,
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "lq.acme.example",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["taskpane_bundle_url"] == "https://lq.acme.example/word-addin/taskpane.html"


@pytest.mark.integration
async def test_get_version_reports_api_package_version(client: AsyncClient) -> None:
    """``deployment_version`` mirrors ``app.__version__`` so the add-in's
    'Update needed' overlay can quote the deployment release number."""
    from app import __version__ as api_version

    response = await client.get(VERSION_PATH)
    assert response.status_code == 200
    assert response.json()["deployment_version"] == api_version
