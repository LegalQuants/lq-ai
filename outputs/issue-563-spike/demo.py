"""Separate-process demo and deliberate crash injection. Uses stub searches only."""

import argparse
import asyncio
import importlib
import json
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import cast

from core import Outcome, Plan, Runner, Service, Store, Topic


def example_plan() -> Plan:
    return Plan(
        "research",
        (
            Topic(
                "topic-a", "Research topic A", ("enabled-source",), ("selected-doc",)
            ),
            Topic(
                "topic-b", "Research topic B", ("enabled-source",), ("selected-doc",)
            ),
        ),
    )


class RecordingSearch:
    def __init__(self, directory: Path, fault: str):
        self.path = directory / "provider.sqlite"
        self.fault = fault

    async def __call__(self, run_id: str, topic: Topic) -> str:
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls(run_id TEXT, topic_id TEXT)")
            db.execute("INSERT INTO calls VALUES (?, ?)", (run_id, topic.id))
        if self.fault == "after-effect":
            os._exit(74)  # Intentional process death before the application receipt.
        # Complete synchronously for a deterministic crash after topic A's receipt,
        # before topic B starts. Actual overlap is checked with barriers in tests.
        return ""  # Empty output is deliberately valid.


def make_runner(backend: str, service: Service, directory: Path) -> Runner:
    # Lazy loading lets `python -S demo.py native ...` run with no third-party deps.
    if backend == "native":
        module = importlib.import_module("native_adapter")
        return cast(Runner, module.NativeRunner(service))
    module = importlib.import_module("langgraph_adapter")
    return cast(Runner, module.LangGraphRunner(service, directory / "cursor.sqlite"))


async def main() -> None:
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=["native", "langgraph"])
    parser.add_argument("action", choices=["prepare", "approve", "run"])
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--fault", choices=["none", "after-receipt", "after-effect"], default="none"
    )
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    store = Store(args.directory / "application.sqlite")
    if args.action == "prepare":
        store.create(example_plan())
    plan = store.plan("research")
    if args.action == "approve":
        store.approve(plan.run_id, plan.digest)
        print(json.dumps({"approved_digest": plan.digest}))
        return

    def after_persist(outcome: Outcome) -> None:
        if args.fault == "after-receipt" and outcome.topic_id == "topic-a":
            os._exit(73)  # Intentional gap: receipt committed, graph not checkpointed.

    service = Service(store, RecordingSearch(args.directory, args.fault), after_persist)
    runner = make_runner(args.backend, service, args.directory)
    result = await runner.tick(plan.run_id)
    response = asdict(result)
    if args.action == "prepare":
        response["plan"] = asdict(plan)
        response["plan_digest"] = plan.digest
    print(json.dumps(response, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
