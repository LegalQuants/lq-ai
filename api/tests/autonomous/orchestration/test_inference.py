"""Actual store/guard with direct inference bindings and stub gateway responses."""

import asyncio
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio

from app.autonomous.orchestration.effects import GuardedEffects
from app.autonomous.orchestration.inference import InferenceRoutes
from app.autonomous.orchestration.policy import InferencePolicy
from app.errors import Conflict, Forbidden, ValidationError
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationEffect as Effect,
    OrchestrationRoot as Root,
)
from app.schemas.autonomous import Phase


class Gateway:
    def __init__(self):
        self.config = {
            "providers": [
                {
                    "name": "selected",
                    "type": "openai",
                    "tier": 1,
                    "enabled": True,
                    "base_url": "https://fixture.invalid",
                }
            ],
            "model_aliases": {"smart": {"primary": {"provider": "other", "model": "expensive"}}},
            "inference_tiers": {"overrides": {}, "defaults": {}},
            "cost_tracking": {
                "enabled": True,
                "rates": {"selected/native": {"input_per_mtok": "2", "output_per_mtok": "6"}},
            },
            "anonymization": {"enabled": True, "apply_at_tiers": [1]},
        }
        self.requests = []
        self.config_reads = 0
        self.config_hook = None
        self.response_changes = {}
        self.prompt_tokens, self.completion_tokens = 10, 5
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def get_admin_config(self):
        self.config_reads += 1
        if self.config_hook:
            await self.config_hook()
        return deepcopy(self.config)

    async def chat_completion(self, request):
        self.requests.append(request)
        self.entered.set()
        await self.release.wait()
        return SimpleNamespace(
            **{
                "model": "native-provider-version-label",
                "routed_provider": "selected",
                "routed_model": "native",
                "routed_inference_tier": 1,
                "anonymization_applied": True,
                "choices": [
                    SimpleNamespace(message=SimpleNamespace(content="result"), finish_reason="stop")
                ],
                "usage": SimpleNamespace(
                    prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens
                ),
                **self.response_changes,
            }
        )


@pytest_asyncio.fixture
async def inference_env(policy_env):
    env = policy_env
    policy = InferencePolicy(
        provider="selected", native_model="native", max_input_bytes=32768, max_output_tokens=256
    )
    env.config.current = env.config.current.model_copy(update={"inference": policy})
    env.plan = env.plan.model_copy(update={"policy_version": env.config.current.version()})
    env.gateway = Gateway()
    env.routes = InferenceRoutes(gateway=env.gateway, operator=lambda: env.config.current)
    env.effects = GuardedEffects(
        env.store, skills=env.holder, gateway=env.gateway, inference=env.routes
    )
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
    )
    env.claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    return env


async def infer(env, *, key="infer:one", inputs=None):
    return await env.effects.infer(
        env.claim, effect_key=key, phase=Phase.analysis, inputs=inputs or {}
    )


async def test_direct_route_and_conservative_accounting_are_recoverable(inference_env):
    env = inference_env
    result = await infer(env, inputs={"model": "unpriced", "max_tokens": 99999})
    request = env.gateway.requests[0]
    assert request.model == "selected/native" and request.max_tokens == 256
    assert request.minimum_inference_tier == request.lq_ai_project_minimum_inference_tier == 1
    assert request.anonymize is True and not request.lq_ai_skills
    assert str(env.root_id) not in request.model_dump_json()
    accounting = result.data["accounting"]
    assert result.cost_usd == Decimal(accounting["reserved_usd"])
    assert result.cost_usd > Decimal(accounting["reported_usage_cost_usd"])
    assert await infer(env, inputs={"model": "unpriced", "max_tokens": 99999}) == result
    assert len(env.gateway.requests) == 1 and env.gateway.config_reads == 2
    async with env.factory.begin() as db:
        account = await db.get(Account, env.root_id)
        assert account.reserved_usd == 0 and account.spent_usd == result.cost_usd
        assert (await db.get(AutonomousSession, env.root_id)).cost_total_usd == result.cost_usd


@pytest.mark.parametrize(
    "mutation",
    [
        "unpriced",
        "disabled_pricing",
        "negative",
        "nan",
        "enormous",
        "bool_rate",
        "alias_collision",
        "disabled_provider",
        "missing_provider",
        "duplicate_provider",
        "weak_tier",
        "anonymization_disabled",
        "anonymization_wrong_tier",
    ],
)
async def test_unavailable_route_or_pricing_refuses_before_admission(inference_env, mutation):
    env = inference_env
    config = env.gateway.config
    if mutation == "unpriced":
        config["cost_tracking"]["rates"] = {}
    elif mutation == "disabled_pricing":
        config["cost_tracking"]["enabled"] = False
    elif mutation in {"negative", "nan", "enormous", "bool_rate"}:
        config["cost_tracking"]["rates"]["selected/native"]["input_per_mtok"] = {
            "negative": "-1",
            "nan": "NaN",
            "enormous": "1e100000000",
            "bool_rate": True,
        }[mutation]
    elif mutation == "alias_collision":
        config["model_aliases"]["selected/native"] = config["model_aliases"]["smart"]
    elif mutation == "disabled_provider":
        config["providers"][0]["enabled"] = False
    elif mutation == "missing_provider":
        config["providers"] = []
    elif mutation == "duplicate_provider":
        config["providers"].append(deepcopy(config["providers"][0]))
    elif mutation == "weak_tier":
        config["providers"][0]["tier"] = 2
    elif mutation == "anonymization_disabled":
        config["anonymization"]["enabled"] = False
    else:
        config["anonymization"]["apply_at_tiers"] = [4]
    with pytest.raises(Forbidden, match="route, protection or pricing"):
        await infer(env)
    assert not env.gateway.requests
    async with env.factory.begin() as db:
        assert await db.get(Effect, (env.root_id, "infer:one")) is None


@pytest.mark.parametrize("layer", ["pair", "provider", "type"])
async def test_tier_overrides_follow_gateway_precedence(inference_env, layer):
    env = inference_env
    env.gateway.config["providers"][0]["tier"] = 5
    tiers = env.gateway.config["inference_tiers"]
    if layer == "pair":
        tiers["overrides"] = {"selected/native": 1, "selected": 4}
        tiers["defaults"] = {"openai": 3}
    elif layer == "provider":
        tiers["overrides"] = {"selected": 1}
        tiers["defaults"] = {"openai": 4}
    else:
        tiers["defaults"] = {"openai": 1}
    await infer(env)
    assert len(env.gateway.requests) == 1


async def test_explicit_free_rates_and_equivalent_spellings(inference_env):
    env = inference_env
    rates = env.gateway.config["cost_tracking"]["rates"]["selected/native"]
    rates.update(input_per_mtok=0, output_per_mtok="0.00000000")
    assert (await infer(env)).cost_usd == 0
    rates.update(input_per_mtok="0.0", output_per_mtok=0.0)
    assert (await infer(env)).cost_usd == 0
    assert len(env.gateway.requests) == 1


async def test_changed_price_cannot_reuse_effect_key(inference_env):
    env = inference_env
    await infer(env)
    env.gateway.config["cost_tracking"]["rates"]["selected/native"]["output_per_mtok"] = "8"
    with pytest.raises(Conflict, match="different input"):
        await infer(env)
    assert len(env.gateway.requests) == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"routed_provider": "other"},
        {"routed_model": None},
        {"routed_model": "other"},
        {"routed_inference_tier": 2},
        {"anonymization_applied": False},
        {"choices": []},
    ],
)
async def test_untrusted_response_retains_uncertain_reservation(inference_env, patch):
    env = inference_env
    env.gateway.response_changes = patch
    with pytest.raises(ValidationError, match="untrusted"):
        await infer(env)
    async with env.factory.begin() as db:
        effect = await db.get(Effect, (env.root_id, "infer:one"))
        account = await db.get(Account, env.root_id)
        assert effect.status == "uncertain" and account.reserved_usd == effect.reserved_usd
        assert (
            account.spent_usd == (await db.get(AutonomousSession, env.root_id)).cost_total_usd == 0
        )


async def test_observed_usage_overrun_is_recorded_in_full_and_stops_root(inference_env):
    env = inference_env
    env.gateway.completion_tokens = 1000000
    result = await infer(env)
    assert result.cost_usd == Decimal("6.0001")
    async with env.factory.begin() as db:
        assert (await db.get(Account, env.root_id)).spent_usd == result.cost_usd
        root = await db.get(Root, env.root_id)
        assert root.status == "halted" and root.stop_reason == "observed_budget_overrun"
    with pytest.raises(Conflict):
        await infer(env, key="infer:two")
    assert len(env.gateway.requests) == 1


async def test_config_io_releases_control_locks_and_halt_prevents_dispatch(inference_env):
    env = inference_env

    async def halt():
        await asyncio.wait_for(env.store.halt(env.root_id, actor_id=env.owner_id), timeout=2)

    env.gateway.config_hook = halt
    with pytest.raises(Conflict):
        await infer(env)
    assert not env.gateway.requests


async def test_revocation_during_config_read_refuses(inference_env):
    env = inference_env

    async def revoke():
        env.config.current = None

    env.gateway.config_hook = revoke
    with pytest.raises(Forbidden, match="disabled or changed"):
        await infer(env)
    assert not env.gateway.requests


async def test_input_limit_refuses_before_config_io(inference_env):
    env = inference_env
    with pytest.raises(Forbidden, match="byte limit"):
        await infer(env, inputs={"text": "x" * 33000})
    assert env.gateway.config_reads == 0


async def test_cancellation_keeps_quote_reserved(inference_env):
    env = inference_env
    env.gateway.release.clear()
    task = asyncio.create_task(infer(env))
    await asyncio.wait_for(env.gateway.entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with env.factory.begin() as db:
        effect = await db.get(Effect, (env.root_id, "infer:one"))
        assert effect.status == "uncertain"
        assert (await db.get(Account, env.root_id)).reserved_usd == effect.reserved_usd


async def test_transport_failure_does_not_echo_provider_error_text(inference_env, caplog):
    env = inference_env

    async def fail(request):
        raise RuntimeError("PRIVATE_PROMPT_ECHO")

    env.gateway.chat_completion = fail
    with pytest.raises(Conflict, match="outcome is uncertain") as failure:
        await infer(env)
    assert "PRIVATE_PROMPT_ECHO" not in caplog.text
    assert "PRIVATE_PROMPT_ECHO" not in str(failure.value)
    async with env.factory.begin() as db:
        effect = await db.get(Effect, (env.root_id, "infer:one"))
        assert effect.status == "uncertain" and effect.result is None
        assert (await db.get(Account, env.root_id)).reserved_usd == effect.reserved_usd
