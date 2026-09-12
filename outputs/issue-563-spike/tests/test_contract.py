import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from core import ContractError, Service, Store, Topic
from demo import example_plan, make_runner


@pytest.fixture(params=["native", "langgraph"])
def backend(request: pytest.FixtureRequest) -> str:
    return str(request.param)


class BarrierSearch:
    """Fails unless two children enter together; no timing-based speed assertion."""

    def __init__(self) -> None:
        self.calls: list[Topic] = []
        self.release = asyncio.Event()
        self.active = 0
        self.peak = 0

    async def __call__(self, run_id: str, topic: Topic) -> str:
        self.calls.append(topic)
        self.active += 1
        self.peak = max(self.peak, self.active)
        if len(self.calls) >= 2:
            self.release.set()
        try:
            await asyncio.wait_for(self.release.wait(), timeout=5)
            return ""
        finally:
            self.active -= 1


async def test_approval_parallel_scope_empty_output_and_idempotence(
    tmp_path: Path, backend: str
) -> None:
    store = Store(tmp_path / "application.sqlite")
    plan = example_plan()
    store.create(plan)
    search = BarrierSearch()
    runner = make_runner(backend, Service(store, search), tmp_path)
    assert (await runner.tick(plan.run_id)).status == "awaiting_approval"
    assert search.calls == []
    with pytest.raises(ContractError, match="stale plan"):
        store.approve(plan.run_id, "stale-digest")
    assert search.calls == []
    store.approve(plan.run_id, plan.digest)
    store.approve(plan.run_id, plan.digest)
    result = await runner.tick(plan.run_id)
    assert result.status == "complete"
    assert [o.output for o in result.outcomes] == ["", ""]
    assert search.peak == 2
    assert set(search.calls) == set(plan.topics)
    assert await runner.tick(plan.run_id) == result
    assert len(search.calls) == 2


@pytest.mark.parametrize("control", ["halt", "revoke", "allowance"])
async def test_current_controls_override_paused_execution(
    tmp_path: Path, backend: str, control: str
) -> None:
    calls: list[str] = []

    async def search(run_id: str, topic: Topic) -> str:
        calls.append(topic.id)
        await asyncio.sleep(0)
        return ""

    store = Store(tmp_path / "application.sqlite")
    plan = replace(example_plan(), call_allowance=1 if control == "allowance" else 2)
    store.create(plan)
    runner = make_runner(backend, Service(store, search), tmp_path)
    await runner.tick(plan.run_id)
    store.approve(plan.run_id, plan.digest)
    if control == "halt":
        store.halt(plan.run_id)
    elif control == "revoke":
        store.revoke_sources(plan.run_id)
    result = await runner.tick(plan.run_id)
    assert result.status == "needs_attention"
    assert len(calls) == (1 if control == "allowance" else 0)
    assert sum(o.status == "blocked" for o in result.outcomes) == 2 - len(calls)


async def test_failure_is_visible_and_does_not_cancel_sibling(
    tmp_path: Path, backend: str
) -> None:
    async def search(run_id: str, topic: Topic) -> str:
        if topic.id == "topic-a":
            raise ValueError("controlled failure")
        return ""

    store = Store(tmp_path / "application.sqlite")
    plan = example_plan()
    store.create(plan)
    store.approve(plan.run_id, plan.digest)
    result = await make_runner(backend, Service(store, search), tmp_path).tick(
        plan.run_id
    )
    assert result.status == "needs_attention"
    assert [o.status for o in result.outcomes] == ["failed", "complete"]


async def test_halt_during_parallel_work_blocks_the_next_wave(
    tmp_path: Path, backend: str
) -> None:
    store = Store(tmp_path / "application.sqlite")
    base = example_plan()
    plan = replace(
        base,
        topics=base.topics
        + tuple(replace(base.topics[0], id=f"topic-{i}") for i in range(2, 4)),
        call_allowance=4,
    )
    store.create(plan)
    store.approve(plan.run_id, plan.digest)
    barrier = BarrierSearch()

    async def search(run_id: str, topic: Topic) -> str:
        await barrier(run_id, topic)
        store.halt(run_id)
        return ""

    result = await make_runner(backend, Service(store, search), tmp_path).tick(
        plan.run_id
    )
    assert barrier.peak == 2
    assert len(barrier.calls) == 2
    assert [o.status for o in result.outcomes] == [
        "complete",
        "complete",
        "blocked",
        "blocked",
    ]


async def test_contract_version_mismatch_refuses_execution(
    tmp_path: Path, backend: str
) -> None:
    store = Store(tmp_path / "application.sqlite")
    store.create(replace(example_plan(), version=999))
    search = BarrierSearch()
    with pytest.raises(ContractError, match="contract version"):
        await make_runner(backend, Service(store, search), tmp_path).tick("research")
    assert search.calls == []


async def test_graph_version_mismatch_refuses_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import langgraph_adapter

    store = Store(tmp_path / "application.sqlite")
    store.create(example_plan())
    search = BarrierSearch()
    runner = make_runner("langgraph", Service(store, search), tmp_path)
    await runner.tick("research")
    monkeypatch.setattr(langgraph_adapter, "GRAPH_VERSION", "incompatible-deployment")
    with pytest.raises(ContractError, match="incompatible graph cursor"):
        await runner.tick("research")
    assert search.calls == []
