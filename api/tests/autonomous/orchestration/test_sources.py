"""Fresh configuration, exact source dispatch, and durable accounting on Postgres."""

import asyncio
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import ResourceScope
from app.autonomous.orchestration.effects import GuardedEffects
from app.autonomous.orchestration.sources import AuthoritySources
from app.errors import Conflict, Forbidden, ToolNotGranted
from app.models.autonomous import AutonomousSession
from app.models.orchestration import OrchestrationAccount as Account, OrchestrationEffect as Effect
from app.models.tool_call_log import ToolCallLog
from app.schemas.autonomous import Phase


class Gateway:
    def __init__(self):
        self.config = {
            "tool_providers": [
                {
                    "name": "other-statutes",
                    "type": "govinfo",
                    "enabled": True,
                    "egress_tier": 1,
                    "cost_per_call": "0",
                },
                {
                    "name": "statutes",
                    "type": "govinfo",
                    "enabled": True,
                    "egress_tier": 1,
                    "cost_per_call": "0.1250",
                    "base_url": "https://fixture.invalid",
                    "api_key_env": "MUST_NOT_APPEAR_IN_BINDING",
                },
            ]
        }
        self.config_reads = 0
        self.calls = []
        self.config_hook = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.response_changes = {}
        self.payload = {"results": []}

    async def get_admin_config(self):
        self.config_reads += 1
        if self.config_hook:
            await self.config_hook()
        return deepcopy(self.config)

    async def call_tool(self, provider, tool, args, *, max_allowed_tier):
        self.calls.append((provider, tool, deepcopy(args), max_allowed_tier))
        self.entered.set()
        await self.release.wait()
        return {
            "provider": provider,
            "tool": tool,
            "tier": 1,
            "payload": self.payload,
            **self.response_changes,
        }


@pytest_asyncio.fixture
async def source_env(policy_env):
    env = policy_env
    grants = env.plan.root.grants.model_copy(
        update={"analysis": (ToolIntent.run_skill, ToolIntent.retrieve_authority)}
    )
    env.config.current = env.config.current.model_copy(
        update={
            "grants": grants,
            "skills": tuple(
                s.model_copy(update={"grants": grants}) for s in env.config.current.skills
            ),
            "require_anonymization": False,
        }
    )
    scope = env.plan.root.model_copy(
        update={
            "grants": grants,
            "resources": ResourceScope(document_ids=(), source_names=("statutes",)),
            "maximum_egress_tier": 2,
            "anonymize": False,
        }
    )
    env.plan = env.plan.model_copy(
        update={
            "policy_version": env.config.current.version(),
            "root": scope,
            "delegation_grants": grants,
            "children": tuple(c.model_copy(update={"execution": scope}) for c in env.plan.children),
        }
    )
    env.gateway = Gateway()
    env.sources = AuthoritySources(gateway=env.gateway, operator=lambda: env.config.current)

    def no_fallback(*args):
        pytest.fail("source pricing must not use legacy or inference quote resolvers")

    env.effects = GuardedEffects(
        env.store,
        skills=env.holder,
        gateway=env.gateway,
        quote=no_fallback,
        model="unused",
        max_tokens=128,
        sources=env.sources,
    )
    return env


async def start(env):
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
    )
    env.claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)


async def search(env, *, key="source:one", **changes):
    return await env.effects.authority(
        env.claim,
        effect_key=key,
        phase=Phase.analysis,
        **{
            "source_name": "statutes",
            "operation": "search_authority",
            "args": {"query": "fixture"},
            **changes,
        },
    )


async def test_exact_provider_price_ceiling_and_empty_success(source_env, monkeypatch):
    env = source_env

    async def forbidden_resolution(*args, **kwargs):
        pytest.fail("bound dispatch must never rediscover a provider or price")

    monkeypatch.setattr("app.autonomous.guard._resolve_external_call", forbidden_resolution)
    monkeypatch.setattr("app.tools.governance.resolve_provider_cost", forbidden_resolution)
    monkeypatch.setattr("app.tools.governance.resolve_provider_tier", forbidden_resolution)
    monkeypatch.setattr("app.research.registry.resolve_available_sources", forbidden_resolution)
    await start(env)
    result = await search(env)
    assert result.data == {"source": "govinfo", "results": []}
    assert result.cost_usd == Decimal("0.1250")
    assert (await search(env)) == result
    assert env.gateway.config_reads == 2
    assert env.gateway.calls == [("statutes", "search_authority", {"query": "fixture"}, 2)]
    async with env.factory.begin() as db:
        account = await db.get(Account, env.root_id)
        assert account.spent_usd == (await db.get(AutonomousSession, env.root_id)).cost_total_usd
        assert account.spent_usd == result.cost_usd
        assert account.reserved_usd == 0
        logs = (
            await db.scalars(select(ToolCallLog).where(ToolCallLog.session_id == env.root_id))
        ).all()
        assert len(logs) == 1
        assert (
            logs[0].provider,
            logs[0].tool,
            logs[0].tier,
            logs[0].outcome,
            logs[0].cost_usd,
        ) == ("statutes", "search_authority", 1, "executed", Decimal("0.1250"))


@pytest.mark.parametrize(
    "patch",
    [
        {"cost_per_call": None},
        {"cost_per_call": True},
        {"cost_per_call": "NaN"},
        {"cost_per_call": "-1"},
        {"cost_per_call": "0.00001"},
        {"cost_per_call": "1000000"},
        {"cost_per_call": "1e100000000"},
        {"cost_per_unit": "0.01"},
        {"enabled": False},
        {"enabled": 1},
        {"egress_tier": True},
        {"egress_tier": 3},
        {"type": "edgar"},
        {"name": "renamed"},
    ],
)
async def test_unavailable_or_changed_config_never_admits(source_env, patch):
    env = source_env
    await start(env)
    env.gateway.config["tool_providers"][1].update(patch)
    with pytest.raises(Forbidden, match="configuration or pricing"):
        await search(env)
    assert not env.gateway.calls
    async with env.factory.begin() as db:
        assert await db.get(Effect, (env.root_id, "source:one")) is None
        assert (await db.get(Account, env.root_id)).reserved_usd == 0


@pytest.mark.parametrize("price", ["0", 0, 0.0])
async def test_explicit_free_price(source_env, price):
    env = source_env
    env.gateway.config["tool_providers"][1]["cost_per_call"] = price
    await start(env)
    assert (await search(env)).cost_usd == 0
    assert len(env.gateway.calls) == 1


async def test_missing_price_and_duplicate_provider_refuse(source_env):
    env = source_env
    await start(env)
    entry = env.gateway.config["tool_providers"][1]
    del entry["cost_per_call"]
    with pytest.raises(Forbidden):
        await search(env)
    entry["cost_per_call"] = "0"
    env.gateway.config["tool_providers"].append(deepcopy(entry))
    with pytest.raises(Forbidden):
        await search(env)
    assert not env.gateway.calls


@pytest.mark.parametrize("changes", [{"source_name": "other-statutes"}, {"operation": "delete"}])
async def test_unselected_source_or_operation_refuses_before_config_io(source_env, changes):
    env = source_env
    await start(env)
    with pytest.raises(Forbidden, match="outside approved scope"):
        await search(env, **changes)
    assert env.gateway.config_reads == 0


async def test_required_anonymization_refuses_before_config_io(source_env):
    env = source_env
    scope = env.plan.root.model_copy(update={"anonymize": True})
    env.plan = env.plan.model_copy(
        update={
            "root": scope,
            "children": tuple(c.model_copy(update={"execution": scope}) for c in env.plan.children),
        }
    )
    await start(env)
    with pytest.raises(Forbidden, match="anonymization"):
        await search(env)
    assert env.gateway.config_reads == 0


async def test_price_change_cannot_reuse_completed_effect_key(source_env):
    env = source_env
    await start(env)
    await search(env)
    env.gateway.config["tool_providers"][1]["cost_per_call"] = "0.25"
    with pytest.raises(Conflict, match="different input"):
        await search(env)
    assert len(env.gateway.calls) == 1
    assert (await search(env, key="source:two")).cost_usd == Decimal("0.25")


async def test_equivalent_decimal_spellings_recover_same_receipt(source_env):
    env = source_env
    await start(env)
    first = await search(env)
    env.gateway.config["tool_providers"][1]["cost_per_call"] = 0.125
    assert (await search(env)) == first
    assert len(env.gateway.calls) == 1


@pytest.mark.parametrize("source_type", ["edgar", "eurlex"])
async def test_other_registered_authority_adapters_bind_exactly(source_env, source_type):
    env = source_env
    operations = ("get_authority",)
    env.config.current = env.config.current.model_copy(
        update={
            "sources": (
                env.config.current.sources[0].model_copy(
                    update={
                        "source_type": source_type,
                        "operations": operations,
                    }
                ),
            ),
            "skills": tuple(
                s.model_copy(update={"source_types": (source_type,)})
                for s in env.config.current.skills
            ),
        }
    )
    env.plan = env.plan.model_copy(update={"policy_version": env.config.current.version()})
    env.gateway.config["tool_providers"][1]["type"] = source_type
    env.gateway.payload = {"external_ref": "fixture", "title": "Fixture", "text": "Evidence"}
    await start(env)
    result = await search(env, operation="get_authority", args={"external_ref": "fixture"})
    assert result.data["authority"]["source"] == source_type
    assert result.data["authority"]["text"] == "Evidence"
    assert result.cost_usd == Decimal("0.1250")
    with pytest.raises(Forbidden, match="outside approved scope"):
        await search(env, key="unsupported-search")


async def test_cancelled_source_call_rolls_back_outcome_but_retains_reservation(source_env):
    env = source_env
    await start(env)
    env.gateway.release.clear()
    task = asyncio.create_task(search(env))
    await asyncio.wait_for(env.gateway.entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with env.factory.begin() as db:
        assert (await db.get(Effect, (env.root_id, "source:one"))).status == "uncertain"
        account = await db.get(Account, env.root_id)
        assert account.reserved_usd == Decimal("0.1250") and account.spent_usd == 0
        assert not await db.scalar(
            select(ToolCallLog.id).where(ToolCallLog.session_id == env.root_id)
        )


async def test_config_io_holds_no_control_locks_and_halt_prevents_dispatch(source_env):
    env = source_env
    await start(env)

    async def halt():
        await asyncio.wait_for(env.store.halt(env.root_id, actor_id=env.owner_id), timeout=2)

    env.gateway.config_hook = halt
    with pytest.raises(Conflict):
        await search(env)
    assert not env.gateway.calls


async def test_policy_revocation_during_config_io_refuses(source_env):
    env = source_env
    await start(env)

    async def revoke():
        env.config.current = None

    env.gateway.config_hook = revoke
    with pytest.raises(Forbidden, match="disabled or changed"):
        await search(env)
    assert not env.gateway.calls


@pytest.mark.parametrize("patch", [{"provider": "other"}, {"tier": 3}, {"payload": None}])
async def test_response_binding_mismatch_is_uncertain(source_env, patch):
    env = source_env
    await start(env)
    env.gateway.response_changes = patch
    with pytest.raises(ValueError, match="response differs"):
        await search(env)
    async with env.factory.begin() as db:
        assert (await db.get(Effect, (env.root_id, "source:one"))).status == "uncertain"
        account = await db.get(Account, env.root_id)
        assert account.reserved_usd == Decimal("0.1250") and account.spent_usd == 0
        assert not await db.scalar(
            select(ToolCallLog.id).where(ToolCallLog.session_id == env.root_id)
        )


async def test_search_preserves_all_candidates(source_env):
    env = source_env
    await start(env)
    env.gateway.payload = {"results": [{"package_id": "one"}, {"package_id": "two"}]}
    assert (await search(env)).data["results"] == env.gateway.payload["results"]


async def test_get_authority_uses_same_bound_price_and_provider(source_env, monkeypatch):
    env = source_env

    async def forbidden_cache(*args, **kwargs):
        pytest.fail("internal evidence must not trigger an untracked shared cache write")

    monkeypatch.setattr("app.citation.authority.store_authority_text", forbidden_cache)
    await start(env)
    env.gateway.payload = {
        "package_id": "USCODE-2024-title15-chap1-sec1",
        "title": "Fixture",
        "text": "Fixture text",
    }
    result = await search(env, operation="get_authority", args={"package_id": "fixture"})
    assert result.data["authority"]["text"] == "Fixture text"
    assert result.cost_usd == Decimal("0.1250")
    assert env.gateway.calls[0][:2] == ("statutes", "get_authority")


async def test_source_binding_is_required_even_with_scoped_guard(source_env):
    from app.autonomous.guard import guarded_tool_call

    env = source_env
    await start(env)
    async with env.factory.begin() as db:
        session = await db.get(AutonomousSession, env.root_id)
        with pytest.raises(ToolNotGranted, match="source binding"):
            await guarded_tool_call(
                session,
                ToolIntent.retrieve_authority,
                {"source": "govinfo", "op": "search_authority", "args": {}},
                db,
                env.gateway,
                execution_scope=env.plan.root,
            )
    assert not env.gateway.calls
