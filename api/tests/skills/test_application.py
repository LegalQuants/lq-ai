"""Actual chat routes/loop and owner API; only model responses are controlled."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.chat.tool_schemas import ChatToolAllowlist
from app.clients.gateway import GatewayClient, set_gateway_client
from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.skill_workspace import SkillWorkspace
from app.models.tool_call_log import ToolCallLog
from app.security import create_access_token
from app.skills.chat_tools import extend_chat_tools
from tests.chat.test_tool_loop import _resp_final, _resp_tool_call
from tests.skills.test_capabilities import (
    binding as binding,
    make_user,
    skill_registry as skill_registry,
    skill_tools as skill_tools,
)


@pytest.fixture
async def application(db_session, skill_registry, monkeypatch):
    owner, other = make_user(), make_user()
    db_session.add_all([owner, other])
    await db_session.flush()

    async def database():
        yield db_session

    monkeypatch.setattr(app.state, "skill_registry", skill_registry, raising=False)
    monkeypatch.setattr(get_settings(), "skill_workspaces_enabled", True)
    app.dependency_overrides[get_db] = database
    gateway = GatewayClient(base_url="http://unused", gateway_key="fixture")
    monkeypatch.setattr(gateway, "list_tool_providers", AsyncMock(return_value=[]))
    set_gateway_client(gateway)
    headers = {
        "Authorization": "Bearer " + create_access_token(owner.id, owner.email, is_admin=False)
    }
    foreign = {
        "Authorization": "Bearer " + create_access_token(other.id, other.email, is_admin=False)
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, owner, headers, foreign
    finally:
        app.dependency_overrides.pop(get_db, None)
        set_gateway_client(None)
        await gateway.aclose()


@pytest.mark.parametrize("stream", [False, True])
async def test_chat_route_saves_and_second_chat_reopens(application, db_session, stream):
    client, owner, headers, _ = application
    notes = "Alpha beta\nGamma"
    observed = []
    for intent, params in (
        (
            "skill_workspace_write",
            {"name": "notes.md", "content": notes, "expected_revision": None},
        ),
        ("skill_workspace_read", {"name": "notes.md"}),
    ):
        chat = await client.post("/api/v1/chats", headers=headers, json={"title": "Skill reuse"})
        assert chat.status_code == 201, chat.text
        chat_id = chat.json()["id"]

        async def complete(_self, request, intent=intent, params=params, **kwargs):
            messages = request.messages
            tool_messages = [m for m in messages if m.role == "tool"]
            if tool_messages:
                observed.append(json.loads(tool_messages[-1].content))
                return _resp_final("Saved" if intent.endswith("write") else "Reopened")
            names = [t["function"]["name"] for t in request.tools]
            return _resp_tool_call(next(n for n in names if n.endswith(intent)), params)

        with patch.object(GatewayClient, "chat_completion", new=complete):
            response = await client.post(
                f"/api/v1/chats/{chat_id}/messages",
                headers=headers,
                json={
                    "content": "Use saved-notes-demo",
                    "skills": ["saved-notes-demo"],
                    "stream": stream,
                },
            )
        assert response.status_code == 200, response.text
    assert "revision" in observed[0]
    assert observed[1]["content"] == notes and observed[1]["revision"] == observed[0]["revision"]
    logs = list(
        await db_session.scalars(select(ToolCallLog).where(ToolCallLog.user_id == owner.id))
    )
    assert len(logs) == 2 and all(log.origin == "chat" for log in logs)
    assert notes not in str([log.args_digest for log in logs])
    # Tool exposure is limited to attached skills, even though saved work exists.
    allowlist = ChatToolAllowlist(specs={})
    from uuid import UUID

    await extend_chat_tools(
        db_session, allowlist, owner_id=owner.id, chat_id=UUID(chat_id), skill_names=[]
    )
    assert not allowlist.specs


async def test_owner_can_inspect_and_reset_after_disable(
    application, db_session, skill_tools, binding, monkeypatch
):
    client, owner, headers, foreign = application
    from app.autonomous.enums import ToolIntent

    await skill_tools.execute(
        db_session,
        binding=binding,
        owner_id=owner.id,
        project_id=None,
        intent=ToolIntent.skill_workspace_write,
        params={
            "name": "notes.md",
            "content": "<script>private notes</script>",
            "expected_revision": None,
        },
    )
    monkeypatch.setattr(get_settings(), "skill_workspaces_enabled", False)
    response = await client.get("/api/v1/skill-workspaces", headers=headers)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1 and "content" not in rows[0]["files"][0]
    identity = rows[0]["id"]
    path = f"/api/v1/skill-workspaces/{identity}"
    assert (await client.get("/api/v1/skill-workspaces", headers=foreign)).json() == []
    assert (await client.get(path + "/files/notes.md", headers=foreign)).status_code == 404
    assert (await client.delete(path, headers=foreign)).status_code == 404
    content = await client.get(path + "/files/notes.md", headers=headers)
    assert content.json()["content"] == "<script>private notes</script>"
    deleted = await client.delete(path, headers=headers)
    assert deleted.status_code == 204 and deleted.content == b""
    assert (await client.get(path + "/files/notes.md", headers=headers)).status_code == 404
    assert not await db_session.scalar(
        select(SkillWorkspace.id).where(SkillWorkspace.owner_id == owner.id)
    )


async def test_chat_tool_runs_real_bundled_helper(
    application, db_session, real_runner, monkeypatch
):
    client, _, headers, _ = application
    monkeypatch.setattr(get_settings(), "skill_script_runner_url", real_runner.url)
    monkeypatch.setattr(get_settings(), "skill_script_runner_token", real_runner.token)
    chat_id = (
        await client.post("/api/v1/chats", headers=headers, json={"title": "Bundled helper"})
    ).json()["id"]
    observed = []

    async def complete(_self, request, **kwargs):
        results = [m for m in request.messages if m.role == "tool"]
        if results:
            observed.append(json.loads(results[-1].content))
            return _resp_final("Two lines, three words")
        name = next(
            t["function"]["name"]
            for t in request.tools
            if t["function"]["name"].endswith("run_bundled_script")
        )
        return _resp_tool_call(
            name, {"script": "summarize_notes", "inputs": {"text": "Alpha beta\nGamma"}}
        )

    with patch.object(GatewayClient, "chat_completion", new=complete):
        response = await client.post(
            f"/api/v1/chats/{chat_id}/messages",
            headers=headers,
            json={"content": "Use the helper", "skills": ["saved-notes-demo"], "stream": False},
        )
    assert response.status_code == 200, response.text
    assert observed[0]["exit_code"] == 0
    assert json.loads(observed[0]["stdout"])["word_count"] == 3


async def test_real_nonzero_exit_is_a_failed_result(
    application, db_session, real_runner, skill_registry, binding, monkeypatch
):
    from app.autonomous.enums import ToolIntent
    from app.skills.tools import SkillTools

    _, owner, _, _ = application
    monkeypatch.setattr(get_settings(), "skill_script_runner_url", real_runner.url)
    monkeypatch.setattr(get_settings(), "skill_script_runner_token", real_runner.token)
    result = await SkillTools(skill_registry).execute(
        db_session,
        binding=binding,
        owner_id=owner.id,
        project_id=None,
        intent=ToolIntent.run_bundled_script,
        params={"script": "summarize_notes", "inputs": {"text": 42}},
    )
    assert result.data["exit_code"] == 2
    assert result.outcome == "skill_script_failed"
