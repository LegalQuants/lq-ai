"""Optional skills retain ordinary guard authority for roots and children."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from tests.skills.conftest import real_runner as real_runner, runner_module as runner_module

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.effects import GuardedEffects
from app.autonomous.orchestration.policy import (
    CurrentPolicy,
    OperatorPolicy,
    SkillPolicy,
    skill_pin,
)
from app.config import get_settings
from app.errors import Conflict, Forbidden, SessionHalted, ToolNotGranted
from app.models.autonomous import AutonomousSession
from app.models.skill_workspace import SkillWorkspace, SkillWorkspaceFile
from app.schemas.autonomous import Phase
from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry
from app.skills.tools import SKILL_TOOL_INTENTS, SkillTools


@pytest.fixture
async def capable(env, monkeypatch):
    env.skills = MutableSkillRegistry(load_registry(Path(__file__).resolve().parents[4] / "skills"))
    pin = skill_pin(env.skills.current().get("saved-notes-demo"))
    grants = env.plan.root.grants.model_copy(update={"analysis": tuple(SKILL_TOOL_INTENTS)})
    scope = env.plan.root.model_copy(update={"skill": pin, "grants": grants})
    policy = OperatorPolicy(
        skills=tuple(
            SkillPolicy(pin=pin, profile=profile, grants=grants, source_types=())
            for profile in ("orchestrator", "research")
        ),
        sources=(),
        grants=grants,
        minimum_inference_tier=1,
        maximum_egress_tier=0,
        require_anonymization=True,
    )
    env.plan = env.plan.model_copy(
        update={
            "root": scope,
            "delegation_grants": grants,
            "policy_version": policy.version(),
            "children": tuple(c.model_copy(update={"execution": scope}) for c in env.plan.children),
        }
    )
    env.store.check_policy = CurrentPolicy(skills=env.skills, operator=lambda: policy)
    monkeypatch.setattr(get_settings(), "skill_workspaces_enabled", True)
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
    )
    env.claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    children = await env.store.admit_children(env.claim)
    env.child = await env.store.claim(env.root_id, children[0], worker_id=uuid4(), seconds=60)
    await env.store.phase(env.claim, Phase.analysis)
    await env.store.phase(env.child, Phase.analysis)
    env.effects = GuardedEffects(
        env.store, skills=env.skills, gateway=AsyncMock(), model="fixture", max_tokens=256
    )
    return env


async def call(env, claim, intent, key, params):
    return await env.effects.skill_tool(
        claim, effect_key=key, phase=Phase.analysis, intent=intent, params=params
    )


async def test_root_and_child_reuse_replay_atomicity_and_run_deletion(capable, monkeypatch):
    env = capable
    params = {"name": "notes.md", "expected_revision": None, "content": "Alpha beta\nGamma"}
    saved = await call(env, env.child, ToolIntent.skill_workspace_write, "save", params)
    replay = await call(env, env.child, ToolIntent.skill_workspace_write, "save", params)
    assert saved.data == replay.data and "revision" in saved.data
    read = await call(env, env.claim, ToolIntent.skill_workspace_read, "read", {"name": "notes.md"})
    assert read.data["content"] == params["content"]
    # Caller text cannot choose a different skill or workspace owner.
    with pytest.raises(ToolNotGranted):
        await call(
            env,
            env.child,
            ToolIntent.skill_workspace_read,
            "escape",
            {"name": "notes.md", "owner_id": str(uuid4())},
        )
    with monkeypatch.context() as patcher:
        patcher.setattr(
            env.store, "_settle_effect", AsyncMock(side_effect=RuntimeError("rollback receipt"))
        )
        with pytest.raises(RuntimeError, match="rollback receipt"):
            await call(
                env,
                env.child,
                ToolIntent.skill_workspace_write,
                "rollback",
                {**params, "name": "rollback.md"},
            )
    async with env.factory.begin() as db:
        assert not await db.scalar(
            select(SkillWorkspaceFile).where(SkillWorkspaceFile.name == "rollback.md")
        )
        await db.execute(delete(AutonomousSession).where(AutonomousSession.id == env.root_id))
        workspace = await db.scalar(
            select(SkillWorkspace).where(SkillWorkspace.owner_id == env.owner_id)
        )
        assert workspace is not None
        assert (await db.get(SkillWorkspaceFile, (workspace.id, "notes.md"))).content == params[
            "content"
        ]


async def test_halt_during_helper_discards_result_and_refuses_later_calls(capable, monkeypatch):
    env = capable
    monkeypatch.setattr(get_settings(), "skill_script_runner_url", "http://private-runner")
    monkeypatch.setattr(get_settings(), "skill_script_runner_token", "test-token-" * 4)
    started, release = asyncio.Event(), asyncio.Event()

    async def blocked(*args):
        started.set()
        await release.wait()
        return {"stdout": "late", "stderr": "", "exit_code": 0}

    monkeypatch.setattr(SkillTools, "run_script", blocked)
    work = asyncio.create_task(
        call(
            env,
            env.child,
            ToolIntent.run_bundled_script,
            "helper",
            {"script": "summarize_notes", "inputs": {"text": "Data"}},
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 5)
        await env.store.halt(env.root_id, actor_id=env.owner_id)
    finally:
        release.set()
    with pytest.raises((SessionHalted, Conflict, Forbidden)):
        await work
    with pytest.raises((SessionHalted, Conflict, Forbidden)):
        await call(env, env.claim, ToolIntent.skill_workspace_list, "after-halt", {})


async def test_guarded_root_and_child_execute_real_helper(capable, real_runner, monkeypatch):
    env = capable
    monkeypatch.setattr(get_settings(), "skill_script_runner_url", real_runner.url)
    monkeypatch.setattr(get_settings(), "skill_script_runner_token", real_runner.token)
    for claim in (env.claim, env.child):
        result = await call(
            env,
            claim,
            ToolIntent.run_bundled_script,
            "summarize",
            {"script": "summarize_notes", "inputs": {"text": "Alpha beta\nGamma"}},
        )
        assert result.data["exit_code"] == 0, result.data
        assert json.loads(result.data["stdout"])["word_count"] == 3
