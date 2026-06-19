"""Fixtures for the chat package tests.

Provides a ``db`` alias for the root ``db_session`` fixture so the
brief-specified test code can use the shorter name without modification.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def db(db_session: AsyncSession) -> AsyncSession:
    """Alias for the root ``db_session`` fixture."""
    return db_session
