# Mini-PRD: Legal Research Sources + MCP Client — gateway-brokered, governed, operator-controlled

> **Status:** Architecture pinned — decisions promoted to [ADR 0014](../adr/0014-gateway-egress-boundary-for-tool-providers.md) (egress boundary) and [ADR 0015](../adr/0015-governed-tool-calling-model.md) (governed tool-calling). Open for contribution.
> **Effort:** L (a milestone, split into ~6 PRs across two architectural cores and two features).
> **Contributor profile:** Backend engineer comfortable in the `gateway/` security boundary and `api/` (FastAPI + httpx + LangGraph). MCP familiarity helpful. The two ADR-level pieces want a contributor who has read [PRD §1.8](../PRD.md#18-security-posture) and the autonomous-layer ADR ([0013](../adr/0013-autonomous-layer-design-influences.md)).
> **Mentor:** Maintainer (via PR review); security review required (`gateway/**`).

## What this is

Bring **case-law research** (CourtListener) and an **MCP client** to LQ.AI with feature parity to the work product a lawyer gets in [MikeOSS](https://github.com/willchen96/mike) — but re-seated on LQ.AI's boundaries rather than copied in MikeOSS's implementation style.

Both capabilities already have committed-but-deferred slots:

- **MCP client** — [DE-200](../PRD.md#de-200) / [PRD §8.5](../PRD.md#85-mcp-client-subsystem). Today only a stub exists (`web/backend/open_webui/utils/mcp/client.py`), not wired into the FastAPI backend.
- **Legal research sources** — [PRD §3.6 Research](../PRD.md#36-research) and [DE-279–281](../PRD.md#de-279). No routes, migrations, or handlers exist yet.

This mini-PRD frames them as one coherent work package because they share the same three new substrates: a gateway egress class, a governed tool-calling loop, and external-source citation provenance.

## The parity target (what MikeOSS ships)

Both features landed in MikeOSS in early–mid June 2026.

**CourtListener** (`backend/src/lib/courtlistener.ts`, `lib/legalSourcesTools/courtlistenerTools.ts`) — five model-callable tools:

| Tool | Purpose |
|---|---|
| `courtlistener_verify_citations` | Reporter citations (`467 U.S. 837`) → cluster IDs + metadata |
| `courtlistener_search_case_law` | Full-text discovery (counts only) |
| `courtlistener_get_cases` | Fetch/cache cluster metadata + opinions by cluster ID |
| `courtlistener_find_in_case` | Keyword search within a fetched opinion (≤3/turn) |
| `courtlistener_read_case` | Read selected opinion text from a fetched cluster |

Optional **bulk-data caching** (opinions in object storage under `courtlistener/opinions/by-cluster/`, metadata in the DB) with live-API fallback; per-turn cluster cache; feature-flagged system-prompt splice; SSE events driving a UI case-law panel; configured via `COURTLISTENER_API_TOKEN`.

**MCP client** (`backend/src/lib/mcp/*`, `lib/mcpConnectors.ts`):

- Transport: **`streamable_http` only** (no stdio)
- **Per-user** connectors in the DB, auth config encrypted (`aes-256-gcm`)
- Auth: `none | bearer | oauth` (full OAuth callback flow, encrypted token rows)
- Tool discovery + cache, per-tool enable/disable, metadata flags `readOnly`/`destructive`/`requiresConfirmation`
- SSRF hardening: HTTPS-required, DNS private-address blocking, `guardedFetch`, header validation, no `Host` override
- Tools surfaced to the model `mcp_`-prefixed; `executeMcpToolCall()` routes invocations

The defining architectural fact: **MikeOSS gives the model an open, per-user function-calling surface that egresses directly from the backend.** That implementation style contradicts three LQ.AI postures — gateway-as-sole-egress, closed bounded tool intents, and operator-controlled credentials. Parity on *capability* is the goal; parity on *implementation* is explicitly not.

## Decisions (pinned with the maintainer → ADRs)

These three forks were put to the maintainer with recommendations and confirmed; they are now promoted to ADRs.

1. **Egress boundary → extend the gateway.** ([ADR 0014](../adr/0014-gateway-egress-boundary-for-tool-providers.md)) CourtListener and every MCP server become a new gateway **"tool provider" / data-source** class alongside inference providers — configured in `gateway.yaml`, tier-tagged, rate-limited (per-provider, at the adapter — see correction C3), SSRF/allowlist-guarded, and written to a `tool_egress_log`. The gateway remains the single audited boundary; the backend never calls a third-party tool endpoint directly. *(Rejected: a separate broker service; backend-direct + guards.)*

2. **Chat tool-calling → governed hybrid loop.** ([ADR 0015](../adr/0015-governed-tool-calling-model.md)) A gateway-mediated function-calling loop restricted to an **operator-enabled allowlist** of research/MCP tools. Every call is tier-checked, audited (new `tool_call_log`), confirmation-gated when a tool is `destructive`, and rendered with provenance pills. The *same* tools are exposed to the [autonomous layer](../adr/0013-autonomous-layer-design-influences.md) as new bounded `ToolIntent`s (`retrieve_caselaw`, `call_mcp_tool`) under the existing `PHASE_GRANTS` + R5→R6→R4 brakes. *(Rejected: closed-intents-only; open function-calling.)*

3. **Connector ownership → operator-allowlisted.** MCP servers are declared in an operator-controlled `mcp.yaml` (mirroring `gateway.yaml.example`), with per-user OAuth **only** where a server needs user identity. Egress destinations stay under operator control and auditable. *(Rejected: per-user connectors; both.)*

## Code-grounded corrections (verified 2026-06-16 against `main`)

The original proposal was checked against the codebase before this plan. Five findings change the work:

- **C1 — Research is PRD §3.6, not §3.8.** §3.8 is "Multi-Model Ensemble Verification" (the citation engine's final stage). All research references point to §3.6. (Corrected throughout this doc.)
- **C2 — Brake order is R5→R6→R4** (temporal/halt → contextual/phase-grant → economic/cost), not "R4/R5/R6." `guarded_tool_call` (`api/app/autonomous/guard.py`) checks halt first. WS4 wording follows the real order.
- **C3 — Gateway rate-limit *enforcement* is not wired.** `RateLimitsConfig` (`gateway/app/config.py`) loads, but enforcement middleware is deferred to the gateway's "Phase E." WS1 does **not** reuse rate-limit enforcement — it ships **per-provider rate limiting at the tool-provider adapter**, independent of the unbuilt global middleware.
- **C4 — No "source-kind" abstraction exists.** The citation engine (`api/app/citation/verification.py`) assumes documents with char-precise offsets (`source_document_id`, `source_offset_start/end`). External-source citations (court / cluster ID / opinion ID / `retrieved_at`) are **net-new modeling** in WS5, not a field extension — larger than the original proposal implied.
- **C5 — Skills frontmatter is declared but not parsed.** `minimum_inference_tier` appears in some SKILL.md frontmatter (e.g. `skills/nda-snapshot/`) but **no parser/validator loads it in code**. WS5's "skill declares its tool usage" needs the parser built first (or scoped to documentation-only in v1 — see WS5).

Also confirmed solid (build directly on these): gateway `ProviderAdapter` + router + `inference_routing_log`; autonomous `ToolIntent`/`PHASE_GRANTS`/`guarded_tool_call`; citation cascade (exact→tolerant→paraphrase→ensemble); `api/app/storage.py` (MinIO/S3); `api/app/models/audit.py` (free-form string actions, **not** an enum — easy to add new actions); `api/app/api/admin.py` (prefix `/admin`, ActiveUser+AdminUser auth). The `web/` MCP stub is production-grade (streamable_http, 5 functions) — a real reference for the WS2 client. Migration head **0047**; `EXPECTED_PATHS` collision-guard count is **118** (`api/tests/test_openapi.py`).

## Why it matters

- **A real capability gap.** In-house legal teams need case-law verification and lookup inside the tool they already use; MCP opens the door to the operator's own systems. PRD §3.6 already commits the research capability.
- **The transparency posture is the differentiator.** MikeOSS's answer is a chat bubble. LQ.AI's answer must be *inspectable*: which opinion, which cluster, a quote verified against the fetched text, the routed tier, and an audit row. That is the whole reason to do this in LQ.AI's frame rather than fork MikeOSS.
- **The egress boundary is a security asset, not overhead.** Routing every external tool call through the gateway means one place to tier, rate-limit, anonymize, allowlist, and audit third-party data egress — exactly what an operator deploying this in a privileged environment needs.

## What we'd ship — six workstreams

WS1 and WS4 are the architectural cores (each ~an ADR + a milestone-sized change). WS2 and WS3 are sizable features that parallelize once WS1 lands. WS5/WS6 ride alongside.

### WS1 — Gateway egress boundary for data-source / tool providers (`gateway/`)

Discharges [ADR 0014](../adr/0014-gateway-egress-boundary-for-tool-providers.md). **Detailed design below.**

- New provider class in the gateway: a **"tool provider"** (a.k.a. data-source) distinct from inference providers, but reusing the existing router/audit machinery.
- `gateway.yaml`: a `tool_providers:` block (name, type, base_url, `api_key_env`/encrypted/admin-API key, tier, allowlist policy). CourtListener is the first concrete `type`.
- SSRF + allowlist controls live here as a gateway primitive: HTTPS-required, DNS private-address blocking, host allowlist, no `Host` override, header validation.
- New **egress audit log** (`tool_egress_log`): timestamp, provider, tool, request_id, tier, bytes/row counts (never raw payloads), refused + reason. Mirrors `inference_routing_log`.
- Per-provider rate limiting **at the adapter** (C3), not via the unbuilt global middleware.
- Egress tier semantics (ADR 0014 D4): a tool provider declares a **data-egress tier** so the gateway can refuse a call whose payload sensitivity exceeds the matter/skill minimum.
- Anonymization of outbound payloads by default; inbound public text marked `skip_anonymization` (ADR 0014 D5).

**Files:** `gateway/app/providers/tool/` (new subpackage), `gateway/app/router.py` (tool-egress path), `gateway.yaml.example`, `gateway/tests/`. **Security review required.**

### WS2 — MCP client subsystem (DE-200)

- `streamable_http` transport client (parity with MikeOSS — no stdio). Lives behind WS1's egress boundary: the gateway brokers the outbound MCP HTTP. Port the proven `web/` stub logic into `api/`.
- Operator config `mcp.yaml` (allowlisted servers: name, server_url, auth type, tier, tool policy). Loaded like `gateway.yaml`.
- Tool discovery + cache (DB-backed), per-tool enable/disable, metadata flags `read_only`/`destructive`/`requires_confirmation` carried through to WS4's confirmation gates.
- Optional **per-user OAuth** only where a server needs user identity (encrypted token storage following the existing Fernet key-encryption pattern). Bearer/none otherwise.
- Admin surface `/api/v1/admin/mcp` to list/refresh connectors and tools. No per-user connector creation in v1 (decision 3).

**Files:** new `api/app/mcp/` (client, discovery, registry), `mcp.yaml.example`, `api/app/api/admin.py` additions, migration, `api/tests/`. Retire/replace the `web/` stub.

### WS3 — CourtListener data source (DE-279)

- The five tools as gateway tool-provider operations + thin `api/` handlers: `verify_citations`, `search_case_law`, `get_cases`, `find_in_case`, `read_case`.
- Opinion caching: object storage for opinion bodies + DB rows for cluster/opinion metadata, with live-API fallback. Per-turn cluster cache to avoid redundant fetches.
- Citation-verification integration (see WS5) so quoted passages are verified, not just pasted.
- `/api/v1/research/` surface for the interactive case-law panel; SSE events for UI parity.

**Files:** `gateway/app/providers/tool/courtlistener.py`, `api/app/research/`, `api/app/api/research.py` (NEW route — remember `IMPLEMENTED_ROUTES` in `api/tests/test_endpoints.py` + bump the pinned **118** path count + `EXPECTED_PATHS` in `api/tests/test_openapi.py`), migration, `docs/api/backend-openapi.yaml`.

### WS4 — Governed tool-calling loop + `ToolIntent` extension

Discharges [ADR 0015](../adr/0015-governed-tool-calling-model.md).

- A gateway-mediated function-calling loop for chat, **restricted to the operator allowlist** (research + enabled MCP tools). Not open function-calling.
- Per-call governance: tier check, `tool_call_log` audit row, cost accounting, **confirmation gate** for `destructive` tools (model proposes → user approves → execute). Per-turn tool-call cap.
- New bounded intents for the autonomous layer: `retrieve_caselaw`, `call_mcp_tool` added to `ToolIntent` (`api/app/autonomous/enums.py`) and to `PHASE_GRANTS` (research in `analysis`; MCP grants per-phase, conservative default), enforced by the existing `guarded_tool_call` **R5→R6→R4** brakes.
- `destructive`/`requires_confirmation` MCP tools are **never** auto-granted to the autonomous layer in v1.

**Files:** `api/app/autonomous/enums.py`, `api/app/autonomous/guard.py`, a chat tool-loop module in `api/app/`, `api/app/api/chats.py` (loop integration), migration (`tool_call_log`), tests.

### WS5 — Transparency surfaces

- **External-source citations (C4 — net-new modeling).** Add an external-source kind (court / cluster ID / opinion ID / `retrieved_at`) so case-law quotes run through the existing exact/tolerant verification cascade and persist provenance. A case-law answer becomes reproducible and trust-pilled, not a bare bubble.
- New `audit_log` actions (`research.search`, `research.read_opinion`, `mcp.tool_call`) — free-form strings, no enum change needed (C-confirmed).
- A **"Case-law research" skill** that *declares* its tool usage and `minimum_inference_tier` in SKILL.md frontmatter. **(C5)** v1 either builds the frontmatter parser/validator or scopes the declaration to documentation-only — pin in the WS5 plan.
- UI: case-law panel parity, MCP tool provenance pills, confirmation prompt for destructive tools.

**Files:** `api/app/citation/` (source-kind extension), `api/app/models/audit.py` (or just new action strings), `skills/case-law-research/`, `web/` panel + pills, `docs/db-schema.md`.

### WS6 — Docs

- PRD: flesh out §3.6 (research) and promote MCP from a §8.5 slot to a specified capability; update DE-200 / DE-279–281 to "in progress".
- **The two ADRs are already written** ([0014](../adr/0014-gateway-egress-boundary-for-tool-providers.md), [0015](../adr/0015-governed-tool-calling-model.md)) — flip Status to "Accepted" when the implementation lands.
- `gateway.yaml.example` (+ `tool_providers`), `mcp.yaml.example`, `docs/db-schema.md` migrations, `docs/api/backend-openapi.yaml` for `/research` + `/admin/mcp`.
- `docs/security/boundary-registers.md`: add the egress-boundary register entry.

## PR decomposition & sequencing (the roadmap)

Dependency spine: **WS1 must land first** (it is the boundary every tool call traverses). WS2 and WS3 parallelize once WS1 is in. WS4 needs WS1 (+ at least one tool provider to call). WS5/WS6 ride alongside their feature.

| PR | Workstream | Depends on | Security review | Acceptance criteria (the merge bar) |
|---|---|---|---|---|
| **PR1** | WS1 — gateway tool-provider boundary | — | **Yes** (`gateway/**`) | `tool_providers:` block parses from `gateway.yaml`; a `ToolProviderAdapter` base + a test/echo provider type; guarded-egress helper enforces HTTPS/DNS-private-block/host-allowlist/no-Host-override (unit-tested with attempted SSRF); `tool_egress_log` migration + rows written (counts only, never payloads); per-adapter rate limit; egress-tier refusal path tested. Gateway mypy `--strict` clean. |
| **PR2** | WS3a — CourtListener provider + read tools | PR1 | Yes (`gateway/**`) | `courtlistener` tool-provider type; `verify_citations` + `search_case_law` + `get_cases` against live API (gated `-m provider`) with VCR/cassette unit tests; opinion-body caching to `api/app/storage.py` under `courtlistener/opinions/by-cluster/` + DB metadata rows + live-API fallback; per-turn cluster cache. |
| **PR3** | WS3b — `/api/v1/research/` surface | PR2 | No (api/) | `POST /api/v1/research` + `GET /api/v1/research/sources` handlers (thin, call the gateway); `IMPLEMENTED_ROUTES` + `EXPECTED_PATHS` (118→) bumped; `find_in_case` + `read_case`; `backend-openapi.yaml` updated + conformance test green; SSE research events. |
| **PR4** | WS2 — MCP client subsystem | PR1 (parallel to PR2/3) | Partial (egress in gateway) | `mcp.yaml` parses; `streamable_http` client in `api/app/mcp/` brokered through the gateway egress boundary; tool discovery + DB cache + per-tool enable/disable + metadata flags; `none`/`bearer` auth; `/api/v1/admin/mcp` list/refresh; per-user OAuth **stub-or-ship** decision pinned; `web/` stub retired. |
| **PR5** | WS4 — governed tool-calling loop + ToolIntent | PR2 (a callable tool) + PR4 | **Yes** (touches autonomous guard) | Chat tool-loop over the operator allowlist with per-turn cap; `tool_call_log` migration + rows; tier check + cost accounting per call; `destructive` confirmation gate (SSE pause→approve→resume) tested; `retrieve_caselaw` + `call_mcp_tool` added to `ToolIntent` + `PHASE_GRANTS`, enforced by R5→R6→R4; destructive tools excluded from all autonomous phase grants (test). |
| **PR6** | WS5 — transparency surfaces + WS6 docs | PR3 + PR5 | No (api/ + web/ + docs) | External-source citation kind through the verification cascade with persisted provenance (C4); new audit actions; case-law-research skill (+ frontmatter parser **or** docs-only per C5 decision); UI case-law panel + provenance pills + destructive-confirm prompt; PRD §3.6/§8.5 + DE updates; ADR statuses → Accepted; `db-schema.md` + boundary-registers updated. |

Six PRs, security review on PR1/PR2/PR5. Each PR is independently shippable behind its feature flag (CourtListener off until `COURTLISTENER_API_TOKEN` set; MCP off until `mcp.yaml` declares a server; the chat loop off until a tool is enabled).

## WS1 detailed design (the first buildable slice)

WS1 is the load-bearing core; everything else calls it. Detailed below so PR1 can start without re-deriving shape. (PRs 2–6 get their own plans at their turn, per the maintainer's chosen planning depth.)

### Config shape — `gateway.yaml` `tool_providers:` block

A new top-level block parallel to `providers:`. Each entry:

```yaml
tool_providers:
  - name: courtlistener-prod        # operator-chosen id, referenced by tool routing
    type: courtlistener             # adapter family (first concrete type)
    base_url: https://www.courtlistener.com/api/rest/v4
    api_key_env: COURTLISTENER_API_TOKEN   # OR api_key_encrypted (Fernet, ADR 0011) OR runtime
    egress_tier: 4                  # data-egress tier (ADR 0014 D4): max matter-sensitivity allowed out
    allowlist:
      hosts: [www.courtlistener.com]   # outbound host allowlist (SSRF guard)
    rate_limit:
      requests_per_minute: 60       # per-provider, enforced at the adapter (C3)
    anonymize_outbound: true        # default true (ADR 0014 D5)
```

Reuses the three credential paths inference providers already have (`api_key_env` / `api_key_encrypted` / runtime admin API per ADR 0011 + #128). A new Pydantic config model `ToolProviderConfig` sits beside the inference provider config in `gateway/app/config.py`.

### `ToolProviderAdapter` base — sibling to `ProviderAdapter`, NOT a subclass

`ProviderAdapter` exposes `chat_completion` / `embeddings` — wrong surface for tools. The new base (`gateway/app/providers/tool/base.py`) exposes:

```python
class ToolProviderAdapter(ABC):
    async def list_tools(self) -> list[ToolSpec]: ...          # name, description, json-schema params, metadata flags
    async def invoke_tool(self, tool: str, args: dict, *, request_id: str) -> ToolResult: ...
    async def health_check(self) -> ProviderHealth: ...        # reuse the existing dataclass
    async def aclose(self) -> None: ...
```

`ToolResult` carries structured provenance (provider, tool, bytes/row counts, and — for read tools — the inbound text marked `skip_anonymization` so it reaches the citation engine verbatim). Typed errors reuse/mirror the existing `ProviderAdapterError` hierarchy (`ToolProviderAuthError`, `ToolProviderHTTPError`, `ToolProviderNetworkError`, `ToolEgressRefused`).

### Guarded egress helper — the SSRF primitive (ADR 0014 D2)

A single `guarded_egress(...)` in the gateway that every tool-provider adapter MUST route outbound HTTP through. Enforces, in order: scheme is HTTPS; resolve DNS and reject private/loopback/link-local/CGNAT ranges; host ∈ provider allowlist; reject caller-supplied `Host`; validate outbound headers (no smuggled auth). Returns a guarded `httpx.AsyncClient` request or raises `ToolEgressRefused(reason)`. This is the gateway-native equivalent of MikeOSS `validateRemoteMcpUrl`/`guardedFetch`. Unit tests attempt each bypass (private IP, IP-literal host, redirect-to-private, Host override) and assert refusal + an audit row.

### Router tool-egress path

`gateway/app/router.py` gains a `route_tool_call(provider_name, tool, args)` alongside the inference dispatch. It: resolves the `tool_providers` entry → builds/holds the adapter (same lazy-build pattern as inference adapters) → applies the per-provider rate limit → checks egress tier vs. the call's declared matter-sensitivity (refuse if exceeded) → applies outbound anonymization → calls `adapter.invoke_tool` → writes a `tool_egress_log` row → returns `ToolResult`. The inference router path is untouched.

### `tool_egress_log` — new table (migration 0048)

Mirrors `inference_routing_log` (`api/app/models/inference.py`). Columns: `id`, `timestamp`, `request_id`, `provider`, `tool`, `tier`, `bytes_out`, `bytes_in` (or `rows`), `refused` (bool), `refusal_reason` (nullable), `anonymization_applied` (bool). **No raw payloads** — counts and types only, the `inference_routing_log` guarantee. Migration sits at head 0048 (current head 0047); verify on a throwaway pgvector container, never host-side `alembic upgrade` on the dev DB. *(Note: this log is read/written from the gateway's egress decision; confirm in PR1 whether the row is written by the gateway directly or returned to the backend to persist — see ADR 0014 O3. Default: gateway writes it, same as `inference_routing_log` is written on the inference path.)*

### What WS1 explicitly does NOT do

No CourtListener semantics (PR2), no MCP (PR4), no chat loop or `ToolIntent` change (PR5), no citation modeling (PR6). PR1 ships the boundary + a trivial echo/test tool-provider type to prove the path end-to-end under test. This keeps the security-review surface tight: PR1 is "is the egress boundary sound?", nothing else.

## Open questions (resolve during WS1/WS5)

- **O1 — Anonymization of tool-call payloads.** *Resolved in [ADR 0014 D5](../adr/0014-gateway-egress-boundary-for-tool-providers.md):* anonymize outbound by default; mark inbound public opinion text `skip_anonymization` (mirrors retrieval-context handling). Rehydration into citations follows the document-citation path. Confirm the exact flag plumbing in PR1.
- **O2 — Object-storage layout for cached opinions.** Reuse `api/app/storage.py`; confirm key scheme `courtlistener/opinions/by-cluster/{cluster_id}/{opinion_id}` and retention policy in the PR2 plan (ADR 0005 sibling).
- **O3 — Bulk data import.** v1 ships live-API + per-turn/object-cache and defers CourtListener bulk import to a DE if operators want it.
- **O4 — `tool_egress_log` write site.** Gateway-writes (default, mirrors inference) vs. backend-persists from a returned provenance struct. Pin in PR1.
- **O5 — Frontmatter parser scope (C5).** WS5: build the `minimum_inference_tier` parser/validator, or ship the case-law-research skill's declaration as documentation-only in v1. Pin in PR6 plan.

## Out of scope (file as DE-XXX if they surface)

- stdio MCP transport (parity is `streamable_http` only).
- Per-user MCP connector registration (decision 3 — operator-allowlisted in v1).
- Async approval channel for autonomous-layer destructive tools (ADR 0015 D4 — excluded in v1).
- Non-US legal sources (GovInfo, EUR-Lex, SEC EDGAR — DE-280/281); the tool-provider class is built to host them next.
- Open model-driven function-calling beyond the operator allowlist.
- Global gateway rate-limit enforcement middleware (the gateway's "Phase E" — C3); WS1 ships per-adapter limiting instead.
