"""Chat tool-loop engine — PR5b Task 5.

Implements the agentic tool-calling loop for chat turns. The loop calls the
gateway in NON-streaming mode each round; when the model requests tool calls,
this module dispatches them through the governance substrate
(:func:`~app.tools.governance.governed_tool_invocation`) and feeds results
back to the model. The loop terminates on one of three outcomes:

- :class:`LoopFinal` — model produced a final text answer (no more tools).
- :class:`LoopConfirmation` — model requested a destructive / confirmation-
  gated tool; the loop surfaces the gate to the caller (Task 6/7) which
  handles the human-approval flow and resumes by calling back with
  ``calls_used`` and ``messages`` from the partial outcome. **Only the FIRST
  such call in a round triggers the gate; remaining proposed calls are
  abandoned for this turn** (the model re-plans after the human decision).
- :class:`LoopMcpAuth` — model requested an OAuth MCP tool but no valid token
  is stored; the caller redirects the user through the authorize flow.

When ``calls_used >= settings.chat_tool_call_cap`` the loop issues ONE final
gateway round WITHOUT tools (``tool_choice="none"``) so the model can
synthesise what it has gathered before returning :class:`LoopFinal`.

**OTel note:** span annotation for the chat tool-path is a follow-on DE (DE-XXX);
pass ``span=None`` throughout.

Security invariants (never weaken):
- Raw args are NEVER written to audit rows or logs.  Only ``args_digest`` flows
  into :func:`~app.tools.governance.governed_tool_invocation`.
- Per-user OAuth token is threaded from :func:`~app.mcp.oauth.get_valid_token`
  to :meth:`~app.clients.gateway.GatewayClient.call_tool` header-only; it never
  touches the DB row or any log line.
- Estimated cost is always ``Decimal("0")`` for both ``retrieve_caselaw`` and
  ``call_mcp_tool`` (DE-344: per-provider tool cost model deferred).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.cost import estimate_tool_cost
from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult, _args_digest
from app.chat.tool_schemas import ChatToolAllowlist, ToolSpec
from app.config import get_settings
from app.errors import MCPAuthorizationRequired, ToolTierRefused
from app.mcp.oauth import get_valid_token
from app.mcp.service import list_servers
from app.models.user import User
from app.research import service as research_service
from app.research.adapters import GovInfoAdapter
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest
from app.tools.governance import governed_tool_invocation, resolve_provider_tier

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Outcome dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LoopFinal:
    """The model produced a final text answer; no more tool calls needed.

    Carries the full message list so the caller can persist the turn.
    """

    text: str
    usage_prompt: int = 0
    usage_completion: int = 0
    tier: int | None = None
    provider: str | None = None
    model: str | None = None
    applied_skills: list[str] | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    calls_used: int = 0
    tool_sources: list[ToolSourceRecord] = field(default_factory=list)


@dataclass
class LoopConfirmation:
    """A destructive or requires_confirmation tool was requested.

    Task 6/7 persists the partial state and emits the human gate.
    ``messages`` and ``calls_used`` are included so the caller can resume
    the loop after the user confirms or cancels.

    **Note:** Only the first such call in a round triggers the gate;
    remaining proposed calls in the same round are abandoned. The model
    re-plans after the human decision is relayed back.
    """

    spec: ToolSpec
    args: dict[str, Any]
    tier: int | None
    args_summary: str  # the args_digest — counts/types only, never raw args
    messages: list[dict[str, Any]] = field(default_factory=list)
    calls_used: int = 0


@dataclass
class LoopMcpAuth:
    """An OAuth MCP server was called but no valid token is stored.

    The caller should redirect the user through the authorize flow at
    ``/api/v1/mcp/oauth/{server}/authorize``.
    ``messages`` and ``calls_used`` allow resuming after authorization.
    """

    server: str
    authorize_url: str | None = None  # populated by Task 6/7 if needed
    messages: list[dict[str, Any]] = field(default_factory=list)
    calls_used: int = 0


LoopOutcome = LoopFinal | LoopConfirmation | LoopMcpAuth

_COURTLISTENER_BASE = "https://www.courtlistener.com"


@dataclass
class ToolSourceRecord:
    """One external source (a case-law cluster) a research tool returned this turn."""

    source_kind: str
    label: str
    subtitle: str | None
    url: str | None
    external_ref: str | None
    provider: str
    tool: str


# ---------------------------------------------------------------------------
# tool_result_message helper
# ---------------------------------------------------------------------------


def tool_result_message(tool_call_id: str, result: ToolResult) -> dict[str, Any]:
    """Build the ``role="tool"`` message fed back to the model.

    The ``content`` field serialises the tool's ``data`` payload as JSON
    so the model can parse structured results.  On ``None`` data, an empty
    JSON object is returned.
    """
    data = result.data if result.data is not None else {}
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(data, default=str),
    }


def _tool_error_message(tool_call_id: str, error: str) -> dict[str, Any]:
    """Build a ``role="tool"`` error message for a refused / failed call."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps({"error": error}),
    }


# ---------------------------------------------------------------------------
# Retrieval-provenance extraction (PR6c)
# ---------------------------------------------------------------------------


def _absolutize_cl_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{_COURTLISTENER_BASE}{url}"


def _cluster_record(cluster: dict[str, Any], tool: str) -> ToolSourceRecord | None:
    """Map a CourtListener cluster dict → a ToolSourceRecord (None if no identity)."""
    cluster_id = cluster.get("cluster_id")
    case_name = cluster.get("case_name")
    if cluster_id is None and not case_name:
        return None
    court = cluster.get("court")
    date_filed = cluster.get("date_filed")
    subtitle_parts = [p for p in (court, date_filed) if p]
    return ToolSourceRecord(
        source_kind="caselaw",
        label=case_name or f"Cluster {cluster_id}",
        subtitle=" · ".join(subtitle_parts) if subtitle_parts else None,
        url=_absolutize_cl_url(cluster.get("absolute_url")),
        external_ref=str(cluster_id) if cluster_id is not None else None,
        provider="courtlistener",
        tool=tool,
    )


def extract_tool_sources(tool_name: str, data: Any) -> list[ToolSourceRecord]:
    """Map a research tool's structured result into retrieval-provenance records.

    Only ``search_case_law`` (each returned cluster) and ``get_cluster`` (the one
    cluster) carry full case identity, so only they produce sources. All other
    tools (read_opinion / find_in_case / verify_citations / MCP) → ``[]``.
    """
    if not isinstance(data, dict):
        return []
    out: list[ToolSourceRecord] = []
    if tool_name == "search_case_law":
        for item in data.get("results", []) or []:
            if isinstance(item, dict):
                rec = _cluster_record(item, tool_name)
                if rec is not None:
                    out.append(rec)
    elif tool_name == "get_cluster":
        cluster = data.get("cluster")
        if isinstance(cluster, dict):
            rec = _cluster_record(cluster, tool_name)
            if rec is not None:
                out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Generic-MCP provenance (DE-350)
# ---------------------------------------------------------------------------

_MCP_TITLE_KEYS: tuple[str, ...] = ("title", "name", "label")
_MCP_URL_KEYS: tuple[str, ...] = ("url", "link", "href")


def _mcp_label_url(data: Any) -> tuple[str | None, str | None]:
    """Best-effort (title, url) from a heterogeneous MCP payload. Never raises.

    Reads a title/url only from dict-shaped data (a top-level dict, or the first
    dict element inside a list — the standard MCP ``content`` block list). Plain
    text blocks yield ``(None, None)``. Any odd shape or error → ``(None, None)``.
    """

    def _from_dict(d: dict[str, Any]) -> tuple[str | None, str | None]:
        title = next((d[k] for k in _MCP_TITLE_KEYS if isinstance(d.get(k), str) and d[k]), None)
        url = next((d[k] for k in _MCP_URL_KEYS if isinstance(d.get(k), str) and d[k]), None)
        return title, url

    try:
        if isinstance(data, dict):
            return _from_dict(data)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    title, url = _from_dict(item)
                    if title is not None or url is not None:
                        return title, url
        return None, None
    except Exception:
        return None, None


def extract_mcp_tool_source(spec: ToolSpec, data: Any) -> ToolSourceRecord | None:
    """One retrieval-provenance record for a successful MCP tool call (DE-350).

    Per-call provenance: ``source_kind='mcp'``, provider/tool from the spec, a
    best-effort label/url, ``external_ref=None``. Returns ``None`` for a
    non-MCP spec (defensive; the router only calls it for ``kind == 'mcp'``).
    """
    if spec.kind != "mcp":
        return None
    title, url = _mcp_label_url(data)
    return ToolSourceRecord(
        source_kind="mcp",
        label=title or f"{spec.provider} · {spec.tool}",
        subtitle=None,
        url=url,
        external_ref=None,
        provider=spec.provider,
        tool=spec.tool,
    )


def collect_tool_sources(spec: ToolSpec, data: Any) -> list[ToolSourceRecord]:
    """Route a tool result to its provenance records by ``spec.kind`` (DE-350).

    MCP → one ``mcp`` record; research → the existing case-law extraction.
    """
    if spec.kind == "mcp":
        rec = extract_mcp_tool_source(spec, data)
        return [rec] if rec is not None else []
    return extract_tool_sources(spec.tool, data)


# ---------------------------------------------------------------------------
# Research dispatch
# ---------------------------------------------------------------------------


async def _dispatch_research(
    db: AsyncSession,
    spec: ToolSpec,
    args: dict[str, Any],
    cluster_cache: dict[Any, Any],
    request_id: str | None,
) -> ToolResult:
    """Dispatch a research (CourtListener) tool call.

    Checks/fills ``cluster_cache`` for ``get_cluster`` and ``read_opinion``
    to avoid redundant gateway round-trips within a single turn.

    Cost is ``Decimal("0")`` in v1 — DE-344 defers per-provider tool cost.
    """
    op = spec.tool
    data: Any
    if op == "verify_citations":
        data = await research_service.verify_citations(args["text"], request_id=request_id)
    elif op == "search_case_law":
        data = await research_service.search_case_law(args, request_id=request_id)
    elif op == "get_cluster":
        key = ("cluster", int(args["cluster_id"]))
        cached = cluster_cache.get(key)
        if cached is None:
            data = await research_service.get_cluster(
                db, cluster_id=int(args["cluster_id"]), request_id=request_id
            )
            cluster_cache[key] = data
        else:
            data = cached
    elif op == "read_opinion":
        key = ("opinion", int(args["opinion_id"]))
        cached = cluster_cache.get(key)
        if cached is None:
            data = await research_service.read_opinion(db, opinion_id=int(args["opinion_id"]))
            cluster_cache[key] = data
        else:
            data = cached
    elif op == "find_in_case":
        data = await research_service.find_in_case(
            db,
            opinion_id=int(args["opinion_id"]),
            query=args["query"],
            max_matches=int(args.get("max_matches", 3)),
        )
    else:
        from app.errors import ToolNotGranted

        raise ToolNotGranted(
            f"_dispatch_research: unknown research op {op!r}",
            intent=str(ToolIntent.retrieve_caselaw),
            phase="chat",
        )
    return ToolResult(cost_usd=Decimal("0"), data=data, outcome="success")


# ---------------------------------------------------------------------------
# Authority dispatch (WS-E PR1c)
# ---------------------------------------------------------------------------


async def _dispatch_authority(
    db: AsyncSession,
    spec: ToolSpec,
    args: dict[str, Any],
    gateway: Any,
    request_id: str | None,
) -> ToolResult:
    """Dispatch an authority op (search_authority/get_authority) via the gateway.

    On get_authority, persist the fetched body to the durable authority cache
    so the finalize verify hook can char-verify quotes against it.  The cache
    write is savepoint-isolated + non-fatal (never poison the session — mirrors
    app/autonomous/guard.py).  Only get_authority yields a quotable body.
    """
    result = await gateway.call_tool(spec.provider, spec.tool, args)
    payload = result.get("payload") if isinstance(result, dict) else None
    authority = GovInfoAdapter().from_response(spec.tool, payload or {})

    if spec.tool == "get_authority" and authority.citable_text:
        # Function-local import breaks the tool_loop <-> citation.authority
        # module cycle (mirrors guard.py:874).
        from app.citation.authority import store_authority_text

        try:
            async with db.begin_nested():
                await store_authority_text(
                    db,
                    source_type=spec.provider,
                    external_ref=authority.external_ref,
                    text=authority.citable_text,
                )
        except Exception:
            log.warning(
                "chat authority dispatch: cache write failed — non-fatal",
                extra={
                    "event": "chat_authority_cache_write_failed",
                    "external_ref": authority.external_ref,
                },
                exc_info=True,
            )

    return ToolResult(
        cost_usd=Decimal("0"),
        data={
            "authority": {
                "source": spec.provider,
                "op": spec.tool,
                "content_kind": authority.content_kind,
                "external_ref": authority.external_ref,
                "label": authority.label,
                "subtitle": authority.subtitle,
                "url": authority.url,
                "citable_text": authority.citable_text,
            }
        },
        outcome="success",
    )


# ---------------------------------------------------------------------------
# MCP dispatch
# ---------------------------------------------------------------------------


async def _dispatch_mcp(
    db: AsyncSession,
    user: User,
    gateway: Any,
    spec: ToolSpec,
    args: dict[str, Any],
    server_auth_map: dict[str, str],
    request_id: str | None,
) -> ToolResult:
    """Dispatch an MCP tool call through the gateway.

    Resolves the per-user OAuth token when ``auth == "oauth"`` for the server.
    Returns ``None`` token (raises :class:`MCPAuthorizationRequired`) when no
    valid token is stored.

    For ``none``/``bearer`` servers, ``user_token=None`` is passed to the
    gateway call.

    Cost is ``Decimal("0")`` in v1 — DE-344 defers per-provider tool cost.
    """
    auth_mode = server_auth_map.get(spec.provider, "none")
    user_token: str | None = None

    if auth_mode == "oauth":
        token = await get_valid_token(db, user_id=user.id, server=spec.provider)
        if token is None:
            # No stored token — direct the user through the authorize flow.
            raise MCPAuthorizationRequired(
                message=(
                    f"MCP server {spec.provider!r} requires authorization; "
                    f"connect via /api/v1/mcp/oauth/{spec.provider}/authorize"
                ),
                details={"server": spec.provider},
            )
        user_token = token

    result = await gateway.call_tool(
        spec.provider,
        spec.tool,
        args,
        max_allowed_tier=None,
        user_token=user_token,
        request_id=request_id,
    )
    return ToolResult(cost_usd=Decimal("0"), data=result.get("payload"), outcome="success")


# ---------------------------------------------------------------------------
# execute_tool
# ---------------------------------------------------------------------------


async def execute_tool(
    db: AsyncSession,
    *,
    user: User,
    gateway: Any,
    spec: ToolSpec,
    args: dict[str, Any],
    cluster_cache: dict[Any, Any],
    server_auth_map: dict[str, str],
    assistant_message_id: UUID,
    chat_id: UUID | None = None,
    request_id: str | None = None,
    confirmation_state: str = "not_required",
) -> ToolResult:
    """Execute a single approved read_only tool call through the governance substrate.

    Wraps the appropriate dispatch closure in
    :func:`~app.tools.governance.governed_tool_invocation` with
    ``origin="chat"``.

    Args:
        db: Active async ORM session.
        user: Authenticated user owning the turn.
        gateway: Gateway client (used for MCP dispatch).
        spec: The resolved :class:`~app.chat.tool_schemas.ToolSpec`.
        args: Parsed arguments from the model's ``tool_calls`` entry.
        cluster_cache: Request-scoped cache for research cluster/opinion data.
        server_auth_map: ``{server_name: auth_mode}`` — built once per turn
            from :func:`~app.mcp.service.list_servers`.
        assistant_message_id: The chat message id for the audit row.
        chat_id: Chat id for the audit row (optional).
        request_id: Correlation header value (optional).
        confirmation_state: Human-gate lifecycle label written to the
            ``tool_call_log`` row.  Default ``"not_required"`` preserves
            all existing callers (the loop's read_only inline path).
            Pass ``"approved"`` from the resume route's approve path so
            the EXECUTING audit row is stamped ``approved``/``executed``
            (separate from the gate row, which is the confirmation-request
            lifecycle record).

    Returns:
        :class:`~app.autonomous.guard.ToolResult` on success.

    Raises:
        :class:`~app.errors.ToolTierRefused`: When the provider's tier exceeds
            ``max_allowed_tier`` (``None`` in the chat path, so this only fires
            when the governance config explicitly blocks the call).
        :class:`~app.errors.MCPAuthorizationRequired`: When the MCP server
            requires OAuth and no valid token is stored.
    """
    if spec.kind == "research":
        intent = ToolIntent.retrieve_caselaw
    elif spec.kind == "authority":
        intent = ToolIntent.retrieve_authority
    else:
        intent = ToolIntent.call_mcp_tool

    estimated_cost = await estimate_tool_cost(intent, args, db)
    provider_tier = await resolve_provider_tier(spec.provider, request_id=request_id)

    async def _dispatch() -> ToolResult:
        if spec.kind == "research":
            return await _dispatch_research(db, spec, args, cluster_cache, request_id)
        elif spec.kind == "authority":
            return await _dispatch_authority(db, spec, args, gateway, request_id)
        else:
            return await _dispatch_mcp(db, user, gateway, spec, args, server_auth_map, request_id)

    return await governed_tool_invocation(
        db,
        origin="chat",
        provider=spec.provider,
        tool=spec.tool,
        intent=intent,
        provider_tier=provider_tier,
        max_allowed_tier=None,  # chat path: no per-session tier ceiling in v1
        estimated_cost=estimated_cost,
        dispatch=_dispatch,
        span=None,  # OTel for chat tool-path is a follow-on DE
        confirmation_state=confirmation_state,
        user_id=user.id,
        chat_id=chat_id,
        message_id=assistant_message_id,
        args_digest=_args_digest(args),
        denied_on=(),
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# run_chat_tool_loop
# ---------------------------------------------------------------------------


async def run_chat_tool_loop(
    db: AsyncSession,
    *,
    user: User,
    gateway: Any,
    base_request: ChatCompletionRequest,
    allowlist: ChatToolAllowlist,
    assistant_message_id: UUID,
    chat_id: UUID | None = None,
    calls_used: int = 0,
    cluster_cache: dict[Any, Any] | None = None,
    request_id: str | None = None,
) -> LoopOutcome:
    """Run the agentic chat tool-loop until a terminal outcome is reached.

    Each round:
    1. Call the gateway (NON-streaming) with the current message list and
       ``tools=allowlist.function_schemas()`` / ``tool_choice="auto"``.
    2. If ``finish_reason != "tool_calls"`` or no ``tool_calls`` on the
       message → return :class:`LoopFinal`.
    3. For each tool call in the round:
       a. Resolve ``spec = allowlist.resolve(fn_name)``.
       b. If ``spec is None`` (model hallucinated) → append a policy-refusal
          ``role="tool"`` error message for that ``tool_call_id``; continue.
       c. If ``spec.destructive or spec.requires_confirmation`` → return
          :class:`LoopConfirmation` for the first such call (remaining calls
          in the round are abandoned; documented above).
       d. Otherwise (read_only & not destructive & not requires_confirmation)
          → call :func:`execute_tool`; on :class:`~app.errors.ToolTierRefused`
          append an error tool message and continue; on
          :class:`~app.errors.MCPAuthorizationRequired` → return
          :class:`LoopMcpAuth`.
    4. Append the assistant tool_calls message + the collected tool result
       messages to ``messages``; increment ``calls_used``.
    5. If ``calls_used >= settings.chat_tool_call_cap`` → fire one final
       round WITHOUT tools to let the model synthesise.

    Args:
        db: Active async ORM session.
        user: Authenticated user owning the turn.
        gateway: Gateway client (must implement ``chat_completion``).
        base_request: The base :class:`~app.schemas.gateway.ChatCompletionRequest`
            used for this turn. Rebuilt each round with the growing ``messages``
            list. The caller sets ``model``, ``stream=False``, and any LQ.AI
            extensions; the loop handles ``tools`` and ``tool_choice``.
        allowlist: The per-turn :class:`~app.chat.tool_schemas.ChatToolAllowlist`
            assembled by Task 3.
        assistant_message_id: UUID of the assistant message row (used as
            ``message_id`` in the governance audit row).
        calls_used: Number of tool calls already executed this turn (non-zero
            when resuming after :class:`LoopConfirmation`).
        cluster_cache: Request-scoped cache for research cluster/opinion data.
            ``None`` initialises to an empty dict.
        request_id: Correlation header value forwarded to gateway / services.

    Returns:
        One of :class:`LoopFinal`, :class:`LoopConfirmation`, or
        :class:`LoopMcpAuth`.
    """
    settings = get_settings()

    if cluster_cache is None:
        cluster_cache = {}

    # Build the server-auth map once per turn from list_servers.  Only
    # ``auth == "oauth"`` servers need per-user token resolution; for
    # ``none``/``bearer`` we pass user_token=None to the gateway.
    raw_servers = await list_servers(request_id=request_id)
    server_auth_map: dict[str, str] = {s["name"]: s.get("auth", "none") for s in raw_servers}

    # Working message list — grows as tool results are appended.
    messages: list[dict[str, Any]] = [
        m.model_dump(exclude_none=True) for m in base_request.messages
    ]

    # PR6c — retrieval-provenance: accumulate case-law sources across all rounds.
    collected_sources: list[ToolSourceRecord] = []
    _seen_source_refs: set[str] = set()

    while True:
        # ── Check cap BEFORE calling gateway ─────────────────────────────────
        # When the cap is already reached (e.g. resuming from a confirmed
        # destructive call that pushed us to the limit), fire the final round
        # immediately without tools.
        if calls_used >= settings.chat_tool_call_cap:
            final_resp = await _final_synthesis_round(gateway, base_request, messages, request_id)
            return _build_loop_final(final_resp, messages, calls_used, collected_sources)

        # ── Build this round's request with tools ──────────────────────────
        round_request = _build_request(
            base_request,
            messages,
            tools=allowlist.function_schemas(),
            tool_choice="auto",
        )
        resp = await gateway.chat_completion(round_request, request_id=request_id)

        choice = resp.choices[0]
        finish_reason = choice.finish_reason
        msg = choice.message

        # ── Terminal: no tool calls ──────────────────────────────────────────
        if finish_reason != "tool_calls" or not msg.tool_calls:
            return _build_loop_final(resp, messages, calls_used, collected_sources)

        # ── Process tool calls in this round ─────────────────────────────────
        # The assistant message (with its tool_calls) goes into the working
        # message list AFTER we collect all result messages for this round.
        # (We collect results first, then append the assistant message + all
        #  results at once per the OpenAI multi-turn tool pattern.)
        tool_result_msgs: list[dict[str, Any]] = []

        # governed_count: number of calls routed to execute_tool this round
        # (both successfully executed AND ToolTierRefused counts — those calls
        # DID reach governance and wrote an audit row).  Hallucinated calls
        # (spec is None) are NOT counted: they never reached governance, so
        # they must not consume cap budget.  This ensures the cap bounds real
        # governed tool work, not model confusion about available tools.
        governed_count: int = 0

        for tc in msg.tool_calls:
            tc_id: str = tc["id"]
            fn_name: str = tc["function"]["name"]
            try:
                tc_args: dict[str, Any] = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                tc_args = {}

            # ── (b.2) Hallucinated tool name — policy refusal ──────────────
            spec = allowlist.resolve(fn_name)
            if spec is None:
                log.warning(
                    "chat_tool_loop: hallucinated tool %r — appending policy refusal",
                    fn_name,
                    extra={"event": "chat_tool_loop_hallucinated_tool", "tool": fn_name},
                )
                tool_result_msgs.append(_tool_error_message(tc_id, "tool not permitted"))
                continue

            # ── (b.3) Destructive / requires_confirmation gate ────────────
            if spec.destructive or spec.requires_confirmation:
                # Only the FIRST such call in a round triggers the gate;
                # remaining proposed calls are abandoned for this turn.
                tier = await resolve_provider_tier(spec.provider, request_id=request_id)
                return LoopConfirmation(
                    spec=spec,
                    args=tc_args,
                    tier=tier,
                    args_summary=_args_digest(tc_args),
                    # Carry current messages (BEFORE appending assistant msg)
                    # so Task 6/7 can resume correctly.
                    messages=messages,
                    calls_used=calls_used,
                )

            # ── (b.4) Read-only — execute (counts as governed) ───────────
            governed_count += 1
            try:
                result = await execute_tool(
                    db,
                    user=user,
                    gateway=gateway,
                    spec=spec,
                    args=tc_args,
                    cluster_cache=cluster_cache,
                    server_auth_map=server_auth_map,
                    assistant_message_id=assistant_message_id,
                    chat_id=chat_id,
                    request_id=request_id,
                )
                tool_result_msgs.append(tool_result_message(tc_id, result))
                # retrieval-provenance: record the sources this call surfaced
                # (case-law clusters and, per DE-350, generic MCP consultations).
                for rec in collect_tool_sources(spec, result.data):
                    if rec.external_ref is None or rec.external_ref not in _seen_source_refs:
                        if rec.external_ref is not None:
                            _seen_source_refs.add(rec.external_ref)
                        collected_sources.append(rec)
            except MCPAuthorizationRequired:
                return LoopMcpAuth(
                    server=spec.provider,
                    authorize_url=None,
                    messages=messages,
                    calls_used=calls_used,
                )
            except ToolTierRefused:
                # ToolTierRefused still counts as governed: governed_tool_invocation
                # was called and wrote an audit row before raising.
                log.info(
                    "chat_tool_loop: ToolTierRefused for %r/%r — appending error message",
                    spec.provider,
                    spec.tool,
                    extra={
                        "event": "chat_tool_loop_tier_refused",
                        "provider": spec.provider,
                        "tool": spec.tool,
                    },
                )
                tool_result_msgs.append(_tool_error_message(tc_id, "tool tier refused"))

        # ── Append assistant tool_calls message + all result messages ─────
        # Convert the assistant message to dict, preserving tool_calls.
        asst_dict = msg.model_dump(exclude_none=True)
        messages.append(asst_dict)
        messages.extend(tool_result_msgs)

        # Increment by governed calls only (executed + tier-refused).
        # Hallucinated calls (unknown function names) are excluded: they never
        # reached governance so they must not consume the per-turn cap budget.
        calls_used += governed_count

        # ── Termination guard: all-hallucination round ────────────────────
        # If every proposed call this round was hallucinated (governed_count
        # == 0) the model made no progress toward the cap and would loop
        # forever.  Break out immediately to the final no-tools round so the
        # model synthesises from whatever it has gathered so far.
        if governed_count == 0:
            final_resp = await _final_synthesis_round(gateway, base_request, messages, request_id)
            return _build_loop_final(final_resp, messages, calls_used, collected_sources)

        # ── Cap check AFTER incrementing ─────────────────────────────────
        if calls_used >= settings.chat_tool_call_cap:
            final_resp = await _final_synthesis_round(gateway, base_request, messages, request_id)
            return _build_loop_final(final_resp, messages, calls_used, collected_sources)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_SYNTHESIS_DIRECTIVE = (
    "Tool access is now disabled for this turn (the per-turn tool-call limit "
    "was reached). Do not request any further tools. Using only the "
    "information already gathered in the tool results above, write your "
    "complete final answer to the user's request now. If some information is "
    "missing, answer with what you have and note the gap explicitly."
)


async def _final_synthesis_round(
    gateway: Any,
    base_request: ChatCompletionRequest,
    messages: list[dict[str, Any]],
    request_id: str | None,
) -> Any:
    """Issue the final no-tools round with an explicit synthesis directive.

    Flipping tools off and re-sending the message list verbatim leaves the
    model mid-research with no instruction to stop and write — empirically it
    then returns empty content (the cap-hit "blank answer" bug: a turn that
    exhausts the tool-call cap mid-research persisted a zero-length assistant
    message). Appending an explicit synthesis directive makes the model
    compose its answer from what it has already gathered.

    The directive is appended to a COPY of ``messages`` so it is sent to the
    model for this round only and never leaks into the persisted turn history.
    """
    synth_messages = [*messages, {"role": "user", "content": _SYNTHESIS_DIRECTIVE}]
    return await gateway.chat_completion(
        _build_request(base_request, synth_messages, tools=None, tool_choice="none"),
        request_id=request_id,
    )


def _build_request(
    base: ChatCompletionRequest,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: str | None,
) -> ChatCompletionRequest:
    """Rebuild the request for each gateway round.

    Copies all fields from ``base`` but replaces ``messages``, ``tools``,
    and ``tool_choice``.  Uses ``model_copy`` (Pydantic v2) so LQ.AI
    extension fields (skill refs, anonymize, etc.) are preserved.
    """
    # Reconstruct the message objects from dicts
    msg_objects = [
        ChatCompletionMessage(**m) if not isinstance(m, ChatCompletionMessage) else m
        for m in messages
    ]
    return base.model_copy(
        update={
            "messages": msg_objects,
            "tools": tools,
            "tool_choice": tool_choice,
            "stream": False,
        }
    )


def _build_loop_final(
    resp: Any,
    messages: list[dict[str, Any]],
    calls_used: int,
    tool_sources: list[ToolSourceRecord] | None = None,
) -> LoopFinal:
    """Build a :class:`LoopFinal` from a gateway response."""
    choice = resp.choices[0]
    usage = resp.usage
    return LoopFinal(
        text=choice.message.content or "",
        usage_prompt=usage.prompt_tokens if usage else 0,
        usage_completion=usage.completion_tokens if usage else 0,
        tier=resp.routed_inference_tier,
        provider=resp.routed_provider,
        model=resp.model,
        applied_skills=resp.lq_ai_applied_skills,
        messages=messages,
        calls_used=calls_used,
        tool_sources=tool_sources or [],
    )
