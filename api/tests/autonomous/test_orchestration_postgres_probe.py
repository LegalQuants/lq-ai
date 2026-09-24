"""W2 characterization: actual Postgres checkpoints and unmodified LQ guard.

Run with --extra orchestration-test and a disposable DATABASE_URL. These tests
deliberately expose unsafe replay/ownership windows in naive integration. Their
passing is NOT production adoption evidence: W3/W4 must close those windows.
"""

from __future__ import annotations

import asyncio
import operator
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, TypedDict
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

pytest.importorskip("langgraph.checkpoint.postgres", reason="requires orchestration-test extra")

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.errors import NodeCancelledError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import guarded_tool_call
from app.errors import SessionHalted
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def disable_remote_traces(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


class CrashAfterCommit(RuntimeError):
    """Injected crash between the LQ effect commit and graph checkpoint."""


class ProbeState(TypedDict, total=False):
    session_id: str
    completed: Annotated[list[str], operator.add]


class BatchState(TypedDict):
    session_ids: list[str]
    completed: Annotated[list[str], operator.add]


@dataclass
class ProbeGateway:
    """Provider stub only; the actual guard, estimator, audit and DB run."""

    calls: Counter = field(default_factory=Counter)
    barrier: asyncio.Barrier | None = None
    cancel_at: str | None = None

    async def chat_completion(self, request):
        key = request.messages[0].content
        self.calls[key] += 1
        if self.barrier is not None and key.endswith(":one"):
            await asyncio.wait_for(self.barrier.wait(), timeout=5)
        if key == self.cancel_at:
            raise asyncio.CancelledError("fixture: request may have reached provider")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=""))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )


@pytest_asyncio.fixture
async def run_ids(test_engine: AsyncEngine) -> AsyncIterator[list[str]]:
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as db:
        owner = User(
            email=f"probe-{uuid4()}@example.com",
            hashed_password="unused-fixture",
            autonomous_enabled=True,
        )
        db.add(owner)
        await db.flush()
        sessions = [
            AutonomousSession(
                user_id=owner.id,
                trigger_kind="manual",
                current_phase="analysis",
                max_cost_usd=Decimal("100"),
            )
            for _ in range(2)
        ]
        db.add_all(sessions)
        await db.commit()
        ids = [str(s.id) for s in sessions]
        owner_id = owner.id
    try:
        yield ids
    finally:
        async with factory() as db:
            await db.execute(delete(AuditLog).where(AuditLog.user_id == owner_id))
            await db.execute(delete(User).where(User.id == owner_id))
            await db.commit()


@asynccontextmanager
async def saver_for(test_db_url: str):
    # Every invocation has a fresh saver/connection. No permissive arbitrary
    # object deserialization, pickle fallback or LangSmith callback is enabled.
    serde = JsonPlusSerializer(
        allowed_json_modules=[], allowed_msgpack_modules=[], pickle_fallback=False
    )
    async with AsyncPostgresSaver.from_conn_string(
        test_db_url.replace("postgresql+asyncpg://", "postgresql://", 1), serde=serde
    ) as saver:
        await saver.setup()
        yield saver


def make_graph(
    engine: AsyncEngine,
    gateway: ProbeGateway,
    saver=None,
    *,
    approval: bool = False,
    crash_at: str | None = None,
):
    factory = async_sessionmaker(engine, expire_on_commit=False)

    def make_effect(step: str):
        async def effect(state: ProbeState):
            # Independent session per effect. This intentionally preserves the
            # current guard's transaction semantics for characterization.
            async with factory() as db:
                session = await db.get(AutonomousSession, UUID(state["session_id"]))
                assert session is not None
                try:
                    result = await guarded_tool_call(
                        session,
                        ToolIntent.run_skill,
                        {
                            "model": "fixture",
                            "messages": [{"role": "user", "content": f"{session.id}:{step}"}],
                        },
                        db,
                        gateway,
                    )
                except SessionHalted:
                    await db.commit()  # Existing flush-only brake/audit contract.
                    raise
                assert result.outcome == "success"
                assert result.data["content"] == ""  # Empty is successful work.
                await db.commit()
            if crash_at == step:
                raise CrashAfterCommit(step)
            return {"completed": [step]}

        return effect

    def wait_for_consent(state: ProbeState):
        consent = interrupt({"session_id": state["session_id"]})
        assert consent is True  # Only a runtime interrupt probe, not LQ approval.
        return {}

    builder = StateGraph(ProbeState)
    builder.add_node("one", make_effect("one"))
    builder.add_node("two", make_effect("two"))
    if approval:
        builder.add_node("consent", wait_for_consent)
        builder.add_edge(START, "consent")
        builder.add_edge("consent", "one")
    else:
        builder.add_edge(START, "one")
    builder.add_edge("one", "two")
    builder.add_edge("two", END)
    return builder.compile(checkpointer=saver)


async def test_interrupt_survives_fresh_saver_and_graph(test_engine, test_db_url, run_ids):
    gateway = ProbeGateway()
    config = {"configurable": {"thread_id": str(uuid4())}}
    async with saver_for(test_db_url) as saver:
        result = await make_graph(test_engine, gateway, saver, approval=True).ainvoke(
            {"session_id": run_ids[0], "completed": []}, config, durability="sync"
        )
        assert result["__interrupt__"]
    assert not gateway.calls
    async with saver_for(test_db_url) as saver:
        result = await make_graph(test_engine, gateway, saver, approval=True).ainvoke(
            Command(resume=True), config, durability="sync"
        )
        assert result["completed"] == ["one", "two"]
    assert gateway.calls == {f"{run_ids[0]}:one": 1, f"{run_ids[0]}:two": 1}


async def test_checkpointed_step_survives_but_committed_uncheckpointed_effect_repeats(
    test_engine, test_db_url, run_ids
):
    gateway = ProbeGateway()
    config = {"configurable": {"thread_id": str(uuid4())}}
    async with saver_for(test_db_url) as saver:
        with pytest.raises(CrashAfterCommit):
            await make_graph(test_engine, gateway, saver, crash_at="two").ainvoke(
                {"session_id": run_ids[0], "completed": []}, config, durability="sync"
            )
    async with saver_for(test_db_url) as saver:
        result = await make_graph(test_engine, gateway, saver).ainvoke(
            None, config, durability="sync"
        )
        assert result["completed"] == ["one", "two"]
    # Characterization of the missing durable effect receipt, not a desired
    # production invariant: sync checkpoints cannot close a separate DB commit.
    assert gateway.calls == {f"{run_ids[0]}:one": 1, f"{run_ids[0]}:two": 2}
    async with async_sessionmaker(test_engine)() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.resource_id == run_ids[0],
                AuditLog.action == "autonomous_session.tool_call",
                AuditLog.details["outcome"].astext == "success",
            )
        )
        assert count == 3


async def test_current_halt_wins_over_checkpoint_resume(test_engine, test_db_url, run_ids):
    gateway = ProbeGateway()
    config = {"configurable": {"thread_id": str(uuid4())}}
    async with saver_for(test_db_url) as saver:
        await make_graph(test_engine, gateway, saver, approval=True).ainvoke(
            {"session_id": run_ids[0], "completed": []}, config, durability="sync"
        )
    async with async_sessionmaker(test_engine)() as db:
        await db.execute(
            update(AutonomousSession)
            .where(AutonomousSession.id == UUID(run_ids[0]))
            .values(halt_state="halt_requested")
        )
        await db.commit()
    async with saver_for(test_db_url) as saver:
        with pytest.raises(SessionHalted):
            await make_graph(test_engine, gateway, saver, approval=True).ainvoke(
                Command(resume=True), config, durability="sync"
            )
    assert not gateway.calls
    async with async_sessionmaker(test_engine)() as db:
        session = await db.get(AutonomousSession, UUID(run_ids[0]))
        assert session.halt_state == "halted"


async def test_interrupted_provider_call_needs_receipt_before_io(test_engine, test_db_url, run_ids):
    gateway = ProbeGateway(cancel_at=f"{run_ids[0]}:two")
    config = {"configurable": {"thread_id": str(uuid4())}}
    async with saver_for(test_db_url) as saver:
        # The locked 1.2.11 runtime makes a node-raised cancellation an explicit
        # failure, rather than silently treating it as a completed node.
        with pytest.raises(NodeCancelledError):
            await make_graph(test_engine, gateway, saver).ainvoke(
                {"session_id": run_ids[0], "completed": []}, config, durability="sync"
            )
    async with async_sessionmaker(test_engine)() as db:
        started = await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.resource_id == run_ids[0],
                AuditLog.action == "autonomous_session.tool_call",
                AuditLog.details["outcome"].astext == "started",
            )
        )
        # The uncommitted second intent disappeared, despite the stub receiving
        # that request. A checkpoint cannot reconstruct an uncertain effect.
        assert started == 1
    gateway.cancel_at = None
    async with saver_for(test_db_url) as saver:
        await make_graph(test_engine, gateway, saver).ainvoke(None, config, durability="sync")
    assert gateway.calls == {f"{run_ids[0]}:one": 1, f"{run_ids[0]}:two": 2}


async def test_langgraph_fanout_overlaps_multistep_children_with_independent_sessions(
    test_engine, test_db_url, run_ids
):
    gateway = ProbeGateway(barrier=asyncio.Barrier(2))
    config = {"configurable": {"thread_id": str(uuid4())}, "max_concurrency": 2}
    async with saver_for(test_db_url) as saver:
        child = make_graph(test_engine, gateway)

        async def research(state: ProbeState):
            result = await child.ainvoke(state)
            assert result["completed"] == ["one", "two"]
            return {"completed": [state["session_id"]]}

        def dispatch(state: BatchState):
            return [
                Send("research", {"session_id": session_id, "completed": []})
                for session_id in state["session_ids"]
            ]

        batch = StateGraph(BatchState)
        batch.add_node("research", research)
        batch.add_conditional_edges(START, dispatch, ["research"])
        batch.add_edge("research", END)
        result = await batch.compile(checkpointer=saver).ainvoke(
            {"session_ids": run_ids, "completed": []}, config, durability="sync"
        )
        assert sorted(result["completed"]) == sorted(run_ids)
    assert gateway.calls == {f"{sid}:{step}": 1 for sid in run_ids for step in ("one", "two")}


async def test_saver_is_not_an_exclusive_worker_claim(test_engine, test_db_url, run_ids):
    gateway = ProbeGateway(barrier=asyncio.Barrier(2))
    config = {"configurable": {"thread_id": str(uuid4())}}
    async with saver_for(test_db_url) as first_saver, saver_for(test_db_url) as second_saver:
        first = make_graph(test_engine, gateway, first_saver)
        second = make_graph(test_engine, gateway, second_saver)
        initial = {"session_id": run_ids[0], "completed": []}
        await asyncio.gather(
            first.ainvoke(initial, config, durability="sync"),
            second.ainvoke(initial, config, durability="sync"),
        )
    # Both owners crossed the real guard and reached the first provider call.
    # The production adapter needs an LQ claim/fence before invoking LangGraph.
    assert gateway.calls[f"{run_ids[0]}:one"] == 2
