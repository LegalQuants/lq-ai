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

import logging
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous import ledger_bridge
from app.autonomous.ledger_bridge import build_session_ledger
from app.citation.authority import store_authority_text
from app.citation.verification import VerificationResult
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


# ---------------------------------------------------------------------------
# DE-371: autonomous-path SUPPORTED tier (budgeted whole-body paraphrase judge)
# ---------------------------------------------------------------------------

_FABRICATED_QUOTE = "the statute expressly permits price fixing"

_SUPPORTED_RESULT = VerificationResult(
    verified=True, method="paraphrase_judge", confidence=0.9, partial=True
)
_MISS_RESULT = VerificationResult(verified=False, method=None, confidence=None)


async def _fetch_rows(
    db: AsyncSession, external_ref: str = "USCODE-2022-title15"
) -> list[MessageAuthorityCitation]:
    return list(
        (
            await db.execute(
                select(MessageAuthorityCitation).where(
                    MessageAuthorityCitation.external_ref == external_ref
                )
            )
        )
        .scalars()
        .all()
    )


async def test_locate_hit_calls_verify_with_gateway_none(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DE-371: on a locate hit, verify() must run verbatim-only (gateway=None) —
    the judge stage is structurally unreachable after a successful locate, so
    passing the real gateway through would be dishonest. PASS row unchanged."""
    from app.citation.verification import verify as real_verify

    seen_gateways: list[object] = []

    async def _spy(cand: object, target: object, **kwargs: object) -> VerificationResult:
        seen_gateways.append(kwargs.get("gateway"))
        return await real_verify(cand, target, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ledger_bridge, "verify", _spy)

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
        gateway=object(),  # a live gateway must still NOT reach verify()
    )
    assert out is not None and out["pass_count"] >= 1 and out["fail_count"] == 0
    assert seen_gateways == [None]


async def test_locate_miss_judge_supported_writes_supported_row(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DE-371: locate miss + supporting judge verdict → SUPPORTED row
    (paraphrase_judge, partial=True, whole-body offsets), no FAIL row, and the
    gate buckets it SUPPORTED (supported_only, not flagged)."""
    judge_calls: list[dict[str, object]] = []

    async def _fake_judge(
        *, passage: str, authority_text: str, gateway: object, judge_model: str
    ) -> VerificationResult:
        judge_calls.append({"passage": passage, "authority_text": authority_text})
        return _SUPPORTED_RESULT

    monkeypatch.setattr(ledger_bridge, "judge_authority_content", _fake_judge)

    sess = await _make_session(db_session)
    await store_authority_text(
        db_session,
        source_type="govinfo",
        external_ref="USCODE-2022-title15",
        text=_BODY,
    )
    findings = [
        {
            "text": "paraphrase",
            "citations": [{"quote": _FABRICATED_QUOTE, "source": 1}],
        }
    ]
    out = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="…",
        findings=findings,
        evidence=_evidence(),
        gateway=object(),
    )
    assert out is not None
    assert out["supported_count"] == 1
    assert out["fail_count"] == 0
    assert out["gate_status"] == "supported_only"
    assert judge_calls == [{"passage": _FABRICATED_QUOTE, "authority_text": _BODY}]

    rows = await _fetch_rows(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.verified is True
    assert row.verification_method == "paraphrase_judge"
    assert row.partial is True
    assert row.verification_confidence == pytest.approx(0.9)
    # Whole-body placeholder offsets, exactly like chat's Pass B rows.
    assert row.source_offset_start == 0
    assert row.source_offset_end == len(_BODY)


async def test_locate_miss_judge_unsupported_keeps_fail_row(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DE-371: locate miss + non-supporting verdict → FAIL row, unchanged shape."""

    async def _fake_judge(**kwargs: object) -> VerificationResult:
        return _MISS_RESULT

    monkeypatch.setattr(ledger_bridge, "judge_authority_content", _fake_judge)

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
            "citations": [{"quote": _FABRICATED_QUOTE, "source": 1}],
        }
    ]
    out = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="…",
        findings=findings,
        evidence=_evidence(),
        gateway=object(),
    )
    assert out is not None and out["fail_count"] >= 1 and out["gate_status"] == "flagged"

    rows = await _fetch_rows(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.verified is False
    assert row.verification_method is None
    assert row.verification_confidence is None
    assert row.partial is False
    assert row.source_offset_start == 0
    assert row.source_offset_end == len(_FABRICATED_QUOTE)


async def test_locate_miss_judge_raises_keeps_fail_row(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DE-371: a raising judge (documented never to raise, but defended) keeps
    the FAIL row — fail-closed."""

    async def _raising_judge(**kwargs: object) -> VerificationResult:
        raise RuntimeError("judge exploded")

    monkeypatch.setattr(ledger_bridge, "judge_authority_content", _raising_judge)

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
            "citations": [{"quote": _FABRICATED_QUOTE, "source": 1}],
        }
    ]
    out = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="…",
        findings=findings,
        evidence=_evidence(),
        gateway=object(),
    )
    assert out is not None and out["fail_count"] >= 1 and out["gate_status"] == "flagged"

    rows = await _fetch_rows(db_session)
    assert len(rows) == 1 and rows[0].verified is False


async def test_budget_exhaustion_mid_turn_skips_later_judges(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DE-371: cumulative spend against AUTHORITY_CONTENT_JUDGE_BUDGET_USD —
    once the pre-flight estimate would exceed the budget, later misses skip the
    judge, keep FAIL rows, and log the budget-exhausted event."""
    judge_calls: list[str] = []

    # Each call estimated at 0.20 USD against the 0.25 budget: the first miss
    # is judged (0.20 <= 0.25), the second would total 0.40 > 0.25 → skipped.
    async def _fake_estimate(db: object, *, judge_model: str, authority_text: str) -> Decimal:
        return Decimal("0.20")

    async def _fake_judge(
        *, passage: str, authority_text: str, gateway: object, judge_model: str
    ) -> VerificationResult:
        judge_calls.append(passage)
        return _SUPPORTED_RESULT

    monkeypatch.setattr(ledger_bridge, "estimate_authority_content_cost_usd", _fake_estimate)
    monkeypatch.setattr(ledger_bridge, "judge_authority_content", _fake_judge)

    sess = await _make_session(db_session)
    await store_authority_text(
        db_session,
        source_type="govinfo",
        external_ref="USCODE-2022-title15",
        text=_BODY,
    )
    second_quote = "another quote that appears nowhere in the body"
    findings = [
        {
            "text": "bogus",
            "citations": [
                {"quote": _FABRICATED_QUOTE, "source": 1},
                {"quote": second_quote, "source": 1},
            ],
        }
    ]
    with caplog.at_level(logging.INFO, logger="app.autonomous.ledger_bridge"):
        out = await build_session_ledger(
            db_session,
            session=sess,
            work_product_text="…",
            findings=findings,
            evidence=_evidence(),
            gateway=object(),
        )
    assert out is not None
    # First miss judged → SUPPORTED; second skipped on budget → FAIL.
    assert judge_calls == [_FABRICATED_QUOTE]
    assert out["supported_count"] == 1
    assert out["fail_count"] == 1
    assert any(
        getattr(r, "event", None) == "autonomous_authority_citation_judge_budget_exhausted"
        for r in caplog.records
    )

    rows = await _fetch_rows(db_session)
    by_quote = {r.source_text: r for r in rows}
    assert by_quote[_FABRICATED_QUOTE].verified is True
    assert by_quote[second_quote].verified is False


async def test_gateway_none_keeps_fail_rows_without_judge(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DE-371 regression: gateway=None → judge never invoked; FAIL rows exactly
    as before (test_fabricated_authority_quote_flags_gate covers the gate)."""

    async def _must_not_run(**kwargs: object) -> VerificationResult:
        raise AssertionError("judge must not be called when gateway is None")

    monkeypatch.setattr(ledger_bridge, "judge_authority_content", _must_not_run)

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
            "citations": [{"quote": _FABRICATED_QUOTE, "source": 1}],
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

    rows = await _fetch_rows(db_session)
    assert len(rows) == 1
    assert rows[0].verified is False
    assert rows[0].verification_method is None


async def test_cost_estimate_error_keeps_fail_row(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DE-371 regression: a raising pre-flight cost estimate must degrade to
    "no judge, keep the FAIL row" — not skip the item entirely (zero rows would
    read as fiduciary_grade at the gate)."""

    async def _raising_estimate(db: object, *, judge_model: str, authority_text: str) -> Decimal:
        raise RuntimeError("routing-log query exploded")

    async def _must_not_run(**kwargs: object) -> VerificationResult:
        raise AssertionError("judge must not be called when the cost estimate fails")

    monkeypatch.setattr(ledger_bridge, "estimate_authority_content_cost_usd", _raising_estimate)
    monkeypatch.setattr(ledger_bridge, "judge_authority_content", _must_not_run)

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
            "citations": [{"quote": _FABRICATED_QUOTE, "source": 1}],
        }
    ]
    out = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="…",
        findings=findings,
        evidence=_evidence(),
        gateway=object(),
    )
    assert out is not None and out["fail_count"] >= 1 and out["gate_status"] == "flagged"

    rows = await _fetch_rows(db_session)
    assert len(rows) == 1
    assert rows[0].verified is False
    assert rows[0].verification_method is None
