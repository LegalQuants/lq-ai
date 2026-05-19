"""Tests for the M3-A3 built-in NDA playbooks (mutual + unilateral).

Three layers:

* **YAML structural validation** — both ``skills/playbooks/*/playbook.yaml``
  files load, parse, and validate against the :class:`PlaybookCreate`
  Pydantic schema. Each position has the eight required fields, ≥2
  fallback tiers, and a severity in the canonical enum.
* **Migration round-trip** — after the test fixture runs Alembic to
  head, the ``playbooks`` table contains rows whose content matches
  the YAML files byte-for-byte (catches drift between the human-
  editable YAML and the migration's load path).
* **Executor smoke** — load the seeded NDA-mutual playbook from the
  DB, invoke the executor against a synthetic NDA-shaped document,
  assert all eight positions are classified by the stubbed gateway.

The tests share the same SAVEPOINT-rolled-back per-test session as
the rest of the API tests.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.playbook import Playbook, PlaybookExecution, PlaybookPosition
from app.models.user import User
from app.playbooks.executor import run_playbook_execution
from app.schemas.playbooks import PlaybookCreate
from app.security import hash_password

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PLAYBOOKS_DIR = _REPO_ROOT / "skills" / "playbooks"

_BUILTIN_SLUGS: list[str] = ["nda", "nda-unilateral"]
_EXPECTED_NAMES: dict[str, str] = {
    "nda": "NDA — Mutual",
    "nda-unilateral": "NDA — Unilateral (Discloser-favorable)",
}
_EXPECTED_CONTRACT_TYPES: dict[str, str] = {
    "nda": "NDA",
    "nda-unilateral": "NDA-unilateral",
}

_REQUIRED_POSITION_ISSUES: set[str] = {
    "Definition of Confidential Information",
    "Permitted Disclosures",
    "Term",
    "Survival of Confidentiality Obligations",
    "Carveouts",
    "Remedies and Injunctive Relief",
    "Governing Law and Venue",
    "Return or Destruction of Confidential Information",
}


def _load_yaml(slug: str) -> dict[str, Any]:
    path = _PLAYBOOKS_DIR / slug / "playbook.yaml"
    return yaml.safe_load(path.read_text())


# ---------------------------------------------------------------------------
# YAML structural validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_playbook_yaml_parses(slug: str) -> None:
    """The YAML file exists, parses, and is a dict."""
    parsed = _load_yaml(slug)
    assert isinstance(parsed, dict)


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_playbook_yaml_validates_against_pydantic_schema(slug: str) -> None:
    """The YAML conforms to :class:`PlaybookCreate` — same schema the
    executor and the M3-A4 UI consume.
    """
    parsed = _load_yaml(slug)
    pb = PlaybookCreate.model_validate(parsed)
    assert pb.name == _EXPECTED_NAMES[slug]
    assert pb.contract_type == _EXPECTED_CONTRACT_TYPES[slug]
    assert pb.version == "1.0.0"


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_playbook_covers_all_eight_required_positions(slug: str) -> None:
    """All eight standard NDA positions are present per the M3-A3 spec."""
    parsed = _load_yaml(slug)
    issues = {pos["issue"] for pos in parsed.get("positions") or []}
    assert issues == _REQUIRED_POSITION_ISSUES, (
        f"Mismatch in {slug}/playbook.yaml: extra={issues - _REQUIRED_POSITION_ISSUES}, "
        f"missing={_REQUIRED_POSITION_ISSUES - issues}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_each_position_has_at_least_two_fallback_tiers(slug: str) -> None:
    """The M3-A3 spec requires ≥2 fallback tiers per position."""
    parsed = _load_yaml(slug)
    for pos in parsed.get("positions") or []:
        tiers = pos.get("fallback_tiers") or []
        assert len(tiers) >= 2, (
            f"{slug}/{pos['issue']}: only {len(tiers)} fallback tier(s); spec requires ≥2."
        )


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_each_position_has_required_string_fields(slug: str) -> None:
    """Standard language and redline_strategy are non-empty strings."""
    parsed = _load_yaml(slug)
    for pos in parsed.get("positions") or []:
        assert pos.get("standard_language"), f"{slug}/{pos['issue']}: missing standard_language."
        assert pos.get("redline_strategy"), f"{slug}/{pos['issue']}: missing redline_strategy."
        assert pos.get("severity_if_missing") in {"critical", "high", "medium", "low"}, (
            f"{slug}/{pos['issue']}: severity_if_missing not in canonical enum."
        )
        assert pos.get("detection_keywords"), (
            f"{slug}/{pos['issue']}: detection_keywords must be non-empty."
        )


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_description_includes_not_legal_advice_disclaimer(slug: str) -> None:
    """The playbook-level description must include the not-legal-advice disclaimer.

    Per the M3-A3 attestation reframe, every built-in playbook
    surfaces a disclaimer that operators must apply professional
    judgment. The text MUST appear in the ``description`` field so
    it renders wherever the playbook is shown.
    """
    parsed = _load_yaml(slug)
    desc = (parsed.get("description") or "").lower()
    assert "not legal advice" in desc, (
        f"{slug}/playbook.yaml: description must include the 'not legal advice' disclaimer."
    )
    assert "professional judgment" in desc, (
        f"{slug}/playbook.yaml: description must reference the user's professional judgment."
    )


# ---------------------------------------------------------------------------
# Migration round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
async def test_migration_seeded_playbook_row(db_session: AsyncSession, slug: str) -> None:
    """After migration 0032 runs, the playbook row exists with the YAML content."""
    parsed = _load_yaml(slug)
    expected_name = _EXPECTED_NAMES[slug]

    result = await db_session.execute(
        select(Playbook).where(Playbook.name == expected_name, Playbook.version == "1.0.0")
    )
    pb = result.scalar_one()
    assert pb.contract_type == parsed["contract_type"]
    assert pb.description == parsed.get("description", "")


@pytest.mark.integration
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
async def test_migration_seeded_positions_match_yaml(db_session: AsyncSession, slug: str) -> None:
    """All eight positions are present after seeding with content matching the YAML."""
    parsed = _load_yaml(slug)
    expected_name = _EXPECTED_NAMES[slug]

    pb_result = await db_session.execute(
        select(Playbook).where(Playbook.name == expected_name, Playbook.version == "1.0.0")
    )
    pb = pb_result.scalar_one()

    positions_result = await db_session.execute(
        select(PlaybookPosition)
        .where(PlaybookPosition.playbook_id == pb.id)
        .order_by(PlaybookPosition.position_order)
    )
    positions = list(positions_result.scalars().all())
    assert len(positions) == 8, f"{slug}: expected 8 positions, got {len(positions)}"

    yaml_positions = sorted(
        (parsed.get("positions") or []), key=lambda p: int(p.get("position_order", 0))
    )
    for db_pos, yaml_pos in zip(positions, yaml_positions, strict=True):
        assert db_pos.issue == yaml_pos["issue"]
        assert db_pos.standard_language == yaml_pos["standard_language"]
        assert db_pos.redline_strategy == yaml_pos["redline_strategy"]
        assert db_pos.severity_if_missing == yaml_pos["severity_if_missing"]
        assert list(db_pos.detection_keywords) == list(yaml_pos.get("detection_keywords") or [])
        assert db_pos.fallback_tiers == (yaml_pos.get("fallback_tiers") or [])


# ---------------------------------------------------------------------------
# Executor integration smoke
# ---------------------------------------------------------------------------


@dataclass
class _StubMessage:
    content: str


@dataclass
class _StubChoice:
    message: _StubMessage


@dataclass
class _StubResponse:
    choices: list[_StubChoice]


@dataclass
class _AllMissingGateway:
    """Stubs every classify call to return a ``missing`` verdict.

    The integration smoke uses a synthetic NDA-shaped document but
    deliberately doesn't try to evaluate whether real classification
    works (that requires a live LLM). We only verify the workflow
    runs end-to-end against the seeded playbook with all 8
    positions: gateway is called once per position, all return
    ``missing``, and the persisted ``results`` payload has 8 entries.
    """

    calls_received: list[Any] = field(default_factory=list)

    async def chat_completion(self, request: Any) -> _StubResponse:
        self.calls_received.append(request)
        payload = json.dumps(
            {
                "verdict": "missing",
                "confidence": "high",
                "matched_fallback_rank": None,
                "matched_text": "",
                "cited_chunk_indices": [],
                "justification": "Stubbed verdict for executor smoke test.",
            }
        )
        return _StubResponse(choices=[_StubChoice(message=_StubMessage(content=payload))])


async def _make_user(db: AsyncSession) -> User:
    u = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(u)
    await db.flush()
    return u


async def _make_synthetic_nda(db: AsyncSession, *, owner: User) -> Document:
    f = FileModel(
        owner_id=owner.id,
        filename="synthetic-nda.pdf",
        mime_type="application/pdf",
        size_bytes=2048,
        hash_sha256="e" * 64,
        storage_path=f"nda-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()

    chunks_text = [
        "MUTUAL NON-DISCLOSURE AGREEMENT. This Agreement is entered into as of the Effective Date.",
        "Confidential Information means any non-public information disclosed by either Party.",
        "Each Party shall hold Confidential Information in confidence for a period of two years.",
        "The obligations of confidentiality shall survive the termination for three years.",
        "Permitted Disclosures: legal counsel and regulators upon notice.",
    ]
    normalized = " ".join(chunks_text)

    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=2,
        character_count=len(normalized),
        normalized_content=normalized,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()

    offset = 0
    for i, text_value in enumerate(chunks_text):
        chunk = DocumentChunk(
            document_id=doc.id,
            chunk_index=i,
            content=text_value,
            page_start=1,
            page_end=1,
            char_offset_start=offset,
            char_offset_end=offset + len(text_value),
        )
        db.add(chunk)
        offset += len(text_value) + 1  # +1 for the space joiner
    await db.flush()
    return doc


@pytest.mark.integration
async def test_executor_runs_against_seeded_nda_mutual_playbook(
    db_session: AsyncSession,
) -> None:
    """End-to-end: load NDA-mutual from DB, execute against a synthetic doc.

    Asserts:
    * Execution completes successfully (status='completed').
    * All 8 positions in the seeded playbook are classified.
    * The stubbed gateway is called exactly 8 times (once per
      position; no redline calls because all stubs return 'missing').
    """
    owner = await _make_user(db_session)
    doc = await _make_synthetic_nda(db_session, owner=owner)

    pb = (
        await db_session.execute(
            select(Playbook).where(
                Playbook.name == _EXPECTED_NAMES["nda"], Playbook.version == "1.0.0"
            )
        )
    ).scalar_one()

    execution = PlaybookExecution(
        playbook_id=pb.id,
        target_document_id=doc.id,
        user_id=owner.id,
    )
    db_session.add(execution)
    await db_session.flush()

    gateway = _AllMissingGateway()
    await run_playbook_execution(
        db_session,
        execution_id=execution.id,
        gateway=gateway,  # type: ignore[arg-type]
    )

    await db_session.refresh(execution)
    assert execution.status == "completed"
    assert execution.error is None
    assert execution.results is not None
    positions: Iterable[dict[str, Any]] = execution.results["positions"]
    assert len(list(positions)) == 8
    # 8 classify calls; 0 redline calls (every verdict is 'missing').
    assert len(gateway.calls_received) == 8
