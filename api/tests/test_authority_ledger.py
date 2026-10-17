"""Authority citations → ledger assembly + resolve + gate (WS-E PR1b + DE-370).

Verifies:
- assemble_ledger_entries writes a CitationLedgerEntry for each
  MessageAuthorityCitation row (source_kind = content_kind, provider = source_type)
- an unverified authority citation produces gate_status == "flagged"
- resolve_ledger_entries returns a passage block with the source text
- DE-370 (attributed-authority FAIL tier): a chat blockquote attributed to a
  fetched authority that verifies nowhere persists a FAIL row and flags the
  gate; unattributed or non-fetched-attributed quotes keep drop-on-miss
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_loop import ToolSourceRecord
from app.citation.authority import (
    store_authority_text,
    verify_and_persist_authority_citations,
)
from app.citation.gate import compute_and_record_gate
from app.citation.ledger import assemble_ledger_entries, resolve_ledger_entries
from app.citation.verification import VerificationResult
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_authority_citation import (
    MessageAuthorityCitation,
)
from app.models.user import User

# ---------------------------------------------------------------------------
# Local helper — mirrors api/tests/citation/conftest.py `seeded` pattern
# ---------------------------------------------------------------------------


async def _message_and_chat(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Create minimal User → Chat → assistant Message; return (message_id, chat_id)."""
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db.add(user)
    await db.flush()
    chat = Chat(owner_id=user.id, title="t")
    db.add(chat)
    await db.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db.add(msg)
    await db.flush()
    return msg.id, chat.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_creates_authority_ledger_entry(
    db_session: AsyncSession,
) -> None:
    mid, _cid = await _message_and_chat(db_session)
    db_session.add(
        MessageAuthorityCitation(
            message_id=mid,
            source_type="govinfo",
            external_ref="USCODE-2022-title15",
            content_kind="statute",
            source_offset_start=0,
            source_offset_end=10,
            source_text="Every cont",
            verified=True,
            verification_method="exact_match",
            verification_confidence=1.0,
            partial=False,
        )
    )
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    rows = (
        (
            await db_session.execute(
                select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == mid)
            )
        )
        .scalars()
        .all()
    )
    entry = next(r for r in rows if r.message_authority_citation_id is not None)
    # source_kind = content_kind (the ledger label); provider = source_type (the source)
    assert entry.source_kind == "statute"
    assert entry.verification_status == "exact_match"
    assert entry.provider == "govinfo"


@pytest.mark.asyncio
async def test_authority_unverified_flags_gate(db_session: AsyncSession) -> None:
    mid, _cid = await _message_and_chat(db_session)
    db_session.add(
        MessageAuthorityCitation(
            message_id=mid,
            source_type="govinfo",
            external_ref="USCODE-x",
            content_kind="statute",
            source_offset_start=0,
            source_offset_end=5,
            source_text="bogus",
            verified=False,
            verification_method=None,
            partial=False,
        )
    )
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    gate = await compute_and_record_gate(db_session, message_id=mid)
    # unverified → verification_status="unverified" → FAIL bucket → gate_status="flagged"
    assert gate is not None
    assert gate.gate_status == "flagged"


@pytest.mark.asyncio
async def test_resolve_returns_authority_passage(db_session: AsyncSession) -> None:
    mid, cid = await _message_and_chat(db_session)
    db_session.add(
        MessageAuthorityCitation(
            message_id=mid,
            source_type="govinfo",
            external_ref="USCODE-2022-title15",
            content_kind="statute",
            source_offset_start=0,
            source_offset_end=10,
            source_text="Every cont",
            verified=True,
            verification_method="exact_match",
            verification_confidence=1.0,
            partial=False,
        )
    )
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    resolved = await resolve_ledger_entries(db_session, chat_id=cid, message_id=mid)
    # source_kind on the outer dict is the content_kind ("statute")
    auth = [e for e in resolved if e.get("source_kind") in {"statute", "regulation"}]
    assert auth, "expected at least one authority entry in resolved output"
    assert "Every cont" in str(auth[0].get("source", {}))


# ---------------------------------------------------------------------------
# DE-370 — attributed-authority FAIL tier (verify -> ledger -> gate)
# ---------------------------------------------------------------------------

_BODY = (
    "Notwithstanding the provisions of sections 106 and 106A, the fair use "
    "of a copyrighted work is not an infringement of copyright."
)
_FABRICATED = "the statute expressly bans all reproduction without a signed license."
_PACKAGE_ID = "USCODE-2022-title17"


def _govinfo_rec(ref: str = _PACKAGE_ID) -> ToolSourceRecord:
    return ToolSourceRecord(
        source_kind="statute",
        label="17 U.S.C. 107",
        subtitle="Fair use",
        url="u",
        external_ref=ref,
        provider="govinfo",
        tool="get_authority",
    )


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Object-storage fake (mirrors tests/citation/test_authority_verify.py)."""
    store: dict[str, bytes] = {}

    async def _upload(*, storage_path: str, body: bytes, content_type: str) -> None:
        store[storage_path] = body

    class _Reader:
        def __init__(self, data: bytes) -> None:
            self._data = data

        async def __aenter__(self) -> AsyncIterator[bytes]:
            data = self._data

            async def _gen() -> AsyncIterator[bytes]:
                yield data

            return _gen()

        async def __aexit__(self, *a: object) -> bool:
            return False

    def _download(*, storage_path: str) -> _Reader:
        return _Reader(store[storage_path])

    monkeypatch.setattr("app.citation.authority.upload_bytes", _upload)
    monkeypatch.setattr("app.citation.authority.stream_download", _download)
    return store


async def _seed_body(db: AsyncSession, ref: str = _PACKAGE_ID) -> None:
    await store_authority_text(db, source_type="govinfo", external_ref=ref, text=_BODY)


async def _rows_for(db: AsyncSession, mid: uuid.UUID) -> list[MessageAuthorityCitation]:
    return list(
        (
            await db.execute(
                select(MessageAuthorityCitation).where(MessageAuthorityCitation.message_id == mid)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_attributed_fabricated_quote_fails_and_flags_gate(
    db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """DE-370 core: a fabricated quote attributed (nearby cite) to a fetched
    authority persists a FAIL row and flags the fiduciary gate."""
    mid, _cid = await _message_and_chat(db_session)
    await _seed_body(db_session)
    text = f"Under 17 U.S.C. § 107:\n\n> {_FABRICATED}\n"
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=mid,
        assistant_text=text,
        tool_sources=[_govinfo_rec()],
        gateway=None,  # Pass B skipped -> fail-closed still FAILs
    )
    assert n == 1
    rows = await _rows_for(db_session, mid)
    assert len(rows) == 1
    row = rows[0]
    # The ledger_bridge FAIL-row shape, exactly:
    assert row.verified is False
    assert row.verification_method is None
    assert row.verification_confidence is None
    assert row.partial is False
    assert row.source_offset_start == 0
    assert row.source_offset_end == len(_FABRICATED)
    assert row.source_text == _FABRICATED
    assert row.source_type == "govinfo"
    assert row.external_ref == _PACKAGE_ID
    assert row.content_kind == "statute"

    await assemble_ledger_entries(db_session, message_id=mid)
    gate = await compute_and_record_gate(db_session, message_id=mid)
    assert gate is not None
    assert gate.gate_status == "flagged"


@pytest.mark.asyncio
async def test_attributed_verbatim_quote_still_passes(
    db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """An attributed quote that verbatim-matches keeps its PASS row — the
    FAIL tier never demotes a verified passage."""
    mid, _cid = await _message_and_chat(db_session)
    await _seed_body(db_session)
    text = f"Under 17 U.S.C. § 107:\n\n> {_BODY}\n"
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=mid,
        assistant_text=text,
        tool_sources=[_govinfo_rec()],
        gateway=None,
    )
    assert n == 1
    rows = await _rows_for(db_session, mid)
    assert len(rows) == 1
    assert rows[0].verified is True
    assert rows[0].verification_method in {"exact_match", "tolerant_match"}

    await assemble_ledger_entries(db_session, message_id=mid)
    gate = await compute_and_record_gate(db_session, message_id=mid)
    assert gate is not None
    assert gate.gate_status == "fiduciary_grade"


@pytest.mark.asyncio
async def test_unattributed_fabricated_quote_still_dropped(
    db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """No nearby citation -> unattributed -> drop-on-miss preserved (no row)."""
    mid, _cid = await _message_and_chat(db_session)
    await _seed_body(db_session)
    text = f"The statute provides:\n\n> {_FABRICATED}\n"
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=mid,
        assistant_text=text,
        tool_sources=[_govinfo_rec()],
        gateway=None,
    )
    assert n == 0
    assert await _rows_for(db_session, mid) == []


_CFR_BODY = (
    "Environmental documents shall concentrate on the issues that are truly "
    "significant to the action in question, rather than amassing needless detail."
)
_CFR_PACKAGE_ID = "CFR-2023-title40"


def _cfr_rec(ref: str = _CFR_PACKAGE_ID) -> ToolSourceRecord:
    return ToolSourceRecord(
        source_kind="regulation",
        label="40 CFR 1500.1",
        subtitle="Purpose",
        url="u",
        external_ref=ref,
        provider="govinfo",
        tool="get_authority",
    )


@pytest.mark.parametrize("cited_first", [True, False], ids=["cited-first", "cited-last"])
@pytest.mark.asyncio
async def test_misattributed_verbatim_quote_fails_and_flags_gate(
    db_session: AsyncSession, fake_storage: dict[str, bytes], cited_first: bool
) -> None:
    """A quote found only in B must FAIL when it cites A, in either ref order."""
    mid, _cid = await _message_and_chat(db_session)
    await _seed_body(db_session)
    await store_authority_text(
        db_session, source_type="govinfo", external_ref=_CFR_PACKAGE_ID, text=_CFR_BODY
    )
    refs = [_govinfo_rec(), _cfr_rec()]
    if not cited_first:
        refs.reverse()
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=mid,
        assistant_text=f"Under 17 U.S.C. § 107:\n\n> {_CFR_BODY}\n",
        tool_sources=refs,
        gateway=None,
    )
    # The quotation names A, so B's matching body is not a verified citation.
    assert n == 1
    rows = await _rows_for(db_session, mid)
    assert len(rows) == 1
    assert rows[0].external_ref == _PACKAGE_ID
    assert rows[0].verified is False
    assert rows[0].verification_method is None
    assert rows[0].source_text == _CFR_BODY

    await assemble_ledger_entries(db_session, message_id=mid)
    gate = await compute_and_record_gate(db_session, message_id=mid)
    assert gate is not None
    assert gate.gate_status == "flagged"
    assert gate.fail_count == 1
    assert gate.pass_count == 0


@pytest.mark.asyncio
async def test_body_load_failure_attributed_quote_fails_and_flags_gate(
    db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """F7: when the fetched authority's body fails to load (object storage
    error on download), an attributed fabricated quote persists a FAIL row
    instead of vanishing — "couldn't check" never becomes "passed"."""
    mid, _cid = await _message_and_chat(db_session)
    await _seed_body(db_session)
    fake_storage.clear()  # object storage errors on the cached-body download
    text = f"Under 17 U.S.C. § 107:\n\n> {_FABRICATED}\n"
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=mid,
        assistant_text=text,
        tool_sources=[_govinfo_rec()],
        gateway=None,
    )
    assert n == 1
    rows = await _rows_for(db_session, mid)
    assert len(rows) == 1
    row = rows[0]
    assert row.verified is False
    assert row.verification_method is None
    assert row.external_ref == _PACKAGE_ID
    assert row.source_text == _FABRICATED

    await assemble_ledger_entries(db_session, message_id=mid)
    gate = await compute_and_record_gate(db_session, message_id=mid)
    assert gate is not None
    assert gate.gate_status == "flagged"


@pytest.mark.asyncio
async def test_attribution_to_non_fetched_authority_dropped(
    db_session: AsyncSession, fake_storage: dict[str, bytes]
) -> None:
    """A quote attributed to an authority NOT fetched this turn (cite title
    doesn't match any fetched external_ref) stays dropped — uploaded-doc
    quotes can never FAIL spuriously."""
    mid, _cid = await _message_and_chat(db_session)
    await _seed_body(db_session)  # fetched: title 17
    text = f"Under 42 U.S.C. § 1983:\n\n> {_FABRICATED}\n"
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=mid,
        assistant_text=text,
        tool_sources=[_govinfo_rec()],
        gateway=None,
    )
    assert n == 0
    assert await _rows_for(db_session, mid) == []


@pytest.mark.parametrize("cited_first", [True, False], ids=["cited-first", "cited-last"])
@pytest.mark.asyncio
async def test_attributed_shared_verbatim_quote_is_order_invariant(
    db_session: AsyncSession, fake_storage: dict[str, bytes], cited_first: bool
) -> None:
    """Shared wording must verify against the cited source, regardless of fetch order."""
    mid, _cid = await _message_and_chat(db_session)
    await _seed_body(db_session)
    await store_authority_text(
        db_session,
        source_type="govinfo",
        external_ref=_CFR_PACKAGE_ID,
        text=f"Another fetched source includes the same wording: {_BODY}",
    )
    refs = [_govinfo_rec(), _cfr_rec()]
    if not cited_first:
        refs.reverse()
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=mid,
        assistant_text=f"Under 17 U.S.C. § 107:\n\n> {_BODY}\n",
        tool_sources=refs,
        gateway=None,
    )
    assert n == 1
    rows = await _rows_for(db_session, mid)
    assert len(rows) == 1
    assert rows[0].external_ref == _PACKAGE_ID
    assert rows[0].verified is True
    assert rows[0].verification_method == "exact_match"

    await assemble_ledger_entries(db_session, message_id=mid)
    gate = await compute_and_record_gate(db_session, message_id=mid)
    assert gate is not None
    assert gate.gate_status == "fiduciary_grade"
    assert gate.pass_count == 1
    assert gate.fail_count == 0


@pytest.mark.parametrize("cited_first", [True, False], ids=["cited-first", "cited-last"])
@pytest.mark.parametrize("other_has_verbatim", [False, True], ids=["both-judge", "other-exact"])
@pytest.mark.asyncio
async def test_attributed_paraphrase_is_order_invariant(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    cited_first: bool,
    other_has_verbatim: bool,
) -> None:
    """Another source's exact/supporting match cannot suppress the cited judge check."""
    mid, _cid = await _message_and_chat(db_session)
    await _seed_body(db_session)
    paraphrase = "Fair use permits reproduction of a protected work without infringement."
    assert paraphrase not in _BODY
    other_body = f"Another fetched source states: {_BODY}"
    if other_has_verbatim:
        other_body += f" {paraphrase}"
    await store_authority_text(
        db_session, source_type="govinfo", external_ref=_CFR_PACKAGE_ID, text=other_body
    )
    judged_bodies: list[str] = []

    async def _estimate(db: object, *, judge_model: str, authority_text: str) -> Decimal:
        return Decimal("0.001")

    async def _judge(
        *, passage: str, authority_text: str, gateway: object, judge_model: str
    ) -> VerificationResult:
        assert passage == paraphrase
        judged_bodies.append(authority_text)
        return VerificationResult(
            verified=True, method="paraphrase_judge", confidence=0.9, partial=True
        )

    monkeypatch.setattr(
        "app.citation.authority_content_judge.estimate_authority_content_cost_usd",
        _estimate,
    )
    monkeypatch.setattr("app.citation.authority_content_judge.judge_authority_content", _judge)
    refs = [_govinfo_rec(), _cfr_rec()]
    if not cited_first:
        refs.reverse()
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=mid,
        assistant_text=f"Under 17 U.S.C. § 107:\n\n> {paraphrase}\n",
        tool_sources=refs,
        gateway=object(),
    )
    assert n == 1
    assert judged_bodies == [_BODY]
    rows = await _rows_for(db_session, mid)
    assert len(rows) == 1
    assert rows[0].external_ref == _PACKAGE_ID
    assert rows[0].verified is True
    assert rows[0].verification_method == "paraphrase_judge"

    await assemble_ledger_entries(db_session, message_id=mid)
    gate = await compute_and_record_gate(db_session, message_id=mid)
    assert gate is not None
    assert gate.gate_status == "supported_only"
    assert gate.supported_count == 1
    assert gate.fail_count == 0
