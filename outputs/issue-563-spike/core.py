"""Application-owned contracts and effect receipts. No workflow-library imports.

SQLite and integer call allowances are experiment substitutes for LQ's database,
identity, guard, and cost accounting. This module is not production governance.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

CONTRACT_VERSION = 1


class ContractError(Exception):
    pass


@dataclass(frozen=True)
class Topic:
    id: str
    question: str
    sources: tuple[str, ...]
    documents: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    run_id: str
    topics: tuple[Topic, ...]
    revision: int = 1
    call_allowance: int = 2
    version: int = CONTRACT_VERSION

    @property
    def digest(self) -> str:
        return hashlib.sha256(encode(asdict(self)).encode()).hexdigest()


@dataclass(frozen=True)
class Outcome:
    topic_id: str
    status: str
    output: str = ""


@dataclass(frozen=True)
class RunView:
    run_id: str
    status: str
    outcomes: tuple[Outcome, ...]


class Search(Protocol):
    async def __call__(self, run_id: str, topic: Topic) -> str: ...


class Runner(Protocol):
    async def tick(self, run_id: str) -> RunView: ...


def encode(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, path: Path):
        self.path = path
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, plan TEXT NOT NULL,
                    approved TEXT, halted INTEGER NOT NULL DEFAULT 0,
                    sources TEXT NOT NULL, documents TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS effects (
                    run_id TEXT NOT NULL, topic_id TEXT NOT NULL,
                    status TEXT NOT NULL, output TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (run_id, topic_id)
                );
            """)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def create(self, plan: Plan) -> None:
        ids = [topic.id for topic in plan.topics]
        if not 1 <= len(ids) <= 4 or len(ids) != len(set(ids)):
            raise ContractError("one to four distinct topics required")
        with self.transaction() as db:
            db.execute(
                "INSERT INTO runs(id, plan, sources, documents) VALUES (?, ?, ?, ?)",
                (
                    plan.run_id,
                    encode(asdict(plan)),
                    encode(sorted({s for t in plan.topics for s in t.sources})),
                    encode(sorted({d for t in plan.topics for d in t.documents})),
                ),
            )

    def plan(self, run_id: str, digest: str | None = None) -> Plan:
        with self.transaction() as db:
            row = db.execute("SELECT plan FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise ContractError("unknown run")
        raw = json.loads(row["plan"])
        raw["topics"] = tuple(
            Topic(t["id"], t["question"], tuple(t["sources"]), tuple(t["documents"]))
            for t in raw["topics"]
        )
        plan = Plan(**raw)
        if plan.version != CONTRACT_VERSION:
            raise ContractError("unsupported application contract version")
        if digest is not None and digest != plan.digest:
            raise ContractError("stale plan digest")
        return plan

    def approve(self, run_id: str, digest: str) -> None:
        self.plan(run_id, digest)
        with self.transaction() as db:
            if db.execute("SELECT halted FROM runs WHERE id = ?", (run_id,)).fetchone()[
                0
            ]:
                raise ContractError("run halted")
            db.execute("UPDATE runs SET approved = ? WHERE id = ?", (digest, run_id))

    def approved(self, run_id: str, digest: str) -> bool:
        self.plan(run_id, digest)
        with self.transaction() as db:
            value = db.execute(
                "SELECT approved FROM runs WHERE id = ?", (run_id,)
            ).fetchone()[0]
        return bool(value == digest)

    def halt(self, run_id: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE runs SET halted = 1 WHERE id = ?", (run_id,))

    def revoke_sources(self, run_id: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE runs SET sources = '[]' WHERE id = ?", (run_id,))

    def claim(self, plan: Plan, topic: Topic) -> Outcome | None:
        """One atomic admission/receipt. None means this caller acquired the effect.

        An existing 'started' receipt has unknown external outcome. This experiment
        requires exclusive coordinator ownership; it does not implement leases.
        """
        with self.transaction() as db:
            run = db.execute(
                "SELECT * FROM runs WHERE id = ?", (plan.run_id,)
            ).fetchone()
            if run["approved"] != plan.digest:
                raise ContractError("approval required")
            previous = db.execute(
                "SELECT status, output FROM effects WHERE run_id = ? AND topic_id = ?",
                (plan.run_id, topic.id),
            ).fetchone()
            if previous:
                status = (
                    "uncertain"
                    if previous["status"] == "started"
                    else previous["status"]
                )
                return Outcome(topic.id, status, previous["output"])
            reason = ""
            if run["halted"]:
                reason = "halted"
            elif not set(topic.sources) <= set(json.loads(run["sources"])):
                reason = "source access revoked"
            elif not set(topic.documents) <= set(json.loads(run["documents"])):
                reason = "document access revoked"
            elif run["used"] >= plan.call_allowance:
                reason = "call allowance exhausted"
            status = "blocked" if reason else "started"
            db.execute(
                "INSERT INTO effects VALUES (?, ?, ?, ?)",
                (plan.run_id, topic.id, status, reason),
            )
            if reason:
                return Outcome(topic.id, status, reason)
            db.execute("UPDATE runs SET used = used + 1 WHERE id = ?", (plan.run_id,))
        return None

    def finish(self, run_id: str, outcome: Outcome) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE effects SET status = ?, output = ? "
                "WHERE run_id = ? AND topic_id = ? AND status = 'started'",
                (outcome.status, outcome.output, run_id, outcome.topic_id),
            )

    def view(self, run_id: str) -> RunView:
        plan = self.plan(run_id)
        with self.transaction() as db:
            rows = db.execute(
                "SELECT topic_id, status, output FROM effects WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        by_id = {
            row["topic_id"]: Outcome(
                row["topic_id"],
                "uncertain" if row["status"] == "started" else row["status"],
                row["output"],
            )
            for row in rows
        }
        outcomes = tuple(by_id[t.id] for t in plan.topics if t.id in by_id)
        if not self.approved(run_id, plan.digest):
            status = "awaiting_approval"
        elif any(o.status != "complete" for o in outcomes):
            status = "needs_attention"
        elif len(outcomes) == len(plan.topics):
            status = "complete"
        else:
            status = "ready"
        return RunView(run_id, status, outcomes)


class Service:
    def __init__(
        self,
        store: Store,
        search: Search,
        after_persist: Callable[[Outcome], None] | None = None,
    ):
        self.store = store
        self.search = search
        self.after_persist = after_persist

    async def execute(self, run_id: str, digest: str, topic_id: str) -> Outcome:
        plan = self.store.plan(run_id, digest)
        topic = next(t for t in plan.topics if t.id == topic_id)
        previous = self.store.claim(plan, topic)
        if previous is not None:
            return previous
        # No await between admission and initiating the stub call. An external
        # action and this database transaction are still not atomic.
        try:
            output = await self.search(run_id, topic)
            outcome = Outcome(topic.id, "complete", output)
        except Exception as exc:
            # An ordinary exception is terminal in this fixture; no automatic retry.
            outcome = Outcome(topic.id, "failed", type(exc).__name__)
        self.store.finish(run_id, outcome)
        if self.after_persist is not None:
            self.after_persist(outcome)
        return outcome
