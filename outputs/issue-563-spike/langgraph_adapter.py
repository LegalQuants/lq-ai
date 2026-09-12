"""The only module allowed to import LangGraph or LangChain.

Public boundary: application run ID -> application RunView. Checkpoint schema,
Send, Command, interrupt, and RunnableConfig remain private to this adapter.
"""

from pathlib import Path
from typing import TypedDict

import aiosqlite
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from core import ContractError, RunView, Service

GRAPH_VERSION = "research-batch-v1"


class _Cursor(TypedDict):
    run_id: str
    digest: str
    graph_version: str


class _Child(TypedDict):
    run_id: str
    digest: str
    topic_id: str


class LangGraphRunner:
    def __init__(self, service: Service, checkpoint_path: Path):
        self.service = service
        self.checkpoint_path = checkpoint_path

    async def tick(self, run_id: str) -> RunView:
        store = self.service.store
        plan = store.plan(run_id)

        def approval(state: _Cursor) -> dict[str, str]:
            store.plan(state["run_id"], state["digest"])
            interrupt({"run_id": state["run_id"], "plan_digest": state["digest"]})
            # A resume payload cannot grant permission. Only the application can.
            if not store.approved(state["run_id"], state["digest"]):
                raise ContractError("approval required")
            return {}

        def fan_out(state: _Cursor) -> list[Send]:
            current = store.plan(state["run_id"], state["digest"])
            return [
                Send(
                    "child",
                    {"run_id": run_id, "digest": current.digest, "topic_id": t.id},
                )
                for t in current.topics
            ]

        async def child(state: _Child) -> dict[str, str]:
            await self.service.execute(
                state["run_id"], state["digest"], state["topic_id"]
            )
            # Results stay in application storage; no reducer duplicates outcomes.
            return {}

        def join(state: _Cursor) -> dict[str, str]:
            store.plan(state["run_id"], state["digest"])
            return {}

        builder = StateGraph(_Cursor)
        builder.add_node("approval", approval)
        builder.add_node("child", child)
        builder.add_node("join", join)
        builder.add_edge(START, "approval")
        builder.add_conditional_edges("approval", fan_out, ["child"])
        builder.add_edge("child", "join")
        builder.add_edge("join", END)
        config: RunnableConfig = {
            "configurable": {"thread_id": run_id},
            "max_concurrency": 2,
        }
        async with aiosqlite.connect(self.checkpoint_path) as connection:
            saver = AsyncSqliteSaver(
                connection,
                serde=JsonPlusSerializer(allowed_msgpack_modules=None),
            )
            graph = builder.compile(checkpointer=saver)
            snapshot = await graph.aget_state(config)
            if snapshot.values:
                if snapshot.values.get("graph_version") != GRAPH_VERSION:
                    raise ContractError("incompatible graph cursor; drain or migrate")
                store.plan(run_id, snapshot.values["digest"])
                # An empty `next` alone is insufficient after a process crash:
                # a checkpoint can still have pending writes/interrupt tasks.
                if not snapshot.next and not snapshot.tasks:
                    return store.view(run_id)
                if not any(task.interrupts for task in snapshot.tasks):
                    await graph.ainvoke(None, config, durability="sync")
            else:
                await graph.ainvoke(
                    {
                        "run_id": run_id,
                        "digest": plan.digest,
                        "graph_version": GRAPH_VERSION,
                    },
                    config,
                    durability="sync",
                )
            snapshot = await graph.aget_state(config)
            if any(task.interrupts for task in snapshot.tasks):
                if store.approved(run_id, plan.digest):
                    await graph.ainvoke(Command(resume=True), config, durability="sync")
            return store.view(run_id)
