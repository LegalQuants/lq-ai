# PR5a — Tool-governance substrate + autonomous tool intents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the shared per-call tool-governance substrate (`tool_call_log` + a `governed_tool_invocation` helper doing tier-check → audit → OTel) and add the two bounded autonomous `ToolIntent`s (`retrieve_caselaw`, `call_mcp_tool`) under the existing R5→R6→R4 brakes — the foundation PR5b's chat tool-loop builds on.

**Architecture:** One governance path for chat AND the autonomous layer. A new `governed_tool_invocation` helper writes the `tool_call_log` row, does the per-call egress-tier check, opens/annotates the `*.tool_call` OTel span, runs the caller-supplied dispatch closure, and records cost/outcome — flush-not-commit. The autonomous chokepoint `guarded_tool_call` keeps its R5→R6→R4 brakes + session audit and **delegates** the tier/audit/dispatch primitives to this helper. The two new intents dispatch to the already-built research service (`retrieve_caselaw`) and `GatewayClient.call_tool` (`call_mcp_tool`); destructive/confirmation-required MCP tools are refused for the autonomous layer (ADR 0015 D4).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, OpenTelemetry (`app.observability_helpers`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-18-pr5-governed-chat-tool-loop-design.md` (§PR5a). **ADR:** 0015 (D2/D3/D4/D5).

## Global Constraints
- **Brake order is R5 (temporal/halt) → R6 (contextual/phase-grant) → R4 (economic/cost).** `guarded_tool_call` (`api/app/autonomous/guard.py`) already implements this; do not reorder.
- **Counts/types only in `tool_call_log` — never raw payloads.** Args are summarized to a digest; tool results are never written to the audit row (mirrors `tool_egress_log`).
- **Cost is estimated ONCE per call.** `guarded_tool_call` computes the estimate for the R4 cap check and passes it to the helper; the helper never re-estimates (no double-charge / no divergence — preserve the existing comment at `guard.py:213-217`).
- **Flush-not-commit.** Neither the helper nor `guarded_tool_call` commits — the executor (autonomous) / the chat handler (PR5b) owns the commit boundary.
- **ADR 0015 D4:** a tool whose cached metadata is `destructive` or `requires_confirmation` is NEVER fired by the autonomous layer in v1.
- ruff pinned **0.15.17** (`ruff format` + `ruff check`); `mypy app` clean (api standard mode). Tests: host venv + throwaway pgvector :15433 (`DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest …`); NEVER `alembic upgrade` the dev DB on :15432.
- Commit `-s` + the trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`; stage explicitly, never `git add -A`.
- **Migration head is 0052** (PR4d); this PR's migration is **0053**.
- **Gate:** touches `api/app/autonomous/guard.py` (the autonomous guard) → **security review (Kevin merges).**

## Locked design decisions
- **D-a1 — span ownership:** `guarded_tool_call` keeps owning the `autonomous.tool_call` span (it must cover the R-brake outcomes that fire before dispatch). The helper is span-agnostic: it accepts an optional span and records `tool`-level attributes on it; it does NOT open its own span. PR5b's chat loop opens a `chat.tool_call` span and passes it in.
- **D-a2 — tier check:** the helper does an explicit api-side pre-check: `if max_allowed_tier is not None and provider_tier > max_allowed_tier → refuse`. The caller resolves `provider_tier` from the gateway admin config via a new cached `resolve_provider_tier(provider)`. The gateway still enforces the ceiling on the actual call (defense in depth).
- **D-a3 — cost of the new intents:** `retrieve_caselaw` and `call_mcp_tool` burn no provider-inference tokens, so `estimate_tool_cost` returns `Decimal("0")` for them in v1 (same treatment as local intents). A per-provider external-tool cost model is a deferred enhancement (file **DE-344**). R4 therefore does not brake on these in v1; the autonomous session cost cap still bounds inference, and PR5b's per-turn cap bounds chat.
- **D-a4 — `call_mcp_tool` grant:** granted in the `analysis` phase only (conservative). The `call_mcp_tool` dispatch handler enforces D4 per-tool: it loads the cached `mcp_tools` row and **refuses** (raises `ToolNotGranted`) any tool whose `destructive` or `requires_confirmation` is true. `retrieve_caselaw` is granted in `analysis`.
- **D-a5 — autonomous MCP token:** in v1 the autonomous layer has no interactive user to drive OAuth, so the `call_mcp_tool` handler passes `user_token=None`; an `auth: oauth` MCP server therefore raises `MCPAuthorizationRequired` from the gateway adapter (correct — autonomous cannot use per-user-OAuth servers). Only `none`/`bearer` MCP servers are autonomously callable. Documented; not a blocker.

## File structure
| File | Responsibility |
|---|---|
| `api/app/models/tool_call_log.py` (create) | `ToolCallLog` ORM model |
| `api/app/models/__init__.py` (modify) | register it |
| `api/alembic/versions/0053_tool_call_log.py` (create) | the table |
| `api/app/tools/governance.py` (create) | `governed_tool_invocation` helper + `ToolTierRefused` + `resolve_provider_tier` + the `tool_call_log` writer |
| `api/app/autonomous/enums.py` (modify) | add `retrieve_caselaw`, `call_mcp_tool` to `ToolIntent` + `PHASE_GRANTS` |
| `api/app/autonomous/cost.py` (modify) | cost estimators (Decimal 0) for the two intents |
| `api/app/autonomous/guard.py` (modify) | `guarded_tool_call` delegates tier/audit/dispatch to the helper; `_dispatch` handlers for the two intents (with D4 exclusion) |
| `api/app/errors.py` (modify) | `ToolTierRefused` (if modeled as LQAIError) — or define in governance.py per the codebase idiom |
| tests | model/migration, helper, enums/cost, guard integration |

---

## Task 1: `tool_call_log` table + model

**Files:** `api/app/models/tool_call_log.py`, `api/app/models/__init__.py`, `api/alembic/versions/0053_tool_call_log.py`, `api/tests/test_tool_call_log_model.py`

Mirror `tool_egress_log` (migration `0048_tool_egress_log.py`) for the migration style and the "counts/types only" discipline, and `api/app/models/mcp.py` for the ORM model style.

**Table `tool_call_log`** (counts/types only — never raw args or results):
```
id                 uuid    PK   (server_default gen_random_uuid() or app-set, match existing uuid PK pattern)
origin             text    NOT NULL          -- "chat" | "autonomous"
user_id            uuid    NULL  FK users.id ON DELETE CASCADE  (name fk_tool_call_log_user)
chat_id            uuid    NULL              -- set for chat-origin
message_id         uuid    NULL
session_id         uuid    NULL              -- set for autonomous-origin
intent             text    NULL              -- ToolIntent value (autonomous) or NULL (chat-origin marker)
provider           text    NOT NULL
tool               text    NOT NULL
tier               int     NOT NULL
confirmation_state text    NOT NULL default 'not_required'  -- not_required|pending_confirmation|approved|denied
outcome            text    NOT NULL          -- pending|executed|refused_tier|error|denied
cost_usd           numeric(12,6)  NULL       -- serialize as JSON string (Decimal)
args_digest        text    NULL              -- a short hash/summary, NEVER raw args
request_id         text    NULL
created_at         timestamptz NOT NULL default now()
updated_at         timestamptz NOT NULL default now()   -- app-bumped
```

- [ ] Model `ToolCallLog` (`Mapped[...]`, the FK with `ondelete="CASCADE", name="fk_tool_call_log_user"`); register in `__init__.py` (`__all__` + import). Decimal column typed for string JSON serialization (see CLAUDE.md: cost fields serialize as JSON strings).
- [ ] Migration 0053 (`revision="0053"`, `down_revision="0052"`); `op.create_table` + the users FK; `downgrade()` drops it. Confirm `alembic history` linear 0053→0052.
- [ ] Test: table + columns + PK + the users-FK CASCADE (insert user + row, delete user, assert row gone) — mirror the PR4c `test_mcp_oauth_models.py` cascade test. **Commit.**

## Task 2: the `governed_tool_invocation` helper

**Files:** `api/app/tools/governance.py`, `api/app/tools/__init__.py` (create the package), `api/tests/test_tool_governance.py`

**Produces (the interface PR5b + Task 4 consume):**
```python
class ToolTierRefused(LQAIError):  # or a module exception; map to 403-ish. code "tool_tier_refused"
    def __init__(self, *, provider: str, tool: str, tier: int, ceiling: int) -> None: ...

async def resolve_provider_tier(provider: str, *, request_id: str | None = None) -> int:
    """The provider's egress_tier from the gateway admin config (process-cached).
    Reads get_admin_config(); returns the tool_providers entry's egress_tier
    (default to the most-restrictive tier if absent — fail safe)."""

async def governed_tool_invocation(
    db: AsyncSession,
    *,
    origin: str,                      # "chat" | "autonomous"
    provider: str,
    tool: str,
    intent: ToolIntent | None,
    provider_tier: int,
    max_allowed_tier: int | None,
    estimated_cost: Decimal,
    dispatch: Callable[[], Awaitable[ToolResult]],
    span: Any | None = None,          # optional OTel span to annotate (D-a1)
    confirmation_state: str = "not_required",
    user_id: UUID | None = None,
    chat_id: UUID | None = None,
    message_id: UUID | None = None,
    session_id: UUID | None = None,
    request_id: str | None = None,
    args_digest: str | None = None,
) -> ToolResult:
    """Shared per-call governance: tier-check → tool_call_log row → dispatch → record.
    Flush-not-commit. Raises ToolTierRefused before dispatch if the ceiling is exceeded."""
```

Behavior:
1. **Tier check:** if `max_allowed_tier is not None and provider_tier > max_allowed_tier` → write a `tool_call_log` row `outcome="refused_tier"`, annotate `span` (`tool_call.outcome="refused_tier"`, counts/types only), raise `ToolTierRefused`.
2. Write a `tool_call_log` row `outcome="pending"` (carrying origin/provider/tool/tier/intent/cost=estimated_cost/confirmation_state/ids/args_digest); `await db.flush()`.
3. `try: result = await dispatch()` — on exception: update the row `outcome="error"`, annotate span, flush, re-raise.
4. Update the row `outcome="executed"`, `cost_usd=result.cost_usd`, bump `updated_at`; annotate span (`tool_call.cost_usd`, `tool_call.outcome`); flush; return `result`.

- [ ] TDD: failing tests using a **fake dispatch** returning a `ToolResult` and a fake `db` (or the real test DB): tier-refusal writes a refused_tier row + raises (no dispatch called); happy path writes pending→executed with the cost; a dispatch that raises writes an error row + re-raises; **no raw args/results in any row** (assert the row fields contain only the digest/counts); span annotations are counts/types only. `resolve_provider_tier` returns the configured tier (respx/mock the gateway config) and the fail-safe default when absent.
- [ ] Implement; gates (pytest, ruff, mypy). **Commit.** (This is the security-critical shared substrate — it will get focused review.)

## Task 3: the two `ToolIntent`s + grants + cost

**Files:** `api/app/autonomous/enums.py`, `api/app/autonomous/cost.py`, `api/tests/test_autonomous_enums.py` (+ extend `test` for cost)

- [ ] `ToolIntent`: add `retrieve_caselaw = "retrieve_caselaw"` and `call_mcp_tool = "call_mcp_tool"`.
- [ ] `PHASE_GRANTS`: add `retrieve_caselaw` AND `call_mcp_tool` to `Phase.analysis`'s frozenset (D-a4). No other phase grants them.
- [ ] `cost.py`: the two new intents return `Decimal("0")` (D-a3) — extend the docstring; they are NOT in `_INFERENCE_INTENTS`. (Current code already returns 0 for non-inference intents, so this may be a no-op + a doc update + a test — verify and add the explicit tests.)
- [ ] Tests: the two intents exist; `retrieve_caselaw`/`call_mcp_tool` ∈ `PHASE_GRANTS[Phase.analysis]` and ∉ every other phase; `estimate_tool_cost` returns 0 for both. **Commit.**

## Task 4: `guarded_tool_call` refactor + dispatch handlers (the integration heart)

**Files:** `api/app/autonomous/guard.py`, `api/tests/test_autonomous_guard_tool_intents.py`

### 4a — route the EXTERNAL-tool intents through the helper
- [ ] In `guarded_tool_call`, keep R5/R6/R4 + the `autonomous.tool_call` span + `autonomous_audit` exactly as-is. The change is only at the dispatch line (guard.py:237): **for the external-tool intents (`retrieve_caselaw`, `call_mcp_tool`)**, route the dispatch through `governed_tool_invocation` (so they get a `tool_call_log` row + the tier check + span annotation); **for all existing intents (`run_skill`, `run_playbook`, `retrieve_chunks`, and the local writes), dispatch exactly as today** via `_dispatch(...)` — they are not external tool calls and stay on `autonomous_audit` only (no `tool_call_log` noise). `tool_call_log` is the external-tool audit; the autonomous session event log (`autonomous_audit`) is unchanged for every intent.
  - For the routed intents: resolve `provider`/`tool` (4b) + `provider_tier` (`resolve_provider_tier`), pass the existing `estimate` as `estimated_cost` (single-estimate invariant — do NOT re-estimate in the helper), `span=span`, `origin="autonomous"`, `session_id=session.id`, `intent=intent`, `max_allowed_tier=<session ceiling or None>`, and a `dispatch` closure that calls the existing per-intent handler. The helper writes the `tool_call_log` row; `autonomous_audit` still records the session "tool_call" event as today.

### 4b — dispatch handlers for the two intents (in `_dispatch`)
- [ ] `retrieve_caselaw`: call the research service (`app.research.service`) — map params (e.g. `{op, ...}`) to `verify_citations`/`search_case_law`/`get_cluster`/`read_opinion`/`find_in_case`; return a `ToolResult(outcome="ok", cost_usd=Decimal("0"), ...)` (match the existing `ToolResult` shape used by other handlers). provider marker = the configured courtlistener provider name.
- [ ] `call_mcp_tool`: params carry `{provider, tool, args}`. **D4 enforcement:** load the cached `mcp_tools` row for `(provider, tool)`; if it is missing OR `destructive` OR `requires_confirmation` → raise `ToolNotGranted` (the autonomous layer cannot fire a human-gated/unknown tool). Else call `GatewayClient.call_tool(provider, tool, args, max_allowed_tier=…, request_id=…)` with `user_token=None` (D-a5) and return a `ToolResult`. (If the gateway raises `MCPAuthorizationRequired` for an oauth server, let it propagate — autonomous can't use per-user OAuth servers.)

### 4c — tests
- [ ] `retrieve_caselaw` granted in `analysis` executes (mock the research service) and writes a `tool_call_log` row; refused (R6 `ToolNotGranted`) in `intake`/`drafting`/etc.
- [ ] `call_mcp_tool` in `analysis` with a cached **read_only** tool executes (mock `call_tool`) + writes a row; with a **destructive** cached tool → `ToolNotGranted` (D4) — and NO gateway call made; with `requires_confirmation` → `ToolNotGranted`; unknown tool → `ToolNotGranted`.
- [ ] the existing `guarded_tool_call` brake tests (R5 halt, R6 grant, R4 cap) still pass after the refactor; a `tool_call_log` row is written for an existing intent (e.g. `retrieve_chunks`) too.
- [ ] **Commit.**

## Task 5: full gates + DE + ship

- [ ] File **DE-344** (per-provider external-tool cost model; v1 estimates 0 for `retrieve_caselaw`/`call_mcp_tool`) in PRD §9.
- [ ] Full api suite (`pytest -q`), `ruff format --check` + `ruff check`, `mypy app`. Final holistic review focused on: single-estimate invariant preserved; no raw args/results in `tool_call_log`; the brakes unchanged; D4 destructive-exclusion airtight (no gateway call for a destructive tool); flush-not-commit preserved. Push both remotes; PR vs `main`; CI; **Kevin reviews/merges** (autonomous guard). Report the squash SHA.

## Definition of done (PR5a)
- `tool_call_log` (migration 0053) records every governed tool call (chat + autonomous), counts/types only.
- `governed_tool_invocation` is the shared tier→audit→dispatch substrate; `guarded_tool_call` delegates to it without changing R5→R6→R4 or the single-estimate discipline.
- `retrieve_caselaw` + `call_mcp_tool` exist, granted only in `analysis`, dispatch to the research service / `call_tool`; destructive/confirmation-required MCP tools are refused for the autonomous layer (D4), proven by test.
- Full api + gates green. **Gate:** security review.

## Self-review notes (coverage vs spec §PR5a)
- tool_call_log ✓ (Task 1) · shared helper w/ tier+audit+OTel ✓ (Task 2) · guarded_tool_call delegates ✓ (Task 4a) · 2 intents + grants + cost ✓ (Task 3) · destructive-exclusion D4 ✓ (Task 4b/c) · OTel span D5 ✓ (D-a1 + helper annotations). Deferred per spec: chat loop + confirmation gate + gateway tools-passthrough + connect-on-demand = **PR5b**; external-source citations/pills/UI = PR6; per-provider tool-cost = DE-344.
