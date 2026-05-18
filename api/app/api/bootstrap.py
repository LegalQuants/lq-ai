"""Bootstrap-state endpoint — M3-0.1 / DE-283.

The fresh-install operator lands on the login screen with a randomly
generated admin password printed to the API container's logs. The web
app surfaces that path more gently than a generic 401 by asking the
backend whether the deployment is still in fresh-install state.

This module exposes:

* ``GET /api/v1/admin/bootstrap-status`` — unauthenticated; returns
  ``{"default_password_active": bool, "logs_hint": str}``.

The endpoint is intentionally unauthenticated — it is consulted by the
login screen *before* the operator has credentials. The signal it
exposes (is an admin user still in ``must_change_password=True`` state?)
is low-sensitivity: the bootstrap password itself is 24 chars of CSPRNG
output, so knowing the deployment is fresh-install does not measurably
help an attacker who lacks the log line.

The detection signal mirrors the one used by ``ensure_first_run_admin``
in :mod:`app.admin_bootstrap`: an admin user with
``must_change_password=True`` indicates the operator has not yet
rotated. Once they hit ``POST /api/v1/auth/change-password`` the flag
flips to False and ``default_password_active`` returns False — the
login UI hides the hint automatically.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])


# The exact command operators run to retrieve the bootstrap password. This
# string is rendered verbatim by the login UI in a copy-friendly chip, so
# the grep target must match the log line emitted by the lifespan handler
# in :mod:`app.main`, which logs the plaintext password once at WARNING.
# The "First-run admin password" prefix is the canonical grep pattern
# already documented in :doc:`/quickstart` (Step 1 / Troubleshooting).
_LOGS_HINT = 'docker compose logs api 2>&1 | grep "First-run admin password"'


class BootstrapStatus(BaseModel):
    """Wire shape for ``GET /api/v1/admin/bootstrap-status``."""

    default_password_active: bool = Field(
        description=(
            "True when at least one non-deleted admin user still has "
            "must_change_password=True — the bootstrap password printed at "
            "first start has not been rotated yet."
        )
    )
    logs_hint: str = Field(
        description=(
            "Shell command an operator can run to retrieve the bootstrap "
            "password from the API container's logs."
        )
    )


@router.get(
    "/bootstrap-status",
    response_model=BootstrapStatus,
    summary="Report whether the first-run bootstrap admin password is still active.",
)
async def get_bootstrap_status(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BootstrapStatus:
    """Unauthenticated probe used by the login UI to render fresh-install hints."""
    result = await db.execute(
        select(User.id)
        .where(
            User.is_admin.is_(True),
            User.must_change_password.is_(True),
            User.deleted_at.is_(None),
        )
        .limit(1)
    )
    default_password_active = result.scalar_one_or_none() is not None
    return BootstrapStatus(
        default_password_active=default_password_active,
        logs_hint=_LOGS_HINT,
    )
