"""Optional skills retain ordinary guard authority for roots and children."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from tests.skills.conftest import real_runner as real_runner, runner_module as runner_module

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult
from app.autonomous.orchestration.effects import GuardedEffects
from app.autonomous.orchestration.policy import (
    CurrentPolicy,
    OperatorPolicy,
    SkillPolicy,
    skill_pin,
)
from app.autonomous.orchestration.store import WorkerClaim
from app.config import get_settings
from app.errors import Conflict, Forbidden, SessionHalted, ToolNotGranted
from app.models.autonomous import AutonomousSession
from app.models.orchestration import OrchestrationEffect
from app.models.skill_workspace import SkillWorkspace, SkillWorkspaceFile
from app.schemas.autonomous import Phase
from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry
from app.skills.tools import SKILL_TOOL_INTENTS, SkillTools


@pytest.fixture
async def capable(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
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
    return await activate(env)


async def activate(env: SimpleNamespace) -> SimpleNamespace:
    """Approve an exact plan and claim both roles through the durable store."""
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


@pytest.fixture
async def reference_capable(
    env: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> SimpleNamespace:
    folder = tmp_path / "reference-demo"
    (folder / "references").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: reference-demo\ndescription: Synthetic reference fixture\n"
        "lq_ai:\n  minimum_inference_tier: 1\n---\nRead the guide on request.\n"
    )
    options = request.param if hasattr(request, "param") and isinstance(request.param, dict) else {}
    env.reference_path = options.get("path", "references/guide.md")
    env.reference = folder / env.reference_path
    env.reference.parent.mkdir(parents=True, exist_ok=True)
    env.reference.write_text(options.get("content", "Synthetic task data; not verified evidence."))
    env.skills = MutableSkillRegistry(load_registry(tmp_path))
    pin = skill_pin(env.skills.current().get("reference-demo"))
    allowed = getattr(request, "param", True)
    grants = env.plan.root.grants.model_copy(
        update={"analysis": (ToolIntent.skill_reference_read,) if allowed else ()}
    )
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
    env.config = SimpleNamespace(current=policy)
    env.plan = env.plan.model_copy(
        update={
            "root": scope,
            "delegation_grants": grants,
            "policy_version": policy.version(),
            "children": tuple(c.model_copy(update={"execution": scope}) for c in env.plan.children),
        }
    )
    env.store.check_policy = CurrentPolicy(skills=env.skills, operator=lambda: env.config.current)
    monkeypatch.setattr(get_settings(), "skill_reference_read_enabled", True)
    monkeypatch.setattr(get_settings(), "skill_workspaces_enabled", False)
    monkeypatch.setattr(get_settings(), "skill_script_runner_url", None)
    return await activate(env)


async def call(
    env: SimpleNamespace,
    claim: WorkerClaim,
    intent: ToolIntent,
    key: str,
    params: dict[str, Any],
) -> ToolResult:
    return await env.effects.skill_tool(
        claim, effect_key=key, phase=Phase.analysis, intent=intent, params=params
    )


@pytest.mark.parametrize("role", ["claim", "child"])
async def test_reference_read_approved_roles_and_durable_replay(
    reference_capable: SimpleNamespace, role: str
) -> None:
    env = reference_capable
    claim = getattr(env, role)
    params = {"path": "references/guide.md"}
    with patch.object(
        SkillTools, "read_reference", autospec=True, side_effect=SkillTools.read_reference
    ) as read:
        result = await call(env, claim, ToolIntent.skill_reference_read, "reference", params)
        replay = await call(env, claim, ToolIntent.skill_reference_read, "reference", params)
    assert (
        result.data
        == replay.data
        == {
            "path": params["path"],
            "content": env.reference.read_text(),
        }
    )
    assert result.cost_usd == replay.cost_usd == 0
    assert result.outcome == replay.outcome == "success"
    assert read.call_count == 1
    async with env.factory() as db:
        receipts = list(
            await db.scalars(
                select(OrchestrationEffect).where(
                    OrchestrationEffect.session_id == claim.session_id
                )
            )
        )
        assert len(receipts) == 1
        assert receipts[0].status == "completed" and receipts[0].charged_usd == 0
        assert receipts[0].result == {"outcome": "success", "data": result.data}


@pytest.mark.parametrize("role", ["claim", "child"])
@pytest.mark.parametrize(
    "reference_capable",
    [
        {"content": "x" * 65536},
        {"content": "\n" * 65536},
        {"content": '"\\' * 32768},
        {
            "content": "\x01" * 65536,
            "path": "references/" + "a" * 95 + "/" + "b" * 95 + "/" + "c" * 52,
        },
        {"content": "🚀" * 16384},
    ],
    indirect=True,
    ids=["plain", "newlines", "quotes-and-backslashes", "worst-escape-longest-path", "utf8"],
)
async def test_reference_byte_boundary_completes_and_replays_exactly(
    reference_capable: SimpleNamespace, role: str
) -> None:
    env = reference_capable
    claim = getattr(env, role)
    expected = {"path": env.reference_path, "content": env.reference.read_text()}
    assert len(expected["content"].encode("utf-8")) == 65536
    with patch.object(
        SkillTools, "read_reference", autospec=True, side_effect=SkillTools.read_reference
    ) as read:
        first = await call(
            env, claim, ToolIntent.skill_reference_read, "boundary", {"path": env.reference_path}
        )
        replay = await call(
            env, claim, ToolIntent.skill_reference_read, "boundary", {"path": env.reference_path}
        )
    assert first.data == replay.data == expected
    assert first.outcome == replay.outcome == "success"
    assert first.cost_usd == replay.cost_usd == 0
    assert read.call_count == 1
    async with env.factory() as db:
        receipts = list(
            await db.scalars(
                select(OrchestrationEffect).where(
                    OrchestrationEffect.session_id == claim.session_id
                )
            )
        )
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt.status == "completed" and receipt.charged_usd == 0
        assert receipt.result == {"data": expected, "outcome": "success"}
        assert len(json.dumps(receipt.result, ensure_ascii=False).encode("utf-8")) <= 394240


@pytest.mark.parametrize("role", ["claim", "child"])
@pytest.mark.parametrize("reference_capable", [False], indirect=True)
async def test_reference_read_requires_an_approved_grant(
    reference_capable: SimpleNamespace, role: str
) -> None:
    env = reference_capable
    with patch.object(SkillTools, "read_reference") as read, pytest.raises(ToolNotGranted):
        await call(
            env,
            getattr(env, role),
            ToolIntent.skill_reference_read,
            "ungranted",
            {"path": "references/guide.md"},
        )
    read.assert_not_called()


@pytest.mark.parametrize("role", ["claim", "child"])
@pytest.mark.parametrize("change", ["policy", "pin", "host"])
async def test_reference_read_rechecks_authority_before_new_calls_and_replay(
    reference_capable: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, role: str, change: str
) -> None:
    env = reference_capable
    claim = getattr(env, role)
    params = {"path": "references/guide.md"}
    await call(env, claim, ToolIntent.skill_reference_read, "reference", params)
    if change == "policy":
        env.config.current = env.config.current.model_copy(
            update={"grants": env.config.current.grants.model_copy(update={"analysis": ()})}
        )
    elif change == "pin":
        env.reference.write_text("Changed after approval; must never be returned.")
    else:
        monkeypatch.setattr(get_settings(), "skill_reference_read_enabled", False)
    refusal = ToolNotGranted if change == "host" else Forbidden
    with patch.object(SkillTools, "read_reference") as read:
        for key in ("reference", "new-reference"):
            with pytest.raises(refusal):
                await call(env, claim, ToolIntent.skill_reference_read, key, params)
    read.assert_not_called()


@pytest.mark.parametrize("role", ["claim", "child"])
async def test_reference_read_cannot_move_its_grant_to_another_phase(
    reference_capable: SimpleNamespace, role: str
) -> None:
    env = reference_capable
    claim = getattr(env, role)
    await env.store.phase(claim, Phase.intake)
    with (
        patch.object(SkillTools, "read_reference") as read,
        pytest.raises(Forbidden, match="phase or grants"),
    ):
        await env.effects.skill_tool(
            claim,
            effect_key="wrong-phase",
            phase=Phase.intake,
            intent=ToolIntent.skill_reference_read,
            params={"path": "references/guide.md"},
        )
    read.assert_not_called()


async def test_root_and_child_reuse_replay_atomicity_and_run_deletion(
    capable: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
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


async def test_halt_during_helper_discards_result_and_refuses_later_calls(
    capable: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = capable
    monkeypatch.setattr(get_settings(), "skill_script_runner_url", "http://private-runner")
    monkeypatch.setattr(get_settings(), "skill_script_runner_token", "test-token-" * 4)
    started, release = asyncio.Event(), asyncio.Event()

    async def blocked(*args: Any) -> dict[str, Any]:
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


async def test_guarded_root_and_child_execute_real_helper(
    capable: SimpleNamespace, real_runner: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
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
