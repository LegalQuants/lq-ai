"""OpenAPI surface tests.

The OpenAPI sketch at `docs/api/backend-openapi.yaml` is the contract.
Task A4 registers every path from the sketch as a 501-returning stub so
the OpenAPI document FastAPI generates matches the contract from day
one. This test pins that match.

When the sketch is updated, this test should be updated in the same PR.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

EXPECTED_PATHS: frozenset[str] = frozenset(
    {
        # auth
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/refresh",
        "/api/v1/auth/mfa/setup",
        "/api/v1/auth/mfa/verify",
        # D5 — MFA enrollment + verification
        "/api/v1/auth/mfa/enable",
        "/api/v1/auth/mfa/disable",
        "/api/v1/auth/change-password",  # B2
        # users
        "/api/v1/users/me",
        "/api/v1/users/me/export",
        # D6 — status-poll for queued export jobs (extends the sketch).
        "/api/v1/users/me/export/{job_id}",
        "/api/v1/users/me/delete",
        # D6 — cancel a pending account deletion (extends the sketch).
        "/api/v1/users/me/delete/cancel",
        # projects
        "/api/v1/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/skills",
        # C7 — detach skill by name (extends the sketch).
        "/api/v1/projects/{project_id}/skills/{skill_name}",
        "/api/v1/projects/{project_id}/files",
        # C7 — detach file by id (extends the sketch).
        "/api/v1/projects/{project_id}/files/{file_id}",
        # Wave D.1 T3 — matter <-> KB attach/detach (extends the sketch).
        "/api/v1/projects/{project_id}/knowledge-bases",
        "/api/v1/projects/{project_id}/knowledge-bases/{kb_id}",
        # chats + messages
        "/api/v1/chats",
        "/api/v1/chats/{chat_id}",
        "/api/v1/chats/{chat_id}/messages",
        "/api/v1/chats/{chat_id}/messages/{message_id}/citations",
        # skills
        "/api/v1/skills",
        "/api/v1/skills/{skill_name}",
        "/api/v1/skills/{skill_name}/fork",
        # internal (gateway → backend, ADR 0006 / C2)
        "/api/v1/internal/skills/{skill_name}",
        # D4-coverage — gateway-facing Organization Profile fetch
        "/api/v1/internal/organization-profile",
        # files
        "/api/v1/files",
        "/api/v1/files/{file_id}",
        "/api/v1/files/{file_id}/content",
        # knowledge bases (C6)
        "/api/v1/knowledge-bases",
        "/api/v1/knowledge-bases/{kb_id}",
        "/api/v1/knowledge-bases/{kb_id}/files",
        "/api/v1/knowledge-bases/{kb_id}/files/{file_id}",
        "/api/v1/knowledge-bases/{kb_id}/query",
        # organization profile
        "/api/v1/organization-profile",
        # D4 — convenience text/markdown endpoint (extends the sketch).
        "/api/v1/organization-profile/raw",
        # saved prompts
        "/api/v1/saved-prompts",
        "/api/v1/saved-prompts/{prompt_id}",
        # user skills (D8 — DB-backed user-scope skills per ADR 0012)
        "/api/v1/user-skills",
        "/api/v1/user-skills/{skill_id}",
        # Wave D.2 — version audit feed + slash_alias autocomplete
        "/api/v1/user-skills/{skill_id}/versions",
        "/api/v1/skills/autocomplete",
        # Wave D.2 Task 2.2 — sandbox matter find-or-create
        "/api/v1/projects/sandbox/ensure",
        # teams (D8.1a — admin CRUD + user-facing read)
        "/api/v1/teams",
        "/api/v1/teams/{team_id}",
        "/api/v1/admin/teams",
        "/api/v1/admin/teams/{team_id}",
        "/api/v1/admin/teams/{team_id}/members",
        "/api/v1/admin/teams/{team_id}/members/{user_id}",
        # Wave A — skill inspection (PRD §3.4) + Enhance Prompt (PRD §3.2)
        "/api/v1/skills/{skill_name}/contents",
        "/api/v1/skills/{skill_name}/inputs",
        "/api/v1/enhance-prompt",
        "/api/v1/enhance-prompt/{interaction_id}",
        # Wave A — user preferences (reasoning_visibility per PRD §3.2)
        "/api/v1/users/me/preferences",
        # Wave B — tier inquiry (PRD §3.13) + cost dashboard (PRD §5.5) + chat search (PRD §1.7)
        "/api/v1/inference/current-tier",
        "/api/v1/inference/tier-config",
        "/api/v1/admin/usage",
        "/api/v1/chats/search",
        # Wave C — RBAC role updates (PRD §5.2)
        "/api/v1/admin/users/{user_id}/role",
        # Wave B v2 — admin user list for DevRoleManagementCard
        "/api/v1/admin/users",
        # admin
        "/api/v1/admin/audit-log",
        "/api/v1/admin/tier-policy",
        # M3-0.1 / DE-283 — unauthenticated fresh-install state probe
        "/api/v1/admin/bootstrap-status",
        # M3-0.3 / DE-276 — admin ingest-health aggregate
        "/api/v1/admin/ingest-health",
        # M3-A2 — Playbook executor surface
        "/api/v1/playbooks/{playbook_id}/execute",
        "/api/v1/playbook-executions/{execution_id}",
        # M3-A4 — Playbook list + detail (GET-only; CRUD deferred to M3-A6)
        "/api/v1/playbooks",
        "/api/v1/playbooks/{playbook_id}",
        # D0.5 — model alias admin
        "/api/v1/admin/config",
        "/api/v1/admin/aliases",
        "/api/v1/admin/aliases/{name}",
        # D0 — model availability proxy
        "/api/v1/models",
        # Wave D.1 T4 — admin tier-floor override re-run
        "/api/v1/inference/override-tier-floor",
        # Wave D.1 T5 — chat receipts (replay-at-read event log)
        "/api/v1/chats/{chat_id}/receipts",
        # Wave D.1 T6 — chat receipts JSONL export
        "/api/v1/chats/{chat_id}/receipts/export.jsonl",
    }
)


@pytest.mark.unit
async def test_openapi_paths_match_sketch() -> None:
    """All paths from `backend-openapi.yaml` are registered.

    Counts: 30 from A4 + 1 from B2 (change-password) + 2 from C7
    (project file/skill detach by id) = 33 total.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    actual = {p for p in spec["paths"] if p.startswith("/api/v1")}
    assert actual == EXPECTED_PATHS, (
        f"OpenAPI surface drift. Missing: {EXPECTED_PATHS - actual}, "
        f"Extra: {actual - EXPECTED_PATHS}"
    )
    # 67 distinct /api/v1 paths: D0's /api/v1/models + D0.5's three admin
    # alias endpoints + D5's two new MFA endpoints + D6's two new GDPR
    # endpoints (status-poll for /users/me/export/{job_id} and
    # /users/me/delete/cancel) + D4's /organization-profile/raw
    # convenience endpoint + D4-coverage's
    # /internal/organization-profile + D8's two /api/v1/user-skills
    # paths + D8.1a's six teams paths + Wave A's five paths +
    # Wave B's four paths + Wave C's /admin/users/{user_id}/role +
    # Wave B v2's /admin/users + Wave D.1's two matter <-> KB attach/detach paths
    # + Wave D.1 T4's /inference/override-tier-floor
    # + Wave D.2's three paths: /user-skills/{id}/versions,
    # /skills/autocomplete, /projects/sandbox/ensure.
    # + M3-0.1's /admin/bootstrap-status.
    # + M3-0.3's /admin/ingest-health.
    # + M3-A2's two playbook-executor endpoints.
    # + M3-A4's two playbook list/detail endpoints.
    assert len(actual) == 79


@pytest.mark.unit
async def test_openapi_includes_health_and_ready() -> None:
    """Liveness and readiness are also documented in the spec."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    spec = response.json()
    assert "/health" in spec["paths"]
    assert "/ready" in spec["paths"]


@pytest.mark.unit
async def test_openapi_version_is_3_1() -> None:
    """We declare OpenAPI 3.1 — FastAPI emits this by default on recent versions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")
    spec = response.json()
    # FastAPI >= 0.99 emits OpenAPI 3.1.x by default.
    assert spec["openapi"].startswith("3.1.")
