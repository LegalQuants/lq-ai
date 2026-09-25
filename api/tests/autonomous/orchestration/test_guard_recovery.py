"""New store closes the W2 gaps with actual Postgres checkpoints and LQ guard.

The graph below is an integration fixture, not the production adapter. Current
resource policy is the explicit fixture checker from conftest. Providers are
stubbed; only ID/step metadata enters framework state.
"""

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import TypedDict
from uuid import uuid4

import pytest
from sqlalchemy import func, update

pytest.importorskip("langgraph.checkpoint.postgres", reason="requires orchestration-test extra")

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import guarded_tool_call
from app.errors import Conflict
from app.models.autonomous import AutonomousSession
from app.models.orchestration import OrchestrationAccount as Account, OrchestrationEffect as Effect
from app.schemas.autonomous import Phase

pytestmark = pytest.mark.integration


class InjectedCrash(RuntimeError):
    pass


class State(TypedDict, total=False):
    completed: str


class Gateway:
    def __init__(self):
        self.calls = Counter()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def chat_completion(self, request):
        self.calls[request.messages[0].content] += 1
        self.entered.set()
        await asyncio.wait_for(self.release.wait(), timeout=5)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=""))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )


@asynccontextmanager
async def graph_for(env, test_db_url, gateway, *, crash=None):
    async def effect(step):
        key = f"analysis:{step}"
        receipt = await env.store.begin_effect(
            env.claim,
            effect_key=key,
            request_hash="b" * 64,
            reservation_usd=Decimal("1"),
            phase=Phase.analysis,
            intent=ToolIntent.run_skill,
        )
        if receipt.status == "completed":
            return {"completed": step}
        assert receipt.status == "admitted"
        async with env.factory.begin() as db:
            session = await db.get(AutonomousSession, env.root_id)
            result = await guarded_tool_call(
                session,
                ToolIntent.run_skill,
                {"model": "fixture", "messages": [{"role": "user", "content": step}]},
                db,
                gateway,
            )
        if crash == "after_provider" and step == "one":
            raise InjectedCrash("outcome unknown to receipt store")
        await env.store.complete_effect(
            env.claim,
            effect_key=key,
            charged_usd=result.cost_usd,
            result={"content": result.data["content"], "outcome": result.outcome},
        )
        if crash == "after_receipt" and step == "one":
            raise InjectedCrash("receipt committed but node not checkpointed")
        return {"completed": step}

    async def one(state: State):
        return await effect("one")

    async def two(state: State):
        return await effect("two")

    serde = JsonPlusSerializer(
        allowed_msgpack_modules=[], allowed_json_modules=[], pickle_fallback=False
    )
    async with AsyncPostgresSaver.from_conn_string(
        test_db_url.replace("postgresql+asyncpg://", "postgresql://", 1), serde=serde
    ) as saver:
        await saver.setup()
        graph = StateGraph(State)
        graph.add_node("one", one)
        graph.add_node("two", two)
        graph.add_edge(START, "one")
        graph.add_edge("one", "two")
        graph.add_edge("two", END)
        yield graph.compile(checkpointer=saver)


async def expire(env):
    async with env.factory.begin() as db:
        await db.execute(
            update(Account)
            .where(Account.session_id == env.root_id)
            .values(lease_until=func.clock_timestamp())
        )


@pytest.fixture(autouse=True)
def no_remote_traces(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


async def test_completed_effect_is_not_repeated_after_checkpoint_gap(ready, test_db_url):
    env, gateway = ready, Gateway()
    config = {"configurable": {"thread_id": str(uuid4())}}
    async with graph_for(env, test_db_url, gateway, crash="after_receipt") as graph:
        with pytest.raises(InjectedCrash):
            await graph.ainvoke({}, config, durability="sync")
    await expire(env)
    env.claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    async with graph_for(env, test_db_url, gateway) as graph:
        result = await graph.ainvoke(None, config, durability="sync")
    assert result["completed"] == "two"
    assert gateway.calls == {"one": 1, "two": 1}


async def test_uncertain_provider_outcome_cannot_be_replayed(ready, test_db_url):
    env, gateway = ready, Gateway()
    config = {"configurable": {"thread_id": str(uuid4())}}
    async with graph_for(env, test_db_url, gateway, crash="after_provider") as graph:
        with pytest.raises(InjectedCrash):
            await graph.ainvoke({}, config, durability="sync")
    await expire(env)
    with pytest.raises(Conflict, match="reconciliation"):
        await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    async with graph_for(env, test_db_url, gateway) as graph:
        with pytest.raises(Conflict):
            await graph.ainvoke(None, config, durability="sync")
    assert gateway.calls == {"one": 1}
    async with env.factory() as db:
        assert (await db.get(Effect, (env.root_id, "analysis:one"))).status == "uncertain"
        assert (await db.get(Account, env.root_id)).reserved_usd == 1


async def test_halt_commits_while_guarded_provider_call_is_waiting(ready, test_db_url):
    env, gateway = ready, Gateway()
    gateway.release.clear()
    config = {"configurable": {"thread_id": str(uuid4())}}
    async with graph_for(env, test_db_url, gateway) as graph:
        execution = asyncio.create_task(graph.ainvoke({}, config, durability="sync"))
        try:
            await asyncio.wait_for(gateway.entered.wait(), timeout=5)
            # This would time out if a control-row lock spanned provider I/O.
            await asyncio.wait_for(env.store.halt(env.root_id, actor_id=env.owner_id), timeout=2)
            gateway.release.set()
            with pytest.raises(Conflict):
                await execution
        finally:
            gateway.release.set()
            if not execution.done():
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
    assert gateway.calls == {"one": 1}
    async with env.factory() as db:
        assert (await db.get(Effect, (env.root_id, "analysis:one"))).status == "completed"
