import asyncio
import io
import json
import shutil
import zipfile
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.autonomous.enums import ToolIntent
from app.errors import Forbidden, ToolNotGranted
from app.models.team import Team, TeamMember
from app.models.user import User
from app.models.user_skill import UserSkill
from app.skills.binding import bind_record, resolve_binding, revalidate_binding
from app.skills.capabilities import SkillCapabilities
from app.skills.loader import load_registry
from app.skills.workspace import workspace_operation
from app.workers.user_export import build_export_zip_for_test
from tests.skills.test_capabilities import (
    ROOT,
    binding as binding,
    make_user,
    skill_registry as skill_registry,
    skill_tools as skill_tools,
)


async def test_concurrent_creation_uses_revision_conflict(test_engine, skill_tools, binding):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    owner = make_user()
    async with factory.begin() as db:
        db.add(owner)

    async def create(content):
        async with factory.begin() as db:
            return await skill_tools.execute(
                db,
                binding=binding,
                owner_id=owner.id,
                project_id=None,
                intent=ToolIntent.skill_workspace_write,
                params={"name": "same.md", "content": content, "expected_revision": None},
            )

    try:
        results = await asyncio.gather(create("First"), create("Second"))
        assert sum("revision" in result.data for result in results) == 1
        assert sum(result.data == {"error": "revision_conflict"} for result in results) == 1
    finally:
        async with factory.begin() as db:
            await db.execute(delete(User).where(User.id == owner.id))


async def test_total_quota_versions_and_export(db_session, binding):
    owner, other = make_user(), make_user()
    db_session.add_all([owner, other])
    await db_session.flush()

    async def call(operation, params, selected=binding, actor=owner):
        return await workspace_operation(
            db_session,
            binding=selected,
            owner_id=actor.id,
            project_id=None,
            operation=operation,
            params=params,
        )

    for n in range(16):
        assert "revision" in await call(
            "write", {"name": f"{n}.md", "content": "x" * 65536, "expected_revision": None}
        )
    assert await call("write", {"name": "overflow", "content": "x", "expected_revision": None}) == {
        "error": "storage_limit"
    }
    new_version = replace(binding, capabilities=SkillCapabilities(workspace_version=2))
    assert await call("read", {"name": "0.md"}, selected=new_version) == {
        "error": "file_unavailable"
    }
    await call(
        "write",
        {"name": "private.md", "content": "OTHER OWNER", "expected_revision": None},
        actor=other,
    )
    archive = zipfile.ZipFile(io.BytesIO(await build_export_zip_for_test(db_session, owner)))
    exported = json.loads(archive.read("skill_workspaces.json"))
    assert len(exported) == 1 and len(exported[0]["files"]) == 16
    assert "OTHER OWNER" not in archive.read("skill_workspaces.json").decode()


async def test_database_shadow_and_team_revocation_do_not_alias(
    db_session, skill_registry, binding
):
    owner = make_user()
    db_session.add(owner)
    await db_session.flush()
    row = UserSkill(
        scope="user",
        owner_user_id=owner.id,
        slug=binding.name,
        display_name="Shadow",
        description="Fixture",
        body="Notes",
        version="1",
        frontmatter_extra={"capabilities": {"workspace_version": 1}},
    )
    db_session.add(row)
    await db_session.flush()
    shadow = await resolve_binding(db_session, owner.id, binding.name, skill_registry)
    assert shadow.key == f"user:{row.id}" and shadow.key != binding.key
    row.frontmatter_extra = {
        "capabilities": {"scripts": [{"name": "generated", "description": "No"}]}
    }
    await db_session.flush()
    with pytest.raises(ToolNotGranted, match="cannot install"):
        await resolve_binding(db_session, owner.id, binding.name, skill_registry)
    team = Team(name="Fixture", slug=f"fixture-{uuid4()}", created_by_user_id=owner.id)
    db_session.add(team)
    await db_session.flush()
    member = TeamMember(team_id=team.id, user_id=owner.id, added_by_user_id=owner.id, role="member")
    row.scope, row.owner_user_id, row.owner_team_id = "team", None, team.id
    row.frontmatter_extra = {"capabilities": {"workspace_version": 1}}
    db_session.add(member)
    await db_session.flush()
    team_binding = await resolve_binding(db_session, owner.id, binding.name, skill_registry)
    assert team_binding.key == f"team:{row.id}"
    await db_session.delete(member)
    await db_session.flush()
    with pytest.raises(ToolNotGranted, match="revoked"):
        await revalidate_binding(db_session, owner.id, team_binding, skill_registry)
    assert (
        await resolve_binding(db_session, owner.id, binding.name, skill_registry)
    ).key == binding.key


def test_script_changes_missing_helpers_and_symlinks_refuse(tmp_path):
    folder = tmp_path / "saved-notes-demo"
    shutil.copytree(ROOT / "skills/saved-notes-demo", folder)
    record = load_registry(tmp_path).get(folder.name)
    original = bind_record(record)
    helper = folder / "scripts/summarize_notes.py"
    helper.write_text(helper.read_text() + "\n# Changed installed source\n")
    assert bind_record(record).digest != original.digest
    helper.unlink()
    with pytest.raises(Forbidden):
        bind_record(record)
    assert load_registry(tmp_path).get(folder.name) is None
    helper.symlink_to(ROOT / "skills/saved-notes-demo/scripts/summarize_notes.py")
    assert load_registry(tmp_path).get(folder.name) is None
    helper.unlink()
    (folder / "scripts").rmdir()
    (folder / "scripts").symlink_to(
        ROOT / "skills/saved-notes-demo/scripts", target_is_directory=True
    )
    assert load_registry(tmp_path).get(folder.name) is None
