"""Issue #593: exercise ceiling enforcement through the real dispatch callers."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any, Literal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult, _governed_external_dispatch, guarded_tool_call
from app.chat.tool_loop import execute_tool
from app.chat.tool_schemas import ToolSpec
from app.config import get_settings
from app.errors import Conflict, ToolTierRefused
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.chat import Chat
from app.models.mcp import MCPToolCache
from app.models.project import Project
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.research.service import reset_provider_cache
from app.tools.governance import _reset_provider_tier_cache_for_tests

pytestmark = pytest.mark.integration

ExternalToolKind = Literal["mcp", "research", "authority"]


class Gateway:
    """Only dispatch is mocked; resolution and governance run unchanged."""

    def __init__(self) -> None:
        self.call_tool = AsyncMock(
            return_value={
                "payload": {
                    "results": [
                        {
                            "package_id": "USCODE-2025-title17",
                            "title": "Copyright",
                            "collection": "USCODE",
                        }
                    ]
                }
            }
        )

    async def get_admin_config(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "tool_providers": [
                {"name": "acme-mcp", "type": "mcp", "egress_tier": 3},
                {"name": "courtlistener-prod", "type": "courtlistener", "egress_tier": 3},
                {"name": "govinfo-prod", "type": "govinfo", "egress_tier": 3},
            ]
        }

    async def list_tool_providers(self, **kwargs: Any) -> list[dict[str, Any]]:
        return (await self.get_admin_config())["tool_providers"]


@pytest.fixture(autouse=True)
def reset_policy(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("LQ_AI_TOOL_MAX_EGRESS_TIER", raising=False)
    monkeypatch.delenv("TOOL_MAX_EGRESS_TIER", raising=False)
    get_settings.cache_clear()
    reset_provider_cache()
    _reset_provider_tier_cache_for_tests()
    yield
    get_settings.cache_clear()
    reset_provider_cache()
    _reset_provider_tier_cache_for_tests()


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> Gateway:
    gw = Gateway()
    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: gw)
    monkeypatch.setattr("app.research.service.get_gateway_client", lambda: gw)
    monkeypatch.setattr("app.clients.gateway.get_gateway_client", lambda: gw)
    return gw


async def context(
    db: AsyncSession, ceiling: int | None
) -> tuple[User, Project | None, Chat, AutonomousSession]:
    user = User(
        email=f"ceiling-{uuid.uuid4().hex}@example.com", hashed_password="unused", role="member"
    )
    db.add(user)
    await db.flush()
    project = None
    if ceiling is not None:
        project = Project(
            owner_id=user.id,
            name="Ceiling",
            slug=f"ceiling-{uuid.uuid4().hex}",
            max_egress_tier=ceiling,
        )
        db.add(project)
        await db.flush()
    chat = Chat(owner_id=user.id, project_id=project.id if project else None, title="Ceiling test")
    session = AutonomousSession(
        user_id=user.id,
        project_id=project.id if project else None,
        trigger_kind="manual",
        current_phase="analysis",
        status="running",
        halt_state="running",
        cost_total_usd=Decimal("0"),
    )
    db.add_all(
        [
            chat,
            session,
            MCPToolCache(
                provider_name="acme-mcp",
                tool_name="read_doc",
                enabled=True,
                read_only=True,
                destructive=False,
                requires_confirmation=False,
            ),
        ]
    )
    await db.flush()
    return user, project, chat, session


def tool(kind: ExternalToolKind) -> tuple[ToolSpec, ToolIntent, dict[str, Any]]:
    if kind == "mcp":
        provider, op, intent, args = (
            "acme-mcp",
            "read_doc",
            ToolIntent.call_mcp_tool,
            {"id": "document"},
        )
        params = {"provider": provider, "tool": op, "args": args}
    elif kind == "research":
        provider, op, intent, args = (
            "courtlistener-prod",
            "search_case_law",
            ToolIntent.retrieve_caselaw,
            {"q": "copyright"},
        )
        params = {"op": op, "args": args}
    else:
        provider, op, intent, args = (
            "govinfo-prod",
            "search_authority",
            ToolIntent.retrieve_authority,
            {"source": "govinfo", "query": "copyright", "collection": "USCODE"},
        )
        params = {
            "source": "govinfo",
            "op": op,
            "args": {"query": "copyright", "collection": "USCODE"},
        }
    spec = ToolSpec(
        function_name=op,
        kind=kind,
        provider=provider,
        tool=op,
        read_only=True,
        destructive=False,
        requires_confirmation=False,
        parameters={},
        description=op,
    )
    return spec, intent, params


async def dispatch(
    db: AsyncSession,
    user: User,
    chat: Chat,
    session: AutonomousSession,
    gw: Gateway,
    caller: str,
    kind: ExternalToolKind,
) -> Any:
    spec, intent, params = tool(kind)
    if caller == "chat":
        args = params["args"] if kind != "authority" else {"source": "govinfo", **params["args"]}
        return await execute_tool(
            db,
            user=user,
            gateway=gw,
            spec=spec,
            args=args,
            cluster_cache={},
            server_auth_map={},
            assistant_message_id=uuid.uuid4(),
            chat_id=chat.id,
        )
    return await guarded_tool_call(session, intent, params, db, gw)


@pytest.mark.parametrize("caller", ["chat", "autonomous"])
@pytest.mark.parametrize("kind", ["mcp", "research", "authority"])
@pytest.mark.parametrize(
    "operator,project_ceiling,expected,source,allowed",
    [
        (None, None, None, None, True),
        (2, None, 2, "operator", False),
        (3, None, 3, "operator", True),
        (4, 2, 2, "project", False),
        (2, 5, 2, "operator", False),
        (None, 3, 3, "project", True),
    ],
)
async def test_callers_apply_and_forward_ceiling(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    gateway: Gateway,
    caller: str,
    kind: ExternalToolKind,
    operator: int | None,
    project_ceiling: int | None,
    expected: int | None,
    source: str | None,
    allowed: bool,
) -> None:
    if operator is not None:
        monkeypatch.setenv("LQ_AI_TOOL_MAX_EGRESS_TIER", str(operator))
        get_settings.cache_clear()
    user, _, chat, session = await context(db_session, project_ceiling)
    if allowed:
        await dispatch(db_session, user, chat, session, gateway, caller, kind)
        gateway.call_tool.assert_awaited_once()
        assert gateway.call_tool.await_args is not None
        assert gateway.call_tool.await_args.kwargs["max_allowed_tier"] == expected
    else:
        with pytest.raises(ToolTierRefused):
            await dispatch(db_session, user, chat, session, gateway, caller, kind)
        gateway.call_tool.assert_not_awaited()
    row = (await db_session.scalars(select(ToolCallLog))).one()
    assert row.origin == caller
    assert row.max_allowed_tier == expected
    assert row.ceiling_source == source
    assert row.outcome == ("executed" if allowed else "refused_tier")
    assert row.args_digest is not None
    assert not hasattr(row, "args") and not hasattr(row, "result")


@pytest.mark.parametrize("kind", ["mcp", "research", "authority"])
@pytest.mark.parametrize(
    "scope,expected,source,allowed",
    [
        (0, 0, "execution_scope", False),
        (2, 2, "execution_scope", False),
        (3, 3, "execution_scope", True),
        (5, 4, "operator", True),
    ],
)
async def test_governed_scope_composes_with_operator_and_project(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    gateway: Gateway,
    kind: ExternalToolKind,
    scope: int,
    expected: int,
    source: str,
    allowed: bool,
) -> None:
    """Scope admission has its own suite; exercise the governed dispatch seam."""
    monkeypatch.setenv("LQ_AI_TOOL_MAX_EGRESS_TIER", "4")
    get_settings.cache_clear()
    _, _, _, session = await context(db_session, 5)
    _, intent, params = tool(kind)

    async def invoke() -> Any:
        return await _governed_external_dispatch(
            intent,
            params,
            db=db_session,
            session=session,
            gateway=gateway,
            estimate=Decimal("0"),
            span=None,
            maximum_egress_tier=scope,
        )

    if allowed:
        await invoke()
        gateway.call_tool.assert_awaited_once()
        assert gateway.call_tool.await_args is not None
        assert gateway.call_tool.await_args.kwargs["max_allowed_tier"] == expected
    else:
        with pytest.raises(ToolTierRefused):
            await invoke()
        gateway.call_tool.assert_not_awaited()
    row = (await db_session.scalars(select(ToolCallLog))).one()
    assert (row.max_allowed_tier, row.ceiling_source) == (expected, source)


@pytest.mark.parametrize(
    "caller,read", [("chat", "chat"), ("chat", "project"), ("autonomous", "project")]
)
async def test_actual_sql_failure_commits_refusal_from_caller(
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
    caller: str,
    read: str,
) -> None:
    """An actual PostgreSQL error must not poison the outer audit transaction."""
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        user, _, chat, session = await context(db, 2)
        await db.commit()
        owner_id, chat_id = user.id, chat.id
        scalar = db.scalar
        failed = False

        async def fail_policy_once(statement: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal failed
            match = "chats.project_id" if read == "chat" else "projects.max_egress_tier"
            if not failed and match in str(statement):
                failed = True
                await db.execute(text("SELECT 1 / 0 AS sensitive_policy_sentinel"))
            return await scalar(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalar", fail_policy_once)
        try:
            with pytest.raises(ToolTierRefused):
                await dispatch(db, user, chat, session, gateway, caller, "mcp")
            assert failed
            gateway.call_tool.assert_not_awaited()
            # Preserve unrelated state: recovery must not roll back the caller.
            chat.title = "Outer transaction retained"
            await db.commit()
            async with AsyncSession(test_engine) as observer:
                row = (
                    await observer.scalars(
                        select(ToolCallLog).where(ToolCallLog.user_id == owner_id)
                    )
                ).one()
                assert row.outcome == "refused_tier"
                assert row.ceiling_source == "unresolved"
                assert row.max_allowed_tier is None
                observed_chat = await observer.get(Chat, chat_id)
                assert observed_chat is not None
                assert observed_chat.title == "Outer transaction retained"
            assert "sensitive_policy_sentinel" not in caplog.text
        finally:
            await db.rollback()
            # This fixture commits intentionally; clean its own retained rows.
            await db.execute(delete(AuditLog).where(AuditLog.user_id == owner_id))
            await db.execute(delete(AutonomousSession).where(AutonomousSession.user_id == owner_id))
            await db.execute(delete(Chat).where(Chat.owner_id == owner_id))
            await db.execute(delete(Project).where(Project.owner_id == owner_id))
            await db.execute(delete(User).where(User.id == owner_id))
            await db.execute(delete(MCPToolCache).where(MCPToolCache.provider_name == "acme-mcp"))
            await db.commit()


async def test_unreadable_proposal_cannot_be_saved_as_unconstrained(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.chats import _resolve_proposal_ceiling

    _, _, chat, _ = await context(db_session, 2)
    monkeypatch.setattr(
        "app.api.chats.resolve_tool_egress_ceiling", AsyncMock(return_value=(None, "unresolved"))
    )
    with pytest.raises(Conflict, match="could not resolve egress policy"):
        await _resolve_proposal_ceiling(db_session, chat_id=chat.id)


@pytest.mark.parametrize("ceiling", [None, 3])
async def test_project_export_includes_egress_policy(
    db_session: AsyncSession, ceiling: int | None
) -> None:
    from app.workers.user_export import _serialize_project

    user, project, _, _ = await context(db_session, ceiling)
    if project is None:
        project = Project(owner_id=user.id, name="Unconstrained", slug=f"unset-{uuid.uuid4().hex}")
        db_session.add(project)
        await db_session.flush()
    exported = _serialize_project(project)
    assert "max_egress_tier" in exported
    assert exported["max_egress_tier"] == ceiling


@pytest.mark.parametrize(
    "operator,project_ceiling,scope_ceiling,expected,source",
    [
        (5, 5, 4, 4, "execution_scope"),
        (4, 3, 5, 3, "project"),
        (2, 5, 4, 2, "operator"),
        (5, 2, 4, 2, "project"),
        (5, 5, 0, 0, "execution_scope"),
    ],
)
async def test_orchestrated_guard_preserves_composed_ceiling(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    gateway: Gateway,
    operator: int,
    project_ceiling: int,
    scope_ceiling: int,
    expected: int,
    source: str,
) -> None:
    from app.autonomous.orchestration.contracts import (
        ExecutionScope,
        PhaseGrants,
        ResourceScope,
        SkillPin,
    )
    from app.autonomous.orchestration.policy import SourcePolicy
    from app.autonomous.orchestration.sources import SourceBinding
    from app.errors import ToolNotGranted

    monkeypatch.setenv("LQ_AI_TOOL_MAX_EGRESS_TIER", str(operator))
    get_settings.cache_clear()
    _, _, _, session = await context(db_session, project_ceiling)
    scope = ExecutionScope(
        resources=ResourceScope(document_ids=(), source_names=("govinfo-prod",)),
        grants=PhaseGrants(
            intake=(),
            analysis=(ToolIntent.retrieve_authority,),
            drafting=(),
            ethics_review=(),
            delivery=(),
        ),
        skill=SkillPin(name="fixture-skill", digest="a" * 64),
        minimum_inference_tier=1,
        maximum_egress_tier=scope_ceiling,
        privileged=False,
        anonymize=False,
    )
    binding = SourceBinding(
        policy_version="fixture",
        source=SourcePolicy(
            name="govinfo-prod",
            source_type="govinfo",
            egress_tier=3,
            operations=("search_authority",),
        ),
        operation="search_authority",
        cost_usd=Decimal("0"),
        config_digest="b" * 64,
        gateway_revision="c" * 64,
        anonymization_expected=False,
    )
    gateway.call_tool.return_value.update(
        provider="govinfo-prod", tool="search_authority", tier=3, anonymization_applied=False
    )

    class AdmittedEffect:
        # Durable store admission/settlement has an independent integration
        # suite. Leave the real scope guard and dispatch policy in this test.
        async def admit(self, intent: ToolIntent, params: dict[str, Any]) -> tuple[Decimal, None]:
            return Decimal("0"), None

        async def settle(self, db: AsyncSession, result: ToolResult) -> None:
            pass

    _, intent, params = tool("authority")

    async def invoke() -> ToolResult:
        return await guarded_tool_call(
            session,
            intent,
            params,
            db_session,
            gateway,
            execution_scope=scope,
            source_binding=binding,
            effect=AdmittedEffect(),
        )

    if scope_ceiling == 0:
        # Existing R6 refuses an out-of-scope source before invocation policy.
        with pytest.raises(ToolNotGranted):
            await invoke()
        gateway.call_tool.assert_not_awaited()
        assert (await db_session.scalars(select(AuditLog))).all()
        return
    if expected < 3:
        with pytest.raises(ToolTierRefused):
            await invoke()
        gateway.call_tool.assert_not_awaited()
    else:
        await invoke()
        gateway.call_tool.assert_awaited_once()
        assert gateway.call_tool.await_args is not None
        assert gateway.call_tool.await_args.kwargs["max_allowed_tier"] == expected
        assert (
            gateway.call_tool.await_args.kwargs["configuration_revision"]
            == binding.gateway_revision
        )
    row = (await db_session.scalars(select(ToolCallLog))).one()
    assert (row.max_allowed_tier, row.ceiling_source) == (expected, source)
