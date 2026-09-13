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
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult, guarded_tool_call
from app.autonomous.orchestration.contracts import ExecutionScope, Money, ShortText, Snapshot
from app.autonomous.orchestration.inference import InferenceBinding, InferenceRoutes
from app.autonomous.orchestration.policy import load_pinned_skill
from app.autonomous.orchestration.sources import AuthoritySources, SourceBinding
from app.autonomous.orchestration.store import ExecutionView, OrchestrationStore, WorkerClaim
from app.errors import Conflict, Forbidden, ValidationError
from app.models.autonomous import AutonomousSession
from app.schemas.autonomous import Phase
from app.skills.registry import MutableSkillRegistry

log = logging.getLogger(__name__)


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


def _bounded_json(value: dict[str, Any]) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 131_072:
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
    ) -> None:
        self.store, self.claim, self.view = store, claim, view
        self.effect_key, self.phase, self.quote = effect_key, phase, quote
        self.admitted = False
        self.source_binding = source_binding
        self.inference_binding = inference_binding

    async def admit(
        self, intent: ToolIntent, params: dict[str, Any]
    ) -> tuple[Decimal, ToolResult | None]:
        # Snapshot the narrowed call before quoting; caller-owned dictionaries
        # and model text cannot change the identity while admission awaits I/O.
        request = _bounded_json(params)
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
            }
        )
        receipt = await self.store.begin_effect(
            self.claim,
            effect_key=self.effect_key,
            request_hash=hashlib.sha256(identity.encode()).hexdigest(),
            reservation_usd=quote.amount_usd,
            phase=self.phase,
            intent=intent,
        )
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
        await self.store._settle_effect(
            db,
            self.claim,
            effect_key=self.effect_key,
            charged_usd=result.cost_usd,
            result={"data": result.data, "outcome": result.outcome},
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
    ) -> ToolResult:
        if intent not in {ToolIntent.run_skill, ToolIntent.plan}:
            raise Forbidden(message="Inference intent is not supported by this adapter")
        # Copy before the first await; only this bounded JSON becomes user data.
        inputs_json = _bounded_json(inputs)
        view = await self.store.execution_view(claim)
        record = self.skills.current().get(view.scope.skill.name)
        if record is None:
            raise Forbidden(message="Pinned skill is unavailable")
        artifact = load_pinned_skill(record)
        if artifact.pin != view.scope.skill:
            raise Forbidden(message="Pinned skill has changed")
        task: Any = (
            view.plan.goal
            if claim.session_id == claim.root_id
            else next(
                c.task.model_dump(mode="json")
                for c in view.plan.children
                if c.dispatch_id == claim.session_id
            )
        )
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": artifact.instructions},
                {
                    "role": "user",
                    "content": _bounded_json({"task": task, "inputs": json.loads(inputs_json)}),
                },
            ],
        }
        binding = None
        if self.inference is not None:
            async with asyncio.timeout(view.lease_seconds):
                binding = await self.inference.bind(view.plan, view.scope, params["messages"])
            params["model"] = binding.policy.model_key
            params["max_tokens"] = binding.policy.max_output_tokens
            view = await self.store.execution_view(claim)
        return await self._call(
            claim, view, effect_key, phase, intent, params, inference_binding=binding
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
        )
        try:
            async with asyncio.timeout(view.lease_seconds), self.store.sessions.begin() as db:
                session = await db.get(AutonomousSession, claim.session_id)
                if session is None:
                    raise Conflict(message="Worker session no longer exists")
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
