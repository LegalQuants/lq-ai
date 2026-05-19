"""Tests for the M3-A5 built-in playbooks (MSA-SaaS, DPA-GDPR, MSA-Commercial-Purchase).

Mirrors the structure of ``test_builtin_nda_playbooks.py`` (M3-A3):

* **YAML structural validation** — each ``skills/playbooks/*/playbook.yaml``
  loads, parses, and validates against the :class:`PlaybookCreate`
  Pydantic schema. Per-position structural invariants (≥2 fallback
  tiers, required string fields, canonical severity enum).
* **Disclaimer enforcement** — every playbook's ``description`` field
  contains the "not legal advice" + "professional judgment" framing
  per Decision F + the 2026-05-19 starting-point clarification.
* **Migration round-trip** — after migration 0033 runs, each playbook
  is present in ``playbooks`` + ``playbook_positions`` with content
  matching the YAML byte-for-byte.
* **Executor smoke** — for each of the three playbooks, load the
  seeded playbook from the DB, build a synthetic contract document,
  run the executor with a stubbed gateway, assert all positions are
  classified.

The sample contracts are built inline rather than read from
``api/tests/fixtures/`` — matches the M3-A3 precedent and avoids
external file management. The M3-A5 spec mentioned a fixtures
directory but the M3-A3 precedent is the actual codebase pattern.

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

_BUILTIN_SLUGS: list[str] = ["msa-saas", "dpa-gdpr", "msa-commercial-purchase"]

_EXPECTED_NAMES: dict[str, str] = {
    "msa-saas": "MSA — SaaS (customer-perspective)",
    "dpa-gdpr": "DPA — GDPR (controller-to-processor)",
    "msa-commercial-purchase": "MSA — Commercial Services (purchase-side)",
}
_EXPECTED_CONTRACT_TYPES: dict[str, str] = {
    "msa-saas": "MSA-SaaS",
    "dpa-gdpr": "DPA-GDPR",
    "msa-commercial-purchase": "MSA-Commercial-Purchase",
}
_EXPECTED_POSITION_COUNTS: dict[str, int] = {
    "msa-saas": 11,
    "dpa-gdpr": 8,
    "msa-commercial-purchase": 10,
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
def test_playbook_has_expected_position_count(slug: str) -> None:
    """Position count matches the M3-A5 spec for each playbook."""
    parsed = _load_yaml(slug)
    positions = parsed.get("positions") or []
    expected = _EXPECTED_POSITION_COUNTS[slug]
    assert len(positions) == expected, (
        f"{slug}: expected {expected} positions, got {len(positions)}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_each_position_has_at_least_two_fallback_tiers(slug: str) -> None:
    """The M3-A5 spec inherits M3-A3's requirement of ≥2 fallback tiers per position."""
    parsed = _load_yaml(slug)
    for pos in parsed.get("positions") or []:
        tiers = pos.get("fallback_tiers") or []
        assert len(tiers) >= 2, (
            f"{slug}/{pos['issue']}: only {len(tiers)} fallback tier(s); spec requires ≥2."
        )


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_each_position_has_required_string_fields(slug: str) -> None:
    """Standard language, redline_strategy, severity, and detection_keywords are populated."""
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
def test_each_fallback_tier_has_required_fields(slug: str) -> None:
    """Each fallback tier has rank, description, and language."""
    parsed = _load_yaml(slug)
    for pos in parsed.get("positions") or []:
        for tier in pos.get("fallback_tiers") or []:
            assert isinstance(tier.get("rank"), int) and tier["rank"] >= 1, (
                f"{slug}/{pos['issue']}: fallback tier rank must be a positive int."
            )
            assert tier.get("description"), (
                f"{slug}/{pos['issue']}/rank={tier.get('rank')}: missing description."
            )
            assert tier.get("language"), (
                f"{slug}/{pos['issue']}/rank={tier.get('rank')}: missing language."
            )


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_position_order_is_dense_and_zero_indexed(slug: str) -> None:
    """Position order values are 0, 1, 2, ..., N-1 with no gaps."""
    parsed = _load_yaml(slug)
    positions = parsed.get("positions") or []
    orders = sorted(int(p.get("position_order", 0)) for p in positions)
    expected = list(range(len(positions)))
    assert orders == expected, f"{slug}: position_order values {orders} are not dense 0..N-1."


@pytest.mark.unit
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
def test_description_includes_not_legal_advice_disclaimer(slug: str) -> None:
    """Every M3-A5 playbook's description carries the Decision F disclaimer.

    Per Decision F (M3-A3) + the 2026-05-19 starting-point clarification,
    every built-in playbook's ``description`` must surface the
    not-legal-advice posture and reference professional judgment so it
    renders wherever the playbook is shown (list page, execute modal,
    result view).
    """
    parsed = _load_yaml(slug)
    desc = (parsed.get("description") or "").lower()
    assert "not legal advice" in desc, (
        f"{slug}/playbook.yaml: description must include the 'not legal advice' disclaimer."
    )
    # The M3-A5 playbooks make the starting-point framing more explicit
    # than M3-A3 did. Accept either "professional judgment" (M3-A3 idiom)
    # or "starting point" (M3-A5 idiom) so the test is forward-compatible
    # if M3-A3 descriptions are retro-updated.
    assert "professional judgment" in desc or "starting point" in desc, (
        f"{slug}/playbook.yaml: description must reference professional judgment or starting-point posture."
    )


# ---------------------------------------------------------------------------
# Migration round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
async def test_migration_seeded_playbook_row(db_session: AsyncSession, slug: str) -> None:
    """After migration 0033 runs, the playbook row exists with the YAML content."""
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
    """All positions are present after seeding with content matching the YAML."""
    parsed = _load_yaml(slug)
    expected_name = _EXPECTED_NAMES[slug]
    expected_count = _EXPECTED_POSITION_COUNTS[slug]

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
    assert len(positions) == expected_count, (
        f"{slug}: expected {expected_count} positions, got {len(positions)}"
    )

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
# Executor integration smoke (one per playbook)
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

    Mirrors the M3-A3 pattern: the integration smoke verifies the
    workflow runs end-to-end against the seeded playbook with all
    positions classified, but doesn't try to evaluate whether real
    classification works (that requires a live LLM and is the
    operator-attorney's responsibility per the starting-point posture).
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


# Synthetic contract texts per playbook. These exercise the executor's
# retrieval + classification path end-to-end against a representative
# document; they are deliberately minimal and not legally meaningful.
# The stubbed gateway returns 'missing' for every position regardless of
# document content, so the smoke test verifies workflow plumbing rather
# than classification correctness.
_SYNTHETIC_DOCS: dict[str, dict[str, Any]] = {
    "msa-saas": {
        "filename": "synthetic-saas-msa.pdf",
        "chunks": [
            "MASTER SERVICES AGREEMENT — Cloud Service. This Agreement is between Vendor and Customer.",
            "Service Level. Vendor will use commercially reasonable efforts to maintain 99.9% uptime.",
            "Security. Vendor maintains SOC 2 Type II certification and encrypts data in transit and at rest.",
            "Customer Data. Customer retains all right, title, and interest in and to Customer Data.",
            "Limitation of Liability. Each party's aggregate liability is capped at fees paid in the preceding 12 months.",
            "Indemnification. Vendor will defend Customer against third-party IP infringement claims.",
            "Termination. Either party may terminate for cause upon thirty days' notice and opportunity to cure.",
            "Governing Law. This Agreement is governed by the laws of the State of Delaware.",
        ],
    },
    "dpa-gdpr": {
        "filename": "synthetic-dpa.pdf",
        "chunks": [
            "DATA PROCESSING ADDENDUM. This DPA forms part of the Master Services Agreement.",
            "Processor will process Personal Data only on documented instructions from Controller.",
            "Article 32. Processor implements appropriate technical and organisational measures.",
            "Personal Data Breach. Processor will notify Controller without undue delay.",
            "International Transfers. The parties incorporate the EU Standard Contractual Clauses.",
            "Sub-processors. Controller grants general authorisation; Processor maintains the list.",
            "Audit Rights. Processor will provide its SOC 2 Type II report under NDA upon request.",
            "Deletion. At Controller's choice, Processor will delete or return Personal Data after services end.",
        ],
    },
    "msa-commercial-purchase": {
        "filename": "synthetic-commercial-msa.pdf",
        "chunks": [
            "MASTER SERVICES AGREEMENT — Professional Services. Between Customer and Vendor.",
            "Acceptance. Customer has thirty business days to test each Deliverable against the criteria.",
            "Warranties. Vendor warrants Services performed in a professional and workmanlike manner.",
            "Indemnification. Vendor will defend Customer against third-party IP infringement claims.",
            "Limitation of Liability. Each party's aggregate liability is capped at two times SOW fees.",
            "Work Product. Customer owns all right, title, and interest in and to the Work Product.",
            "Change Orders. Any scope change requires a written Change Order signed by both parties.",
            "Termination. Customer may terminate for convenience upon thirty days' written notice.",
            "Governing Law. This Agreement is governed by the laws of the State of Delaware.",
        ],
    },
}


async def _make_synthetic_doc(db: AsyncSession, slug: str, *, owner: User) -> Document:
    """Build a synthetic contract document for the playbook's contract type."""
    spec = _SYNTHETIC_DOCS[slug]
    f = FileModel(
        owner_id=owner.id,
        filename=spec["filename"],
        mime_type="application/pdf",
        size_bytes=2048,
        hash_sha256="f" * 64,
        storage_path=f"{slug}-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()

    chunks_text: list[str] = spec["chunks"]
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
@pytest.mark.parametrize("slug", _BUILTIN_SLUGS)
async def test_executor_runs_against_seeded_playbook(db_session: AsyncSession, slug: str) -> None:
    """End-to-end: load each M3-A5 playbook from DB and execute against a synthetic doc.

    Asserts:
    * Execution completes successfully (status='completed').
    * All positions in the seeded playbook are classified.
    * The stubbed gateway is called exactly once per position
      (no redline calls because all stubs return 'missing').

    This is a structural smoke test — it does not validate the legal
    correctness of any verdict (per the starting-point posture, that's
    the operator-attorney's responsibility).
    """
    owner = await _make_user(db_session)
    doc = await _make_synthetic_doc(db_session, slug, owner=owner)

    expected_name = _EXPECTED_NAMES[slug]
    pb = (
        await db_session.execute(
            select(Playbook).where(Playbook.name == expected_name, Playbook.version == "1.0.0")
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
    expected_count = _EXPECTED_POSITION_COUNTS[slug]
    assert len(list(positions)) == expected_count, (
        f"{slug}: expected {expected_count} positions in results, got {len(list(positions))}"
    )
    # One classify call per position; zero redline calls because every
    # stubbed verdict is 'missing' (redline only fires on 'deviates').
    assert len(gateway.calls_received) == expected_count
