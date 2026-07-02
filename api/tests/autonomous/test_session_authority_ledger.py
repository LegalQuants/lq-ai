"""TDD tests for build_authority_citations + build_session_ledger authority branch.

Tests the authority half of the ledger bridge: given authority evidence from
the agentic loop (kind="authority", source="govinfo", content_kind="statute"),
build_session_ledger routes the citation into build_authority_citations, which
verifies the quote against the durable cache and persists a
MessageAuthorityCitation row → CitationLedgerEntry → gate verdict.

Three scenarios:
(a) Verbatim quote, cache seeded → verified row → gate pass_count >= 1.
(b) Fabricated quote, cache seeded → no-locate FAIL row → gate fail_count >= 1,
    gate_status == "flagged".
(c) Cache miss, carried content used → still verified → gate pass_count >= 1.

Object storage is backed by the in-memory fake fixture from
test_authority_cache_write.py, patching upload_bytes/stream_download at the
app.citation.authority import point.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.ledger_bridge import build_session_ledger
from app.citation.authority import store_authority_text
from app.models.autonomous import AutonomousSession
from app.models.message_authority_citation import MessageAuthorityCitation
from app.models.user import User
from app.security import hash_password

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# A phrase that appears verbatim so locate_passage + exact-match verify pass.
_BODY = "Every contract, combination ... in restraint of trade ... is declared to be illegal."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_session(db: AsyncSession) -> AutonomousSession:
    """Create a minimal User + AutonomousSession; returns the session."""
    user = User(
        email=f"auth-sl-{uuid.uuid4().hex[:6]}@x.com",
        hashed_password=hash_password("p"),
        role="member",
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual", params={"query": "q"})
    db.add(sess)
    await db.flush()
    return sess


def _evidence() -> list[dict]:  # type: ignore[type-arg]
    return [
        {
            "n": 1,
            "kind": "authority",
            "ref": "USCODE-2022-title15",
            "content": _BODY,
            "display": "15 U.S.C. § 1",
            "source": "govinfo",
        }
    ]


# ---------------------------------------------------------------------------
# Object-storage fake (mirrors test_authority_cache_write.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """In-memory object-store double so store_authority_text/load_authority_text succeed."""
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_verbatim_authority_quote_verified_and_counted(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
) -> None:
    """Verbatim quote found in seeded cache body → verified row → pass_count >= 1, fail_count == 0."""
    sess = await _make_session(db_session)
    await store_authority_text(
        db_session,
        source_type="govinfo",
        external_ref="USCODE-2022-title15",
        text=_BODY,
    )
    findings = [
        {
            "text": "The statute bars restraint of trade.",
            "citations": [{"quote": "in restraint of trade", "source": 1}],
        }
    ]
    out = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="… in restraint of trade …",
        findings=findings,
        evidence=_evidence(),
        gateway=None,
    )
    assert out is not None and out["pass_count"] >= 1 and out["fail_count"] == 0


async def test_fabricated_authority_quote_flags_gate(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
) -> None:
    """Fabricated quote not found in body → FAIL row → fail_count >= 1, gate_status == 'flagged'."""
    sess = await _make_session(db_session)
    await store_authority_text(
        db_session,
        source_type="govinfo",
        external_ref="USCODE-2022-title15",
        text=_BODY,
    )
    findings = [
        {
            "text": "bogus",
            "citations": [{"quote": "the statute expressly permits price fixing", "source": 1}],
        }
    ]
    out = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="…",
        findings=findings,
        evidence=_evidence(),
        gateway=None,
    )
    assert out is not None and out["fail_count"] >= 1 and out["gate_status"] == "flagged"


async def test_cache_miss_falls_back_to_carried_content(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
) -> None:
    """Cache miss: load_authority_text returns None → falls back to ev['content'] → verified."""
    sess = await _make_session(db_session)
    # Do NOT seed the cache → load_authority_text returns None → fallback to ev["content"]
    findings = [
        {
            "text": "…",
            "citations": [{"quote": "in restraint of trade", "source": 1}],
        }
    ]
    out = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="…",
        findings=findings,
        evidence=_evidence(),
        gateway=None,
    )
    assert out is not None and out["pass_count"] >= 1


# ---------------------------------------------------------------------------
# DE-371: autonomous carry-through — EDGAR evidence must keep content_kind
# "sec_filing", not fall back to build_authority_citations' "statute" default.
# ---------------------------------------------------------------------------

_EDGAR_BODY = (
    "Item 1A. Risk Factors. Our business is subject to numerous risks and "
    "uncertainties, including those highlighted in this Annual Report on Form 10-K."
)


def _edgar_evidence() -> list[dict]:  # type: ignore[type-arg]
    """Mirrors dataclasses.asdict(EvidenceItem(...)) for an EDGAR authority hit:
    source="edgar", content_kind="sec_filing" (both always set by EdgarAdapter,
    per app/research/adapters.py)."""
    return [
        {
            "n": 1,
            "kind": "authority",
            "ref": "0000320193-24-000123",
            "content": _EDGAR_BODY,
            "display": "Apple Inc. 10-K (sec_filing)",
            "source": "edgar",
            "content_kind": "sec_filing",
        }
    ]


async def test_autonomous_edgar_authority_content_kind_not_forced_to_statute(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
) -> None:
    """DE-371: an EDGAR evidence item carries content_kind="sec_filing" end to
    end — build_session_ledger/build_authority_citations must NOT default it
    to "statute" when the evidence explicitly supplies a different kind."""
    sess = await _make_session(db_session)
    await store_authority_text(
        db_session,
        source_type="edgar",
        external_ref="0000320193-24-000123",
        text=_EDGAR_BODY,
    )
    findings = [
        {
            "text": "The filing discloses risk factors.",
            "citations": [{"quote": "Item 1A. Risk Factors", "source": 1}],
        }
    ]
    out = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="… Item 1A. Risk Factors …",
        findings=findings,
        evidence=_edgar_evidence(),
        gateway=None,
    )
    assert out is not None and out["pass_count"] >= 1

    rows = (
        (
            await db_session.execute(
                select(MessageAuthorityCitation).where(
                    MessageAuthorityCitation.external_ref == "0000320193-24-000123"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].content_kind == "sec_filing"
    assert rows[0].source_type == "edgar"


async def test_autonomous_missing_content_kind_falls_back_to_unknown_not_statute(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
) -> None:
    """DE-371: when an evidence dict genuinely lacks a content_kind (e.g. a
    stale/legacy session predating PR1b's content_kind threading), the
    ledger bridge must NOT confidently mislabel it "statute" — that is an
    overclaim for a source (edgar) that is never a statute. It should fall
    back to "unknown" (honest non-claim), matching how the rest of the
    codebase signals an unrecognised content kind (see
    app.research.adapters._content_kind_from_id).

    This is the actual hardcoded-default bug: build_session_ledger's
    ``ev.get("content_kind") or "statute"`` (ledger_bridge.py, in the
    authority branch of the evidence-splitting loop) forces "statute" for
    ANY evidence item missing the key, regardless of source.
    """
    sess = await _make_session(db_session)
    await store_authority_text(
        db_session,
        source_type="edgar",
        external_ref="0000320193-24-000123",
        text=_EDGAR_BODY,
    )
    findings = [
        {
            "text": "The filing discloses risk factors.",
            "citations": [{"quote": "Item 1A. Risk Factors", "source": 1}],
        }
    ]
    evidence = [
        {
            "n": 1,
            "kind": "authority",
            "ref": "0000320193-24-000123",
            "content": _EDGAR_BODY,
            "display": "Apple Inc. 10-K",
            "source": "edgar",
            # content_kind deliberately absent.
        }
    ]
    out = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="… Item 1A. Risk Factors …",
        findings=findings,
        evidence=evidence,
        gateway=None,
    )
    assert out is not None and out["pass_count"] >= 1

    rows = (
        (
            await db_session.execute(
                select(MessageAuthorityCitation).where(
                    MessageAuthorityCitation.external_ref == "0000320193-24-000123"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].content_kind == "unknown"
    assert rows[0].content_kind != "statute"
