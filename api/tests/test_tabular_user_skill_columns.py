"""DE-297 — table-mode user skills: authoring validation + tabular hydration.

Two halves of the same contract:

* **Persisted shape** — ``POST /api/v1/user-skills`` / ``PATCH`` validate
  ``frontmatter_extra`` table-mode keys through the SAME
  :class:`app.skills.schema.LQAIFrontmatter` model the built-in loader
  uses, so a user-authored ``output_format: table`` skill can never be
  stored in a shape the built-in path would reject (zero columns, blank
  query, tier outside 1-5). The stored extra round-trips verbatim and
  the merged ``GET /skills`` summary surfaces ``output_format: table``
  — which is what makes the skill pickable in the Tabular wizard.

* **Hydration** — ``POST /api/v1/tabular/execute`` (and preview-cost)
  resolve a ``skill_name`` through the D8.1b stack: the caller's
  user-scope shadow first, then team shadow, then the built-in
  registry. A user table skill therefore RUNS with its own columns —
  including when it shadows a built-in at the same slug — and the
  resolved spec (with the skill-level ``ensemble_verification``
  fallback baked in) is snapshotted onto the execution row.

Fixture pattern mirrors ``test_user_skills.py`` (fixture-skills registry
injected via ``app.state.skill_registry``) plus the document seeding
helper from ``test_tabular_endpoints.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import get_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.tabular import TabularExecution
from app.models.user import User
from app.models.user_skill import UserSkill
from app.security import create_access_token, hash_password
from app.skills import load_registry
from app.skills.registry import MutableSkillRegistry
from app.skills.schema import ColumnSpec

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "skills"

TABLE_COLUMNS = [
    {"name": "Term", "query": "What is the term of this agreement?"},
    {
        "name": "Governing law",
        "query": "Which law governs this agreement?",
        "ensemble_verification": True,
        "minimum_inference_tier": 4,
    },
]


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with the fixture-skills registry installed."""

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    holder = MutableSkillRegistry(load_registry(FIXTURES_DIR))
    prior_holder = getattr(app.state, "skill_registry", None)
    app.state.skill_registry = holder

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    if prior_holder is None:
        delattr(app.state, "skill_registry")
    else:
        app.state.skill_registry = prior_holder
    app.dependency_overrides.pop(get_db, None)


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"table-skill-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    return await _make_user(db_session)


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


def _table_skill_body(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "slug": "contract-grid",
        "display_name": "Contract Grid",
        "description": "Row-per-document contract comparison grid.",
        "body": "Extract the configured columns from each document.",
        "frontmatter_extra": {
            "output_format": "table",
            "columns": TABLE_COLUMNS,
        },
    }
    base.update(overrides)
    return base


async def _make_document(db: AsyncSession, *, owner: User) -> Document:
    """Seed a File + Document + one chunk so execute/preview can run."""

    f = FileModel(
        owner_id=owner.id,
        filename=f"doc-{uuid.uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_path=f"table-skill-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()
    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=64,
        normalized_content="This agreement runs for two years under Delaware law.",
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()
    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content="This agreement runs for two years under Delaware law.",
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=53,
    )
    db.add(chunk)
    await db.flush()
    return doc


# ---------------------------------------------------------------------------
# Schema parity — ColumnSpec floors shared by built-ins and user skills
# ---------------------------------------------------------------------------


def test_column_spec_rejects_empty_query() -> None:
    with pytest.raises(ValidationError):
        ColumnSpec.model_validate({"name": "Term", "query": ""})


def test_column_spec_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        ColumnSpec.model_validate({"name": "", "query": "What is the term?"})


# ---------------------------------------------------------------------------
# Persisted shape — create / patch validation + round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_table_mode_skill_persists_and_is_wizard_pickable(
    client: AsyncClient, user_a: User
) -> None:
    resp = await client.post(
        "/api/v1/user-skills", headers=_bearer(user_a), json=_table_skill_body()
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["frontmatter_extra"] == {
        "output_format": "table",
        "columns": TABLE_COLUMNS,
    }

    # Round-trip through the management GET — the edit page reloads from here.
    detail = await client.get(f"/api/v1/user-skills/{created['id']}", headers=_bearer(user_a))
    assert detail.status_code == 200
    assert detail.json()["frontmatter_extra"]["columns"] == TABLE_COLUMNS

    # Merged picker summary carries output_format=table — the Tabular
    # wizard filters on exactly this field.
    merged = await client.get("/api/v1/skills", headers=_bearer(user_a))
    assert merged.status_code == 200
    mine = [s for s in merged.json() if s["name"] == "contract-grid"]
    assert len(mine) == 1
    assert mine[0]["output_format"] == "table"
    assert mine[0]["scope"] == "user"


@pytest.mark.integration
async def test_create_table_mode_without_columns_returns_422(
    client: AsyncClient, user_a: User
) -> None:
    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(frontmatter_extra={"output_format": "table"}),
    )
    assert resp.status_code == 422, resp.text
    assert "columns" in resp.json()["detail"]


@pytest.mark.integration
async def test_create_table_mode_with_empty_columns_returns_422(
    client: AsyncClient, user_a: User
) -> None:
    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(frontmatter_extra={"output_format": "table", "columns": []}),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
async def test_create_column_with_empty_query_returns_422(
    client: AsyncClient, user_a: User
) -> None:
    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(
            frontmatter_extra={
                "output_format": "table",
                "columns": [{"name": "Term", "query": ""}],
            }
        ),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
@pytest.mark.parametrize("tier", [0, 6])
async def test_create_column_with_out_of_range_tier_returns_422(
    client: AsyncClient, user_a: User, tier: int
) -> None:
    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(
            frontmatter_extra={
                "output_format": "table",
                "columns": [
                    {"name": "Term", "query": "What is the term?", "minimum_inference_tier": tier}
                ],
            }
        ),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
async def test_create_column_missing_name_returns_422(client: AsyncClient, user_a: User) -> None:
    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(
            frontmatter_extra={
                "output_format": "table",
                "columns": [{"query": "What is the term?"}],
            }
        ),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
async def test_non_table_output_format_needs_no_columns(client: AsyncClient, user_a: User) -> None:
    """Parity with the loader: ``output_format`` other than ``table``
    carries no columns requirement."""

    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(frontmatter_extra={"output_format": "report"}),
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.integration
async def test_patch_validates_table_mode_and_persists_valid_spec(
    client: AsyncClient, user_a: User
) -> None:
    created = (
        await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_table_skill_body())
    ).json()

    # Invalid PATCH (table without columns) is rejected...
    bad = await client.patch(
        f"/api/v1/user-skills/{created['id']}",
        headers=_bearer(user_a),
        json={"frontmatter_extra": {"output_format": "table", "columns": []}},
    )
    assert bad.status_code == 422, bad.text

    # ...and the stored spec is untouched.
    detail = await client.get(f"/api/v1/user-skills/{created['id']}", headers=_bearer(user_a))
    assert detail.json()["frontmatter_extra"]["columns"] == TABLE_COLUMNS

    # A valid PATCH moves the columns.
    new_columns = [{"name": "Renewal", "query": "Does the agreement auto-renew?"}]
    good = await client.patch(
        f"/api/v1/user-skills/{created['id']}",
        headers=_bearer(user_a),
        json={"frontmatter_extra": {"output_format": "table", "columns": new_columns}},
    )
    assert good.status_code == 200, good.text
    assert good.json()["frontmatter_extra"]["columns"] == new_columns


# ---------------------------------------------------------------------------
# Hydration — tabular execute / preview resolve user-skill columns
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_execute_resolves_user_skill_columns_and_snapshots_them(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    created = (
        await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_table_skill_body())
    ).json()
    doc = await _make_document(db_session, owner=user_a)

    resp = await client.post(
        "/api/v1/tabular/execute",
        headers=_bearer(user_a),
        json={"document_ids": [str(doc.id)], "skill_name": created["slug"]},
    )
    assert resp.status_code == 202, resp.text
    payload = resp.json()
    assert payload["skill_name"] == "contract-grid"
    assert [c["name"] for c in payload["columns"]] == ["Term", "Governing law"]

    # Snapshot invariant (Decision C-1): the resolved spec is persisted
    # on the execution row, not re-read from the skill at render time.
    row = await db_session.get(TabularExecution, uuid.UUID(payload["id"]))
    assert row is not None
    assert [c["name"] for c in row.columns] == ["Term", "Governing law"]
    assert row.columns[1]["minimum_inference_tier"] == 4
    assert row.columns[1]["ensemble_verification"] is True


@pytest.mark.integration
async def test_execute_user_shadow_wins_over_builtin_at_same_slug(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """A user-scope table skill at a built-in's slug resolves to the
    USER columns. Before DE-297 this request failed with 400 — the
    resolver only consulted the registry, and the fixture built-in
    ``alpha-test-skill`` has no columns."""

    body = _table_skill_body(slug="alpha-test-skill", display_name="Alpha (mine)")
    created = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=body)
    assert created.status_code == 201, created.text
    doc = await _make_document(db_session, owner=user_a)

    resp = await client.post(
        "/api/v1/tabular/execute",
        headers=_bearer(user_a),
        json={"document_ids": [str(doc.id)], "skill_name": "alpha-test-skill"},
    )
    assert resp.status_code == 202, resp.text
    assert [c["name"] for c in resp.json()["columns"]] == ["Term", "Governing law"]


@pytest.mark.integration
async def test_execute_non_table_user_skill_returns_400(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    body = _table_skill_body(slug="prose-skill", frontmatter_extra={"output_format": "report"})
    created = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=body)
    assert created.status_code == 201, created.text
    doc = await _make_document(db_session, owner=user_a)

    resp = await client.post(
        "/api/v1/tabular/execute",
        headers=_bearer(user_a),
        json={"document_ids": [str(doc.id)], "skill_name": "prose-skill"},
    )
    assert resp.status_code == 400, resp.text
    assert "no columns" in resp.json()["detail"]


@pytest.mark.integration
async def test_execute_legacy_malformed_columns_returns_400_not_500(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """Rows written before DE-297 validation could hold invalid shapes;
    hydration surfaces them as a 400 with a re-save hint."""

    row = UserSkill(
        scope="user",
        owner_user_id=user_a.id,
        slug="legacy-broken-grid",
        display_name="Legacy Broken Grid",
        description="Pre-DE-297 row with a malformed column spec.",
        version="1.0.0",
        tags=[],
        frontmatter_extra={
            "output_format": "table",
            "columns": [{"name": "Term", "query": "", "minimum_inference_tier": 9}],
        },
        body="legacy",
    )
    db_session.add(row)
    await db_session.flush()
    doc = await _make_document(db_session, owner=user_a)

    resp = await client.post(
        "/api/v1/tabular/execute",
        headers=_bearer(user_a),
        json={"document_ids": [str(doc.id)], "skill_name": "legacy-broken-grid"},
    )
    assert resp.status_code == 400, resp.text
    assert "invalid column spec" in resp.json()["detail"]


@pytest.mark.integration
async def test_skill_level_ensemble_fallback_bakes_into_user_columns(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """A skill-level ``ensemble_verification: true`` in the extra block
    fills columns that declared no per-column value — mirroring the
    built-in resolution path."""

    body = _table_skill_body(
        slug="ensemble-grid",
        frontmatter_extra={
            "output_format": "table",
            "ensemble_verification": True,
            "columns": [
                {"name": "Term", "query": "What is the term?"},
                {"name": "Venue", "query": "What is the venue?", "ensemble_verification": False},
            ],
        },
    )
    created = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=body)
    assert created.status_code == 201, created.text
    doc = await _make_document(db_session, owner=user_a)

    resp = await client.post(
        "/api/v1/tabular/execute",
        headers=_bearer(user_a),
        json={"document_ids": [str(doc.id)], "skill_name": "ensemble-grid"},
    )
    assert resp.status_code == 202, resp.text
    columns = resp.json()["columns"]
    assert columns[0]["ensemble_verification"] is True  # inherited
    assert columns[1]["ensemble_verification"] is False  # explicit override kept


class _StubGateway:
    """preview-cost only touches the ensemble-config accessor."""

    async def get_citation_engine_ensemble_config(self) -> None:
        return None


@pytest.mark.integration
async def test_preview_cost_resolves_user_skill_columns(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    created = (
        await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_table_skill_body())
    ).json()
    docs = [await _make_document(db_session, owner=user_a) for _ in range(2)]

    app.dependency_overrides[get_gateway_client] = lambda: _StubGateway()
    try:
        resp = await client.post(
            "/api/v1/tabular/preview-cost",
            headers=_bearer(user_a),
            json={
                "document_ids": [str(d.id) for d in docs],
                "skill_name": created["slug"],
            },
        )
    finally:
        app.dependency_overrides.pop(get_gateway_client, None)

    assert resp.status_code == 200, resp.text
    # 2 documents x 2 user-skill columns = 4 cells.
    assert resp.json()["cells_count"] == 4
