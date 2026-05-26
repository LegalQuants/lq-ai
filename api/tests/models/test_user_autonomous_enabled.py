"""autonomous_enabled column — defaults off, persists true (M4-C2 opt-in)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.integration
async def test_autonomous_enabled_defaults_false(db_session: AsyncSession) -> None:
    user = User(email="optin@example.com", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    assert user.autonomous_enabled is False


@pytest.mark.integration
async def test_autonomous_enabled_persists_true(db_session: AsyncSession) -> None:
    user = User(email="optin2@example.com", hashed_password="x", autonomous_enabled=True)
    db_session.add(user)
    await db_session.flush()
    fetched = (
        await db_session.execute(select(User).where(User.email == "optin2@example.com"))
    ).scalar_one()
    assert fetched.autonomous_enabled is True
