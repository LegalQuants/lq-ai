"""0070 preserves prior runs and refuses to discard retained work."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError
from tests.autonomous.orchestration.test_executor import approve, demonstration as demonstration

from app.autonomous.enums import ToolIntent
from app.errors import ValidationError
from app.models.autonomous import AutonomousSession
from app.models.orchestration import OrchestrationFile
from app.schemas.autonomous import Phase


async def migrate(url, engine, direction, revision):
    def run():
        config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[3] / "alembic")
        )
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        try:
            getattr(command, direction)(config, revision)
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous

    try:
        await asyncio.to_thread(run)
    finally:
        # Clear prepared statements after DDL; this is the isolated test engine.
        await engine.dispose()


async def test_workspace_upgrade_downgrade_preserves_history(
    demonstration, test_engine, test_db_url
):
    env = demonstration
    await migrate(test_db_url, test_engine, "downgrade", "0069")
    try:
        with pytest.raises(ValidationError, match="0070"):
            await env.checkpoints.setup()
    finally:
        await migrate(test_db_url, test_engine, "upgrade", "head")
    async with env.factory() as db:
        assert await db.get(AutonomousSession, env.root_id) is not None
    await approve(env)
    await env.executor.run_one(env.root_id, env.root_id)
    claim = await env.store.claim(env.root_id, env.children[0], worker_id=uuid4(), seconds=60)
    await env.store.phase(claim, Phase.analysis)
    await env.effects.workspace(
        claim,
        effect_key="migration:write",
        phase=Phase.analysis,
        intent=ToolIntent.workspace_write,
        params={"name": "notes.md", "revision": 0, "content": "Retained work"},
    )
    await env.store.release_claim(claim)
    with pytest.raises(DBAPIError, match="draining and exporting"):
        await migrate(test_db_url, test_engine, "downgrade", "0069")
    async with env.factory.begin() as db:
        assert (
            await db.get(OrchestrationFile, (env.children[0], "notes.md"))
        ).content == "Retained work"
        await db.execute(delete(AutonomousSession).where(AutonomousSession.id == env.root_id))
        assert not await db.scalar(select(OrchestrationFile.session_id))
    await migrate(test_db_url, test_engine, "downgrade", "0069")
    await migrate(test_db_url, test_engine, "upgrade", "head")
