"""Per-call tool-governance substrate — PR5a Task 2.

Provides the shared ``governed_tool_invocation`` helper that BOTH the
chat loop (PR5b) and the autonomous layer use for every external tool
call.  The helper enforces:

1. **Tier check (D-a2):** api-side pre-flight check against the caller's
   supplied ceiling.  A refusal writes a ``refused_tier`` audit row and
   raises :exc:`~app.errors.ToolTierRefused` — dispatch is never called.

2. **Audit row:** writes a ``tool_call_log`` row with ``outcome="pending"``
   before dispatch (counts/types only — no raw args or results, ever).

3. **Dispatch:** runs the caller-supplied closure; updates the row to
   ``outcome="executed"`` on success or ``outcome="error"`` on exception.

4. **OTel annotation (D-a1):** annotates the *caller's* span (if
   provided) with counts/types.  Does NOT open its own span.

5. **Flush-not-commit:** all DB mutations go through ``db.flush()``.
   The caller (chat handler / executor) owns the commit boundary.

Security invariants (enforced, never relaxed):

- Raw args and tool results are NEVER written to any DB row or log
  statement.  Only ``args_digest`` (a caller-supplied short hash) and
  outcome labels flow into the audit row.
- Estimated cost is accepted as a parameter; the helper never calls
  ``estimate_tool_cost`` itself (single-estimate invariant, prevents
  double-charge / divergence).
- ``resolve_provider_tier`` fails safe to the **most-restrictive tier**
  (5) when the gateway config is absent or the provider is not found.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult
from app.clients.gateway import get_gateway_client
from app.errors import ToolTierRefused
from app.models.tool_call_log import ToolCallLog
from app.observability_helpers import record_attributes

log = logging.getLogger(__name__)

# The most-restrictive egress tier — used as a fail-safe when the
# provider is missing from the gateway config (D-a2: fail restrictive).
_MAX_TIER: int = 5

# Process-level cache: provider name → egress_tier.
# Gateway config is treated as immutable per process lifetime (same
# lifecycle as GatewayClient's citation-engine cache).
_provider_tier_cache: dict[str, int] = {}
_provider_tier_cache_loaded: bool = False

# DE-344: per-provider external-tool cost caches, populated alongside the
# tier cache in a single _load_provider_tier_cache pass.
# provider name → cost_per_call (Decimal); absent ⟹ Decimal("0").
_provider_cost_cache: dict[str, Decimal] = {}
# provider type string → provider name; used by retrieve_authority to map
# the source type (e.g. "govinfo") to the logical provider name.
_provider_type_to_name: dict[str, str] = {}


async def resolve_provider_tier(
    provider: str,
    *,
    request_id: str | None = None,
) -> int:
    """Return the configured egress tier for *provider*.

    Reads ``GET /admin/v1/config`` via :func:`~app.clients.gateway.get_gateway_client`
    once per process and caches the entire ``tool_providers`` map.
    On any failure (network, non-200, missing key) returns ``_MAX_TIER``
    (5) — the most-restrictive tier — so the system fails safe rather
    than failing open.

    Args:
        provider: The logical provider name as it appears in
            ``gateway.yaml`` (e.g. ``"courtlistener-prod"``).
        request_id: Optional request-id for cross-service trace
            correlation.

    Returns:
        The provider's ``egress_tier`` (int 0-5), or ``_MAX_TIER`` (5)
        when the provider is absent or the lookup fails.
    """
    global _provider_tier_cache_loaded

    if not _provider_tier_cache_loaded:
        await _load_provider_tier_cache(request_id=request_id)

    return _provider_tier_cache.get(provider, _MAX_TIER)


async def _load_provider_tier_cache(*, request_id: str | None = None) -> None:
    """Populate the process-level provider-tier cache from gateway config.

    Best-effort: any exception leaves the cache empty (all lookups then
    fall back to ``_MAX_TIER``).  Marks the cache as loaded regardless
    so a repeated broken gateway is not re-polled on every call.
    """
    global _provider_tier_cache_loaded

    try:
        config = await get_gateway_client().get_admin_config(request_id=request_id)
        providers = config.get("tool_providers") or []
        for entry in providers:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            tier_raw = entry.get("egress_tier")
            if name and tier_raw is not None:
                with contextlib.suppress(TypeError, ValueError):
                    _provider_tier_cache[str(name)] = int(tier_raw)
            # DE-344: cache cost_per_call and type→name for external-tool cost model.
            if name:
                cost_raw = entry.get("cost_per_call")
                if cost_raw is not None:
                    with contextlib.suppress(TypeError, ValueError, ArithmeticError):
                        _provider_cost_cache[str(name)] = Decimal(str(cost_raw))
                type_str = entry.get("type")
                if type_str:
                    _provider_type_to_name[str(type_str)] = str(name)
    except Exception:
        log.warning(
            "resolve_provider_tier: gateway config fetch failed; "
            "all providers default to max tier (%d)",
            _MAX_TIER,
            extra={"event": "tool_governance_tier_cache_load_failed"},
        )
    finally:
        _provider_tier_cache_loaded = True


def _reset_provider_tier_cache_for_tests() -> None:
    """Drop the tier and cost caches.  Tests use this to force a fresh fetch."""
    global _provider_tier_cache_loaded
    _provider_tier_cache.clear()
    _provider_cost_cache.clear()
    _provider_type_to_name.clear()
    _provider_tier_cache_loaded = False


async def resolve_provider_cost(
    provider: str,
    *,
    request_id: str | None = None,
) -> Decimal:
    """Return the configured cost_per_call for *provider* as a :class:`~decimal.Decimal`.

    Reads ``GET /admin/v1/config`` once per process (same cache and load
    flag as :func:`resolve_provider_tier`).  Returns :data:`decimal.Decimal`
    ``"0"`` when the provider is absent or no ``cost_per_call`` is set —
    never raises (D-a3: external-tool cost is non-fatal).

    Args:
        provider: The logical provider name (e.g. ``"courtlistener-prod"``).
        request_id: Optional cross-service trace correlation header value.

    Returns:
        The provider's ``cost_per_call`` as a ``Decimal``, or
        ``Decimal("0")`` when absent/unknown.
    """
    global _provider_tier_cache_loaded

    if not _provider_tier_cache_loaded:
        await _load_provider_tier_cache(request_id=request_id)

    return _provider_cost_cache.get(provider, Decimal("0"))


async def resolve_provider_name_by_type(
    type_str: str,
    *,
    request_id: str | None = None,
) -> str | None:
    """Return the provider name for a given source *type_str*.

    Maps the source type string from the content-source registry (e.g.
    ``"govinfo"``) to the logical provider name used in ``gateway.yaml``
    (e.g. ``"govinfo-prod"``), so :func:`resolve_provider_cost` can be
    called with the correct key for ``retrieve_authority`` tool calls.

    Shares the same cache and load flag as :func:`resolve_provider_tier`.
    Returns ``None`` when the type is absent or the cache load failed —
    never raises.

    Args:
        type_str: The source type string (e.g. ``"govinfo"``,
            ``"courtlistener"``).
        request_id: Optional cross-service trace correlation header value.

    Returns:
        The provider name string, or ``None`` when not found.
    """
    global _provider_tier_cache_loaded

    if not _provider_tier_cache_loaded:
        await _load_provider_tier_cache(request_id=request_id)

    return _provider_type_to_name.get(type_str)


async def governed_tool_invocation(
    db: AsyncSession,
    *,
    origin: str,
    provider: str,
    tool: str,
    intent: ToolIntent | None,
    provider_tier: int,
    max_allowed_tier: int | None,
    estimated_cost: Decimal,
    dispatch: Callable[[], Awaitable[ToolResult]],
    span: Any | None = None,
    confirmation_state: str = "not_required",
    user_id: UUID | None = None,
    chat_id: UUID | None = None,
    message_id: UUID | None = None,
    session_id: UUID | None = None,
    request_id: str | None = None,
    args_digest: str | None = None,
    denied_on: tuple[type[Exception], ...] = (),
) -> ToolResult:
    """Shared per-call governance: tier-check → audit row → dispatch → record.

    Flush-not-commit.  Raises :exc:`~app.errors.ToolTierRefused` before
    dispatch when the tier ceiling is exceeded.

    **Security invariants (never weaken):**

    - No raw args or result payloads are written to any row or log line.
      Only ``args_digest`` (caller-supplied) and counts/labels flow into
      the audit row.
    - The helper never calls ``estimate_tool_cost``; it accepts
      ``estimated_cost`` from the caller (single-estimate invariant).
    - The helper never commits; the caller owns the commit boundary.

    Args:
        db: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        origin: ``"chat"`` or ``"autonomous"`` — which execution context
            is firing the tool.
        provider: Logical provider name (e.g. ``"courtlistener-prod"``).
        tool: Tool / function name within the provider.
        intent: :class:`~app.autonomous.enums.ToolIntent` for autonomous
            calls; ``None`` for chat-origin calls.
        provider_tier: The provider's egress tier, resolved by the caller
            via :func:`resolve_provider_tier` before this call.
        max_allowed_tier: The ceiling this caller is operating under.
            ``None`` means unconstrained (no tier check performed).
        estimated_cost: Pre-computed cost estimate in USD; recorded on
            the audit row as-is — the helper never re-estimates.
        dispatch: Zero-argument async callable that performs the actual
            tool call and returns a :class:`~app.autonomous.guard.ToolResult`.
        span: Optional OTel span to annotate with counts/types (D-a1).
            The helper does NOT open its own span.
        confirmation_state: Human-gate lifecycle label for the row.
            Defaults to ``"not_required"``.
        user_id: FK to ``users.id``; ``None`` for headless/autonomous.
        chat_id: Set for chat-origin calls.
        message_id: Chat message id.
        session_id: Autonomous session id.
        request_id: Cross-service trace correlation header value.
        args_digest: A short hash/summary of the call arguments produced
            by the caller.  NEVER the raw args.
        denied_on: A tuple of exception types (supplied by the caller)
            that represent a **policy refusal** rather than a tool
            failure.  When ``dispatch`` raises an exception that is an
            instance of one of these types, the audit row is labeled
            ``outcome="denied"`` instead of ``outcome="error"`` before
            the exception is re-raised.  Passing the empty tuple
            (default) preserves the existing behaviour: all dispatch
            exceptions → ``"error"``.  Callers pass the specific
            exception classes — this module never imports autonomous
            symbols directly (no circular-import risk).

    Returns:
        The :class:`~app.autonomous.guard.ToolResult` from ``dispatch``.

    Raises:
        ToolTierRefused: If ``max_allowed_tier is not None`` and
            ``provider_tier > max_allowed_tier``.  An audit row with
            ``outcome="refused_tier"`` is written and flushed before
            the raise.
        Any exception raised by ``dispatch`` is re-raised after updating
        the audit row to ``outcome="denied"`` (if the exception type is
        listed in ``denied_on``) or ``outcome="error"`` (all other
        exceptions) and flushing.
    """
    # ── D-a2 tier check ────────────────────────────────────────────────────
    if max_allowed_tier is not None and provider_tier > max_allowed_tier:
        row = ToolCallLog(
            origin=origin,
            provider=provider,
            tool=tool,
            tier=provider_tier,
            intent=str(intent) if intent is not None else None,
            confirmation_state=confirmation_state,
            outcome="refused_tier",
            cost_usd=None,
            args_digest=args_digest,
            request_id=request_id,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            session_id=session_id,
        )
        db.add(row)
        await db.flush()
        if span is not None:
            record_attributes(
                span,
                **{
                    "tool_call.outcome": "refused_tier",
                    "tool_call.provider": provider,
                    "tool_call.tool": tool,
                    "tool_call.tier": provider_tier,
                },
            )
        raise ToolTierRefused(
            provider=provider,
            tool=tool,
            tier=provider_tier,
            ceiling=max_allowed_tier,
        )

    # ── Write pending row ───────────────────────────────────────────────────
    row = ToolCallLog(
        origin=origin,
        provider=provider,
        tool=tool,
        tier=provider_tier,
        intent=str(intent) if intent is not None else None,
        confirmation_state=confirmation_state,
        outcome="pending",
        cost_usd=estimated_cost,
        args_digest=args_digest,
        request_id=request_id,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        session_id=session_id,
    )
    db.add(row)
    await db.flush()

    # ── Dispatch ────────────────────────────────────────────────────────────
    try:
        result = await dispatch()
    except Exception as exc:
        outcome = "denied" if (denied_on and isinstance(exc, denied_on)) else "error"
        row.outcome = outcome
        row.updated_at = datetime.now(UTC)
        await db.flush()
        if span is not None:
            record_attributes(
                span,
                **{
                    "tool_call.outcome": outcome,
                    "tool_call.provider": provider,
                    "tool_call.tool": tool,
                    "tool_call.tier": provider_tier,
                },
            )
        raise

    # ── Record success ──────────────────────────────────────────────────────
    row.outcome = "executed"
    row.cost_usd = result.cost_usd
    row.updated_at = datetime.now(UTC)
    await db.flush()
    if span is not None:
        record_attributes(
            span,
            **{
                "tool_call.outcome": "executed",
                "tool_call.provider": provider,
                "tool_call.tool": tool,
                "tool_call.tier": provider_tier,
                "tool_call.cost_usd": float(result.cost_usd),
            },
        )
    return result
