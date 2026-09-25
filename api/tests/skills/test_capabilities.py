"""Optional storage survives invocations; skill text cannot install a runner."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.autonomous.enums import ToolIntent
from app.config import get_settings
from app.errors import ToolNotGranted
from app.models.project import Project
from app.models.skill_workspace import SkillWorkspace
from app.models.user import User
from app.skills.binding import bind_record
from app.skills.capabilities import ScriptInput
from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry
from app.skills.tools import SkillTools, parse_skill_tool
from app.skills.workspace import workspace_operation

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def skill_registry():
    return MutableSkillRegistry(load_registry(ROOT / "skills"))


@pytest.fixture
def skill_tools(skill_registry):
    settings = get_settings().model_copy(update={"skill_workspaces_enabled": True})
    return SkillTools(skill_registry, settings)


@pytest.fixture
def binding(skill_registry):
    return bind_record(skill_registry.current().get("saved-notes-demo"))


def make_user():
    return User(
        id=uuid4(),
        email=f"skill-{uuid4()}@example.test",
        hashed_password="test-hash",
        role="member",
    )


async def test_separate_invocations_reopen_saved_work(test_engine, skill_tools, binding):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    owner = make_user()
    async with factory.begin() as db:
        db.add(owner)
    try:
        async with factory.begin() as db:
            written = await skill_tools.execute(
                db,
                binding=binding,
                owner_id=owner.id,
                project_id=None,
                intent=ToolIntent.skill_workspace_write,
                params={
                    "name": "notes.md",
                    "content": "Alpha beta\nGamma",
                    "expected_revision": None,
                },
            )
        # A new connection/session and new service object share only durable data.
        async with factory.begin() as db:
            read = await SkillTools(skill_tools.registry, skill_tools.settings).execute(
                db,
                binding=binding,
                owner_id=owner.id,
                project_id=None,
                intent=ToolIntent.skill_workspace_read,
                params={"name": "notes.md"},
            )
            assert read.data["content"] == "Alpha beta\nGamma"
            assert read.data["revision"] == written.data["revision"]
            assert (
                await skill_tools.execute(
                    db,
                    binding=binding,
                    owner_id=owner.id,
                    project_id=None,
                    intent=ToolIntent.skill_workspace_write,
                    params={"name": "notes.md", "content": "overwrite", "expected_revision": None},
                )
            ).data == {"error": "revision_conflict"}
    finally:
        async with factory.begin() as db:
            await db.execute(delete(User).where(User.id == owner.id))


async def test_owner_project_and_reset_isolation(db_session, skill_tools, binding):
    owner, other = make_user(), make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    project = Project(id=uuid4(), owner_id=owner.id, name="First", slug=f"skill-{uuid4()}")
    db_session.add(project)
    await db_session.flush()

    async def call(intent, params, user=owner, project_id=project.id):
        return await skill_tools.execute(
            db_session,
            binding=binding,
            owner_id=user.id,
            project_id=project_id,
            intent=intent,
            params=params,
        )

    saved = await call(
        ToolIntent.skill_workspace_write,
        {"name": "notes.md", "content": "Private", "expected_revision": None},
    )
    assert (
        await call(ToolIntent.skill_workspace_read, {"name": "notes.md"}, project_id=None)
    ).data == {"error": "file_unavailable"}
    assert (
        await call(
            ToolIntent.skill_workspace_read, {"name": "notes.md"}, user=other, project_id=None
        )
    ).data == {"error": "file_unavailable"}
    with pytest.raises(ToolNotGranted, match="project"):
        await call(ToolIntent.skill_workspace_read, {"name": "notes.md"}, user=other)
    await workspace_operation(
        db_session,
        binding=binding,
        owner_id=owner.id,
        project_id=project.id,
        operation="reset",
        params={},
    )
    await call(
        ToolIntent.skill_workspace_write,
        {"name": "notes.md", "content": "New", "expected_revision": None},
    )
    assert (
        await call(
            ToolIntent.skill_workspace_write,
            {"name": "notes.md", "content": "Stale", "expected_revision": saved.data["revision"]},
        )
    ).data == {"error": "revision_conflict"}
    await db_session.delete(project)
    await db_session.flush()
    assert not await db_session.scalar(
        select(SkillWorkspace.id).where(SkillWorkspace.project_id == project.id)
    )


async def test_optional_and_file_limits(db_session, skill_tools, binding):
    owner = make_user()
    db_session.add(owner)
    await db_session.flush()
    undeclared = bind_record(skill_tools.registry.current().get("nda-review"))
    with pytest.raises(ToolNotGranted, match="not enabled"):
        await skill_tools.execute(
            db_session,
            binding=undeclared,
            owner_id=owner.id,
            project_id=None,
            intent=ToolIntent.skill_workspace_list,
            params={},
        )
    for index in range(32):
        result = await skill_tools.execute(
            db_session,
            binding=binding,
            owner_id=owner.id,
            project_id=None,
            intent=ToolIntent.skill_workspace_write,
            params={"name": f"n{index}.md", "content": "小", "expected_revision": None},
        )
        assert "error" not in result.data
    assert (
        await skill_tools.execute(
            db_session,
            binding=binding,
            owner_id=owner.id,
            project_id=None,
            intent=ToolIntent.skill_workspace_write,
            params={"name": "overflow", "content": "x", "expected_revision": None},
        )
    ).data == {"error": "storage_limit"}


@pytest.mark.parametrize(
    "params",
    [
        {"script": "../escape", "inputs": {}},
        {"script": "summarize_notes", "code": "print(1)"},
        {"script": "summarize_notes", "command": "python helper.py"},
        {"script": "summarize_notes", "image": "unapproved"},
        {"script": "summarize_notes", "inputs": {"text": "x" * 65536}},
    ],
)
def test_execution_accepts_only_named_helpers_and_bounded_data(params):
    with pytest.raises(ToolNotGranted):
        parse_skill_tool(ToolIntent.run_bundled_script, params)


def test_generated_text_remains_input_data():
    text = "__import__('os').system('touch /work/generated')"
    request = ScriptInput(script="summarize_notes", inputs={"text": text})
    assert request.inputs == {"text": text}


@pytest.mark.parametrize(
    "name,content",
    [("../notes", "x"), ("/etc/passwd", "x"), ("notes", "\x00"), ("notes", "字" * 22000)],
)
def test_no_host_paths_or_unbounded_workspace_content(name, content):
    with pytest.raises(ToolNotGranted):
        parse_skill_tool(
            ToolIntent.skill_workspace_write,
            {"name": name, "content": content, "expected_revision": None},
        )
