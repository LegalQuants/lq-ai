import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.citation.gate import compute_and_record_gate, resolve_gates
from app.citation.ledger import assemble_ledger_entries
from app.models.chat import Chat, Message, MessageCitation
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.file import File as FileModel
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.message_tool_source import MessageToolSource
from app.models.user import User
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded(db_session):
    user = User(email=f"g-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="member")
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="gate")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="a")
    db_session.add(msg)
    await db_session.flush()
    return user, chat, msg


async def _seed_entry(db_session, chat, msg, status, conf, *, opinion_id):
    """Create an FK-valid caselaw-citation-backed ledger entry whose
    verification_status is overridden to ``status`` (the entry's status is what
    the gate reads — it need not equal the citation's real method)."""
    cc = MessageCaselawCitation(
        message_id=msg.id,
        opinion_id=opinion_id,
        cluster_id=opinion_id,
        source_offset_start=0,
        source_offset_end=3,
        source_text="abc",
        verified=True,
        verification_method="exact_match",
        verification_confidence=1.0,
    )
    db_session.add(cc)
    await db_session.flush()
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat.id,
            message_id=msg.id,
            source_kind="caselaw",
            message_caselaw_citation_id=cc.id,
            verification_status=status,
            confidence=conf,
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_all_pass_is_fiduciary_grade(db_session, seeded):
    _user, chat, msg = seeded
    # Seed ledger entries directly via real caselaw-citation rows so FKs resolve.
    for status, conf in [("exact_match", 1.0), ("tolerant_match", 0.95)]:
        cc = MessageCaselawCitation(
            message_id=msg.id,
            opinion_id=1,
            cluster_id=1,
            source_offset_start=0,
            source_offset_end=3,
            source_text="abc",
            verified=True,
            verification_method=status,
            verification_confidence=conf,
        )
        db_session.add(cc)
        await db_session.flush()
        db_session.add(
            CitationLedgerEntry(
                chat_id=chat.id,
                message_id=msg.id,
                source_kind="caselaw",
                message_caselaw_citation_id=cc.id,
                verification_status=status,
                confidence=conf,
            )
        )
    await db_session.flush()

    gate = await compute_and_record_gate(db_session, message_id=msg.id)
    assert gate is not None
    assert gate.gate_status == "fiduciary_grade"
    assert gate.pass_count == 2
    assert gate.supported_count == 0
    assert gate.fail_count == 0
    assert gate.total_assertions == 2
    assert abs(gate.confidence - 0.975) < 1e-6


@pytest.mark.asyncio
async def test_supported_only_when_paraphrase_no_fail(db_session, seeded):
    _user, chat, msg = seeded
    # one PASS (tolerant_match) + one SUPPORTED (paraphrase_judge), no FAIL
    await _seed_entry(db_session, chat, msg, "tolerant_match", 0.95, opinion_id=101)
    await _seed_entry(db_session, chat, msg, "paraphrase_judge", 0.8, opinion_id=102)

    gate = await compute_and_record_gate(db_session, message_id=msg.id)
    assert gate is not None
    assert gate.gate_status == "supported_only"
    assert gate.pass_count == 1
    assert gate.supported_count == 1
    assert gate.fail_count == 0
    assert gate.total_assertions == 2


@pytest.mark.asyncio
async def test_any_fail_is_flagged(db_session, seeded):
    _user, chat, msg = seeded
    # one PASS (exact_match, conf=1.0) + one FAIL (unverified, conf=None)
    await _seed_entry(db_session, chat, msg, "exact_match", 1.0, opinion_id=201)
    await _seed_entry(db_session, chat, msg, "unverified", None, opinion_id=202)

    gate = await compute_and_record_gate(db_session, message_id=msg.id)
    assert gate is not None
    assert gate.gate_status == "flagged"
    assert gate.pass_count == 1
    assert gate.supported_count == 0
    assert gate.fail_count == 1
    assert gate.total_assertions == 2
    # confidence = mean of non-null only: 1.0
    assert gate.confidence == 1.0


@pytest.mark.asyncio
async def test_provenance_excluded(db_session, seeded):
    _user, chat, msg = seeded
    # one PASS entry + one provenance entry (via a real MessageToolSource)
    await _seed_entry(db_session, chat, msg, "exact_match", 1.0, opinion_id=301)

    ts = MessageToolSource(
        message_id=msg.id,
        source_kind="caselaw",
        label="Cluster 301",
        subtitle=None,
        url=None,
        external_ref="301",
        provider="courtlistener",
        tool="get_cluster",
    )
    db_session.add(ts)
    await db_session.flush()
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat.id,
            message_id=msg.id,
            source_kind="caselaw",
            message_tool_source_id=ts.id,
            verification_status="provenance",
            confidence=None,
        )
    )
    await db_session.flush()

    gate = await compute_and_record_gate(db_session, message_id=msg.id)
    assert gate is not None
    assert gate.total_assertions == 1
    assert gate.pass_count == 1
    assert gate.gate_status == "fiduciary_grade"


@pytest.mark.asyncio
async def test_zero_assertions_is_fiduciary_grade(db_session, seeded):
    _user, chat, msg = seeded
    # only a provenance entry — no assertion entries
    ts = MessageToolSource(
        message_id=msg.id,
        source_kind="caselaw",
        label="Cluster 401",
        subtitle=None,
        url=None,
        external_ref="401",
        provider="courtlistener",
        tool="get_cluster",
    )
    db_session.add(ts)
    await db_session.flush()
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat.id,
            message_id=msg.id,
            source_kind="caselaw",
            message_tool_source_id=ts.id,
            verification_status="provenance",
            confidence=None,
        )
    )
    await db_session.flush()

    gate = await compute_and_record_gate(db_session, message_id=msg.id)
    assert gate is not None
    assert gate.gate_status == "fiduciary_grade"
    assert gate.total_assertions == 0
    assert gate.confidence is None


@pytest.mark.asyncio
async def test_unknown_status_excluded(db_session, seeded):
    _user, chat, msg = seeded
    # one valid PASS + one entry with unknown status "weird"
    await _seed_entry(db_session, chat, msg, "exact_match", 1.0, opinion_id=501)
    await _seed_entry(db_session, chat, msg, "weird", 0.5, opinion_id=502)

    gate = await compute_and_record_gate(db_session, message_id=msg.id)
    assert gate is not None
    # unknown is excluded; only the valid PASS counts
    assert gate.total_assertions == 1
    assert gate.pass_count == 1


@pytest.mark.asyncio
async def test_upsert_replaces(db_session, seeded):
    _user, chat, msg = seeded
    # First call: one exact_match (PASS) → fiduciary_grade
    await _seed_entry(db_session, chat, msg, "exact_match", 1.0, opinion_id=601)
    gate1 = await compute_and_record_gate(db_session, message_id=msg.id)
    assert gate1 is not None
    assert gate1.gate_status == "fiduciary_grade"

    # Add a FAIL entry and call again — second verdict should win
    await _seed_entry(db_session, chat, msg, "unverified", None, opinion_id=602)
    gate2 = await compute_and_record_gate(db_session, message_id=msg.id)
    assert gate2 is not None
    assert gate2.gate_status == "flagged"

    # Exactly one row remains for this message
    count = len(
        (
            await db_session.execute(
                select(WorkProductFiduciaryGate).where(
                    WorkProductFiduciaryGate.message_id == msg.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert count == 1


@pytest.mark.asyncio
async def test_resolve_gates_shapes(db_session, seeded):
    _user, chat, msg = seeded
    await _seed_entry(db_session, chat, msg, "exact_match", 1.0, opinion_id=701)
    await compute_and_record_gate(db_session, message_id=msg.id)

    # all turns in the chat
    results = await resolve_gates(db_session, chat_id=chat.id)
    assert len(results) == 1
    r = results[0]
    for key in (
        "message_id",
        "gate_status",
        "pass_count",
        "supported_count",
        "fail_count",
        "total_assertions",
        "confidence",
        "created_at",
    ):
        assert key in r, f"missing key: {key}"
    assert r["message_id"] == str(msg.id)

    # filtered by message_id
    filtered = await resolve_gates(db_session, chat_id=chat.id, message_id=msg.id)
    assert len(filtered) == 1

    # wrong message_id → empty
    empty = await resolve_gates(db_session, chat_id=chat.id, message_id=uuid.uuid4())
    assert empty == []


@pytest.mark.asyncio
async def test_assembler_marks_unverified_kb_citation(db_session, seeded):
    """Regression: an unverified KB citation must land as 'unverified', not 'verified'."""
    user, _chat, msg = seeded

    # Need a real File row for source_file_id FK
    f = FileModel(
        owner_id=user.id,
        filename="doc.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="a" * 64,
        storage_path=f"k/{uuid.uuid4().hex}",
    )
    db_session.add(f)
    await db_session.flush()

    # An unverified KB citation (verified=False, verification_method=None)
    doc_cite = MessageCitation(
        message_id=msg.id,
        source_file_id=f.id,
        source_offset_start=0,
        source_offset_end=5,
        source_page=1,
        source_text="hello",
        verified=False,
        verification_method=None,
        verification_confidence=None,
    )
    db_session.add(doc_cite)
    await db_session.flush()

    await assemble_ledger_entries(db_session, message_id=msg.id)
    await db_session.flush()

    entries = (
        (
            await db_session.execute(
                select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == msg.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
    e = entries[0]
    # The mislabel fix: must be "unverified", not "verified"
    assert e.verification_status == "unverified"
    assert e.confidence is None

    # And compute_and_record_gate should detect the FAIL
    gate = await compute_and_record_gate(db_session, message_id=msg.id)
    assert gate is not None
    assert gate.fail_count == 1
    assert gate.gate_status == "flagged"
