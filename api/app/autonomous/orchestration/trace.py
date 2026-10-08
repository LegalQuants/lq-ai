"""How a run was set up, and what its model wrote back (ADR 0038 D2).

Owner-only. For one session of a run (the orchestrator, or one sub-agent) this
read gives:

* each model call's opening: the system message the session is pinned to, the
  opening user message, and the tool schemas offered;
* each turn's reply: the text the model wrote and the tool calls it asked for,
  with their arguments.

The opening is not stored. It is rebuilt from the run's own records by the same
builder that sent it (:mod:`.assembly`), and the rebuilt request is compared
with the digest recorded when the call went out. The read says which of three
things is true: the two match, they differ, or no digest was recorded.

What this is not. It is what the application sent to the gateway, before any
pseudonymization there. A later turn's full request is not kept; only its reply
is. Document text returned by a read tool, and passages returned by a
knowledge-base search, are not in this view: the step list already says which
document and which characters were read, and which files a search found. Full
payload capture is PRD §5.4 and is not built.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.autonomous.orchestration import assembly
from app.autonomous.orchestration.contracts import PreparedPlan, SkillPin
from app.autonomous.orchestration.inference import conversation_identity
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.policy import load_instructions
from app.autonomous.orchestration.profiles import RunProfile, get_profile
from app.autonomous.orchestration.tools import get_tool
from app.errors import Conflict, Forbidden, LQAIError, NotFound
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationEffect as Effect,
    OrchestrationPlan as PlanRow,
    OrchestrationRoot as Root,
)
from app.schemas.autonomous import Phase
from app.skills.registry import SkillRegistry

NOTE = (
    "The opening messages are rebuilt from this run's records by the code that sent them. "
    "They are what the application sent to the gateway, before any pseudonymization there. "
    "A later turn's full request is not kept; its reply and tool calls are. "
    "Document text returned by a read, and passages returned by a search, are not shown here."
)
_PLAN_KEY, _COMBINE_KEY, _TASK_KEY = "chat:plan:v1", "demo:synthesis:v1", "topic:t1"
_MAX_BYTES = 2 * 1_048_576

Check = Literal["matches", "differs", "not_recorded", "not_rebuilt"]


class InstructionsRead(BaseModel):
    """A session's pinned system message."""

    kind: Literal["skill", "prompt"]
    name: str
    version: str | None = None
    digest: str
    # The pinned text, while the installed file still has the pinned digest.
    text: str | None = None


class CallRead(BaseModel):
    """What one model call was opened with."""

    step: Literal["plan", "task", "combine"]
    effect_key: str
    # Whether the call has been made (an effect exists under this key).
    sent: bool
    system: InstructionsRead
    # None for a skill-pinned session, whose opening this read does not rebuild.
    opening: str | None = None
    # Function schemas offered on this call. Empty for the orchestrator.
    tools: list[dict[str, Any]] = []
    check: Check


class ToolCallRead(BaseModel):
    id: str
    name: str
    # The arguments exactly as the model wrote them: text, never parsed here.
    arguments: str


class TurnRead(BaseModel):
    """One model reply. ``text`` is model-written: display it as text only."""

    effect_key: str
    status: str
    text: str | None = None
    finish_reason: str | None = None
    tool_calls: list[ToolCallRead] = []


class SessionTraceRead(BaseModel):
    root_id: UUID
    session_id: UUID
    role: Literal["orchestrator", "sub-agent"]
    calls: list[CallRead]
    turns: list[TurnRead]
    note: str = NOTE


def _instructions(
    registry: SkillRegistry, pin: SkillPin, version: str | None
) -> tuple[InstructionsRead, str | None]:
    """The pin as shown, and its text when that can still be read unchanged."""
    text: str | None = None
    try:
        current = load_instructions(registry, pin.kind, pin.name)
        if current.pin == pin:
            text = current.instructions
    except LQAIError:
        text = None
    return (
        InstructionsRead(
            kind=pin.kind, name=pin.name, version=version, digest=pin.digest, text=text
        ),
        text,
    )


def _check(effect: Effect | None, system: str | None, opening: str | None, tools: list) -> Check:
    if system is None or opening is None:
        return "not_rebuilt"
    data = (effect.result or {}).get("data") if effect is not None else None
    accounting = data.get("accounting") if isinstance(data, dict) else None
    recorded = accounting.get("messages_digest") if isinstance(accounting, dict) else None
    if not isinstance(recorded, str):
        return "not_recorded"
    try:
        digest, _ = conversation_identity(
            [{"role": "system", "content": system}, {"role": "user", "content": opening}],
            tools or None,
            max_bytes=_MAX_BYTES,
        )
    except LQAIError:
        return "differs"
    return "matches" if digest == recorded else "differs"


def _opening(build: Any) -> str | None:
    try:
        return build()
    except (Forbidden, KeyError, TypeError, ValueError):
        return None


# The steps that are model calls. No other step is read here: a document read's
# result holds document text, which this read never returns.
MODEL_CALL_INTENTS = ("run_skill", "plan")


def _turns(effects: list[Effect]) -> list[TurnRead]:
    turns = []
    for effect in effects:
        if effect.intent not in MODEL_CALL_INTENTS:
            continue
        data = (effect.result or {}).get("data")
        data = data if isinstance(data, dict) else {}
        text, finish = data.get("content"), data.get("finish_reason")
        calls = [
            ToolCallRead(
                id=str(call.get("id") or ""),
                name=str(call.get("name") or ""),
                arguments=str(call.get("arguments") or ""),
            )
            for call in data.get("tool_calls") or ()
            if isinstance(call, dict)
        ]
        turns.append(
            TurnRead(
                effect_key=effect.effect_key,
                status=effect.status,
                text=text if isinstance(text, str) else None,
                finish_reason=finish if isinstance(finish, str) else None,
                tool_calls=calls,
            )
        )
    return turns


async def read_session_trace(
    sessions: async_sessionmaker[AsyncSession],
    registry: SkillRegistry,
    root_id: UUID,
    actor_id: UUID,
    session_id: UUID,
) -> SessionTraceRead:
    async with sessions() as db:
        root = await db.scalar(
            select(Root).where(
                Root.session_id == root_id,
                Root.owner_id == actor_id,
                Root.profile != "demonstration",
            )
        )
        if root is None or not root.planning_snapshot:
            raise NotFound(message="Orchestration root not found")
        plan: PreparedPlan | None = None
        try:
            snapshot = PlanningSnapshot.model_validate_json(json.dumps(root.planning_snapshot))
            if root.current_revision is not None:
                row = await db.get(PlanRow, (root_id, root.current_revision))
                if row is not None:
                    plan = PreparedPlan.model_validate_json(json.dumps(row.snapshot))
        except SchemaError:
            raise Conflict(message="Stored orchestration plan is invalid") from None
        child = (
            next((c for c in plan.children if c.dispatch_id == session_id), None)
            if plan is not None and session_id != root_id
            else None
        )
        if session_id != root_id and child is None:
            raise NotFound(message="Orchestration session not found")
        effects = list(
            await db.scalars(
                select(Effect)
                .where(Effect.session_id == session_id, Effect.intent.in_(MODEL_CALL_INTENTS))
                .order_by(Effect.created_at, Effect.effect_key)
            )
        )
        topics: list[dict[str, Any]] = []
        if plan is not None and session_id == root_id:
            for planned in plan.children:
                session = await db.get(AutonomousSession, planned.dispatch_id)
                topics.append(
                    {
                        "topic": planned.task.topic,
                        "outcome": session.result if session and session.result else {},
                    }
                )
    by_key = {effect.effect_key: effect for effect in effects}
    profile: RunProfile | None = get_profile(root.profile)
    prompted = profile is not None and profile.prompted
    calls: list[CallRead] = []

    def call(
        step: Literal["plan", "task", "combine"],
        key: str,
        pin: SkillPin,
        version: str | None,
        build: Any,
        tools: list[dict[str, Any]],
    ) -> None:
        shown, text = _instructions(registry, pin, version)
        opening = _opening(build) if prompted and pin.kind == "prompt" else None
        calls.append(
            CallRead(
                step=step,
                effect_key=key,
                sent=key in by_key,
                system=shown,
                opening=opening,
                tools=tools,
                check=_check(by_key.get(key), text, opening, tools),
            )
        )

    if session_id == root_id:
        call(
            "plan",
            _PLAN_KEY,
            snapshot.root.skill,
            snapshot.root_skill_version,
            lambda: assembly.planning_message(profile, snapshot),  # type: ignore[arg-type]
            # The plan tool, where this run's plan was handed over by tool call.
            assembly.planning_tools(profile, snapshot) if prompted and profile else [],
        )
        if plan is not None and _COMBINE_KEY in by_key:
            approved = plan
            call(
                "combine",
                _COMBINE_KEY,
                plan.root.skill,
                snapshot.root_skill_version,
                lambda: assembly.combine_message(profile, approved, snapshot, topics),  # type: ignore[arg-type]
                [],
            )
    else:
        assert plan is not None and child is not None
        approved, task = plan, child
        offered = [
            tool.schema()
            for name in task.tools.for_phase(Phase.analysis)
            if (tool := get_tool(name)) is not None
        ]
        call(
            "task",
            # A task with tool turns starts at its first turn; one without makes one call.
            _TASK_KEY if task.turn_limit else "demo:topic:v1",
            task.execution.skill,
            snapshot.child_skill_version,
            lambda: assembly.task_message(profile, approved, snapshot, task),  # type: ignore[arg-type]
            offered,
        )
    return SessionTraceRead(
        root_id=root_id,
        session_id=session_id,
        role="orchestrator" if session_id == root_id else "sub-agent",
        calls=calls,
        turns=_turns(effects),
    )
