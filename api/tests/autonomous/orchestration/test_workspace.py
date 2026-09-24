"""Storage acceptance: real process death, private WIP and parent file handoff."""

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from tests.autonomous.orchestration.test_executor import (
    approve,
    demonstration as demonstration,
    finish,
)

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import guarded_tool_call
from app.autonomous.orchestration.views import read_workspace_file
from app.autonomous.orchestration.workspace import parse_request
from app.errors import Conflict, Forbidden, NotFound, SessionHalted, ToolNotGranted
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationEffect as Effect,
    OrchestrationFile,
)
from app.schemas.autonomous import Phase

PEER = r"""
import asyncio, json, sys
from pathlib import Path
from uuid import UUID
from app.config import get_settings
from app.db.session import get_session_factory
from app.autonomous.orchestration.service import DemonstrationService
from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry

async def main():
    data = json.loads(sys.stdin.readline())
    settings = get_settings().model_copy(update={
        "database_url": data["url"], "orchestration_demo_enabled": True,
        "orchestration_deployment_children": 2,
    })
    # The environment also selects the same disposable database for the factory.
    service = DemonstrationService(settings,
        MutableSkillRegistry(load_registry(Path(data["skills"]))), get_session_factory())
    executor = service.executor()
    real = executor.effects.workspace
    async def stop_after_commit(*args, **kwargs):
        result = await real(*args, **kwargs)
        if kwargs["effect_key"] == "demo:notes:create:v1":
            print("notes_committed", flush=True)
            await asyncio.Event().wait()
        return result
    executor.effects.workspace = stop_after_commit
    await executor.run_one(UUID(data["root"]), UUID(data["child"]))

asyncio.run(main())
"""


async def test_wip_survives_process_death_and_parent_synthesizes_shared_file(
    demonstration, test_db_url, tmp_path
):
    env = demonstration
    await approve(env)
    await env.executor.run_one(env.root_id, env.root_id)
    child = env.children[0]
    peer_env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    peer_env.update(DATABASE_URL=test_db_url, JWT_SECRET="disposable-workspace-worker-secret-563")
    with (tmp_path / "workspace-peer.log").open("w+") as log:
        peer = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            PEER,
            cwd=Path(__file__).resolve().parents[3],
            env=peer_env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=log,
        )
        try:
            peer.stdin.write(
                (
                    json.dumps(
                        {
                            "url": test_db_url,
                            "root": str(env.root_id),
                            "child": str(child),
                            "skills": str(Path(__file__).resolve().parents[4] / "skills"),
                        }
                    )
                    + "\n"
                ).encode()
            )
            await peer.stdin.drain()
            signal = await asyncio.wait_for(peer.stdout.readline(), 15)
            if signal != b"notes_committed\n":
                log.seek(0)
                pytest.fail(f"Workspace peer did not reach commit: {log.read()}")
        finally:
            if peer.returncode is None:
                peer.kill()
            await peer.wait()
    assert not env.gateway.requests
    saved = await read_workspace_file(env.factory, env.root_id, env.owner_id, child, "notes.md")
    assert saved.revision == 1 and not saved.shared and "Work in progress" in saved.content
    async with env.factory.begin() as db:
        # Advance the dead worker's lease to the recovery boundary without a
        # minute-long sleep. The process and its saver connection are truly gone.
        now = await db.scalar(select(func.clock_timestamp()))
        await db.execute(
            update(Account)
            .where(Account.session_id == child)
            .values(lease_until=now - timedelta(seconds=1))
        )
    assert await env.store.recover_expired_claims(env.root_id) == 1
    status, result = await finish(env)
    assert status == "completed"
    first = json.loads(env.gateway.requests[0].messages[1].content)
    assert first["inputs"]["working_notes"] == saved.content
    synthesis = json.loads(env.gateway.requests[-1].messages[1].content)
    assert all(
        t["outcome"]["artifact"]["name"] == "findings.json" for t in synthesis["inputs"]["topics"]
    )
    async with env.factory() as db:
        assert (await db.get(OrchestrationFile, (child, "notes.md"))).revision == 2
        receipt = await db.get(Effect, (child, "demo:notes:create:v1"))
        assert receipt.status == "completed" and receipt.result["data"]["revision"] == 1
        for topic in result.topics:
            row = await db.get(OrchestrationFile, (topic.session_id, "findings.json"))
            assert row.shared and row.digest == topic.outcome.artifact.digest
            collected = await db.get(Effect, (env.root_id, f"demo:collect:{topic.session_id}:v1"))
            assert collected.result["data"]["content"] == row.content
    async with env.factory.begin() as db:
        await db.execute(delete(AutonomousSession).where(AutonomousSession.id == env.root_id))
        assert not await db.scalar(select(OrchestrationFile.session_id))


async def workspace_call(env, claim, intent, *, key, name="notes.md", revision=1, **params):
    return await env.effects.workspace(
        claim,
        effect_key=key,
        phase=Phase.analysis,
        intent=intent,
        params={"name": name, "revision": revision, **params},
    )


async def test_workspace_isolation_versions_sharing_and_halt(demonstration):
    env = demonstration
    await approve(env)
    await env.executor.run_one(env.root_id, env.root_id)
    child = await env.store.claim(env.root_id, env.children[0], worker_id=uuid4(), seconds=60)
    sibling = await env.store.claim(env.root_id, env.children[1], worker_id=uuid4(), seconds=60)
    root = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    for claim in (child, sibling):
        await env.store.phase(claim, Phase.analysis)
    created = await workspace_call(
        env, child, ToolIntent.workspace_write, key="create", revision=0, content="private notes"
    )
    replay = await workspace_call(
        env, child, ToolIntent.workspace_write, key="create", revision=0, content="private notes"
    )
    assert created.data == replay.data
    read = {"name": "notes.md", "revision": 1, "session_id": str(child.session_id)}
    assert (
        await workspace_call(env, sibling, ToolIntent.workspace_read, key="sibling", **read)
    ).data == {"error": "file_unavailable"}
    assert (
        await workspace_call(env, root, ToolIntent.workspace_read, key="private", **read)
    ).data == {"error": "file_unavailable"}
    assert (
        await workspace_call(
            env, child, ToolIntent.workspace_read, key="other-run", session_id=str(uuid4())
        )
    ).data == {"error": "file_unavailable"}
    assert (
        await workspace_call(
            env, child, ToolIntent.workspace_write, key="stale", revision=0, content="replace"
        )
    ).data == {"error": "revision_conflict"}
    # Sharing is a drafting grant and never allows a sibling to read the file.
    await env.store.phase(child, Phase.drafting)
    await env.effects.workspace(
        child,
        effect_key="share",
        phase=Phase.drafting,
        intent=ToolIntent.workspace_share,
        params={"name": "notes.md", "revision": 1},
    )
    frozen = await env.effects.workspace(
        child,
        effect_key="frozen",
        phase=Phase.drafting,
        intent=ToolIntent.workspace_write,
        params={"name": "notes.md", "revision": 1, "content": "rewrite"},
    )
    assert frozen.data == {"error": "file_is_shared"}
    assert (await workspace_call(env, root, ToolIntent.workspace_read, key="shared", **read)).data[
        "content"
    ] == "private notes"
    assert (
        await workspace_call(env, sibling, ToolIntent.workspace_read, key="sibling-shared", **read)
    ).data == {"error": "file_unavailable"}
    with pytest.raises(NotFound):
        await read_workspace_file(env.factory, env.root_id, uuid4(), child.session_id, "notes.md")
    await env.store.halt(env.root_id, actor_id=env.owner_id)
    with pytest.raises((Conflict, Forbidden, SessionHalted)):
        await workspace_call(
            env, sibling, ToolIntent.workspace_write, key="halted", revision=0, content="late"
        )
    assert (
        await read_workspace_file(
            env.factory, env.root_id, env.owner_id, child.session_id, "notes.md"
        )
    ).content == "private notes"


async def test_workspace_quotas_unicode_and_unscoped_calls(demonstration):
    env = demonstration
    await approve(env)
    await env.executor.run_one(env.root_id, env.root_id)
    claim = await env.store.claim(env.root_id, env.children[0], worker_id=uuid4(), seconds=60)
    await env.store.phase(claim, Phase.analysis)
    for n in range(8):
        content = "🌱" * 8192 if n < 7 else ""
        result = await workspace_call(
            env,
            claim,
            ToolIntent.workspace_write,
            key=f"create:{n}",
            name=f"file{n}.txt",
            revision=0,
            content=content,
        )
        assert "error" not in result.data
    assert (
        await workspace_call(
            env,
            claim,
            ToolIntent.workspace_write,
            key="ninth",
            name="ninth",
            revision=0,
            content="x",
        )
    ).data == {"error": "storage_limit"}
    assert (
        await workspace_call(
            env,
            claim,
            ToolIntent.workspace_write,
            key="bytes",
            name="file7.txt",
            content="x" * 65536,
        )
    ).data == {"error": "storage_limit"}
    read = await workspace_call(
        env, claim, ToolIntent.workspace_read, key="unicode", name="file0.txt"
    )
    assert read.data["content"] == "🌱" * 8192
    async with env.factory.begin() as db:
        session = await db.get(AutonomousSession, claim.session_id)
        with pytest.raises(ToolNotGranted, match="durable orchestration"):
            await guarded_tool_call(
                session, ToolIntent.workspace_read, {"name": "file0.txt", "revision": 1}, db, None
            )


async def test_workspace_write_and_effect_receipt_roll_back_together(demonstration, monkeypatch):
    env = demonstration
    await approve(env)
    await env.executor.run_one(env.root_id, env.root_id)
    claim = await env.store.claim(env.root_id, env.children[0], worker_id=uuid4(), seconds=60)
    await env.store.phase(claim, Phase.analysis)
    settle = env.store._settle_effect

    async def fail_commit(*args, **kwargs):
        await settle(*args, **kwargs)
        raise RuntimeError("Injected outcome transaction failure")

    monkeypatch.setattr(env.store, "_settle_effect", fail_commit)
    with pytest.raises(RuntimeError, match="Injected"):
        await workspace_call(
            env,
            claim,
            ToolIntent.workspace_write,
            key="rollback",
            revision=0,
            content="Uncommitted notes",
        )
    async with env.factory() as db:
        assert await db.get(OrchestrationFile, (claim.session_id, "notes.md")) is None
        assert (await db.get(Effect, (claim.session_id, "rollback"))).status == "uncertain"


@pytest.mark.parametrize(
    "params",
    [
        {"name": "../secret", "revision": 0, "content": "x"},
        {"name": "/tmp/work", "revision": 0, "content": "x"},
        {"name": "ok", "revision": True, "content": "x"},
        {"name": "ok", "revision": 0, "content": "\x00"},
        {"name": "ok", "revision": 0, "content": "🌱" * 16385},
        {"name": "ok", "revision": 0, "content": "x", "owner_id": str(uuid4())},
    ],
)
def test_workspace_rejects_paths_and_unbounded_authority(params):
    with pytest.raises(ToolNotGranted):
        parse_request(ToolIntent.workspace_write, params)
