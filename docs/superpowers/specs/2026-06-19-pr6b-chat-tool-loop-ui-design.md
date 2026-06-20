# PR6b / WS5 — Chat tool-loop UI (confirmation gate + connect-on-demand) — Design spec

**Date:** 2026-06-19 · **Milestone:** legal-research + MCP (WS5, sub-PR 6b) · **Consumes:** PR5b's chat tool-loop SSE protocol + PR4d's per-user OAuth `return_url` · **Gate:** not security-gated by CODEOWNERS (frontend + narrative docs); self-merge after CI green (maintainer may review the OAuth-redirect UX).

> Second of the four WS5 transparency sub-PRs (6a merged → **6b** → 6c → 6d). PR5b shipped the governed chat tool-loop **backend protocol** (the two terminal SSE events + the resume endpoint); the UI to render it was deferred to here. 6b makes the loop usable in chat: the in-chat destructive-tool **confirmation prompt** (approve/deny → resume) and the MCP **connect-on-demand prompt**. Per the maintainer's D6 honesty rule, 6b also flips the 6a narrative's "coming next" availability claims to "shipped."

## Goal

Let a user actually drive the governed tool-loop from chat: when the model proposes a destructive/`requires_confirmation` tool, show an in-message approve/deny card that resumes the turn on a decision; when a tool needs a connector the user hasn't authorized, show an in-message connect card that runs the per-user OAuth round-trip and brings them back to continue. Frontend-only — the endpoints already exist.

## Locked decisions (brainstormed with the maintainer 2026-06-19)

- **L1 — Scope = the two SSE events + the D6 narrative update. The case-law results panel moves to 6c** (PR5b folds research results into the assistant's *text* answer; a structured panel needs 6c's source-kind/citation data). No backend code; no new endpoints.
- **L2 — In-message cards, not modals.** Both prompts render as cards attached to the assistant turn, matching the existing `RefusalMessageBubble` precedent (banner + actions below the message content). One component `ToolGatePrompt.svelte` with a `variant: 'confirm' | 'connect'` prop (both are terminal-gate prompts sharing the card chrome).
- **L3 — Resume finalizes the SAME assistant message.** PR5b's resume reuses the same `assistant_message_id`; the resume's fresh SSE stream streams into the same bubble that showed the card. Stream consumption is factored into ONE shared helper used by both the initial send and the resume, so a **chained gate** (approve → the model proposes another destructive tool → another card) is handled by re-entrancy with no duplicated logic.
- **L4 — Connect = same-tab OAuth redirect + a "Continue" return bridge.** The connect button does a full-page redirect to `authorize_url?return_url=<current chat URL>` (OAuth requires a real redirect, not a popup). PR4d's callback returns to the chat with `?mcp_connected` (or `?mcp_error&server=`). The chat route reads that on mount, strips the query, and shows a toast with a **Continue** button that re-sends the last user message (the user message was already persisted by PR5b; the assistant turn ended at the auth gate). No silent auto-resend — matches PR5b's "user re-asks" contract; the Continue button is the bridge. (Auto-resume-after-connect → a DE.)
- **L5 — D6 forward consistency.** 6b flips the centralized availability claims from "coming next" → "shipped": the explorer's `AVAILABILITY` block + station 5/7 markers, the Learn section-17 availability sentence, and the README availability sentence. This is a first-class task, not a footnote.

## Non-goals (out of scope for 6b)

- No case-law results panel (→ 6c), no provenance pills / external-source citations (→ 6c).
- No backend code, no new endpoints, no schema change.
- No persistent "Connected MCP servers" management UI (revoke/list) — a settings panel is a future DE; 6b's connect flow is self-contained (token persisted server-side by PR4c).
- No auto-resend after connect (the Continue button is the v1 bridge).
- The end-of-PR6 release gate (fresh-clone Docker / GHCR images / macOS launcher / version tag) is tracked separately ([[project-pr6-release-completion-gate]]) and lands with 6d, not here.

---

## Architecture

All in `web/` (SvelteKit) + the 6a narrative docs. Units:

| Unit | File | Responsibility |
|---|---|---|
| Frame types | `web/src/lib/lq-ai/types.ts` (modify) | Add `ToolConfirmationRequiredFrame` + `McpAuthorizationRequiredFrame` to the `MessageStreamEvent` union. |
| SSE parser | `web/src/lib/lq-ai/sse/parser.ts` (modify) | Two switch cases (dispatch then `return` — terminal, like `onError`) + two callbacks on `MessageStreamCallbacks`. |
| Gate prompt | `web/src/lib/lq-ai/components/ToolGatePrompt.svelte` (new) | Renders the confirm (approve/deny) or connect card; emits decision/connect events. |
| Message render | `web/src/lib/lq-ai/components/MessageBubble.svelte` (modify) | Render `ToolGatePrompt` below the assistant content when a gate is pending for that message. |
| Chat orchestration | `web/src/lib/lq-ai/components/ChatPanel.svelte` (modify) | Pending-gate state; the shared `consumeIntoMessage` helper; `resumeToolCall`; `connectMcp`; the `?mcp_connected` return handler + Continue. |
| Resume/return helpers | `web/src/lib/lq-ai/chat/toolGate.ts` (new) | Pure, testable helpers: build the resume request, parse the OAuth-return query, build the `authorize_url?return_url=…`. Keeps ChatPanel thin and unit-testable. |
| Narrative (D6) | `web/static/learn/playgrounds/governed-tool-flow.html`, `web/src/routes/lq-ai/learn/how/+page.svelte`, `README.md` (modify) | Flip availability "coming next" → "shipped". |

The new `toolGate.ts` exists so the resume-request construction, the OAuth-return parsing, and the `authorize_url` building are unit-testable without mounting Svelte — ChatPanel just wires them.

## Data flow

**Confirmation gate.** Send → stream emits `tool_confirmation_required` → parser dispatches `onToolConfirmation` → ChatPanel sets `pendingGate = {assistantId, kind:'confirm', frame}` and ends the stream → `MessageBubble` renders the confirm `ToolGatePrompt` below the (partial) assistant bubble → user clicks **Approve**/**Deny** → `resumeToolCall(decision)` POSTs `/api/v1/chats/{chat_id}/tool-calls/{pending_call_id}` `{decision}` → `consumeIntoMessage(res, assistantId)` streams the continuation into the same bubble (which may surface another gate — chained). On the resume returning 409 (expired/replayed pending) → clear the card, show inline "This confirmation expired — re-send your message."

**Connect-on-demand.** Stream emits `mcp_authorization_required` → `onMcpAuthorization` → `pendingGate = {assistantId, kind:'connect', frame}` → connect `ToolGatePrompt` → user clicks **Connect** → full-page redirect to `authorize_url?return_url=<chat URL>` → (OAuth at the AS) → PR4d callback 302s back to the chat URL with `?mcp_connected` / `?mcp_error&server=` → chat route on mount: parse + strip the query, toast "Connected to {server}" (or an error toast) with a **Continue** button → re-sends the last user message.

## Error handling

- **Resume 409/410** (pending already resolved or expired): clear the gate card, inline notice "This confirmation expired — re-send your message." No crash.
- **Resume network/5xx**: surface the existing `sendError` banner; leave the card so the user can retry.
- **OAuth return `?mcp_error&server=`**: error toast naming the server ("Couldn't connect {server} — try again"); strip the query.
- **Chained gate**: the resume stream re-emits a gate event → handled by the same `consumeIntoMessage` callbacks (re-entrant); the new card replaces the old on the same message.
- **Navigation away mid-gate**: the pending `chat_pending_tool_call` row is single-use + TTL-bounded server-side (PR5b); a stale `pending_call_id` simply 409s on resume → the expired notice. No client cleanup needed.

## Testing

Vitest (the Web CI gate = `svelte-check` + Vitest):
- **Parser** (`__tests__/sse-parser.test.ts`): `normalizeFrame` coerces both new bare frames; `consumeMessageStream` dispatches `onToolConfirmation` / `onMcpAuthorization` and **terminates** the stream after each (like `onError`).
- **`toolGate.ts`** (new test): resume-request shape (path + `{decision}` body); OAuth-return parser (`?mcp_connected` → connected; `?mcp_error&server=x` → error w/ server; neither → none); `authorize_url` + `return_url` builder (correct encoding of the current chat URL).
- **`ToolGatePrompt.svelte`** (component test, @testing-library/svelte like the existing component tests): confirm variant renders tool/args_summary/tier + destructive marker and fires approve/deny; connect variant renders the server + fires connect; buttons disable while busy.
- The narrative D6 edits are covered by 6a's existing `svelte-check` + a manual re-render check.

## Surface / gating

- No new route, no `EXPECTED_PATHS`/`IMPLEMENTED_ROUTES` change (the resume + oauth endpoints already exist from PR5b/PR4c-d).
- **Not security-gated by CODEOWNERS** (no `gateway/**`, `docs/security/**`, or auth-logic — frontend wiring of existing endpoints + narrative docs). Self-merge after CI green; the maintainer may review the OAuth-redirect UX if desired.
- Branch `feat/pr6b-chat-tool-loop-ui` off `main` (`205efd9`); push origin + tucuxi; PR vs `main` (protected — PR + merge, then sync tucuxi). Commit `-s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Web is a pre-built static bundle** — rebuild `web` to view; verify the gate cards render and the flows work before ship.

## Open items to pin during planning

- The exact `ChatPanel.sendMessage` structure + the existing `consumeMessageStream` call site, so `consumeIntoMessage` factors out cleanly without changing initial-send behavior (the `onStart` reconciliation: initial send creates a draft; resume continues the existing message).
- The api-client helper for the resume POST (`messagesApi`/`apiStreamRequest`) + how the access token + API base URL are threaded.
- The chat route file that owns the URL (for the `?mcp_connected` return handler) and how it reads/strips query params (SvelteKit `$page`/`goto`).
- The exact `RefusalMessageBubble` markup/classes to mirror for `ToolGatePrompt`'s house style.
- Where the "last user message" lives in the store (for the Continue re-send).
