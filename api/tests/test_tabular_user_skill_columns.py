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
@pytest.mark.parametrize("query", ["", " ", "\t\n"])
async def test_create_column_with_empty_query_returns_422(
    client: AsyncClient, user_a: User, query: str
) -> None:
    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(
            frontmatter_extra={
                "output_format": "table",
                "columns": [{"name": "Term", "query": query}],
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
            "minimum_inference_tier": 2,
            "columns": [
                {"name": "Term", "query": "What is the term?"},
                {
                    "name": "Venue",
                    "query": "What is the venue?",
                    "ensemble_verification": False,
                    "minimum_inference_tier": 4,
                },
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
    assert columns[0]["minimum_inference_tier"] == 2
    assert columns[1]["minimum_inference_tier"] == 4


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


@pytest.mark.parametrize("field", ["name", "query"])
@pytest.mark.parametrize("blank", [" ", "\t\n", "\u2003"])
def test_column_spec_rejects_whitespace_only(field: str, blank: str) -> None:
    values = {"name": " Term ", "query": " What is the term? "}
    values[field] = blank
    with pytest.raises(ValidationError):
        ColumnSpec.model_validate(values)


def test_column_spec_preserves_nonblank_text() -> None:
    column = ColumnSpec(name=" Term ", query="\nWhat is the term?\n")
    assert column.name == " Term "
    assert column.query == "\nWhat is the term?\n"


@pytest.mark.parametrize("output_format", [None, "report", {"custom": True}])
def test_non_table_metadata_is_opaque(output_format: object) -> None:
    from app.api.user_skills import _validate_frontmatter_extra
    from app.skills.schema import parse_table_skill_extra

    extra = {
        "columns": {"custom": "metadata"},
        "minimum_inference_tier": "custom",
        "ensemble_verification": ["custom"],
    }
    if output_format is not None:
        extra["output_format"] = output_format
    assert _validate_frontmatter_extra(extra) is extra
    assert parse_table_skill_extra(extra) is None


def test_table_authoring_and_hydration_share_projection() -> None:
    from app.api.tabular import _columns_from_user_skill_row
    from app.api.user_skills import _validate_frontmatter_extra

    extra = {
        "output_format": "table",
        "columns": TABLE_COLUMNS,
        "tags": {"custom": True},
        "capabilities": "not-built-in-capabilities",
        "title": ["custom", "title"],
    }
    assert _validate_frontmatter_extra(extra) is extra
    row = UserSkill(frontmatter_extra=extra)
    columns = _columns_from_user_skill_row(row, skill_name="grid")
    assert [column.name for column in columns] == ["Term", "Governing law"]
    assert row.frontmatter_extra == extra


@pytest.mark.parametrize("output_format", [None, "report"])
def test_runtime_requires_explicit_table_mode(output_format: str | None) -> None:
    from fastapi import HTTPException

    from app.api.tabular import _columns_from_user_skill_row

    row = UserSkill(frontmatter_extra={"output_format": output_format, "columns": TABLE_COLUMNS})
    with pytest.raises(HTTPException) as exc:
        _columns_from_user_skill_row(row, skill_name="grid")
    assert exc.value.status_code == 400


@pytest.mark.integration
async def test_create_patch_preserve_non_table_extension_metadata(
    client: AsyncClient, user_a: User
) -> None:
    extra = {"columns": "custom", "minimum_inference_tier": {"arbitrary": True}}
    created = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(frontmatter_extra=extra),
    )
    assert created.status_code == 201, created.text
    assert created.json()["frontmatter_extra"] == extra
    extra = {"output_format": "report", "ensemble_verification": ["opaque"]}
    patched = await client.patch(
        f"/api/v1/user-skills/{created.json()['id']}",
        headers=_bearer(user_a),
        json={"frontmatter_extra": extra},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["frontmatter_extra"] == extra


@pytest.mark.integration
@pytest.mark.parametrize("scope", ["user", "team"])
async def test_skill_resolution_enforces_caller_boundary(
    client: AsyncClient, db_session: AsyncSession, user_a: User, scope: str
) -> None:
    from app.models.team import Team, TeamMember

    other = await _make_user(db_session)
    owner_fields = {"owner_user_id": other.id}
    team = None
    if scope == "team":
        team = Team(
            name="Grid team", slug=f"grid-{uuid.uuid4().hex[:8]}", created_by_user_id=other.id
        )
        db_session.add(team)
        await db_session.flush()
        db_session.add(
            TeamMember(team_id=team.id, user_id=other.id, role="admin", added_by_user_id=other.id)
        )
        owner_fields = {"owner_team_id": team.id}
    skill = UserSkill(
        scope=scope,
        **owner_fields,
        slug="private-grid",
        display_name="Private grid",
        description="Access boundary test",
        version="1.0.0",
        tags=[],
        body="Extract columns.",
        frontmatter_extra={"output_format": "table", "columns": TABLE_COLUMNS},
    )
    db_session.add(skill)
    await db_session.flush()
    doc = await _make_document(db_session, owner=user_a)
    request = {"document_ids": [str(doc.id)], "skill_name": "private-grid"}
    denied = await client.post("/api/v1/tabular/execute", headers=_bearer(user_a), json=request)
    assert denied.status_code == 404, denied.text
    if team is not None:
        db_session.add(
            TeamMember(team_id=team.id, user_id=user_a.id, role="member", added_by_user_id=other.id)
        )
        await db_session.flush()
        allowed = await client.post(
            "/api/v1/tabular/execute", headers=_bearer(user_a), json=request
        )
        assert allowed.status_code == 202, allowed.text
        assert [column["name"] for column in allowed.json()["columns"]] == ["Term", "Governing law"]


@pytest.mark.integration
async def test_table_extension_metadata_survives_create_patch_and_execute(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    extra = {
        "output_format": "table",
        "columns": TABLE_COLUMNS,
        "tags": {"custom": True},
        "capabilities": "custom",
    }
    created = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(frontmatter_extra=extra),
    )
    assert created.status_code == 201, created.text
    assert created.json()["frontmatter_extra"] == extra
    extra["title"] = ["arbitrary", "title"]
    patched = await client.patch(
        f"/api/v1/user-skills/{created.json()['id']}",
        headers=_bearer(user_a),
        json={"frontmatter_extra": extra},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["frontmatter_extra"] == extra
    doc = await _make_document(db_session, owner=user_a)
    executed = await client.post(
        "/api/v1/tabular/execute",
        headers=_bearer(user_a),
        json={"document_ids": [str(doc.id)], "skill_name": "contract-grid"},
    )
    assert executed.status_code == 202, executed.text
    assert [column["name"] for column in executed.json()["columns"]] == ["Term", "Governing law"]


async def test_builtin_resolution_snapshots_skill_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.api import skills, tabular
    from app.skills.schema import LQAIFrontmatter

    lq = LQAIFrontmatter.model_validate(
        {
            "output_format": "table",
            "ensemble_verification": True,
            "minimum_inference_tier": 2,
            "columns": [
                {"name": "Term", "query": "What is the term?"},
                {
                    "name": "Law",
                    "query": "Which law?",
                    "ensemble_verification": False,
                    "minimum_inference_tier": 4,
                },
            ],
        }
    )
    record = SimpleNamespace(frontmatter=SimpleNamespace(lq_ai=lq))
    registry = SimpleNamespace(current=lambda: {"builtin-grid": record})
    monkeypatch.setattr(tabular, "_registry", lambda request: registry)
    monkeypatch.setattr(skills, "_load_user_shadow", AsyncMock(return_value=None))
    monkeypatch.setattr(skills, "_load_team_shadow", AsyncMock(return_value=None))
    _, columns = await tabular._resolve_columns(
        None,
        None,
        user=User(id=uuid.uuid4()),
        skill_name="builtin-grid",
        ad_hoc=None,
    )
    assert columns[0].ensemble_verification is True
    assert columns[0].minimum_inference_tier == 2
    assert columns[1].ensemble_verification is False
    assert columns[1].minimum_inference_tier == 4
    # Snapshot baking must not mutate the shared registry defaults.
    assert lq.columns is not None
    assert lq.columns[0].minimum_inference_tier is None
    lq.output_format = "report"
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await tabular._resolve_columns(
            None,
            None,
            user=User(id=uuid.uuid4()),
            skill_name="builtin-grid",
            ad_hoc=None,
        )
    assert exc.value.status_code == 400


@pytest.mark.integration
@pytest.mark.parametrize("duplicate_name", ["Term", "term", " TERM "])
async def test_duplicate_column_names_rejected_on_create_patch_and_legacy_run(
    client: AsyncClient, db_session: AsyncSession, user_a: User, duplicate_name: str
) -> None:
    extra = {
        "output_format": "table",
        "columns": [
            {"name": "Term", "query": "What is the term?"},
            {"name": duplicate_name, "query": "When does it end?"},
        ],
    }
    rejected = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(frontmatter_extra=extra),
    )
    assert rejected.status_code == 422, rejected.text
    assert "Duplicate column name" in rejected.json()["detail"]
    created = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_table_skill_body(),
    )
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]
    rejected_patch = await client.patch(
        f"/api/v1/user-skills/{skill_id}",
        headers=_bearer(user_a),
        json={"frontmatter_extra": extra},
    )
    assert rejected_patch.status_code == 422, rejected_patch.text
    assert "Duplicate column name" in rejected_patch.json()["detail"]
    detail = await client.get(f"/api/v1/user-skills/{skill_id}", headers=_bearer(user_a))
    assert detail.json()["frontmatter_extra"]["columns"] == TABLE_COLUMNS
    # Existing stored duplicates remain readable/editable, but cannot start a new run.
    row = await db_session.get(UserSkill, uuid.UUID(skill_id))
    assert row is not None
    row.frontmatter_extra = extra
    await db_session.flush()
    detail = await client.get(f"/api/v1/user-skills/{skill_id}", headers=_bearer(user_a))
    assert detail.status_code == 200, detail.text
    assert detail.json()["frontmatter_extra"] == extra
    doc = await _make_document(db_session, owner=user_a)
    rejected_run = await client.post(
        "/api/v1/tabular/execute",
        headers=_bearer(user_a),
        json={"document_ids": [str(doc.id)], "skill_name": "contract-grid"},
    )
    assert rejected_run.status_code == 400, rejected_run.text
    assert "invalid column spec" in rejected_run.json()["detail"]


def test_non_table_duplicate_column_metadata_remains_opaque() -> None:
    from app.api.user_skills import _validate_frontmatter_extra

    extra = {
        "output_format": "report",
        "columns": [
            {"name": "Term", "query": "One"},
            {"name": "term", "query": "Two"},
        ],
    }
    assert _validate_frontmatter_extra(extra) is extra
