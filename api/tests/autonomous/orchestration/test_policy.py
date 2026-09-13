"""Current policy and selected-resource checks against migrated Postgres."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, update

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import guarded_tool_call
from app.autonomous.orchestration.contracts import ResourceScope
from app.autonomous.orchestration.policy import (
    SourcePolicy,
)
from app.errors import Forbidden, SessionHalted, ToolNotGranted
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.document import Document, DocumentChunk
from app.models.file import File
from app.models.project import ProjectFile
from app.schemas.autonomous import Phase


async def add_document(env, *, attached=True):
    async with env.factory.begin() as db:
        file = File(
            owner_id=env.owner_id,
            filename="fixture.txt",
            mime_type="text/plain",
            size_bytes=4,
            hash_sha256="a" * 64,
            storage_path=str(uuid4()),
            ingestion_status="ready",
        )
        db.add(file)
        await db.flush()
        document = Document(file_id=file.id, parser="fixture", normalized_content="text")
        db.add(document)
        if attached:
            db.add(ProjectFile(project_id=env.project_id, file_id=file.id))
        await db.flush()
        return file.id, document.id


def select_documents(env, *ids):
    scope = env.plan.root.model_copy(
        update={
            "resources": ResourceScope(document_ids=tuple(ids), source_names=()),
        }
    )
    env.plan = env.plan.model_copy(
        update={
            "root": scope,
            "children": tuple(c.model_copy(update={"execution": scope}) for c in env.plan.children),
        }
    )


async def approve(env):
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    await env.store.approve(
        env.root_id,
        actor_id=env.owner_id,
        revision=1,
        plan_hash=env.plan.approval_hash(),
    )


async def test_real_policy_allows_approved_selected_documents(policy_env):
    env = policy_env
    _, document_id = await add_document(env)
    select_documents(env, document_id)
    await approve(env)
    claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    assert len(await env.store.admit_children(claim)) == 2


@pytest.mark.parametrize("mutation", ["delete", "detach", "missing", "unattached"])
async def test_selected_document_access_is_current(policy_env, mutation):
    env = policy_env
    file_id, document_id = await add_document(env, attached=mutation != "unattached")
    select_documents(env, uuid4() if mutation == "missing" else document_id)
    if mutation in {"missing", "unattached"}:
        with pytest.raises(Forbidden, match="Selected documents"):
            await env.store.save_plan(env.plan, actor_id=env.owner_id)
        return
    await approve(env)
    async with env.factory.begin() as db:
        if mutation == "delete":
            await db.execute(
                update(File).where(File.id == file_id).values(deleted_at=datetime.now(UTC))
            )
        else:
            await db.execute(delete(ProjectFile).where(ProjectFile.file_id == file_id))
    with pytest.raises(Forbidden, match="Selected documents"):
        await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)


@pytest.mark.parametrize(
    "mutation", ["body", "reference", "missing_reference", "new_reference", "reload"]
)
async def test_skill_drift_after_approval_refuses_worker(policy_env, mutation):
    env = policy_env
    await approve(env)
    if mutation == "body":
        with (env.folder / "SKILL.md").open("a") as file:
            file.write("Changed instructions")
    elif mutation == "reference":
        (env.folder / "reference" / "limits.md").write_text("Changed coverage")
    elif mutation == "missing_reference":
        (env.folder / "reference" / "limits.md").unlink()
    elif mutation == "new_reference":
        (env.folder / "reference" / "new.md").write_text("New instructions")
    else:
        registry = env.holder.current()
        registry = replace(registry, records={})
        env.holder.replace(registry)
    with pytest.raises(Forbidden, match=r"[Ss]kill"):
        await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)


@pytest.mark.parametrize("mutation", ["disabled", "source", "tier", "grants"])
async def test_operator_change_requires_new_approval(policy_env, mutation):
    env = policy_env
    await approve(env)
    policy = env.config.current
    changes = {
        "source": {"sources": ()},
        "tier": {"minimum_inference_tier": 2},
        "grants": {"grants": policy.grants.model_copy(update={"analysis": ()})},
    }
    env.config.current = (
        None if mutation == "disabled" else policy.model_copy(update=changes[mutation])
    )
    with pytest.raises(Forbidden, match="operator policy"):
        await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)


@pytest.mark.parametrize("name,tier", [("unconfigured", 2), ("statutes", 0)])
async def test_source_name_and_egress_ceiling_are_enforced(policy_env, name, tier):
    env = policy_env
    scope = env.plan.root.model_copy(
        update={
            "resources": ResourceScope(document_ids=(), source_names=(name,)),
            "maximum_egress_tier": tier,
        }
    )
    env.plan = env.plan.model_copy(update={"root": scope})
    with pytest.raises(Forbidden, match="Selected source"):
        await env.store.save_plan(env.plan, actor_id=env.owner_id)


async def test_skill_source_coverage_is_not_universal(policy_env):
    env = policy_env
    policy = env.config.current
    env.config.current = policy.model_copy(
        update={
            "skills": tuple(s.model_copy(update={"source_types": ()}) for s in policy.skills),
        }
    )
    env.plan = env.plan.model_copy(
        update={
            "policy_version": env.config.current.version(),
            "root": env.plan.root.model_copy(
                update={
                    "resources": ResourceScope(document_ids=(), source_names=("statutes",)),
                    "maximum_egress_tier": 2,
                }
            ),
        }
    )
    with pytest.raises(Forbidden, match="Selected source"):
        await env.store.save_plan(env.plan, actor_id=env.owner_id)


@pytest.mark.parametrize(
    "source,ops", [("unknown", ("search",)), ("eurlex", ("search_authority",))]
)
def test_unimplemented_source_operations_cannot_be_configured(source, ops):
    with pytest.raises(ValidationError, match="registered adapter"):
        SourcePolicy(name="fixture", source_type=source, egress_tier=1, operations=ops)


async def test_operator_grant_does_not_expand_closed_research_profile(policy_env):
    env = policy_env
    grants = env.plan.root.grants.model_copy(update={"analysis": (ToolIntent.run_playbook,)})
    policy = env.config.current
    env.config.current = policy.model_copy(
        update={
            "grants": grants,
            "skills": tuple(s.model_copy(update={"grants": grants}) for s in policy.skills),
        }
    )
    scope = env.plan.root.model_copy(update={"grants": grants})
    env.plan = env.plan.model_copy(
        update={
            "policy_version": env.config.current.version(),
            "root": scope,
            "delegation_grants": grants,
            "children": tuple(c.model_copy(update={"execution": scope}) for c in env.plan.children),
        }
    )
    with pytest.raises(Forbidden, match="closed research profile"):
        await env.store.save_plan(env.plan, actor_id=env.owner_id)


@pytest.mark.parametrize("selected", [True, False])
async def test_guard_reads_only_selected_document_text(policy_env, selected):
    env = policy_env
    file_id, document_id = await add_document(env)
    select_documents(env, *([document_id] if selected else []))
    async with env.factory.begin() as db:
        db.add(
            DocumentChunk(
                document_id=document_id,
                chunk_index=0,
                content="text",
                char_offset_start=0,
                char_offset_end=4,
            )
        )
    async with env.factory.begin() as db:
        session = await db.get(AutonomousSession, env.root_id)
        session.current_phase = "intake"
        await db.flush()
        if not selected:
            with pytest.raises(ToolNotGranted, match="selected project scope"):
                await guarded_tool_call(
                    session,
                    ToolIntent.retrieve_chunks,
                    {"file_id": str(file_id)},
                    db,
                    None,
                    execution_scope=env.plan.root,
                )
        else:
            result = await guarded_tool_call(
                session,
                ToolIntent.retrieve_chunks,
                {"file_id": str(file_id)},
                db,
                None,
                execution_scope=env.plan.root,
            )
            assert [c["content"] for c in result.data["chunks"]] == ["text"]


@pytest.mark.parametrize(
    "params",
    [
        {"kb_id": str(uuid4()), "query": "read everything"},
        {"file_id": str(uuid4()), "query": "additional scope"},
        {"file_id": "invalid"},
    ],
)
async def test_guard_rejects_unbounded_or_malformed_retrieval(policy_env, params):
    env = policy_env
    async with env.factory.begin() as db:
        session = await db.get(AutonomousSession, env.root_id)
        session.current_phase = "intake"
        await db.flush()
        with pytest.raises(ToolNotGranted, match="selected file"):
            await guarded_tool_call(
                session,
                ToolIntent.retrieve_chunks,
                params,
                db,
                None,
                execution_scope=env.plan.root,
            )


async def test_guard_scope_overrides_model_policy_params(policy_env, monkeypatch):
    env = policy_env
    requests = []

    async def estimate(*args):
        return Decimal("0")

    async def chat_completion(request):
        requests.append(request)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=""))],
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
        )

    monkeypatch.setattr("app.autonomous.guard.estimate_tool_cost", estimate)
    scope = env.plan.root.model_copy(update={"minimum_inference_tier": 4, "privileged": True})
    params = {
        "model": "fixture",
        "messages": [{"role": "user", "content": "fixture"}],
        "minimum_inference_tier": 1,
        "lq_ai_project_minimum_inference_tier": 1,
        "lq_ai_privileged": False,
        "anonymize": False,
    }
    async with env.factory.begin() as db:
        session = await db.get(AutonomousSession, env.root_id)
        await guarded_tool_call(
            session,
            ToolIntent.run_skill,
            params,
            db,
            SimpleNamespace(chat_completion=chat_completion),
            execution_scope=scope,
        )
    request = requests[0]
    assert request.minimum_inference_tier == request.lq_ai_project_minimum_inference_tier == 4
    assert request.lq_ai_privileged is True
    assert request.anonymize is True
    assert params["anonymize"] is False  # no mutation of caller/planner input
    assert not request.lq_ai_skills  # never ask gateway to re-resolve a mutable slug


async def test_guard_r5_precedes_scope_refusal_and_cost(policy_env, monkeypatch):
    env = policy_env

    async def unexpected_estimate(*args):
        pytest.fail("R4 must not run for a stopped or ungranted call")

    monkeypatch.setattr("app.autonomous.guard.estimate_tool_cost", unexpected_estimate)
    async with env.factory.begin() as db:
        session = await db.get(AutonomousSession, env.root_id)
        session.halt_state = "halt_requested"
        await db.flush()
        with pytest.raises(SessionHalted):
            await guarded_tool_call(
                session,
                ToolIntent.run_skill,
                {},
                db,
                None,
                execution_scope=env.plan.root,
            )


async def test_guard_denies_external_dispatch_until_bound_adapter_exists(policy_env, monkeypatch):
    env = policy_env

    async def unexpected_estimate(*args):
        pytest.fail("No cost/provider I/O for an unsupported scope path")

    monkeypatch.setattr("app.autonomous.guard.estimate_tool_cost", unexpected_estimate)
    scope = env.plan.root.model_copy(
        update={
            "grants": env.plan.root.grants.model_copy(
                update={"analysis": (ToolIntent.retrieve_authority,)}
            ),
        }
    )
    async with env.factory.begin() as db:
        session = await db.get(AutonomousSession, env.root_id)
        with pytest.raises(ToolNotGranted, match="implemented orchestration scope"):
            await guarded_tool_call(
                session,
                ToolIntent.retrieve_authority,
                {"source": "govinfo"},
                db,
                None,
                execution_scope=scope,
            )
        row = await db.scalar(
            select(AuditLog).where(
                AuditLog.resource_id == str(env.root_id),
                AuditLog.action == "autonomous_session.tool_call",
            )
        )
        assert row.details == {"tool": "retrieve_authority", "outcome": "tool_not_granted"}


async def test_revocation_allows_admitted_call_to_settle_but_blocks_next(policy_env, monkeypatch):
    env = policy_env
    await approve(env)
    claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    await env.store.begin_effect(
        claim,
        effect_key="analysis:one",
        request_hash="b" * 64,
        reservation_usd=Decimal("1"),
        phase=Phase.analysis,
        intent=ToolIntent.run_skill,
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def estimate(*args):
        return Decimal("1")

    async def chat_completion(request):
        entered.set()
        await asyncio.wait_for(release.wait(), timeout=5)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=""))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    monkeypatch.setattr("app.autonomous.guard.estimate_tool_cost", estimate)

    async def invoke():
        async with env.factory.begin() as db:
            session = await db.get(AutonomousSession, env.root_id)
            return await guarded_tool_call(
                session,
                ToolIntent.run_skill,
                {"model": "fixture", "messages": [{"role": "user", "content": "fixture"}]},
                db,
                SimpleNamespace(chat_completion=chat_completion),
                execution_scope=env.plan.root,
            )

    async with asyncio.TaskGroup() as group:
        task = group.create_task(invoke())
        await asyncio.wait_for(entered.wait(), timeout=2)
        env.config.current = None
        release.set()
    result = task.result()
    receipt = await env.store.complete_effect(
        claim,
        effect_key="analysis:one",
        charged_usd=result.cost_usd,
        result={"content": result.data["content"], "outcome": result.outcome},
    )
    assert receipt.status == "completed"
    assert receipt.charged_usd == Decimal("1")
    with pytest.raises(Forbidden, match="operator policy"):
        await env.store.begin_effect(
            claim,
            effect_key="analysis:two",
            request_hash="c" * 64,
            reservation_usd=Decimal("1"),
            phase=Phase.analysis,
            intent=ToolIntent.run_skill,
        )


@pytest.mark.parametrize("restriction", ["inference", "egress", "anonymization", "skill_grants"])
async def test_plan_must_fit_current_data_and_skill_policy(policy_env, restriction):
    env = policy_env
    policy = env.config.current
    scope = env.plan.root
    if restriction == "inference":
        policy = policy.model_copy(update={"minimum_inference_tier": 2})
    elif restriction == "egress":
        scope = scope.model_copy(update={"maximum_egress_tier": 3})
    elif restriction == "anonymization":
        scope = scope.model_copy(update={"anonymize": False})
    else:
        narrowed = policy.grants.model_copy(update={"analysis": ()})
        policy = policy.model_copy(
            update={
                "skills": tuple(s.model_copy(update={"grants": narrowed}) for s in policy.skills),
            }
        )
    env.config.current = policy
    env.plan = env.plan.model_copy(update={"root": scope, "policy_version": policy.version()})
    with pytest.raises(Forbidden, match="current data or grant policy"):
        await env.store.save_plan(env.plan, actor_id=env.owner_id)


@pytest.mark.parametrize("halt_state,status", [("halted", "running"), ("running", "completed")])
async def test_guard_rechecks_terminal_state(policy_env, halt_state, status):
    env = policy_env
    async with env.factory.begin() as db:
        session = await db.get(AutonomousSession, env.root_id)
        # A separate transaction changes the row after the worker loads it.
        async with env.factory.begin() as other:
            await other.execute(
                update(AutonomousSession)
                .where(
                    AutonomousSession.id == env.root_id,
                )
                .values(halt_state=halt_state, status=status)
            )
        with pytest.raises(SessionHalted, match="stopped"):
            await guarded_tool_call(
                session,
                ToolIntent.run_skill,
                {},
                db,
                None,
                execution_scope=env.plan.root,
            )
