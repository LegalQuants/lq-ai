"""Checkpoint readiness check: python -m app.autonomous.orchestration.setup.

Run before enabling the demo, after migration 0067. This read-only command does
not create tables, users, plans, approvals or provider calls.
"""

import asyncio

from app.autonomous.orchestration.checkpoints import CheckpointRuntime
from app.config import get_settings
from app.errors import ValidationError


async def main() -> None:
    settings = get_settings()
    if settings.orchestration_deployment_children is None:
        raise ValidationError(message="Configure explicit deployment child capacity before setup")
    await CheckpointRuntime(
        settings.database_url, deployment_children=settings.orchestration_deployment_children
    ).setup()


if __name__ == "__main__":
    asyncio.run(main())
