from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.skill_workspace import SkillWorkspace
from app.models.user import User
from tests.autonomous.orchestration.test_workspace_migration import migrate
from tests.skills.test_capabilities import make_user


async def test_migration_preserves_users_and_refuses_retained_work(test_engine, test_db_url):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    owner = make_user()
    async with factory.begin() as db:
        db.add(owner)
    try:
        await migrate(test_db_url, test_engine, "downgrade", "0070")
        await migrate(test_db_url, test_engine, "upgrade", "head")
        async with factory.begin() as db:
            assert await db.get(User, owner.id)
            db.add(
                SkillWorkspace(
                    id=uuid4(),
                    owner_id=owner.id,
                    project_id=None,
                    skill_key="built-in:fixture",
                    skill_name="fixture",
                    format_version=1,
                )
            )
        with pytest.raises(DBAPIError, match="exporting and clearing"):
            await migrate(test_db_url, test_engine, "downgrade", "0070")
        async with factory.begin() as db:
            assert await db.scalar(
                select(SkillWorkspace.id).where(SkillWorkspace.owner_id == owner.id)
            )
    finally:
        await migrate(test_db_url, test_engine, "upgrade", "head")
        async with factory.begin() as db:
            await db.execute(delete(User).where(User.id == owner.id))
