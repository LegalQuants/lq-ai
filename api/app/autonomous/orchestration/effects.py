"""Guarded execution with durable, fenced admission and atomic outcomes.

No graph/queue types or public routes. Inference and authority sources have exact
route/price bindings; fixtures may supply an explicit current quote (including
explicit free pricing). Shared policy/configuration distribution remains an
enablement gate; the legacy cold-start estimator is never a fallback here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from pydantic import field_serializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult, guarded_tool_call
from app.autonomous.orchestration import assembly
from app.autonomous.orchestration.contracts import (
    ExecutionScope,
    Money,
    PreparedPlan,
    RunCorrelation,
    ShortText,
    Snapshot,
)
from app.autonomous.orchestration.inference import (
    InferenceBinding,
    InferenceRoutes,
    identity_limit,
)
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.policy import load_instructions
from app.autonomous.orchestration.profiles import get_profile
from app.autonomous.orchestration.sources import AuthoritySources, SourceBinding
from app.autonomous.orchestration.store import (
    EffectReceipt,
    ExecutionView,
    OrchestrationStore,
    WorkerClaim,
)
from app.autonomous.orchestration.tools import StepNote
from app.autonomous.orchestration.workspace import WORKSPACE_INTENTS, WorkspaceAccess, parse_request
from app.errors import Conflict, Forbidden, ValidationError
from app.models.autonomous import AutonomousSession
from app.models.chat import Message
from app.observability_helpers import get_tracer, quiet_span, record_attributes
from app.schemas.autonomous import Phase
from app.skills.registry import MutableSkillRegistry
from app.skills.tools import SKILL_TOOL_INTENTS, SkillTools, parse_skill_tool

log = logging.getLogger(__name__)
_tracer = get_tracer(__name__)

_EFFECT_INPUT_BYTES = 131_072


class CostQuote(Snapshot):
    amount_usd: Money
    pricing_version: ShortText

    @field_serializer("amount_usd")
    def serialize_amount(self, value: Decimal) -> str:
        return format(value, ".4f")


class QuoteProvider(Protocol):
    def __call__(
        self, intent: ToolIntent, params: dict[str, Any], scope: ExecutionScope
    ) -> CostQuote | None:
        """Local current pricing only; None for unavailable/unknown paid pricing."""
        ...


def _bounded_json(value: dict[str, Any], limit: int = _EFFECT_INPUT_BYTES) -> str:
    try:
        # Characters are sent as themselves, not as \uXXXX escapes: a model told
        # to keep a quotation exactly copies an escape into its answer, and a
        # section mark or a curly quote then no longer matches the document.
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
        )
        if len(encoded.encode("utf-8")) > limit:
            raise ValueError("oversized input")
        return encoded
    except (TypeError, ValueError, RecursionError):
        raise ValidationError(message="Effect input must be bounded JSON") from None


class _Invocation:
    """One use only, held by one guarded call; never shared between children."""

    def __init__(
        self,
        store: OrchestrationStore,
        claim: WorkerClaim,
        view: ExecutionView,
        effect_key: str,
        phase: Phase,
        quote: QuoteProvider | None,
        source_binding: SourceBinding | None = None,
        inference_binding: InferenceBinding | None = None,
        tool_quote: CostQuote | None = None,
        step: StepNote | None = None,
    ) -> None:
        self.store, self.claim, self.view = store, claim, view
        self.effect_key, self.phase, self.quote = effect_key, phase, quote
        self.admitted = False
        self.source_binding = source_binding
        self.inference_binding = inference_binding
        self.tool_quote, self.step = tool_quote, step
        self.receipt: EffectReceipt | None = None

    async def admit(
        self, intent: ToolIntent, params: dict[str, Any]
    ) -> tuple[Decimal, ToolResult | None]:
        # Snapshot the narrowed call before quoting; caller-owned dictionaries
        # and model text cannot change the identity while admission awaits I/O.
        request = _bounded_json(
            params,
            identity_limit(self.inference_binding.policy) + 4096
            if self.inference_binding is not None
            else _EFFECT_INPUT_BYTES,
        )
        quote: CostQuote | None
        if self.inference_binding is not None:
            if self.inference_binding.policy_version != self.view.plan.policy_version:
                raise Forbidden(message="Inference binding differs from approved policy")
            quote = CostQuote(
                amount_usd=self.inference_binding.reservation_usd,
                pricing_version=self.inference_binding.config_digest,
            )
        elif self.source_binding is not None:
            if self.source_binding.policy_version != self.view.plan.policy_version:
                raise Forbidden(message="Source binding differs from approved policy")
            quote = CostQuote(
                amount_usd=self.source_binding.cost_usd,
                pricing_version=self.source_binding.config_digest,
            )
        elif self.tool_quote is not None:
            # A registry tool carries its own known quote (ADR 0038 D3).
            quote = self.tool_quote
        elif intent in WORKSPACE_INTENTS or intent in SKILL_TOOL_INTENTS:
            quote = CostQuote(amount_usd=Decimal("0"), pricing_version="local-workspace-v1")
        elif self.quote is not None:
            quote = self.quote(intent, json.loads(request), self.view.scope)
        elif intent == ToolIntent.retrieve_chunks:
            quote = CostQuote(amount_usd=Decimal("0"), pricing_version="local-document-read-v1")
        else:
            quote = None
        if quote is None:
            raise Forbidden(message="Known current pricing is required for orchestration")
        quote = CostQuote.model_validate(quote)
        identity = _bounded_json(
            {
                "plan_hash": self.view.plan.approval_hash(),
                "session_id": str(self.claim.session_id),
                "phase": self.phase.value,
                "intent": intent.value,
                "request": json.loads(request),
                "quote": quote.model_dump(mode="json"),
                "source_binding": (
                    self.source_binding.model_dump(mode="json") if self.source_binding else None
                ),
                "inference_binding": (
                    self.inference_binding.model_dump(mode="json")
                    if self.inference_binding
                    else None
                ),
            },
            len(request.encode("utf-8")) + 16_384,
        )
        receipt = await self.store.begin_effect(
            self.claim,
            effect_key=self.effect_key,
            request_hash=hashlib.sha256(identity.encode()).hexdigest(),
            reservation_usd=quote.amount_usd,
            phase=self.phase,
            intent=intent,
        )
        self.receipt = receipt
        if receipt.status == "completed":
            if receipt.result is None or receipt.charged_usd is None:
                raise Conflict(message="Completed effect is missing its outcome")
            return quote.amount_usd, ToolResult(
                cost_usd=receipt.charged_usd,
                data=receipt.result["data"],
                outcome=receipt.result["outcome"],
            )
        if receipt.status != "admitted":
            raise Conflict(message="Uncertain effect requires reconciliation")
        self.admitted = True
        return quote.amount_usd, None

    async def settle(self, db: AsyncSession, result: ToolResult) -> None:
        # The legacy inference handler normalizes transport/response failures.
        # An attempted request without a trustworthy response is not a completed
        # effect. Leave the reservation for reconciliation, never auto-replay it.
        if result.outcome == "gateway_error":
            raise Conflict(message="Provider outcome is uncertain; reconciliation is required")
        if self.inference_binding and self.view.planning:
            snapshot = self.view.planning
            result.data["skill"] = {
                "name": self.view.scope.skill.name,
                "digest": self.view.scope.skill.digest,
                "version": snapshot.root_skill_version
                if self.claim.root_id == self.claim.session_id
                else snapshot.child_skill_version,
            }
            if self.view.scope.skill.kind != "skill":
                # An engine prompt file, not an installed skill (ADR 0038 D3).
                result.data["skill"]["kind"] = self.view.scope.skill.kind
        if self.tool_quote is not None and result.cost_usd == 0 and result.outcome == "success":
            # A fixed-price registry tool is charged its quote when it ran.
            result.cost_usd = self.tool_quote.amount_usd
        payload: dict[str, Any] = {"data": result.data, "outcome": result.outcome}
        if self.step is not None:
            payload["step"] = self.step.record(result.data)
        await self.store._settle_effect(
            db,
            self.claim,
            effect_key=self.effect_key,
            charged_usd=result.cost_usd,
            result=payload,
        )


class GuardedEffects:
    """Internal adapter for pinned inference, selected reads and bound sources.

    The store resolves the scope from durable approval on every call. Consumers
    cannot pass a scope, system prompt, provider handler or another child's task.
    A failed outcome transaction rolls back all local writes and marks the
    admitted effect uncertain in a separate recovery transaction.
    """

    def __init__(
        self,
        store: OrchestrationStore,
        *,
        skills: MutableSkillRegistry,
        gateway: Any,
        quote: QuoteProvider | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        sources: AuthoritySources | None = None,
        inference: InferenceRoutes | None = None,
    ) -> None:
        if inference is None and (
            not isinstance(model, str) or not model.strip() or len(model) > 256
        ):
            raise ValidationError(message="Inference model must be explicitly configured")
        if inference is None and (type(max_tokens) is not int or not 1 <= max_tokens <= 8192):
            raise ValidationError(message="Inference output limit must be between 1 and 8192")
        if sources is not None and sources.gateway is not gateway:
            raise ValidationError(
                message="Source configuration and dispatch must use the same gateway"
            )
        self.store, self.skills, self.gateway = store, skills, gateway
        self.quote, self.model, self.max_tokens = quote, model, max_tokens
        self.sources = sources
        if inference is not None and inference.gateway is not gateway:
            raise ValidationError(
                message="Inference configuration and dispatch must use the same gateway"
            )
        self.inference = inference

    async def infer(
        self,
        claim: WorkerClaim,
        *,
        effect_key: str,
        phase: Phase,
        inputs: dict[str, Any],
        intent: ToolIntent = ToolIntent.run_skill,
        turns: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        step: StepNote | None = None,
    ) -> ToolResult:
        """One inference under the session's pinned instructions.

        ``turns`` are an approved child's own earlier tool turns and ``tools``
        the function schemas its plan grants (ADR 0038 D4). Both are built by
        the engine from durable receipts and the registry; a caller cannot
        supply a system prompt, and the route binding covers every byte sent.

        A planning call takes no turns. It may be offered one tool, the plan
        tool of a profile that hands its plan over that way, and the schema
        passed here must be exactly the one the run's intake produces.

        The system message is the pinned skill or prompt file, whole. For a
        skill the user message is the task and ``inputs`` as JSON, as in 0.8.0.
        For a prompt file it is assembled from the run's plan and intake
        (:mod:`..assembly`); ``inputs`` then names the step only, plus the
        collected results when combining.
        """
        if intent not in {ToolIntent.run_skill, ToolIntent.plan}:
            raise Forbidden(message="Inference intent is not supported by this adapter")
        if (turns or tools) and self.inference is None:
            raise Forbidden(message="Tool turns require a bound skill inference")
        if turns and intent != ToolIntent.run_skill:
            raise Forbidden(message="Only an approved task has tool turns")
        # Copy before the first await; only this bounded JSON becomes user data.
        inputs_json = _bounded_json(inputs)
        turns_json = json.dumps(turns or [], allow_nan=False)
        tools_json = json.dumps(tools or [], allow_nan=False)
        view = await self.store.execution_view(claim)
        # The pin's kind decides where its name is read from: a prompt name is
        # never looked up among installed skills, nor a skill among prompts.
        artifact = load_instructions(
            self.skills.current(), view.scope.skill.kind, view.scope.skill.name
        )
        if artifact.pin != view.scope.skill:
            raise Forbidden(message="Pinned skill has changed")
        offered = json.loads(tools_json)
        plan_tools: list[dict[str, Any]] = []
        if view.scope.skill.kind == "prompt":
            profile = get_profile(view.plan.profile or "")
            if profile is None or not profile.prompted:
                raise Forbidden(message="Pinned prompt does not belong to the run's profile")
            if isinstance(view.plan, PlanningSnapshot):
                plan_tools = assembly.planning_tools(profile, view.plan)
        if intent == ToolIntent.plan and offered != plan_tools:
            raise Forbidden(message="A planning call is offered its plan tool and nothing else")
        if view.scope.skill.kind == "prompt":
            assert profile is not None
            opening = assembly.opening(
                profile,
                plan=view.plan,
                snapshot=view.planning,
                session_id=claim.session_id,
                inputs=json.loads(inputs_json),
            )
        else:
            task: Any = (
                view.plan.goal
                if claim.session_id == claim.root_id
                else next(
                    c.task.model_dump(mode="json")
                    for c in view.plan.children
                    if c.dispatch_id == claim.session_id
                )
            )
            opening = _bounded_json({"task": task, "inputs": json.loads(inputs_json)})
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": artifact.instructions},
                {"role": "user", "content": opening},
                *json.loads(turns_json),
            ],
        }
        if offered:
            params["tools"] = offered
        binding = None
        if self.inference is not None:
            async with asyncio.timeout(view.lease_seconds):
                binding = await self.inference.bind(
                    view.plan,
                    view.scope,
                    params["messages"],
                    offered or None,
                )
            if view.planning and binding.gateway_revision != view.planning.gateway_revision:
                raise Forbidden(message="Gateway configuration changed; start a new approved run")
            params["model"] = binding.policy.model_key
            params["max_tokens"] = binding.policy.max_output_tokens
            if binding.policy.reasoning_effort is not None:
                # Part of the bound policy, so of the call's identity. Absent
                # when the route sets none, as before the field existed.
                params["reasoning_effort"] = binding.policy.reasoning_effort
            if binding.restore_tool_arguments:
                # Part of the binding, so of the call's identity. Absent
                # for a call offered no tools, and where the route does not
                # pseudonymize.
                params["lq_ai_restore_tool_arguments"] = True
            view = await self.store.execution_view(claim)
        return await self._call(
            claim, view, effect_key, phase, intent, params, inference_binding=binding, step=step
        )

    async def workspace(
        self,
        claim: WorkerClaim,
        *,
        effect_key: str,
        phase: Phase,
        intent: ToolIntent,
        params: dict[str, Any],
        step: StepNote | None = None,
        tool_quote: CostQuote | None = None,
    ) -> ToolResult:
        request = parse_request(intent, params)
        view = await self.store.execution_view(claim)
        return await self._call(
            claim,
            view,
            effect_key,
            phase,
            intent,
            request.model_dump(mode="json"),
            step=step,
            tool_quote=tool_quote,
        )

    async def retrieve(
        self,
        claim: WorkerClaim,
        *,
        effect_key: str,
        phase: Phase,
        file_id: UUID,
    ) -> ToolResult:
        view = await self.store.execution_view(claim)
        return await self._call(
            claim, view, effect_key, phase, ToolIntent.retrieve_chunks, {"file_id": str(file_id)}
        )

    async def read_document(
        self,
        claim: WorkerClaim,
        *,
        effect_key: str,
        phase: Phase,
        file_id: UUID,
        offset: int,
        max_chars: int,
        step: StepNote | None = None,
        tool_quote: CostQuote | None = None,
    ) -> ToolResult:
        """One bounded span of a selected document's text, through the boundary."""
        view = await self.store.execution_view(claim)
        return await self._call(
            claim,
            view,
            effect_key,
            phase,
            ToolIntent.retrieve_chunks,
            {"file_id": str(file_id), "offset": offset, "max_chars": max_chars},
            step=step,
            tool_quote=tool_quote,
        )

    async def search_knowledge(
        self,
        claim: WorkerClaim,
        *,
        effect_key: str,
        phase: Phase,
        knowledge_base_ids: tuple[UUID, ...],
        query: str,
        top_k: int,
        max_chars: int,
        step: StepNote | None = None,
        tool_quote: CostQuote | None = None,
    ) -> ToolResult:
        """One keyword search of the knowledge bases the plan lists, through the boundary.

        The request names every listed knowledge base, so it is the same on a
        replay whatever has changed since. Which of them may still be searched
        is decided inside the call, when it runs.
        """
        view = await self.store.execution_view(claim)
        return await self._call(
            claim,
            view,
            effect_key,
            phase,
            ToolIntent.retrieve_chunks,
            {
                "kb_ids": sorted(str(k) for k in knowledge_base_ids),
                "query": query,
                "top_k": top_k,
                "max_chars": max_chars,
            },
            step=step,
            tool_quote=tool_quote,
        )

    async def refuse(
        self,
        claim: WorkerClaim,
        *,
        effect_key: str,
        phase: Phase,
        tool: str | None,
        code: str,
        requested: dict[str, Any],
        reason: str | None = None,
    ) -> EffectReceipt:
        """Record a refused tool call as a completed observation; nothing runs."""
        view = await self.store.execution_view(claim)
        identity = _bounded_json(
            {
                "plan_hash": view.plan.approval_hash(),
                "session_id": str(claim.session_id),
                "phase": phase.value,
                "intent": "refused",
                "request": requested,
                "code": code,
            }
        )
        note = StepNote(kind="tool_refused", tool=tool, reason=reason).record(None)
        note["summary"] = {"code": code}
        # A refusal is a step of the run, so it is traced like one.
        with quiet_span(_tracer, "orchestration.effect") as span:
            record_attributes(
                span,
                **{
                    "orchestration.root_id": str(claim.root_id),
                    "orchestration.session_id": str(claim.session_id),
                    "orchestration.phase": phase.value,
                    "orchestration.intent": "refused",
                    "orchestration.skill": view.scope.skill.name,
                    "orchestration.step_kind": "tool_refused",
                },
            )
            return await self.store.record_refusal(
                claim,
                effect_key=effect_key,
                request_hash=hashlib.sha256(identity.encode()).hexdigest(),
                phase=phase,
                tool=tool,
                code=code,
                step=note,
            )

    async def skill_tool(
        self,
        claim: WorkerClaim,
        *,
        effect_key: str,
        phase: Phase,
        intent: ToolIntent,
        params: dict[str, Any],
    ) -> ToolResult:
        params = parse_skill_tool(intent, params)
        view = await self.store.execution_view(claim)
        return await self._call(claim, view, effect_key, phase, intent, params)

    async def authority(
        self,
        claim: WorkerClaim,
        *,
        effect_key: str,
        phase: Phase,
        source_name: str,
        operation: str,
        args: dict[str, Any],
    ) -> ToolResult:
        args_json = _bounded_json(args)
        if self.sources is None:
            raise Forbidden(message="Authority sources are not configured")
        view = await self.store.execution_view(claim)
        if not isinstance(view.plan, PreparedPlan):
            raise Forbidden(message="Planning cannot call authority sources")
        # No control or outcome transaction is open during gateway config I/O.
        async with asyncio.timeout(view.lease_seconds):
            binding = await self.sources.bind(
                view.plan, view.scope, source_name=source_name, operation=operation
            )
        # Config fetch consumed lease time. Refresh the remaining attempt time
        # and current authority before entering the dispatch transaction.
        view = await self.store.execution_view(claim)
        return await self._call(
            claim,
            view,
            effect_key,
            phase,
            ToolIntent.retrieve_authority,
            {"source": binding.source.source_type, "op": operation, "args": json.loads(args_json)},
            source_binding=binding,
        )

    async def _call(
        self,
        claim: WorkerClaim,
        view: ExecutionView,
        effect_key: str,
        phase: Phase,
        intent: ToolIntent,
        params: dict[str, Any],
        *,
        source_binding: SourceBinding | None = None,
        inference_binding: InferenceBinding | None = None,
        step: StepNote | None = None,
        tool_quote: CostQuote | None = None,
    ) -> ToolResult:
        invocation = _Invocation(
            self.store,
            claim,
            view,
            effect_key,
            phase,
            self.quote,
            source_binding,
            inference_binding,
            tool_quote,
            step,
        )
        # A run step is traced like an ordinary turn's work (ADR 0038 D2).
        # Identifiers and labels only; a span never carries prompt or document text.
        with quiet_span(_tracer, "orchestration.effect") as span:
            record_attributes(
                span,
                **{
                    "orchestration.root_id": str(claim.root_id),
                    "orchestration.session_id": str(claim.session_id),
                    "orchestration.phase": phase.value,
                    "orchestration.intent": intent.value,
                    "orchestration.skill": view.scope.skill.name,
                    "orchestration.step_kind": step.kind if step else "",
                },
            )
            try:
                async with asyncio.timeout(view.lease_seconds), self.store.sessions.begin() as db:
                    session = await db.get(AutonomousSession, claim.session_id)
                    if session is None:
                        raise Conflict(message="Worker session no longer exists")
                    # The chat turn a run is bound to, from server records only.
                    bound = (
                        await db.execute(
                            select(Message.chat_id, Message.id).where(
                                Message.autonomous_session_id == claim.root_id
                            )
                        )
                    ).one_or_none()
                    return await guarded_tool_call(
                        session,
                        intent,
                        params,
                        db,
                        self.gateway,
                        execution_scope=view.scope,
                        effect=invocation,
                        source_binding=source_binding,
                        inference_binding=inference_binding,
                        workspace_access=WorkspaceAccess(self.store, claim)
                        if intent in WORKSPACE_INTENTS
                        else None,
                        skill_tools=SkillTools(self.skills)
                        if intent in SKILL_TOOL_INTENTS
                        else None,
                        correlation=RunCorrelation(chat_id=bound.chat_id, message_id=bound.id)
                        if bound is not None
                        else None,
                    )
            except BaseException:
                # The outcome transaction has rolled back before recovery acquires
                # any control locks. A process death here is covered by lease expiry.
                if invocation.admitted:
                    try:
                        async with asyncio.timeout(5):
                            await self.store.mark_effect_uncertain(claim, effect_key=effect_key)
                    except Exception:
                        log.warning("Effect recovery deferred to lease watchdog", exc_info=False)
                raise
