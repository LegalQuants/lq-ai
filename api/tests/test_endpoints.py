"""Endpoint scaffold tests — every still-stub /api/v1 route returns the canonical 501 body.

A4 registered every endpoint from `docs/api/backend-openapi.yaml` as a stub
returning HTTP 501 with a structured body that names the implementing M1
task. As tasks land, their endpoints leave the stub set; the remaining
stubs continue to honor the contract:

    {
      "error": {
        "code": "not_implemented",
        "message": "Endpoint scaffold; full implementation lands in Task ...",
        "endpoint": "<METHOD /path>",
        "next_task": "<task ID — task title>"
      }
    }

This test enumerates the registered routes via `app.routes` and exercises
every one EXCEPT those whose implementing task has shipped (tracked in
`IMPLEMENTED_ROUTES` below). Implemented routes have their own dedicated
test files (e.g., `test_auth.py` for B1, `test_change_password.py` for B2).

Most stub routers are mounted under the `ActiveUser` dependency since
Task B2 — they require a valid bearer token whose user has cleared the
must-change-password gate. Tests therefore mint a JWT for an inserted
test user (with `must_change_password=False`) and pass it on every
request.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password

# Substitution table for path parameters when exercising stubs.
# Any UUID-shaped parameter gets a fixed UUID v4; named params get a
# safe identifier.
_DUMMY_UUID = "00000000-0000-4000-8000-000000000000"
_PARAM_VALUES: dict[str, str] = {
    "project_id": _DUMMY_UUID,
    "chat_id": _DUMMY_UUID,
    "message_id": _DUMMY_UUID,
    "file_id": _DUMMY_UUID,
    "kb_id": _DUMMY_UUID,
    "prompt_id": _DUMMY_UUID,
    "skill_id": _DUMMY_UUID,
    "skill_name": "nda-review",
    "team_id": _DUMMY_UUID,
    "user_id": _DUMMY_UUID,
    "interaction_id": _DUMMY_UUID,
    "job_id": _DUMMY_UUID,
    # M3-A2 + M3-A6 — playbook surface
    "playbook_id": _DUMMY_UUID,
    "execution_id": _DUMMY_UUID,
    "generation_id": _DUMMY_UUID,
    # M3-D4 — admin intake-bridges surface
    "workspace_id": _DUMMY_UUID,
    "tenant_id": _DUMMY_UUID,
}


def _materialise(path: str) -> str:
    """Replace `{param}` placeholders with concrete values for the request."""

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in _PARAM_VALUES:
            raise AssertionError(
                f"Path parameter '{name}' has no test value — "
                f"add it to _PARAM_VALUES in test_endpoints.py"
            )
        return _PARAM_VALUES[name]

    return re.sub(r"\{([^}]+)\}", repl, path)


# Routes whose implementing task has landed. These are exercised by their
# own dedicated test files; this scaffold-test must skip them or the
# now-implemented handler returns 200/204/etc. and fails the 501 assertion.
# Format: (METHOD, registered_path).
IMPLEMENTED_ROUTES: set[tuple[str, str]] = {
    # B1 — User model + auth endpoints (backend)
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/users/me"),
    # Donna-3 — caller-scoped profile edit (display_name)
    ("PATCH", "/api/v1/users/me"),
    # B2 — first-run admin + forced password change
    ("POST", "/api/v1/auth/change-password"),
    # D5 — MFA enrollment + verification
    ("POST", "/api/v1/auth/mfa/setup"),
    ("POST", "/api/v1/auth/mfa/enable"),
    ("POST", "/api/v1/auth/mfa/verify"),
    ("POST", "/api/v1/auth/mfa/disable"),
    # D6 — GDPR Article 17 + 20 surface
    ("POST", "/api/v1/users/me/export"),
    ("GET", "/api/v1/users/me/export/{job_id}"),
    ("POST", "/api/v1/users/me/delete"),
    ("POST", "/api/v1/users/me/delete/cancel"),
    # D4-coverage — gateway-facing internal Organization Profile endpoint
    # (X-LQ-AI-Gateway-Key auth, returns Skill-shaped JSON for the
    # gateway's prompt-assembly path).
    ("GET", "/api/v1/internal/organization-profile"),
    # B5 + C3 — backend chats + messages with persistence; SSE streaming.
    ("POST", "/api/v1/chats"),
    ("GET", "/api/v1/chats"),
    ("GET", "/api/v1/chats/{chat_id}"),
    ("PATCH", "/api/v1/chats/{chat_id}"),
    ("DELETE", "/api/v1/chats/{chat_id}"),
    ("GET", "/api/v1/chats/{chat_id}/messages"),
    ("POST", "/api/v1/chats/{chat_id}/messages"),
    ("GET", "/api/v1/chats/{chat_id}/messages/{message_id}/citations"),
    # C1 — Skill Service: filesystem loading
    ("GET", "/api/v1/skills"),
    ("GET", "/api/v1/skills/{skill_name}"),
    # D8 — fork built-in into user scope (replaces the C1-era 501 stub)
    ("POST", "/api/v1/skills/{skill_name}/fork"),
    # D8 — user-skills CRUD per ADR 0012
    ("GET", "/api/v1/user-skills"),
    ("POST", "/api/v1/user-skills"),
    ("GET", "/api/v1/user-skills/{skill_id}"),
    ("PATCH", "/api/v1/user-skills/{skill_id}"),
    ("DELETE", "/api/v1/user-skills/{skill_id}"),
    # D8.1a — teams (admin CRUD + read-only user-facing routes)
    ("GET", "/api/v1/teams"),
    ("GET", "/api/v1/teams/{team_id}"),
    ("GET", "/api/v1/admin/teams"),
    ("POST", "/api/v1/admin/teams"),
    ("GET", "/api/v1/admin/teams/{team_id}"),
    ("PATCH", "/api/v1/admin/teams/{team_id}"),
    ("DELETE", "/api/v1/admin/teams/{team_id}"),
    ("POST", "/api/v1/admin/teams/{team_id}/members"),
    ("PATCH", "/api/v1/admin/teams/{team_id}/members/{user_id}"),
    ("DELETE", "/api/v1/admin/teams/{team_id}/members/{user_id}"),
    # C2 — gateway-facing internal skills endpoint (X-LQ-AI-Gateway-Key auth)
    ("GET", "/api/v1/internal/skills/{skill_name}"),
    # C4 — file upload + storage
    ("POST", "/api/v1/files"),
    ("GET", "/api/v1/files/{file_id}"),
    ("GET", "/api/v1/files/{file_id}/content"),
    ("DELETE", "/api/v1/files/{file_id}"),
    # C7 — Project service
    ("POST", "/api/v1/projects"),
    ("GET", "/api/v1/projects"),
    ("GET", "/api/v1/projects/{project_id}"),
    ("PATCH", "/api/v1/projects/{project_id}"),
    ("DELETE", "/api/v1/projects/{project_id}"),
    ("POST", "/api/v1/projects/{project_id}/files"),
    ("DELETE", "/api/v1/projects/{project_id}/files/{file_id}"),
    ("POST", "/api/v1/projects/{project_id}/skills"),
    ("DELETE", "/api/v1/projects/{project_id}/skills/{skill_name}"),
    # Wave D.1 T3 — matter <-> KB attach/detach
    ("POST", "/api/v1/projects/{project_id}/knowledge-bases"),
    ("DELETE", "/api/v1/projects/{project_id}/knowledge-bases/{kb_id}"),
    # Wave D.1 T4 — admin tier-floor override re-run
    ("POST", "/api/v1/inference/override-tier-floor"),
    # Wave D.1 T5 — chat receipts (replay-at-read event log)
    ("GET", "/api/v1/chats/{chat_id}/receipts"),
    # Wave D.1 T6 — chat receipts JSONL export
    ("GET", "/api/v1/chats/{chat_id}/receipts/export.jsonl"),
    # D0 — Model availability (proxy to gateway /v1/models)
    ("GET", "/api/v1/models"),
    # M3-0.1 / DE-283 — unauthenticated fresh-install state probe
    ("GET", "/api/v1/admin/bootstrap-status"),
    # D0.5 — Admin alias CRUD proxy
    ("GET", "/api/v1/admin/aliases"),
    ("GET", "/api/v1/admin/aliases/{name}"),
    ("POST", "/api/v1/admin/aliases"),
    ("PATCH", "/api/v1/admin/aliases/{name}"),
    ("DELETE", "/api/v1/admin/aliases/{name}"),
    # Donna #7 — runtime provider-key (BYOK) admin proxy
    ("GET", "/api/v1/admin/provider-keys"),
    ("POST", "/api/v1/admin/provider-keys"),
    ("PATCH", "/api/v1/admin/provider-keys/{provider}"),
    ("DELETE", "/api/v1/admin/provider-keys/{provider}"),
    ("GET", "/api/v1/admin/config"),
    # D3 — admin audit-log read endpoint
    ("GET", "/api/v1/admin/audit-log"),
    # M3-0.3 / DE-276 — admin ingest-health aggregate
    ("GET", "/api/v1/admin/ingest-health"),
    # M3-A2 — Playbook executor surface
    ("POST", "/api/v1/playbooks/{playbook_id}/execute"),
    ("GET", "/api/v1/playbook-executions/{execution_id}"),
    # M3-A4 — Playbook list + detail
    ("GET", "/api/v1/playbooks"),
    ("GET", "/api/v1/playbooks/{playbook_id}"),
    # M3-A6 — Playbook CRUD (Phase 2) + Easy Playbook wizard (Phase 5)
    ("POST", "/api/v1/playbooks"),
    ("PATCH", "/api/v1/playbooks/{playbook_id}"),
    ("DELETE", "/api/v1/playbooks/{playbook_id}"),
    ("POST", "/api/v1/playbooks/easy"),
    ("GET", "/api/v1/playbooks/easy/{generation_id}"),
    # M3-C2 — Tabular / Multi-Document Review surface (PRD §3.14).
    # Six method-tuples across five unique paths (cancel is a
    # sub-resource of /executions/{id}).
    ("POST", "/api/v1/tabular/preview-cost"),
    ("POST", "/api/v1/tabular/execute"),
    ("GET", "/api/v1/tabular/executions"),
    ("GET", "/api/v1/tabular/executions/{execution_id}"),
    ("DELETE", "/api/v1/tabular/executions/{execution_id}"),
    ("POST", "/api/v1/tabular/executions/{execution_id}/cancel"),
    # M3-C4a — XLSX/CSV export.
    ("GET", "/api/v1/tabular/executions/{execution_id}/export"),
    # M3-B1 — Word add-in admin manifest generation
    ("GET", "/api/v1/admin/word-addin/manifest"),
    # M3-B8 — Word add-in version handshake (unauthenticated)
    ("GET", "/api/v1/word-addin/version"),
    # M3-D1 — slack-bridge persistence surface (bridge-token bearer auth)
    ("POST", "/api/v1/integrations/slack/workspaces"),
    # M3-D3 — teams-bridge persistence surface (bridge-token bearer auth)
    ("POST", "/api/v1/integrations/teams/tenants"),
    # M3-D4 — admin intake-bridges surface
    ("GET", "/api/v1/admin/intake-bridges"),
    ("DELETE", "/api/v1/admin/intake-bridges/slack/{workspace_id}"),
    ("DELETE", "/api/v1/admin/intake-bridges/teams/{tenant_id}"),
    # D4 — Organization Profile singleton
    ("GET", "/api/v1/organization-profile"),
    ("PUT", "/api/v1/organization-profile"),
    ("GET", "/api/v1/organization-profile/raw"),
    # D7 — Saved Prompts CRUD
    ("GET", "/api/v1/saved-prompts"),
    ("POST", "/api/v1/saved-prompts"),
    ("GET", "/api/v1/saved-prompts/{prompt_id}"),
    ("PATCH", "/api/v1/saved-prompts/{prompt_id}"),
    ("DELETE", "/api/v1/saved-prompts/{prompt_id}"),
    # C6 — Knowledge bases
    ("POST", "/api/v1/knowledge-bases"),
    ("GET", "/api/v1/knowledge-bases"),
    ("GET", "/api/v1/knowledge-bases/{kb_id}"),
    ("PATCH", "/api/v1/knowledge-bases/{kb_id}"),
    ("DELETE", "/api/v1/knowledge-bases/{kb_id}"),
    ("POST", "/api/v1/knowledge-bases/{kb_id}/files"),
    ("DELETE", "/api/v1/knowledge-bases/{kb_id}/files/{file_id}"),
    ("POST", "/api/v1/knowledge-bases/{kb_id}/query"),
    # Wave A — Enhance Prompt (PRD §3.2)
    ("POST", "/api/v1/enhance-prompt"),
    ("PATCH", "/api/v1/enhance-prompt/{interaction_id}"),
    # Wave A — skill inspection (PRD §3.4)
    ("GET", "/api/v1/skills/{skill_name}/contents"),
    ("GET", "/api/v1/skills/{skill_name}/inputs"),
    # Wave A — user preferences (reasoning_visibility per PRD §3.2)
    ("GET", "/api/v1/users/me/preferences"),
    ("PATCH", "/api/v1/users/me/preferences"),
    # Wave B — tier inquiry (PRD §3.13)
    ("GET", "/api/v1/inference/current-tier"),
    ("GET", "/api/v1/inference/tier-config"),
    # Wave B — admin tier-policy (replaces D1 stubs)
    ("GET", "/api/v1/admin/tier-policy"),
    ("PATCH", "/api/v1/admin/tier-policy"),
    # Wave B — admin/usage cost dashboard (PRD §5.5)
    ("GET", "/api/v1/admin/usage"),
    # Wave B — chats search (PRD §1.7 acceptance criterion)
    ("GET", "/api/v1/chats/search"),
    # Wave C — RBAC role updates (PRD §5.2)
    ("PATCH", "/api/v1/admin/users/{user_id}/role"),
    # Wave B v2 — admin user list for DevRoleManagementCard (PRD §5.2)
    ("GET", "/api/v1/admin/users"),
    # Wave D.2 — sandbox ensure, skills autocomplete, user-skill versions, KB files
    ("POST", "/api/v1/projects/sandbox/ensure"),
    ("GET", "/api/v1/skills/autocomplete"),
    ("GET", "/api/v1/user-skills/{skill_id}/versions"),
    ("GET", "/api/v1/knowledge-bases/{kb_id}/files"),
    # M4 — Autonomous Layer (opt-in) + Phase-1 run-now. Fully implemented;
    # each has dedicated coverage under tests/autonomous/, so they must be
    # excluded from this 501-scaffold sweep.
    ("GET", "/api/v1/autonomous/memory"),
    ("DELETE", "/api/v1/autonomous/memory/{memory_id}"),
    ("POST", "/api/v1/autonomous/memory/{memory_id}/dismiss"),
    ("POST", "/api/v1/autonomous/memory/{memory_id}/keep"),
    ("GET", "/api/v1/autonomous/notifications"),
    ("POST", "/api/v1/autonomous/notifications/{notification_id}/read"),
    ("GET", "/api/v1/autonomous/precedents"),
    ("POST", "/api/v1/autonomous/precedents/{precedent_id}/dismiss"),
    ("POST", "/api/v1/autonomous/precedents/{precedent_id}/promote"),
    ("GET", "/api/v1/autonomous/project-context-proposals"),
    ("POST", "/api/v1/autonomous/project-context-proposals/{proposal_id}/accept"),
    ("POST", "/api/v1/autonomous/project-context-proposals/{proposal_id}/reject"),
    ("POST", "/api/v1/autonomous/run-now"),
    ("GET", "/api/v1/autonomous/schedules"),
    ("POST", "/api/v1/autonomous/schedules"),
    ("DELETE", "/api/v1/autonomous/schedules/{schedule_id}"),
    ("PATCH", "/api/v1/autonomous/schedules/{schedule_id}"),
    ("GET", "/api/v1/autonomous/sessions"),
    ("GET", "/api/v1/autonomous/sessions/{session_id}"),
    ("GET", "/api/v1/autonomous/sessions/{session_id}/artifacts"),
    ("GET", "/api/v1/autonomous/sessions/{session_id}/findings"),
    ("POST", "/api/v1/autonomous/sessions/{session_id}/halt"),
    ("GET", "/api/v1/autonomous/watches"),
    ("POST", "/api/v1/autonomous/watches"),
    ("DELETE", "/api/v1/autonomous/watches/{watch_id}"),
    ("PATCH", "/api/v1/autonomous/watches/{watch_id}"),
}


def _api_v1_routes() -> list[tuple[str, str, str]]:
    """Return (method, registered_path, materialised_path) for every still-stub /api/v1 route."""
    rows: list[tuple[str, str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/api/v1"):
            continue
        for method in route.methods or ():
            if method in {"HEAD", "OPTIONS"}:
                continue
            if (method, route.path) in IMPLEMENTED_ROUTES:
                continue
            rows.append((method, route.path, _materialise(route.path)))
    return rows


# Materialised once at import time so pytest reports the route in the parametrize id.
ROUTES = _api_v1_routes()


@pytest.mark.unit
async def test_route_inventory_is_nonempty() -> None:
    """Sanity: /api/v1 surface is registered.

    Originally checked that stub routes existed. After Wave B (PRD §3.13
    tier-policy + §5.5 admin/usage) every documented endpoint has a
    real handler — so we now check the *implemented* set instead. The
    primary purpose of this assertion is to catch the failure mode of
    accidentally dropping all the include_router calls; the floor at
    50 routes is generous against the current 60+ but tight enough to
    fail loudly if a wholesale drop happens.
    """

    from app.main import app as _app

    api_routes = [r for r in _app.routes if getattr(r, "path", "").startswith("/api/v1")]
    assert len(api_routes) >= 50


@pytest_asyncio.fixture
async def stub_test_user(db_session: AsyncSession) -> User:
    """Insert a user with must_change_password=False so stub tests can pass the B2 gate."""
    user = User(
        email=f"stub-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Stub Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def stub_client(
    db_session: AsyncSession, stub_test_user: User
) -> AsyncIterator[tuple[AsyncClient, str]]:
    """Async HTTP client + a bearer token good for the stub tests' authenticated routers."""

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override
    token = create_access_token(
        stub_test_user.id, stub_test_user.email, is_admin=stub_test_user.is_admin
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, token
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("method", "path_template", "path"),
    ROUTES,
    ids=[f"{m} {p}" for (m, p, _) in ROUTES],
)
async def test_endpoint_returns_canonical_501_body(
    stub_client: tuple[AsyncClient, str],
    method: str,
    path_template: str,
    path: str,
) -> None:
    """Every /api/v1 endpoint returns HTTP 501 with the documented body shape.

    Authenticated routers (most of them since B2) are exercised with a
    bearer token whose user has `must_change_password=False`, so the gate
    passes and the request reaches the stub handler. Unauthenticated
    endpoints (auth/login etc.) ignore the header.
    """
    client, token = stub_client
    response = await client.request(method, path, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 501, (
        f"{method} {path} returned {response.status_code}, expected 501"
    )
    body = response.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "not_implemented"
    # Endpoint label is the (template) METHOD + path the stub was registered for.
    # We don't assert exact equality on the verb because the stub helper formats
    # it as a method+path label.
    assert path_template in err["endpoint"]
    assert err["next_task"]
    assert err["message"].startswith("Endpoint scaffold")
