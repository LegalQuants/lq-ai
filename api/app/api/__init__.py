"""HTTP API routers for the backend.

Each module under `app.api` corresponds to one tag-group in
`docs/api/backend-openapi.yaml`. In Task A4 (this scaffold), every endpoint
is registered but returns HTTP 501 with a structured "not implemented" body
that names the M1 task implementing it. Subsequent tasks (B1, B5, C3, C4,
C7, etc.) replace each 501 with a real handler.

Auth gating (Task B2): the `auth` and `users` routers are mounted without
a router-level auth dependency — they need different per-endpoint policies
(login is unauthenticated, /users/me must be reachable while
must_change_password is true so the client can read the flag, etc.). Every
other router is mounted under the `ActiveUser` dependency, which enforces:

1. A valid bearer token (401 without it).
2. `must_change_password = false` (403 with `password_change_required`).

This means future C-/D-phase implementations of these endpoints inherit
the auth+gate without any change at the handler level — they just need a
real handler body to replace the 501.
"""

from fastapi import APIRouter, Depends

from app.api import (
    admin,
    auth,
    bootstrap,
    chat_receipts,
    chats,
    enhance_prompt,
    files,
    inference,
    inference_override,
    internal,
    knowledge_bases,
    models,
    organization_profile,
    playbooks as playbooks_api,
    projects,
    saved_prompts,
    skills,
    teams,
    user_skills,
    users,
    word_addin,
)
from app.api.dependencies import get_active_user

api_router = APIRouter(prefix="/api/v1")

# Routers with mixed per-endpoint policies — see each module for details.
api_router.include_router(auth.router)
api_router.include_router(users.router)

# Unauthenticated probe used by the login UI to surface fresh-install hints
# (M3-0.1 / DE-283). Mounted without `_active` because the login screen
# consults it before the operator has credentials.
api_router.include_router(bootstrap.router)

# Service-to-service router (gateway → backend). Authenticated by the
# shared X-LQ-AI-Gateway-Key header per ADR 0006, NOT by the user-token
# gate. Mounted without `_active` deliberately: the gateway has no user.
api_router.include_router(internal.router)

# M3-B8 — Word add-in version handshake. Unauthenticated: the task pane
# calls this on mount BEFORE the user has signed in, so an out-of-date
# add-in can surface an "Update needed" overlay before the OAuth dialog
# even tries to load.
api_router.include_router(word_addin.public_router)

# Routers that uniformly require an authenticated, must_change_password=false
# user. Applying this at the router level means every current stub and every
# future real handler in these modules inherits the gate automatically.
_active = [Depends(get_active_user)]
api_router.include_router(projects.router, dependencies=_active)
api_router.include_router(chats.router, dependencies=_active)
api_router.include_router(chat_receipts.router, dependencies=_active)
api_router.include_router(skills.router, dependencies=_active)
api_router.include_router(models.router, dependencies=_active)
api_router.include_router(files.router, dependencies=_active)
api_router.include_router(knowledge_bases.router, dependencies=_active)
api_router.include_router(organization_profile.router, dependencies=_active)
api_router.include_router(saved_prompts.router, dependencies=_active)
api_router.include_router(user_skills.router, dependencies=_active)
api_router.include_router(teams.user_router, dependencies=_active)
api_router.include_router(teams.admin_router, dependencies=_active)
api_router.include_router(enhance_prompt.router, dependencies=_active)
api_router.include_router(inference.router, dependencies=_active)
api_router.include_router(inference_override.router, dependencies=_active)
api_router.include_router(admin.router, dependencies=_active)
# M3-A2: Playbook executor — two endpoints under different prefixes
# (``/playbooks/{id}/execute`` and ``/playbook-executions/{id}``) so
# they live alongside the M3-A4 list/CRUD endpoints in the same module.
api_router.include_router(playbooks_api.router, dependencies=_active)
# M3-B1: Word add-in admin surface (manifest generation). Mounted with
# the AdminUser dep at handler level. M3-B8's version-handshake route
# lives in the same module but on a separate ``public_router`` mounted
# above without the ``_active`` gate.
api_router.include_router(word_addin.admin_router, dependencies=_active)

__all__ = ["api_router"]
