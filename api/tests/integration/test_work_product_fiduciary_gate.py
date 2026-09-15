import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message
from app.models.user import User
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_message(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"gate-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="member",
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="gate test")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="answer")
    db_session.add(msg)
    await db_session.flush()
    return chat.id, msg.id


@pytest.mark.asyncio
async def test_gate_row_roundtrips(
    db_session: AsyncSession, seeded_message: tuple[uuid.UUID, uuid.UUID]
) -> None:
    chat_id, mid = seeded_message
    db_session.add(
        WorkProductFiduciaryGate(
            message_id=mid,
            chat_id=chat_id,
            gate_status="fiduciary_grade",
            pass_count=2,
            supported_count=0,
            fail_count=0,
            total_assertions=2,
            confidence=0.97,
        )
    )
    await db_session.flush()
    got = (
        await db_session.execute(
            select(WorkProductFiduciaryGate).where(WorkProductFiduciaryGate.message_id == mid)
        )
    ).scalar_one()
    assert got.gate_status == "fiduciary_grade"
    assert got.total_assertions == 2
    assert got.confidence == 0.97


@pytest.mark.asyncio
async def test_message_id_unique(
    db_session: AsyncSession, seeded_message: tuple[uuid.UUID, uuid.UUID]
) -> None:
    chat_id, mid = seeded_message
    for _ in range(2):
        db_session.add(
            WorkProductFiduciaryGate(
                message_id=mid,
                chat_id=chat_id,
                gate_status="flagged",
                pass_count=0,
                supported_count=0,
                fail_count=1,
                total_assertions=1,
                confidence=None,
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_confidence_range_check(
    db_session: AsyncSession, seeded_message: tuple[uuid.UUID, uuid.UUID]
) -> None:
    chat_id, mid = seeded_message
    db_session.add(
        WorkProductFiduciaryGate(
            message_id=mid,
            chat_id=chat_id,
            gate_status="fiduciary_grade",
            pass_count=1,
            supported_count=0,
            fail_count=0,
            total_assertions=1,
            confidence=1.5,  # out of [0,1]
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
