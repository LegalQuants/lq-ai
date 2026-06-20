# PR6a / WS5 — Transparency narrative (governed-tool-flow explorer + Learn + README + authority docs) — Design spec

**Date:** 2026-06-19 · **Milestone:** legal-research + MCP (WS5, sub-PR 6a) · **Narrates:** [ADR 0014](../../adr/0014-gateway-egress-boundary-for-tool-providers.md), [ADR 0015](../../adr/0015-governed-tool-calling-model.md), proposal [WS5](../../proposals/legal-research-and-mcp.md) · **Gate:** security review (touches `docs/security/boundary-registers.md`).

> Built on merged PR1–PR5b (gateway egress boundary, CourtListener research, MCP + per-user OAuth, the governed chat tool-loop). This is the **first** of the WS5 transparency sub-PRs (6a → 6b → 6c → 6d, decomposed 2026-06-19). 6a is the **posture narrative**: an interactive "how it works" explorer + Learn page + README + the authority docs the explorer cites. **No `api/`/`gateway/` logic** — web (static + Svelte) + docs only.

## Goal

Make the legal-research + MCP **security posture** legible to an in-house lawyer — not just the data flow. Per the maintainer's directive (2026-06-17), the posture decisions across the milestone exist to stay consistent with LQ.AI's founding principles (transparency, security, user control, operator control) and must be **captured for users**, not left implicit in ADRs/code. 6a delivers the interactive explorer (the maintainer's explicit `playground`-skill ask) + the README/docs narrative around it. The bar: a viewer should come away understanding "your data goes here, gated like this, audited like this, and **you** control the connectors."

## Locked decisions (brainstormed with the maintainer 2026-06-19)

- **D1 — Decomposition.** WS5 ships as four sub-PRs: **6a** (transparency narrative, this spec) → **6b** (chat tool-loop UI consuming the PR5b SSE protocol + case-law panel) → **6c** (external-source citations / source-kind C4 + provenance pills) → **6d** (case-law skill + C5 frontmatter parser + retire the OpenWebUI MCP stub DE-341). Each is its own spec → plan → build cycle.
- **D2 — Explorer interaction = step-through + guardrail toggles.** A "follow a question" walk through the governed tool flow, with toggles that re-run the flow and surface the refusal/confirm paths — so the *protections* are legible by showing what happens with and without them. (Not a passive flow diagram; not a posture-register-first view.)
- **D3 — Docs scope = narrative + its authority docs.** 6a includes the explorer + Learn section + README posture narrative + the docs the explorer's source-links point at: ADR 0014/0015 Status → **Accepted**, the egress-boundary entry in `docs/security/boundary-registers.md`, and the operator-allowlist surfaces in `gateway.yaml.example`/`mcp.yaml.example`. **Deferred to a later WS6 docs pass:** PRD §3.6 research prose + MCP capability promotion, and the `docs/db-schema.md` audit against migrations 0049–0054.
- **D4 — One explorer, both providers.** A single explorer covers the governed tool path; CourtListener (research) and MCP are two provider types *on the same path* (the toggles blend their concerns — tier/connector for research, OAuth/connect-on-demand for MCP). Not two separate explorers.
- **D5 — Accuracy is a hard requirement (the transparency principle applied to the viz).** Every station, toggle, and audit note must reflect real merged PR1–PR5b behavior; example data is clearly labeled "illustrative" (no live network calls — it is a static single-file HTML artifact); each posture callout links to its verifiable source file. The explorer must **not overclaim** — where a surface is backend-only until 6b, say so.
- **D6 — Forward consistency: the narrative must stay honest as the rest of WS5 lands.** Accuracy is not a one-time check at 6a; a "coming in the next release" note that ships in 6a becomes a *stale under-claim* the moment 6b ships the thing it describes. Two mechanisms enforce this: (1) **6a centralizes its temporal/availability claims** in ONE place (a single `AVAILABILITY` block in the explorer + one parallel line in the Learn framing copy + README) rather than sprinkling "coming soon" through the prose — so the update is one edit, not a hunt. (2) **Each subsequent WS5 sub-PR (6b/6c/6d) carries a REQUIRED task to update the 6a narrative** to reflect what it just shipped, and the **final sub-PR (6d) carries a milestone-completion honesty pass** over the whole narrative. See "Forward consistency & milestone honesty" below. This obligation is recorded in the milestone memory + handoff so it survives across sessions.

## Non-goals (explicitly out of scope for 6a)

- No `api/` or `gateway/` code; no new endpoints; no schema/migration changes.
- No chat-UI wiring of the confirmation gate / inline-connect (that consumes PR5b's SSE events — **6b**).
- No external-source citation modeling or provenance pills (**6c**); no case-law skill / C5 parser / stub retirement (**6d**).
- No `learn/use/+page.svelte` "how to use" feature-tour entry (that lands with the actual UI in 6b).
- Deferred reference docs per D3 (PRD §3.6, MCP promotion, db-schema audit).

---

## Architecture

Three additive surfaces + four doc edits, all in `web/` (static + SvelteKit) and `docs/`:

| Unit | File | Responsibility |
|---|---|---|
| The explorer | `web/static/learn/playgrounds/governed-tool-flow.html` (new) | Self-contained single-file interactive HTML (inline CSS/JS, no build step, no external deps) — the step-through + guardrail-toggle explorer. Matches the existing 18 playgrounds' house style. |
| Learn entry | `web/src/routes/lq-ai/learn/how/+page.svelte` (modify) | A new numbered section embedding the explorer via `<iframe>` with a framing paragraph + "open full-screen" link + verifiable source links — mirroring the existing entries. |
| README | `README.md` (modify) | A legal-research + MCP capability section narrating the posture, linking to the Learn explorer + the two ADRs. |
| Authority: ADRs | `docs/adr/0014-*.md`, `docs/adr/0015-*.md` (modify) | Flip `**Status:** Proposed` → `**Status:** Accepted` (line 3 of each) — the implementation has landed. |
| Authority: boundary register | `docs/security/boundary-registers.md` (modify) | Add the tool-provider egress-boundary register entry (the gateway as sole egress for tool/data-source providers). **This edit makes 6a security-gated.** |
| Authority: config examples | `gateway.yaml.example`, `mcp.yaml.example` (modify if thin) | Ensure the `tool_providers` (gateway) and MCP-server (mcp.yaml) operator-allowlist surfaces are clearly shown, with comments an operator can follow. Add example/comment only — no behavior. |

The explorer is the only non-trivial unit. It is intentionally a single static file (the established playground pattern) so it ships without a build pipeline and is itself forkable/inspectable — consistent with the work-product-transparency principle it narrates.

## The explorer in detail

**Layout.** An "ask a legal question" input (illustrative, prefilled) → a vertical flow of **7 stations** → a right-hand **guardrail panel** (4 toggles) → a **posture callout** that updates with the active station and toggle state. Visual style matches the existing playgrounds (the house theme used by `system-architecture.html`, `request-lifecycle.html`, `autonomous-flow.html`, etc.).

**The 7 stations** (the governed tool path; each carries a one-line posture sentence + a "what's recorded / never logged" note, both accurate to merged code):

1. **Allowlist assembled** — the backend builds the per-turn *closed* tool set from operator-enabled research + MCP tools (`api/app/chat/tool_schemas.py`; PR5b). Posture: *the operator decides which connectors exist; the model cannot reach beyond the allowlist.*
2. **Model picks a tool** — the model chooses among allowed tools only (e.g. CourtListener `search_case_law`, or an enabled MCP tool). Posture: *a closed set, not open-ended function-calling (ADR 0015, alternative A).*
3. **Gateway egress + SSRF check** — the call leaves the operator's environment **only** through the gateway, which validates the egress target (`gateway/app/providers/tool/`, `validate_egress_target`; PR1). Posture: *the gateway is the sole egress and the only MCP-protocol speaker; the backend never calls a third party directly (ADR 0014).*
4. **Tier gate + rate limit** — the provider's egress tier is checked and rate-limited; a call over the ceiling is refused (`route_tool_call`; PR1). Posture: *tier-gated egress, per-provider.*
5. **Per-user OAuth (MCP `auth: oauth` only)** — the per-user token travels as the `X-LQ-AI-User-Token` **header** (never query/body/logs), Fernet-encrypted at rest; the gateway stays user-unaware (`oauth_passthrough.py`, `app/mcp/oauth.py`; PR4c). Posture: *per-user consent; tokens never logged; the gateway never learns the user.*
6. **Audit row written** — the gateway writes `tool_egress_log` and the api writes `tool_call_log`, **counts/types only — never the raw args or results** (`args_digest`, not payloads; PR1/PR5a). Posture: *every call is audited, anonymization-safe.*
7. **Result / confirmation gate** — `read_only` results feed back inline; `destructive`/`requires_confirmation` tools (un-annotated MCP tools ⇒ requires confirmation, safe-by-default) **pause for a human approve/deny** (the PR5b persist-and-resume gate). Posture: *tool safety flags carried from MCP annotations; a human gate for destructive actions.* **Honesty note:** the explorer states the **in-chat prompt** that renders this gate is "coming in the next release" (6b) — the backend protocol exists today; the UI does not yet.

**The 4 guardrail toggles** (each flip re-runs the flow and reveals the refusal/confirm path at the relevant station):

| Toggle (default) | Off → what the explorer shows | Posture it makes legible |
|---|---|---|
| `connector allowlisted?` (on) | Refused at station 1/3 — the tool never appears in the allowlist / never reaches the network | Nothing reaches a third party unless the operator wired it |
| `OAuth connected?` (on) | Station 5 shows the inline connect-on-demand prompt (PR5b `mcp_authorization_required`) | Per-user consent is required and obtained out-of-band |
| `tier within ceiling?` (on) | Refused at station 4 (egress-tier refusal) | Tier-gated egress is enforced at the boundary |
| `tool read-only?` (on) | Pauses at station 7's confirmation gate (destructive path) | Destructive actions require a human |

**Accuracy contract (D5).** A short visible footer states the data is illustrative and links each posture claim to its source (ADR 0014/0015 sections, `gateway/app/providers/tool/`, `app/tools/governance.py`, `tool_egress_log`/`tool_call_log`, `oauth_passthrough.py`, `app/chat/tool_schemas.py`). No live calls — the artifact is static.

**Availability block (D6 — single source of temporal truth).** All "what exists today vs. coming next" claims live in ONE clearly-marked `AVAILABILITY` block in the explorer (e.g. a small labeled panel: "Available today: the governed backend tool-loop, gateway egress boundary, per-user OAuth, audit, and the confirmation-gate protocol. Coming in the next release: the in-chat confirmation prompt and connect-on-demand UI."). Station 7's and station 5's "coming next" markers reference this single block rather than restating it. The Learn framing paragraph and the README each carry exactly one parallel availability sentence. This is the **only** place that changes when 6b/6c/6d ship — making the D6 update mechanical and unmissable.

## Forward consistency & milestone honesty

The transparency principle requires the narrative to be honest at the *end* of PR6, not only at 6a. The "Available today / coming next" framing is correct when 6a ships (6b's UI does not yet exist) but becomes a stale under-claim as later sub-PRs land. Enforcement:

- **6b** (chat tool-loop UI) — **required task in its plan:** update the explorer `AVAILABILITY` block + station 5/7 markers + the Learn availability sentence + README to state the in-chat confirmation prompt and connect-on-demand UI now ship; remove the "coming next" framing for those.
- **6c** (external-source citations + provenance pills) — **required task:** update the narrative where it describes case-law results as "fed back as raw text, rich provenance coming later" to reflect that source-kinded, verified provenance now persists.
- **6d** (case-law skill + C5 + stub retirement) — **required task + milestone-completion honesty pass:** update for the shipped case-law skill, AND do a final read-through of the entire WS5 narrative (explorer + Learn + README) confirming every "coming next" / "today" claim matches the now-complete milestone. This is the gate that PR6 ends honest.

This obligation is recorded in `[[project-pr6-transparency-posture-narrative]]` and the WS5 handoff so it is carried into the 6b/6c/6d planning sessions even across context resets. Each sub-PR's `writing-plans` output MUST include its narrative-update task as a first-class task, not a footnote.

## Build approach

- The explorer HTML is generated with the **`playground` skill**, then adapted to match the existing playground house style (theme, typography, the source-links footer pattern) so it reads as one of the set. It must be a single self-contained file with no external dependencies.
- The Learn entry follows the exact structure of the existing 18 entries in `how/+page.svelte` (heading → framing paragraph → `<iframe src="/learn/playgrounds/governed-tool-flow.html">` → "Open full-screen" link → source links).
- README + ADR + boundary-register + yaml-example edits are plain Markdown/YAML.

## Testing & verification

- **Accuracy review (the load-bearing gate):** a reviewer checks every station/toggle/audit claim against the cited source files. Because the project's thesis is transparency, an inaccurate viz is a defect, not a polish item — this review is mandatory and blocks merge.
- **`svelte-check`** passes for the modified `how/+page.svelte` (and the existing web lint/test gates: `svelte-check` + Vitest in CI).
- **Build + visual check:** the `web` container serves a **pre-built static bundle** — rebuild `web` before viewing; confirm the iframe loads, the toggles re-run the flow, and the full-screen link works. A screenshot is attached to the PR.
- No `api`/`gateway` test changes (no backend code). No new route → no `EXPECTED_PATHS`/`IMPLEMENTED_ROUTES` change.

## Gating & process

- **Security-gated:** the `docs/security/boundary-registers.md` edit is under CODEOWNERS (`docs/security/**`), so the PR auto-routes to security review → **the maintainer reviews/merges**; do not self-merge.
- Branch `feat/pr6a-transparency-narrative` off `main` (`97ccbc0`); push origin + tucuxi; PR vs `main` (protected — PR + merge, then sync tucuxi). Commit `-s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- After 6a merges: 6b (chat tool-loop UI).

## Open items to pin during planning

- The exact existing playground house-style conventions (theme variables, the source-links footer markup) — read 2–3 existing playgrounds (`request-lifecycle.html`, `autonomous-flow.html`) before generating, so the new one matches.
- The precise insertion point + numbering for the new section in `how/+page.svelte` (it appends to the existing ordered list of 18).
- Whether `gateway.yaml.example`/`mcp.yaml.example` already show the `tool_providers`/MCP-server allowlist clearly (verify first; edit only if thin).
- The exact README section location (where the capability list / feature narrative lives today).
