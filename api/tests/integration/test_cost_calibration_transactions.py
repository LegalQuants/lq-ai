"""Issue #747: real chat-finalization commits after a calibration SQL failure.

These tests deliberately bypass db_session's externally owned transaction and
savepoint-restart listener. The application owns its commits; separate database
connections check both the pre-commit boundary and durable results afterwards.
"""

from __future__ import annotations

import json
import uuid
from functools import partial
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import chats
from app.chat.tool_loop import LoopFinal, ToolSourceRecord
from app.chat.tool_schemas import ChatToolAllowlist, ToolSpec
from app.citation.authority import verify_and_persist_authority_citations
from app.citation.cost import invalidate_cache
from app.citation.verification import VerificationResult
from app.clients.gateway import GatewayClient
from app.models.audit import AuditLog
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_authority_citation import MessageAuthorityCitation
from app.models.message_tool_source import MessageToolSource
from app.models.user import User
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

pytestmark = pytest.mark.integration

_BODY = (
    "Notwithstanding the provisions of sections 106 and 106A, the fair use "
    "of a copyrighted work is not an infringement of copyright."
)
_PARAPHRASE = "Fair use permits reproduction of a protected work without infringement."
_ANSWER = f"Under 17 U.S.C. § 107:\n\n> {_PARAPHRASE}\n"


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
@pytest.mark.parametrize(
    ("judge_supports", "expected_gate"),
    [(True, "supported_only"), (False, "flagged")],
    ids=["supported", "rejected"],
)
async def test_chat_finalization_commits_after_calibration_sql_failure(
    isolated_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    stream: bool,
    judge_supports: bool,
    expected_gate: str,
) -> None:
    """Recover only the optional read, then commit citations, gate and audit.

    Tool-source provenance is flushed before the failed lookup in the same
    transaction. It must survive the recovery, remain invisible to another
    connection before the finalizer's audit commit, and become visible with
    the citation/ledger/gate/audit afterwards. No test-side commit repairs the
    application path, and closing the writer rolls back any uncommitted work.
    """
    engine = create_async_engine(isolated_db_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    failure_injected = False
    audit_checked = False

    def fail_calibration_once(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> tuple[str, Any]:
        nonlocal failure_injected
        if not failure_injected and "avg(" in statement.lower():
            failure_injected = True
            # A real server-side error: the helper must recover PostgreSQL's
            # aborted transaction state, rather than merely catch a fake error.
            return "SELECT 1/0", ()
        return statement, parameters

    event.listen(engine.sync_engine, "before_cursor_execute", fail_calibration_once, retval=True)
    invalidate_cache()
    try:
        async with sessions() as writer:
            user = User(email=f"calibration-{uuid.uuid4().hex}@example.com", hashed_password="x")
            writer.add(user)
            await writer.flush()
            chat = Chat(owner_id=user.id, title="calibration recovery")
            writer.add(chat)
            await writer.flush()
            user_message = Message(
                chat_id=chat.id, role="user", kind="user", content="Explain fair use"
            )
            writer.add(user_message)
            await writer.commit()
            assistant_id = uuid.uuid4()

            outcome = LoopFinal(
                text=_ANSWER,
                tier=3,
                provider="test-provider",
                model="test-model",
                tool_sources=[
                    ToolSourceRecord(
                        source_kind="statute",
                        label="17 U.S.C. 107",
                        subtitle="Fair use",
                        url=None,
                        external_ref="USCODE-2022-title17",
                        provider="govinfo",
                        tool="get_authority",
                    )
                ],
            )
            gateway = AsyncMock(spec=GatewayClient)
            gateway.get_citation_engine_judge_model.return_value = "test-judge"
            judge = AsyncMock(
                return_value=VerificationResult(
                    verified=judge_supports,
                    method="paraphrase_judge" if judge_supports else None,
                    confidence=0.9 if judge_supports else None,
                    partial=judge_supports,
                )
            )
            monkeypatch.setattr(chats, "run_chat_tool_loop", AsyncMock(return_value=outcome))
            monkeypatch.setattr(chats, "enqueue_treatment_derivation_job", AsyncMock())
            # The loader is an explicit dependency bound as a default argument;
            # keep the real verifier and replace only the external body fetch.
            monkeypatch.setattr(
                chats,
                "verify_and_persist_authority_citations",
                partial(
                    verify_and_persist_authority_citations,
                    load_authority_text=AsyncMock(return_value=_BODY),
                ),
            )
            monkeypatch.setattr(
                "app.citation.authority_content_judge.judge_authority_content", judge
            )

            real_audit = chats._audit_message_sent

            async def check_boundary_then_audit(db: AsyncSession, **kwargs: Any) -> None:
                nonlocal audit_checked
                assert failure_injected, "the calibration query did not run"
                # Earlier provenance survived; an indiscriminate outer rollback
                # would have discarded it along with the calibration failure.
                assert (
                    await db.scalar(
                        select(MessageToolSource.id).where(
                            MessageToolSource.message_id == assistant_id
                        )
                    )
                ) is not None
                async with sessions() as before_commit:
                    for model in (
                        MessageToolSource,
                        MessageAuthorityCitation,
                        CitationLedgerEntry,
                        WorkProductFiduciaryGate,
                    ):
                        assert (
                            await before_commit.scalar(
                                select(model.id).where(model.message_id == assistant_id)
                            )
                        ) is None, (
                            f"{model.__tablename__} committed before the caller's audit boundary"
                        )
                await real_audit(db, **kwargs)
                audit_checked = True

            monkeypatch.setattr(chats, "_audit_message_sent", check_boundary_then_audit)
            spec = ToolSpec(
                function_name="get_authority",
                kind="authority",
                provider="govinfo",
                tool="get_authority",
                read_only=True,
                destructive=False,
                requires_confirmation=False,
                parameters={},
            )
            kwargs: dict[str, Any] = {
                "db": writer,
                "user": user,
                "gateway": gateway,
                "request": ChatCompletionRequest(
                    model="test-model",
                    messages=[ChatCompletionMessage(role="user", content="Explain fair use")],
                    stream=stream,
                ),
                "chat": chat,
                "assistant_message_id": assistant_id,
                "user_message_id": user_message.id,
                "request_id": "calibration-recovery",
                "allowlist": ChatToolAllowlist(specs={spec.function_name: spec}),
            }
            if stream:
                stream_response = await chats._stream_response(**kwargs)
                frames: list[bytes] = []
                async for chunk in stream_response.body_iterator:
                    frames.append(chunk.encode() if isinstance(chunk, str) else bytes(chunk))
                body = b"".join(frames).decode()
                assert '"type":"complete"' in body
                assert "[DONE]" in body
            else:
                json_response = await chats._non_streaming_response(**kwargs)
                assert json_response.status_code == 200
                assert json.loads(bytes(json_response.body))["message"]["id"] == str(assistant_id)
            assert failure_injected
            assert audit_checked, "real chat audit finalization did not complete"
            judge.assert_awaited_once()

        # NullPool opens a new physical connection after the writer is closed.
        # There is no extra commit here: only production finalization persisted it.
        async with sessions() as reader:
            earlier = await reader.get(Message, user_message.id)
            assert earlier is not None and earlier.content == "Explain fair use"
            assistant = await reader.get(Message, assistant_id)
            assert assistant is not None and assistant.content == _ANSWER
            source = (
                await reader.scalars(
                    select(MessageToolSource).where(MessageToolSource.message_id == assistant_id)
                )
            ).one()
            assert source.external_ref == "USCODE-2022-title17"
            citation = (
                await reader.scalars(
                    select(MessageAuthorityCitation).where(
                        MessageAuthorityCitation.message_id == assistant_id
                    )
                )
            ).one()
            assert citation.verified is judge_supports
            ledger = (
                await reader.scalars(
                    select(CitationLedgerEntry).where(
                        CitationLedgerEntry.message_authority_citation_id == citation.id
                    )
                )
            ).one()
            assert ledger.verification_status == (
                "paraphrase_judge" if judge_supports else "unverified"
            )
            gate = (
                await reader.scalars(
                    select(WorkProductFiduciaryGate).where(
                        WorkProductFiduciaryGate.message_id == assistant_id
                    )
                )
            ).one()
            assert gate.gate_status == expected_gate
            assert gate.total_assertions == 1
            assert gate.fail_count == (0 if judge_supports else 1)
            audit = (
                await reader.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "chat.message_sent",
                        AuditLog.resource_id == str(assistant_id),
                    )
                )
            ).one()
            assert audit.user_id == user.id
            assert audit.details is not None
            assert audit.details["user_message_id"] == str(user_message.id)
    finally:
        invalidate_cache()
        await engine.dispose()
