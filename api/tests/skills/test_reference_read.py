"""A skill's ``references/`` files are listed, and read one at a time on request."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.nodes import make_analysis_node
from app.autonomous.orchestration.policy import load_pinned_skill
from app.chat.tool_schemas import ChatToolAllowlist
from app.clients.gateway import GatewayClient, set_gateway_client
from app.config import Settings, get_settings
from app.db.session import get_db
from app.errors import ToolNotGranted
from app.main import app
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.project import Project
from app.models.tool_call_log import ToolCallLog
from app.models.user_skill import UserSkill
from app.schemas.gateway import ChatCompletionRequest, ChatCompletionResponse
from app.security import create_access_token
from app.skills.binding import SkillBinding, bind_record
from app.skills.capabilities import ReferenceRead
from app.skills.chat_tools import extend_chat_tools
from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry
from app.skills.tools import SkillTools, parse_skill_tool
from tests.autonomous.test_agentic_loop import _ScriptedGateway
from tests.chat.test_tool_loop import _resp_final, _resp_tool_call
from tests.skills.test_capabilities import make_user

GUIDE = "Guide text that is only ever read on request. " * 4
DETAIL = "Detail for one topic."


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """One skill with two on-demand files, and one with none."""
    root = tmp_path / "skills"
    demo = root / "ref-demo"
    (demo / "references" / "topic").mkdir(parents=True)
    (demo / "SKILL.md").write_text(
        "---\nname: ref-demo\ndescription: Reads its references on request.\n---\n"
        "Read `references/guide.md` when the task needs it.\n"
    )
    (demo / "references" / "guide.md").write_text(GUIDE)
    (demo / "references" / "topic" / "detail.md").write_text(DETAIL)
    plain = root / "plain"
    plain.mkdir()
    (plain / "SKILL.md").write_text("---\nname: plain\ndescription: No references.\n---\nBody\n")
    return root


@pytest.fixture
def registry(skills_dir: Path) -> MutableSkillRegistry:
    return MutableSkillRegistry(load_registry(skills_dir))


@pytest.fixture
def tools(registry: MutableSkillRegistry) -> SkillTools:
    # Both operator-enabled capabilities stay off: reading needs neither.
    settings = get_settings().model_copy(
        update={"skill_workspaces_enabled": False, "skill_script_runner_url": None}
    )
    return SkillTools(registry, settings)


def _binding(registry: MutableSkillRegistry, name: str = "ref-demo") -> SkillBinding:
    record = registry.current().get(name)
    assert record is not None
    return bind_record(record)


def test_reference_read_host_setting_defaults_on_and_accepts_both_env_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LQ_AI_SKILL_REFERENCE_READ_ENABLED", raising=False)
    monkeypatch.delenv("SKILL_REFERENCE_READ_ENABLED", raising=False)
    # BaseSettings supports _env_file at runtime; the generated constructor
    # signature exposes only model fields to mypy.
    assert Settings(_env_file=None).skill_reference_read_enabled is True  # type: ignore[call-arg]
    monkeypatch.setenv("SKILL_REFERENCE_READ_ENABLED", "false")
    assert Settings(_env_file=None).skill_reference_read_enabled is False  # type: ignore[call-arg]
    monkeypatch.setenv("LQ_AI_SKILL_REFERENCE_READ_ENABLED", "true")
    assert Settings(_env_file=None).skill_reference_read_enabled is True  # type: ignore[call-arg]


async def test_disabled_host_refuses_a_previously_built_binding(
    registry: MutableSkillRegistry,
    tools: SkillTools,
) -> None:
    binding = _binding(registry)
    tools.settings.skill_reference_read_enabled = False
    assert ToolIntent.skill_reference_read not in tools.available(binding)
    with pytest.raises(ToolNotGranted):
        await tools.execute(
            AsyncMock(),
            binding=binding,
            owner_id=uuid4(),
            project_id=None,
            intent=ToolIntent.skill_reference_read,
            params={"path": "references/guide.md"},
        )


def test_reference_result_uses_the_pinned_snapshot(
    registry: MutableSkillRegistry,
    tools: SkillTools,
    skills_dir: Path,
) -> None:
    binding = _binding(registry)
    (skills_dir / "ref-demo" / "references" / "guide.md").write_text("unvalidated new bytes")
    # Execution separately revalidates the pin. The result must never perform
    # a second disk read after that check, even if the file changes meanwhile.
    assert tools.read_reference(binding, ReferenceRead(path="references/guide.md")) == {
        "path": "references/guide.md",
        "content": GUIDE,
    }
    assert GUIDE not in repr(binding)


@pytest.mark.parametrize("parent_link", [False, True])
def test_reference_snapshot_refuses_replaced_symlinks(
    skills_dir: Path,
    tmp_path: Path,
    parent_link: bool,
) -> None:
    from app.skills.references import read_reference_snapshot

    folder = skills_dir / "ref-demo"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "detail.md").write_text("outside private text")
    if parent_link:
        target = folder / "references" / "topic"
        (target / "detail.md").unlink()
        target.rmdir()
        target.symlink_to(outside, target_is_directory=True)
        path = target / "detail.md"
    else:
        path = folder / "references" / "guide.md"
        path.unlink()
        path.symlink_to(outside / "detail.md")
    with pytest.raises(OSError):
        read_reference_snapshot(folder, path)


async def test_tool_reads_one_listed_file_with_no_operator_setting(
    db_session: AsyncSession, registry: MutableSkillRegistry, tools: SkillTools
) -> None:
    owner = make_user()
    db_session.add(owner)
    await db_session.flush()
    binding = _binding(registry)
    assert binding.reference_paths == ("references/guide.md", "references/topic/detail.md")
    assert tools.available(binding) == (ToolIntent.skill_reference_read,)

    result = await tools.execute(
        db_session,
        binding=binding,
        owner_id=owner.id,
        project_id=None,
        intent=ToolIntent.skill_reference_read,
        params={"path": "references/topic/detail.md"},
    )
    assert result.outcome == "success"
    assert result.data == {"path": "references/topic/detail.md", "content": DETAIL}

    # A skill with no references/ folder gets no tool at all.
    plain = _binding(registry, "plain")
    assert tools.available(plain) == ()
    with pytest.raises(ToolNotGranted):
        await tools.execute(
            db_session,
            binding=plain,
            owner_id=owner.id,
            project_id=None,
            intent=ToolIntent.skill_reference_read,
            params={"path": "references/guide.md"},
        )


async def test_only_listed_paths_can_be_read(
    db_session: AsyncSession, registry: MutableSkillRegistry, tools: SkillTools
) -> None:
    owner = make_user()
    db_session.add(owner)
    await db_session.flush()
    binding = _binding(registry)

    # Well-formed but not one of the skill's files: a refusal, not a fault.
    missing = await tools.execute(
        db_session,
        binding=binding,
        owner_id=owner.id,
        project_id=None,
        intent=ToolIntent.skill_reference_read,
        params={"path": "references/absent.md"},
    )
    assert missing.outcome == "skill_tool_refused"
    assert missing.data == {"error": "file_unavailable"}

    # Anything that is not a plain path under references/ never reaches the disk.
    for path in (
        "references/../SKILL.md",
        "../ref-demo/references/guide.md",
        "/etc/passwd",
        "SKILL.md",
        "references/.hidden",
        "references//guide.md",
        "references/",
    ):
        with pytest.raises(ToolNotGranted):
            parse_skill_tool(ToolIntent.skill_reference_read, {"path": path})
    with pytest.raises(ToolNotGranted):
        parse_skill_tool(
            ToolIntent.skill_reference_read, {"path": "references/guide.md", "extra": 1}
        )


async def test_a_file_changed_after_binding_is_refused(
    db_session: AsyncSession, registry: MutableSkillRegistry, tools: SkillTools, skills_dir: Path
) -> None:
    """The binding pins the reference files' bytes. A file edited on disk
    after the turn began is not served under the old identity."""
    owner = make_user()
    db_session.add(owner)
    await db_session.flush()
    binding = _binding(registry)
    (skills_dir / "ref-demo" / "references" / "guide.md").write_text("edited after binding")
    with pytest.raises(ToolNotGranted):
        await tools.execute(
            db_session,
            binding=binding,
            owner_id=owner.id,
            project_id=None,
            intent=ToolIntent.skill_reference_read,
            params={"path": "references/guide.md"},
        )


def test_pinned_instructions_name_the_files_and_hash_their_content(
    registry: MutableSkillRegistry, skills_dir: Path
) -> None:
    record = registry.current().get("ref-demo")
    assert record is not None
    pinned = load_pinned_skill(record)
    assert "## Reference files available on request" in pinned.instructions
    assert "- references/guide.md" in pinned.instructions
    assert "- references/topic/detail.md" in pinned.instructions
    assert GUIDE not in pinned.instructions and DETAIL not in pinned.instructions

    (skills_dir / "ref-demo" / "references" / "topic" / "detail.md").write_text("changed")
    assert load_pinned_skill(record).pin.digest != pinned.pin.digest


ChatClient = tuple[AsyncClient, Any, dict[str, str]]


@pytest.fixture
async def chat_client(
    db_session: AsyncSession, registry: MutableSkillRegistry, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[ChatClient]:
    owner = make_user()
    db_session.add(owner)
    await db_session.flush()

    async def database() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(app.state, "skill_registry", registry, raising=False)
    monkeypatch.setattr(get_settings(), "skill_workspaces_enabled", False)
    monkeypatch.setattr(get_settings(), "skill_script_runner_url", None)
    app.dependency_overrides[get_db] = database
    gateway = GatewayClient(base_url="http://unused", gateway_key="fixture")
    monkeypatch.setattr(gateway, "list_tool_providers", AsyncMock(return_value=[]))
    set_gateway_client(gateway)
    headers = {
        "Authorization": "Bearer " + create_access_token(owner.id, owner.email, is_admin=False)
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, owner, headers
    finally:
        app.dependency_overrides.pop(get_db, None)
        set_gateway_client(None)
        await gateway.aclose()


async def test_chat_offers_the_tool_and_returns_the_file(
    chat_client: ChatClient, db_session: AsyncSession
) -> None:
    client, owner, headers = chat_client
    chat = await client.post("/api/v1/chats", headers=headers, json={"title": "References"})
    assert chat.status_code == 201, chat.text
    chat_id = chat.json()["id"]
    observed: list[dict[str, Any]] = []
    offered: list[dict[str, Any]] = []

    async def complete(
        _self: GatewayClient, request: ChatCompletionRequest, **kwargs: Any
    ) -> ChatCompletionResponse:
        tool_messages = [m for m in request.messages if m.role == "tool"]
        if tool_messages:
            content = tool_messages[-1].content
            assert content is not None
            observed.append(json.loads(content))
            return _resp_final("Read it")
        assert request.tools is not None
        offered.extend(request.tools)
        name = next(
            t["function"]["name"]
            for t in request.tools
            if t["function"]["name"].endswith("skill_reference_read")
        )
        return _resp_tool_call(name, {"path": "references/guide.md"})

    with patch.object(GatewayClient, "chat_completion", new=complete):
        response = await client.post(
            f"/api/v1/chats/{chat_id}/messages",
            headers=headers,
            json={"content": "Use ref-demo", "skills": ["ref-demo"], "stream": False},
        )
    assert response.status_code == 200, response.text
    assert observed == [{"path": "references/guide.md", "content": GUIDE}]
    # The schema names the files, so the model cannot ask for anything else.
    function = next(
        t["function"] for t in offered if t["function"]["name"].endswith("skill_reference_read")
    )
    assert function["parameters"]["properties"]["path"]["enum"] == [
        "references/guide.md",
        "references/topic/detail.md",
    ]
    logs = list(
        await db_session.scalars(select(ToolCallLog).where(ToolCallLog.user_id == owner.id))
    )
    assert [(log.origin, log.tool) for log in logs] == [("chat", "skill_reference_read")]
    assert GUIDE not in str([log.args_digest for log in logs])

    # A skill without references/ adds no tool, so its chats stay single-shot.
    allowlist = ChatToolAllowlist(specs={})
    await extend_chat_tools(
        db_session, allowlist, owner_id=owner.id, chat_id=UUID(chat_id), skill_names=["plain"]
    )
    assert not allowlist.specs


async def test_disabled_reads_leave_human_inspection_and_metadata_available(
    chat_client: ChatClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, headers = chat_client
    monkeypatch.setattr(get_settings(), "skill_reference_read_enabled", False)
    monkeypatch.setattr(get_settings(), "lq_ai_gateway_key", "inspection-fixture-key")
    detail = await client.get("/api/v1/skills/ref-demo", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["reference_read_enabled"] is False
    assert detail.json()["on_demand_files"] == [
        {"path": "references/guide.md", "size_bytes": len(GUIDE.encode())},
        {"path": "references/topic/detail.md", "size_bytes": len(DETAIL.encode())},
    ]
    assert "on_demand_contents" not in detail.json() and GUIDE not in detail.text
    contents = await client.get("/api/v1/skills/ref-demo/contents", headers=headers)
    assert contents.status_code == 200, contents.text
    assert contents.json()["on_demand_contents"] == [
        {"path": "references/guide.md", "content": GUIDE},
        {"path": "references/topic/detail.md", "content": DETAIL},
    ]
    internal = await client.get(
        "/api/v1/internal/skills/ref-demo",
        headers={"X-LQ-AI-Gateway-Key": "inspection-fixture-key"},
    )
    assert internal.status_code == 200, internal.text
    assert "on_demand_contents" not in internal.json()
    assert GUIDE not in internal.text and DETAIL not in internal.text


async def test_chat_host_disable_removes_tools_and_refuses_saved_binding(
    chat_client: ChatClient,
    db_session: AsyncSession,
    registry: MutableSkillRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, owner, headers = chat_client
    chat = await client.post("/api/v1/chats", headers=headers, json={"title": "References"})
    allowlist = ChatToolAllowlist(specs={})
    await extend_chat_tools(
        db_session,
        allowlist,
        owner_id=owner.id,
        chat_id=UUID(chat.json()["id"]),
        skill_names=["ref-demo"],
    )
    binding = next(iter(allowlist.specs.values())).skill_binding
    assert binding is not None
    monkeypatch.setattr(get_settings(), "skill_reference_read_enabled", False)
    disabled = ChatToolAllowlist(specs={})
    await extend_chat_tools(
        db_session,
        disabled,
        owner_id=owner.id,
        chat_id=UUID(chat.json()["id"]),
        skill_names=["ref-demo"],
    )
    assert not disabled.specs
    with pytest.raises(ToolNotGranted):
        await SkillTools(registry).execute(
            db_session,
            binding=binding,
            owner_id=owner.id,
            project_id=None,
            intent=ToolIntent.skill_reference_read,
            params={"path": "references/guide.md"},
        )


@pytest.mark.parametrize("scope", ["user", "team"])
async def test_shadow_inspection_never_inherits_installed_references(
    scope: str,
    registry: MutableSkillRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.requests import Request

    from app.api import skills as endpoints

    row = UserSkill(
        id=uuid4(),
        slug="ref-demo",
        scope=scope,
        version="1.0.0",
        display_name="Shadow",
        description="Private replacement",
        body="Shadow body",
        tags=[],
        frontmatter_extra={},
    )
    monkeypatch.setattr(app.state, "skill_registry", registry, raising=False)
    monkeypatch.setattr(
        endpoints, "_load_user_shadow", AsyncMock(return_value=row if scope == "user" else None)
    )
    monkeypatch.setattr(
        endpoints, "_load_team_shadow", AsyncMock(return_value=row if scope == "team" else None)
    )
    request = Request({"type": "http", "app": app, "headers": []})
    payload = await endpoints._resolve_full_skill_payload(
        request,
        db=AsyncMock(),
        user_id=uuid4(),
        skill_name="ref-demo",
        inspect_references=True,
    )
    assert payload["on_demand_files"] == []
    assert payload["on_demand_contents"] == []
    assert GUIDE not in json.dumps(payload)


async def test_new_shadow_invalidates_an_existing_installed_binding(
    registry: MutableSkillRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.skills import binding as bindings
    from app.skills.capabilities import SkillCapabilities

    saved = _binding(registry)
    shadow = SkillBinding("ref-demo", "user:" + str(uuid4()), "shadow-digest", SkillCapabilities())
    monkeypatch.setattr(bindings, "resolve_binding", AsyncMock(return_value=shadow))
    with pytest.raises(ToolNotGranted):
        await bindings.revalidate_binding(AsyncMock(), uuid4(), saved, registry)


async def test_planner_uses_shadow_instructions_with_shadow_tools(
    db_session: AsyncSession,
    registry: MutableSkillRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = make_user()
    owner.autonomous_enabled = True
    db_session.add(owner)
    await db_session.flush()
    project = Project(owner_id=owner.id, name="Shadow", slug=f"shadow-{uuid4()}")
    db_session.add(project)
    db_session.add(
        UserSkill(
            id=uuid4(),
            slug="ref-demo",
            scope="user",
            owner_user_id=owner.id,
            version="1.0.0",
            display_name="Shadow",
            description="Shadow tools",
            body="Unique shadow instructions",
            tags=[],
            frontmatter_extra={"capabilities": {"workspace_version": 1}},
        )
    )
    await db_session.flush()
    session = AutonomousSession(
        user_id=owner.id,
        project_id=project.id,
        trigger_kind="manual",
        params={"skill_ref": "ref-demo", "model": "fixture"},
    )
    db_session.add(session)
    await db_session.flush()
    monkeypatch.setattr(app.state, "skill_registry", registry, raising=False)
    monkeypatch.setattr(get_settings(), "skill_workspaces_enabled", True)
    monkeypatch.setattr(get_settings(), "skill_script_runner_url", None)
    gateway = _ScriptedGateway([{"done": True, "rationale": "no action needed"}])
    await make_analysis_node(db_session, gateway)(
        {"session_id": str(session.id), "query": "Follow the shadow", "retrieved_chunks": []}
    )
    first = json.dumps([m.content for m in gateway.captured_requests[0].messages])
    assert "Unique shadow instructions" in first
    assert "Read `references/guide.md` when the task needs it." not in first
    assert "references/guide.md" not in first


@pytest.mark.parametrize("enabled", [True, False])
async def test_background_planner_reads_a_reference_file(
    db_session: AsyncSession,
    registry: MutableSkillRegistry,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
) -> None:
    owner = make_user()
    owner.autonomous_enabled = True
    db_session.add(owner)
    await db_session.flush()
    project = Project(owner_id=owner.id, name="Fixture", slug=f"fixture-{uuid4()}")
    db_session.add(project)
    await db_session.flush()
    session = AutonomousSession(
        user_id=owner.id,
        project_id=project.id,
        trigger_kind="manual",
        params={"skill_ref": "ref-demo", "model": "fixture"},
    )
    db_session.add(session)
    await db_session.flush()
    monkeypatch.setattr(app.state, "skill_registry", registry, raising=False)
    monkeypatch.setattr(get_settings(), "skill_workspaces_enabled", False)
    monkeypatch.setattr(get_settings(), "skill_script_runner_url", None)
    monkeypatch.setattr(get_settings(), "skill_reference_read_enabled", enabled)
    gateway = _ScriptedGateway(
        [
            {
                "next_intent": "skill_reference_read",
                "args": {"path": "references/guide.md"},
                "rationale": "the task needs the guide",
            },
            {"done": True, "rationale": "enough"},
        ]
        if enabled
        else [{"done": True, "rationale": "reference reads disabled"}]
    )
    result = await make_analysis_node(db_session, gateway)(
        {"session_id": str(session.id), "query": "Follow the guide", "retrieved_chunks": []}
    )
    assert result["analysis_plan_trace"]["steps"] == int(enabled)
    # The planner is told which files exist before it asks for one...
    first_prompt = json.dumps([m.content for m in gateway.captured_requests[0].messages])
    if not enabled:
        assert "skill_reference_read" not in first_prompt
        assert GUIDE not in first_prompt
        return
    assert "references/guide.md" in first_prompt and GUIDE not in first_prompt
    # ...and sees the file's text only after reading it.
    assert GUIDE in gateway.captured_requests[1].messages[-1].content
    # The text is prompt data. It is not evidence and it is not in the trace or the audit log.
    assert result["analysis_evidence"] == []
    assert GUIDE not in json.dumps(result["analysis_plan_trace"])
    audit = list(await db_session.scalars(select(AuditLog).where(AuditLog.user_id == owner.id)))
    assert GUIDE not in json.dumps([row.details for row in audit])
