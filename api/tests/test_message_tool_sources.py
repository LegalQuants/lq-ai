from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MessageToolSource
from app.models.chat import Chat, Message
from app.models.user import User
from app.security import hash_password

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# extract_tool_sources unit tests (no DB required — no integration mark)
# ---------------------------------------------------------------------------


def test_extract_from_search_case_law():
    from app.chat.tool_loop import extract_tool_sources

    data = {
        "count": 1,
        "results": [
            {
                "cluster_id": 42,
                "case_name": "Roe v. Wade",
                "court": "scotus",
                "date_filed": "1973-01-22",
                "absolute_url": "/opinion/42/",
                "snippet": "…",
            }
        ],
    }
    recs = extract_tool_sources("search_case_law", data)
    assert len(recs) == 1
    r = recs[0]
    assert r.source_kind == "caselaw"
    assert r.label == "Roe v. Wade"
    assert r.subtitle == "scotus · 1973-01-22"
    assert r.url == "https://www.courtlistener.com/opinion/42/"  # absolutized
    assert r.external_ref == "42"
    assert r.provider == "courtlistener"
    assert r.tool == "search_case_law"


def test_extract_from_get_cluster():
    from app.chat.tool_loop import extract_tool_sources

    data = {
        "cluster": {
            "cluster_id": 7,
            "case_name": "X v. Y",
            "court": "ca9",
            "date_filed": "2001-05-05",
            "absolute_url": "https://www.courtlistener.com/opinion/7/",
        },
        "opinions": [],
    }
    recs = extract_tool_sources("get_cluster", data)
    assert len(recs) == 1
    assert recs[0].label == "X v. Y"
    assert recs[0].external_ref == "7"
    assert recs[0].url == "https://www.courtlistener.com/opinion/7/"  # already absolute → unchanged


def test_extract_non_research_and_empty():
    from app.chat.tool_loop import extract_tool_sources

    assert extract_tool_sources("read_opinion", {"opinion_id": 1}) == []
    assert extract_tool_sources("find_in_case", {"matches": []}) == []
    assert extract_tool_sources("some_mcp_tool", {"payload": {}}) == []
    assert extract_tool_sources("search_case_law", {"results": []}) == []
    assert extract_tool_sources("search_case_law", None) == []


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"src-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Sources Test Owner",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _assistant_message(db_session: AsyncSession, owner: User) -> tuple[Chat, Message]:
    chat = Chat(owner_id=owner.id, project_id=None, title="src-chat")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="answer")
    db_session.add(msg)
    await db_session.flush()
    return chat, msg


@pytest.mark.asyncio
async def test_message_tool_source_roundtrips(db_session: AsyncSession, owner_user: User):
    _chat, msg = await _assistant_message(db_session, owner_user)
    row = MessageToolSource(
        message_id=msg.id,
        source_kind="caselaw",
        label="Roe v. Wade",
        subtitle="scotus · 1973-01-22",
        url="https://www.courtlistener.com/opinion/42/",
        external_ref="42",
        provider="courtlistener",
        tool="search_case_law",
    )
    db_session.add(row)
    await db_session.flush()
    got = (
        await db_session.execute(
            select(MessageToolSource).where(MessageToolSource.message_id == msg.id)
        )
    ).scalar_one()
    assert got.label == "Roe v. Wade"
    assert got.source_kind == "caselaw"
    assert got.external_ref == "42"
    assert got.created_at is not None
