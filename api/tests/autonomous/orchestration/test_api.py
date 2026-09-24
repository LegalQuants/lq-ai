"""Committed consent/tree flow and an optional disposable real-arq probe."""

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.api.dependencies import get_active_user
from app.api.orchestration import service
from app.autonomous.orchestration.service import DemonstrationService
from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.autonomous import AutonomousSession
from app.models.orchestration import OrchestrationRoot as Root
from app.models.user import User
from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry
from app.workers.autonomous_worker import _run_idle_sweep
from app.workers.orchestration_worker import orchestration_session_job, orchestration_watchdog

BASE = "/api/v1/autonomous/orchestration"


@pytest_asyncio.fixture
async def api_demo(env, test_db_url, monkeypatch):
    skills = MutableSkillRegistry(load_registry(Path(__file__).resolve().parents[4] / "skills"))
    settings = get_settings().model_copy(
        update={
            "database_url": test_db_url,
            "orchestration_demo_enabled": True,
            "orchestration_deployment_children": 2,
        }
    )
    runtime = DemonstrationService(settings, skills, env.factory)
    await runtime.executor().checkpoints.setup()
    async with env.factory() as db:
        user = await db.get(User, env.owner_id)
    queued = []

    async def enqueue(root_id, session_id):
        queued.append((root_id, session_id))
        return True

    monkeypatch.setattr("app.api.orchestration.enqueue_orchestration_job", enqueue)
    monkeypatch.setattr("app.workers.orchestration_worker.enqueue_orchestration_job", enqueue)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_active_user] = lambda: user
    app.dependency_overrides[service] = lambda: runtime
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, runtime=runtime, env=env, user=user, queued=queued)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


async def prepare(api):
    result = await api.client.post(
        f"{BASE}/plans",
        json={
            "project_id": str(api.env.project_id),
            "goal": "Demonstrate the orchestrator",
            "topics": ["Scope", "Evidence"],
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


async def test_api_approval_worker_progress_and_root_delivery(api_demo):
    api = api_demo
    tree = await prepare(api)
    assert tree["status"] == "awaiting_approval" and not tree["approved"]
    assert all(child["status"] == "pending" for child in tree["children"])
    assert not api.queued
    root_id = tree["root_id"]
    consent = {"revision": tree["plan"]["revision"], "plan_hash": tree["plan_hash"]}
    stale = await api.client.post(
        f"{BASE}/{root_id}/approve", json={**consent, "plan_hash": "0" * 64}
    )
    assert stale.status_code == 409 and not api.queued
    approved = await api.client.post(f"{BASE}/{root_id}/approve", json=consent)
    assert approved.status_code == 200 and approved.json()["approved"]
    ctx = {"orchestration_runtime": api.runtime}
    assert await orchestration_session_job(ctx, root_id, root_id) == {"status": "waiting_children"}
    for child in tree["children"]:
        assert await orchestration_session_job(ctx, root_id, child["session_id"]) == {
            "status": "completed"
        }
    assert await orchestration_session_job(ctx, root_id, root_id) == {"status": "completed"}
    finished = (await api.client.get(f"{BASE}/{root_id}/tree")).json()
    assert finished["status"] == "completed" and finished["result"]["coverage"] == "complete"
    assert finished["verification"] == finished["result"]["verification"] == "unverified"
    assert finished["spent_usd"] == finished["reserved_usd"] == "0.0000"
    assert len(finished["root"]["effects"]) == 3  # Two shared-file reads and synthesis.
    assert all(len(child["files"]) == 2 for child in finished["children"])
    child_id = finished["children"][0]["session_id"]
    file_url = f"{BASE}/{root_id}/files/{child_id}/notes.md"
    api.runtime.settings.orchestration_demo_enabled = False
    api.user.autonomous_enabled = False
    file = await api.client.get(file_url)
    assert file.status_code == 200 and file.json()["revision"] == 2
    assert not file.json()["shared"]
    api.user.id = uuid4()
    assert (await api.client.get(file_url)).status_code == 404


async def test_feature_gate_privacy_and_audit_after_opt_out(api_demo):
    api = api_demo
    tree = await prepare(api)
    root_id = tree["root_id"]
    api.runtime.settings.orchestration_demo_enabled = False
    assert not (await api.client.get(f"{BASE}/capabilities")).json()["enabled"]
    denied = await api.client.post(
        f"{BASE}/plans",
        json={"project_id": str(api.env.project_id), "goal": "Try disabled", "topics": ["One"]},
    )
    assert denied.status_code == 403
    api.user.autonomous_enabled = False
    assert (await api.client.get(f"{BASE}/{root_id}/tree")).status_code == 200
    halt = await api.client.post(f"{BASE}/{root_id}/halt")
    assert halt.status_code == 200 and halt.json()["partial_summary"]
    api.user.id = uuid4()
    for method, suffix, body in [("GET", "tree", None), ("POST", "halt", None)]:
        assert (
            await api.client.request(method, f"{BASE}/{root_id}/{suffix}", json=body)
        ).status_code == 404


async def test_rejection_and_explicit_intake_validation(api_demo):
    api = api_demo
    for changes in (
        {"topics": []},
        {"topics": ["x"] * 5},
        {"goal": "  "},
        {"handler": "untrusted"},
        {"max_active_children": True},
    ):
        response = await api.client.post(
            f"{BASE}/plans",
            json={
                "project_id": str(api.env.project_id),
                "goal": "Demo",
                "topics": ["One"],
                **changes,
            },
        )
        assert response.status_code == 422
    tree = await prepare(api)
    rejected = await api.client.post(f"{BASE}/{tree['root_id']}/reject", json={"revision": 1})
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert not api.queued
    # Rejection frees the one-active-root allowance.
    assert (await prepare(api))["root_id"] != tree["root_id"]


async def test_recovery_requeues_lost_wakeup_and_legacy_idle_ignores_tree(api_demo):
    api = api_demo
    tree = await prepare(api)
    root_id = tree["root_id"]
    await api.client.post(
        f"{BASE}/{root_id}/approve", json={"revision": 1, "plan_hash": tree["plan_hash"]}
    )
    api.queued.clear()
    ctx = {"orchestration_runtime": api.runtime}
    result = await orchestration_watchdog(ctx)
    assert result["woken"] == 1 and api.queued
    await orchestration_session_job(ctx, root_id, root_id)
    async with api.env.factory.begin() as db:
        now = await db.scalar(select(func.clock_timestamp()))
        await db.execute(
            update(AutonomousSession)
            .where(AutonomousSession.root_session_id == root_id)
            .values(last_activity_at=now - timedelta(minutes=30))
        )
        await _run_idle_sweep(db, now=now)
    async with api.env.factory() as db:
        rows = list(
            await db.scalars(
                select(AutonomousSession).where(AutonomousSession.root_session_id == root_id)
            )
        )
        assert all(row.halt_state == "running" for row in rows)
        assert (await db.get(Root, root_id)).status == "waiting_children"


async def test_existing_receipt_halt_and_legacy_job_preserve_governed_boundary(
    api_demo, monkeypatch
):
    from app.workers import autonomous_worker

    api = api_demo
    tree = await prepare(api)
    root_id = tree["root_id"]
    await api.client.post(
        f"{BASE}/{root_id}/approve", json={"revision": 1, "plan_hash": tree["plan_hash"]}
    )
    await orchestration_session_job({"orchestration_runtime": api.runtime}, root_id, root_id)
    child_id = tree["children"][0]["session_id"]
    monkeypatch.setattr(autonomous_worker, "get_session_factory", lambda: api.env.factory)
    monkeypatch.setattr(autonomous_worker, "_gateway_from_ctx", lambda ctx: None)
    blocked = await autonomous_worker.autonomous_session_job({}, child_id)
    assert blocked["status"] == "governed_orchestration_only"

    async def db_override():
        async with api.env.factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr("app.api.orchestration.service", lambda request: api.runtime)
    halted = await api.client.post(f"/api/v1/autonomous/sessions/{child_id}/halt")
    assert halted.status_code == 200 and halted.json()["status"] == "halted"
    state = (await api.client.get(f"{BASE}/{root_id}/tree")).json()
    assert state["status"] == "halted"
    assert all(child["status"] == "halted" for child in state["children"])


@pytest.mark.integration
async def test_real_arq_worker_completes_tree_from_one_approved_wakeup(api_demo, tmp_path):
    """Optional real Redis probe; the supplied Redis must be disposable."""
    from arq import create_pool
    from arq.connections import RedisSettings

    redis_url = os.environ.get("LQ_ORCHESTRATION_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("Set LQ_ORCHESTRATION_TEST_REDIS_URL to a disposable Redis database")
    api = api_demo
    tree = await prepare(api)
    root_id = tree["root_id"]
    await api.client.post(
        f"{BASE}/{root_id}/approve", json={"revision": 1, "plan_hash": tree["plan_hash"]}
    )
    pool = await create_pool(RedisSettings.from_dsn(redis_url), default_queue_name="arq:m3a6")
    peer_env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
    peer_env.update(
        {
            "DATABASE_URL": api.runtime.settings.database_url,
            "REDIS_URL": redis_url,
            "LQ_AI_SKILLS_DIR": str(Path(__file__).resolve().parents[4] / "skills"),
            "LQ_AI_ORCHESTRATION_DEMO_ENABLED": "true",
            "LQ_AI_ORCHESTRATION_DEPLOYMENT_CHILDREN": "2",
            "LQ_AI_DEV_MODE": "true",
            "JWT_SECRET": "disposable-orchestration-worker-secret-563",
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
        }
    )
    with (tmp_path / "arq.log").open("w+") as log:
        worker = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "arq",
            "app.workers.arq_setup.WorkerSettings",
            cwd=Path(__file__).resolve().parents[3],
            env=peer_env,
            stdout=log,
            stderr=log,
        )
        try:
            await pool.enqueue_job(
                "orchestration_session_job", root_id, root_id, _job_id=f"orchestration:{root_id}"
            )
            async with asyncio.timeout(40):
                while True:
                    result = (await api.client.get(f"{BASE}/{root_id}/tree")).json()
                    if result["status"] == "completed":
                        break
                    if worker.returncode is not None:
                        log.seek(0)
                        pytest.fail(f"Disposable worker exited: {log.read()}")
                    await asyncio.sleep(0.2)
            assert result["result"]["coverage"] == "complete"
            assert len(result["root"]["effects"]) == 3
            assert all(len(child["effects"]) == 7 for child in result["children"])
        finally:
            if worker.returncode is None:
                worker.terminate()
            try:
                await asyncio.wait_for(worker.wait(), 10)
            except TimeoutError:
                worker.kill()
                await worker.wait()
            await pool.aclose()


@pytest.mark.unit
async def test_disabled_worker_has_no_database_or_queue_work():
    assert await orchestration_session_job({}, str(uuid4()), str(uuid4())) == {"status": "disabled"}
    assert await orchestration_watchdog({}) == {"status": "disabled"}
    disabled = SimpleNamespace(policy=lambda: None, store=object())
    assert await orchestration_watchdog({"orchestration_runtime": disabled}) == {
        "status": "disabled"
    }
