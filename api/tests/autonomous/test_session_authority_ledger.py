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
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.ledger_bridge import build_session_ledger
from app.citation.authority import store_authority_text
from app.models.autonomous import AutonomousSession
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
