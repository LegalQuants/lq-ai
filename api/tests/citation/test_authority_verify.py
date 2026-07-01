"""Tests for verify_and_persist_authority_citations (WS-E PR1c chat finalize hook).

Mirrors tests/integration/test_caselaw_citations.py's orchestrator tests (message
seeding) and tests/test_authority_substrate.py's fake object-storage fixture
(store_authority_text hits real object storage otherwise).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_loop import ToolSourceRecord
from app.citation.authority import store_authority_text, verify_and_persist_authority_citations
from app.models.chat import Chat, Message
from app.models.message_authority_citation import MessageAuthorityCitation
from app.models.user import User
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionResponse,
    ChatCompletionUsage,
)
from app.security import hash_password

_BODY = (
    "Notwithstanding the provisions of sections 106 and 106A, the fair use "
    "of a copyrighted work is not an infringement of copyright."
)


def _rec(kind: str = "statute", ref: str = "USCODE-2022-title17") -> ToolSourceRecord:
    return ToolSourceRecord(
        source_kind=kind,
        label="17 U.S.C. 107",
        subtitle="Fair use",
        url="u",
        external_ref=ref,
        provider="govinfo",
        tool="get_authority",
    )


# ---------------------------------------------------------------------------
# Object-storage fake (mirrors fake_storage from tests/test_authority_substrate.py,
# patching upload_bytes/stream_download at the app.citation.authority import point).
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
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


@pytest_asyncio.fixture
async def seeded_authority_cache(db_session: AsyncSession, fake_storage: dict[str, bytes]) -> None:
    """Store _BODY under (govinfo, USCODE-2022-title17) in the fake cache."""
    await store_authority_text(
        db_session, source_type="govinfo", external_ref="USCODE-2022-title17", text=_BODY
    )


@pytest_asyncio.fixture
async def seeded_message(db_session: AsyncSession) -> uuid.UUID:
    """Seed a user + chat + assistant message; return the message id."""
    user = User(
        email=f"authority-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Authority Test User",
        hashed_password=hash_password("hunter2"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()

    chat = Chat(owner_id=user.id, project_id=None, title="authority-chat")
    db_session.add(chat)
    await db_session.flush()

    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="relevant passage")
    db_session.add(msg)
    await db_session.flush()

    return msg.id


class _StubJudgeGateway:
    """Records calls and returns a canned chat-completion judge verdict.

    Matches the real protocol app.citation.verification.verify_paraphrase calls:
    ``await gateway.chat_completion(request)`` returning a ChatCompletionResponse
    whose ``choices[0].message.content`` is a JSON string
    ``{"verdict": "yes"|"partial"|"no", "confidence": "high"|"medium"|"low"}``.
    """

    def __init__(self, *, verdict: str = "yes", confidence: str = "high") -> None:
        self._verdict = verdict
        self._confidence = confidence
        self.call_count = 0

    async def chat_completion(self, request: object, *, request_id: str | None = None) -> object:
        self.call_count += 1
        model = getattr(request, "model", "fast")
        return ChatCompletionResponse(
            id="chatcmpl-judge",
            created=0,
            model=model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionMessage(
                        role="assistant",
                        content=json.dumps(
                            {"verdict": self._verdict, "confidence": self._confidence}
                        ),
                    ),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verbatim_quote_persists_pass_row(
    db_session: AsyncSession,
    seeded_message: uuid.UUID,
    seeded_authority_cache: None,
) -> None:
    message_id = seeded_message
    text = f"The statute provides:\n\n> {_BODY}\n\nThat is the rule."
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=message_id,
        assistant_text=text,
        tool_sources=[_rec()],
        gateway=None,
    )
    assert n == 1
    rows = (
        (
            await db_session.execute(
                select(MessageAuthorityCitation).where(
                    MessageAuthorityCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].verified is True
    assert rows[0].verification_method in {"exact_match", "tolerant_match"}
    assert rows[0].content_kind == "statute"
    assert rows[0].source_type == "govinfo"
    assert rows[0].external_ref == "USCODE-2022-title17"


@pytest.mark.asyncio
async def test_quote_matching_no_body_is_dropped(
    db_session: AsyncSession,
    seeded_message: uuid.UUID,
    seeded_authority_cache: None,
) -> None:
    message_id = seeded_message
    text = "> This sentence appears in no fetched authority body whatsoever."
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=message_id,
        assistant_text=text,
        tool_sources=[_rec()],
        gateway=None,
    )
    assert n == 0  # drop-on-miss: NO row (no false-FAIL)


@pytest.mark.asyncio
async def test_cache_miss_ref_skipped(
    db_session: AsyncSession,
    seeded_message: uuid.UUID,
) -> None:
    message_id = seeded_message
    text = f"> {_BODY}"
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=message_id,
        assistant_text=text,
        tool_sources=[_rec(ref="USCODE-NOT-CACHED")],
        gateway=None,
    )
    assert n == 0


@pytest.mark.asyncio
async def test_no_authority_refs_returns_zero(
    db_session: AsyncSession,
    seeded_message: uuid.UUID,
) -> None:
    message_id = seeded_message
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=message_id,
        assistant_text=f"> {_BODY}",
        tool_sources=[],
        gateway=None,
    )
    assert n == 0


@pytest.mark.asyncio
async def test_paraphrase_supported_via_stub_gateway(
    db_session: AsyncSession,
    seeded_message: uuid.UUID,
    seeded_authority_cache: None,
) -> None:
    """Pass B: a passage that does NOT appear verbatim in the fetched body
    (so Pass A drops it) is judged against the whole body by the stub
    gateway's judge, which accepts -> a paraphrase_judge SUPPORTED row.

    This is the load-bearing correctness check: it asserts the judge was
    actually invoked (gateway.call_count >= 1), not merely that some row
    landed via whichever tier happened to catch it.
    """
    message_id = seeded_message
    # Paraphrased, not a substring of _BODY -> Pass A's locate_passage misses.
    text = "> unauthorized reproduction of protected works is permitted under the fair use doctrine"
    assert text.strip("> ") not in _BODY

    gateway = _StubJudgeGateway(verdict="yes", confidence="high")
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=message_id,
        assistant_text=text,
        tool_sources=[_rec()],
        gateway=gateway,
        judge_model="fast",
    )
    assert n == 1
    assert gateway.call_count >= 1
    rows = (
        (
            await db_session.execute(
                select(MessageAuthorityCitation).where(
                    MessageAuthorityCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].verification_method == "paraphrase_judge"
    assert rows[0].verified is True
    assert rows[0].partial is True


@pytest.mark.asyncio
async def test_paraphrase_budget_cap(
    db_session: AsyncSession,
    seeded_message: uuid.UUID,
    seeded_authority_cache: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the pre-flight cost estimate exceeds the Pass-B budget, no judge
    calls are made and no SUPPORTED rows are persisted."""
    from decimal import Decimal

    async def _huge_estimate(db: object, *, judge_model: str, authority_text: str) -> Decimal:
        return Decimal("999")

    monkeypatch.setattr(
        "app.citation.authority_content_judge.estimate_authority_content_cost_usd",
        _huge_estimate,
    )

    message_id = seeded_message
    text = "> unauthorized reproduction of protected works is permitted under the fair use doctrine"
    gateway = _StubJudgeGateway(verdict="yes", confidence="high")
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=message_id,
        assistant_text=text,
        tool_sources=[_rec()],
        gateway=gateway,
        judge_model="fast",
    )
    assert n == 0
    assert gateway.call_count == 0


@pytest.mark.asyncio
async def test_gateway_none_skips_pass_b(
    db_session: AsyncSession,
    seeded_message: uuid.UUID,
    seeded_authority_cache: None,
) -> None:
    """gateway=None: only Pass A (verbatim) can run; a paraphrased quote
    that misses verbatim matching is dropped deterministically, no judge
    call is possible."""
    message_id = seeded_message
    text = "> unauthorized reproduction of protected works is permitted under the fair use doctrine"
    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=message_id,
        assistant_text=text,
        tool_sources=[_rec()],
        gateway=None,
    )
    assert n == 0
