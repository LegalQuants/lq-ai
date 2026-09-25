"""One connection owns both checkpoint writes and bounded execution slots.

Session advisory locks survive a governance lease expiring, so a replacement
cannot race the previous graph's saver. The saver uses this exact connection,
never a reconnecting pool: losing its lock also loses its ability to write.
All callers use the same database and explicit deployment limit. No application
row locks are retained during graph/provider I/O.
"""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row

from app.errors import ValidationError


def _key(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], signed=True)


async def _lock(conn: AsyncConnection[DictRow], value: str) -> bool:
    result = await conn.execute("SELECT pg_try_advisory_lock(%s) AS locked", (_key(value),))
    row = await result.fetchone()
    return bool(row and row["locked"])


def _saver(conn: AsyncConnection[DictRow]) -> AsyncPostgresSaver:
    return AsyncPostgresSaver(
        conn,
        serde=JsonPlusSerializer(
            allowed_msgpack_modules=[], allowed_json_modules=[], pickle_fallback=False
        ),
    )


class CheckpointRuntime:
    def __init__(self, database_url: str, *, deployment_children: int) -> None:
        if type(deployment_children) is not int or not 1 <= deployment_children <= 32:
            raise ValidationError(message="Deployment child capacity must be explicitly 1-32")
        self.url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self.deployment_children = deployment_children

    async def setup(self) -> None:
        """Check the migration-owned schema; never run framework DDL at runtime."""
        async with await AsyncConnection.connect(
            self.url, autocommit=True, prepare_threshold=0, row_factory=dict_row
        ) as conn:
            row = await (
                await conn.execute(
                    "SELECT max(v) AS version, to_regclass('public.orchestration_files') AS workspace "
                    "FROM orchestration_checkpoints.checkpoint_migrations"
                )
            ).fetchone()
            if row is None or row["version"] != 9 or row["workspace"] is None:
                raise ValidationError(message="Orchestration migration 0067 is required")

    @asynccontextmanager
    async def acquire(
        self, root_id: UUID, session_id: UUID, *, root_children: int
    ) -> AsyncIterator[AsyncPostgresSaver | None]:
        if type(root_children) is not int or not 1 <= root_children <= 4:
            raise ValidationError(message="Root child capacity must be 1-4")
        async with await AsyncConnection.connect(
            self.url,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
            connect_timeout=5,
            options="-c statement_timeout=5000 -c search_path=orchestration_checkpoints,public",
        ) as conn:
            if not await _lock(conn, f"lq-orchestration:thread:{session_id}"):
                yield None
                return
            if session_id != root_id:
                # Non-blocking acquisition avoids holding a connection in a wait
                # queue. Closing this connection releases every acquired slot.
                for count, prefix in (
                    (root_children, f"lq-orchestration:root:{root_id}"),
                    (self.deployment_children, "lq-orchestration:deployment"),
                ):
                    for slot in range(count):
                        if await _lock(conn, f"{prefix}:{slot}"):
                            break
                    else:
                        yield None
                        return
            yield _saver(conn)
