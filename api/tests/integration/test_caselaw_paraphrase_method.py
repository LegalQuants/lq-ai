import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from app.models.chat import Chat, Message
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def msg(db_session):
    u = User(email=f"cm-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(u)
    await db_session.flush()
    c = Chat(owner_id=u.id, title="t")
    db_session.add(c)
    await db_session.flush()
    m = Message(chat_id=c.id, role="assistant", kind="ai", content="a")
    db_session.add(m)
    await db_session.flush()
    return m.id


@pytest.mark.asyncio
async def test_paraphrase_judge_method_accepted(db_session, msg):
    db_session.add(
        MessageCaselawCitation(
            message_id=msg,
            opinion_id=1,
            cluster_id=1,
            source_offset_start=0,
            source_offset_end=10,
            source_text="held that",
            verified=True,
            verification_method="paraphrase_judge",
            verification_confidence=0.7,
            partial=True,
        )
    )
    await db_session.flush()  # must NOT raise


@pytest.mark.asyncio
async def test_bogus_method_rejected(db_session, msg):
    db_session.add(
        MessageCaselawCitation(
            message_id=msg,
            opinion_id=1,
            cluster_id=1,
            source_offset_start=0,
            source_offset_end=10,
            source_text="x",
            verified=True,
            verification_method="made_up",
            verification_confidence=0.5,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
