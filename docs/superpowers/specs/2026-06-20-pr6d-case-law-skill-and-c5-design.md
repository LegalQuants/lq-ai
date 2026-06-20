# PR6d — Case-law-research skill + C5 tool-usage (declare & surface) + milestone honesty pass — Design Spec

> **Milestone:** Legal research + MCP (WS5 / PR6). **Slice:** 6d (after 6c external-source citations; the last *capability* PR of the milestone). DE-341 stub retirement is split out to **6e**; the release gate follows 6e.
> **Date:** 2026-06-20. **Branch:** `feat/pr6d-case-law-skill` off `main` (`13a5f9e`).

## Goal

Ship the `case-law-research` skill — the user-facing capability the whole legal-research+MCP milestone was building toward — make a skill's declared tool usage **load-bearing but non-gating** (the C5 "declare & surface" decision), and run the milestone's final D6 honesty pass so the narrative is true at the close of PR6 (including filing DE-350 and fixing a dangling DE reference).

## Decisions locked in brainstorming (2026-06-20)

1. **C5 = declare + surface (non-gating), not docs-only and not gating.** A skill declares the connectors it uses in frontmatter; the backend parses that, checks it against the operator's actually-configured connectors, and **surfaces** any mismatch — but never blocks the skill from loading, listing, or running. Chosen over docs-only because a declaration nothing checks is decorative (weak on the transparency/operator-control principles); chosen over execution-gating because gating is over-scoped for the last PR before the release gate and raises its own design questions (skill available but tool briefly down?).
2. **The case-law-research skill is procedural, not substantive → self-merge.** It asserts *method* (how to drive the CourtListener tools and cite what they return), not legal positions. No practicing-attorney attestation required; 6d self-merges after CI like the other WS5 PRs. **Escalation rule:** if review finds substantive legal assertions in the skill body, stop and route to the CLAUDE.md attestation path.
3. **Scope split: 6d = skill + C5 + honesty pass; DE-341 stub retirement → 6e.** The DE-341 OpenWebUI-`MCPClient` retirement is a behavioral `web/backend/` migration; isolating it in its own small PR keeps the release-gate bring-up clean (a regression in the old MCP path can't muddy the milestone close).

## Non-goals (explicit scope guard)

- **No execution-gating** on tool availability. The `tool_usage` check is informational only; skills always load/list/run.
- **No DE-341 stub retirement** here (→ 6e). No edits to `web/backend/open_webui/utils/mcp/client.py`, `routers/configs.py`, or `utils/middleware.py`.
- **No generic-MCP provenance** (that's DE-350, deferred — this PR only *files* it).
- **No new skill-execution behavior** — `tool_usage` does not change routing, tier, or tool-loop dispatch.
- **No `minimum_inference_tier` enforcement** (still declared-not-enforced; unchanged).
- The skill ships **US case law via CourtListener only**; it is not a citator/Shepardizing substitute (stated in the skill body, not built).

## Architecture

```
skills/case-law-research/SKILL.md   (frontmatter: tool_usage: [courtlistener])
        │  loaded by
        ▼
api/app/skills/loader.py → schema.py (LQAIFrontmatter.tool_usage parsed)
        │                         │ derive_summary → SkillSummary.tool_usage
        ▼                         ▼
GET /api/v1/skills/{name}  ──►  resolve_available_connectors()  (gateway caps ∪ mcp servers)
        │                         │  → unavailable_tool_usage (declared − available)
        ▼                         ▼  (null if availability undeterminable)
web SkillDetail UI: "Uses: CourtListener" + non-blocking "⚠ not configured" note
```

Provider-availability is computed at **skill-detail request time** (not skill-load), so it reflects the operator's *current* config, reusing already-cached gateway capabilities; it degrades to "unknown" rather than false-negative when the gateway is unreachable.

## Component 1 — the `case-law-research` skill

**Files:** `skills/case-law-research/SKILL.md`, `skills/case-law-research/examples/<one-worked-example>.md` (+ optional `skills/case-law-research/reference/`).

- **Layout** follows the existing skills (`skills/nda-review/` pattern): `SKILL.md` with `lq_ai` frontmatter + an `examples/` worked example.
- **Frontmatter** (`lq_ai` block): `title`, `version: 1.0.0`, `author`, `tags` (≥ discovery set), `jurisdiction: us`, `trigger_examples` (≥3), `inputs` (e.g. an optional research question / jurisdiction scope), `output_format: report`, `use_organization_profile: true`, **and the new `tool_usage: [courtlistener]`**.
- **Body — procedural methodology only:**
  - The CourtListener tool chain the gateway exposes: `search_case_law` → `get_cluster` → `read_opinion` / `find_in_case`.
  - Grounding: cite only what the tools returned; the 6c "Sources consulted" provenance panel makes that visible to the user.
  - Honesty: state what was searched and what was *not* found; do not infer holdings not present in retrieved text.
  - Scope limits (explicit): US case law via CourtListener; **not** a substitute for a citator / Shepardizing / validation.
- **Worked example:** a research question → the tool calls made → a cited answer with the provenance trail.
- **Procedural-framing review gate:** the spec/code review confirms the body asserts method, not substantive legal positions. If it drifts substantive → escalate to attestation (per decision 2).

## Component 2 — C5: `tool_usage` declare & surface

### Parse (`api/app/skills/schema.py`)

- Add `tool_usage: list[str] | None = None` to `LQAIFrontmatter` (the `extra="allow"` config already tolerates it on older skills; we make it first-class).
- Carry it into `SkillSummary` via `derive_summary` (so the API echoes it).
- A skill with no `tool_usage` behaves exactly as today (field is `None`/absent).

### Check (`api/app/skills/connectors.py` — new, or a helper in the skills service)

- `async def resolve_available_connectors(...) -> set[str] | None` — the set of connector identifiers the operator has wired:
  - CourtListener: from the gateway research capabilities (`app/research/service.get_capabilities` / the cached resolved provider) → include `"courtlistener"` when enabled.
  - MCP servers: from `app/mcp` `list_servers()` → each server name.
  - Returns `None` when availability cannot be determined (gateway unreachable / capabilities error) — the caller treats `None` as "unknown," not "all missing."
- `def unavailable_tool_usage(declared: list[str] | None, available: set[str] | None) -> list[str] | None` — pure:
  - `declared` empty/None → `[]`.
  - `available` is `None` → `None` (undeterminable).
  - else → the declared entries not in `available` (case-insensitive match on connector id).

### Surface (`api/app/api/skills.py` — skill-detail endpoint)

- `GET /api/v1/skills/{name}` response gains:
  - `tool_usage: list[str] | null` (echoed from frontmatter).
  - `unavailable_tool_usage: list[str] | null` (computed; `null` = undeterminable, `[]` = all available, non-empty = the declared-but-unconfigured connectors).
- Computed **only on skill-detail**, not the list endpoint (keeps listing light + dependency-free).
- **Never gating:** the endpoint still returns the full skill regardless; these fields are informational. Failure to resolve availability must not fail the request (degrade to `null`).
- OpenAPI: update the skill-detail response schema in `docs/api/backend-openapi.yaml`; honor the collision guards if the path set changes (it does **not** — same path, new response fields).

### UI (`web/` skill-detail surface, e.g. `SkillDetailTabs.svelte`)

- Show "Uses: CourtListener" when `tool_usage` is non-empty.
- When `unavailable_tool_usage` is non-empty: a **non-blocking** warning note — "⚠ {connector} isn't configured in this deployment — ask your operator to enable it." Nothing is disabled.
- When `unavailable_tool_usage` is `null`: show the "Uses:" line without a verdict (availability unknown).
- New `tool_usage`/`unavailable_tool_usage` fields added to the `web` skill type mirroring the API.

### Tests

- Schema: `LQAIFrontmatter` parses `tool_usage`; absent → `None`.
- Resolver: all-declared-available → `[]`; a declared-missing connector → listed; gateway-unreachable → `None`. `unavailable_tool_usage` pure-function table.
- API: skill-detail includes both fields; a skill with no `tool_usage` returns `null`/absent; availability-resolution failure degrades to `null` (request still 200).
- Web: skill type carries the fields; the detail UI's note logic (a small testable helper for the three states) — follow the house module-helper test pattern (no `@testing-library/svelte`).

## Component 3 — D6 milestone honesty pass

**Files:** `docs/PRD.md` (§9 DEs, §3.6 research spec), the 6c spec doc, `web/static/learn/playgrounds/governed-tool-flow.html`, `web/src/routes/lq-ai/learn/how/+page.svelte`, `README.md`, `docs/skill-authoring-guide.md`, and a verify-only sweep of ADR 0014/0015 + boundary-registers + db-schema.md.

1. **File DE-350** in PRD §9 after DE-349: *"DE-350 — generic-MCP-result provenance — extend `message_tool_sources` to `source_kind='mcp'` for non-case-law connector results (6c shipped case-law only)."*
2. **Fix the dangling `DE-360` reference** in `docs/superpowers/specs/2026-06-20-pr6c-external-source-citations-design.md` → point at DE-350. Grep the repo for any other `DE-360` and repoint/remove.
3. **Reconcile the three narrative surfaces** (explorer Availability block, Learn §17, README legal-research paragraph): move "the case-law research skill" into "available today"; **drop the forward-looking "coming next"** promise — the milestone's user-facing capabilities are now all shipped, and the remaining DE-341 stub retirement is internal cleanup that does not belong in a user-facing availability narrative. (It stays tracked as DE-341 in PRD §9.)
4. **Document `tool_usage` in `docs/skill-authoring-guide.md`** with honest framing: declarations are **parsed and surfaced, not enforced** — a skill with an unconfigured connector still loads/runs; the operator sees the gap.
5. **Verify-don't-redo sweep:** confirm ADR 0014/0015 are `Accepted` (6a), the boundary-register tool-provider egress entry is SHIPPED (6a), `message_tool_sources` is in `db-schema.md` (6c), and PRD §3.6 research-capability language reads as shipped (tighten any residual "will/coming" wording). Fix only genuine drift.

**Grep gate:** after the surface edits, no user-facing narrative still promises the case-law skill as "coming"; any remaining "coming"/"next" refers only to genuinely-future work outside this milestone (or is gone).

## Security / gating

Not security-gated by CODEOWNERS: skill content + `api/app/skills/**` + `api/app/api/skills.py` + `web/` + docs. No `gateway/**`, no `docs/security/**`, no auth/crypto/audit-log changes. The C5 availability check only *reads* gateway capabilities (already a read path). → **self-merge after CI green.** If review finds the skill body makes substantive legal claims, stop and route to attestation (decision 2).

## Dev-environment guardrails (CLAUDE.md)

- No migration in 6d (no schema change — `tool_usage` is frontmatter, `unavailable_tool_usage` is computed).
- Tests via host venv (`api/.venv`, run from `api/`); web via `npm run check:lq-ai` + Vitest. Run BOTH `ruff format` and `ruff check`.
- The skills loader is filesystem-based — the new skill is picked up from `skills/`; no DB seeding.

## Build shape

One PR, three phases — mostly subagent-driven TDD with an inline visual pass:
1. **C5 backend** (schema field → resolver + pure `unavailable_tool_usage` → skill-detail surfacing + OpenAPI → tests) — subagent-driven TDD.
2. **The skill** (SKILL.md + worked example + frontmatter `tool_usage`) — drafted + procedural-framing review.
3. **Honesty pass** (DE-350 + dangling-ref fix + 3 surfaces + authoring-guide + verify sweep) — docs; grep-gated.
4. **Web surfacing + visual check** — the skill-detail note (three states) — inline with a headless render.

## Acceptance criteria

1. `skills/case-law-research/` exists with a valid `lq_ai` frontmatter (incl. `tool_usage: [courtlistener]`) + ≥1 worked example; the loader parses it; review confirms the body is procedural.
2. `GET /api/v1/skills/case-law-research` returns `tool_usage: ["courtlistener"]` and a correct `unavailable_tool_usage` (`[]` when CourtListener is configured, `["courtlistener"]` when not, `null` when undeterminable) — and the skill still loads/lists/runs regardless.
3. The skill-detail UI shows "Uses: CourtListener" and a non-blocking "not configured" note only when applicable.
4. DE-350 is filed in PRD §9; no dangling `DE-360` reference remains; the three narrative surfaces no longer promise the case-law skill as "coming"; the authoring guide documents `tool_usage` as surfaced-not-enforced.
5. Gates green: api ruff/mypy/pytest (skills schema + resolver + endpoint), web svelte-check + Vitest; grep gate clean. Not security-gated → self-merge after CI.
