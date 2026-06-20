# PR6b — Chat tool-loop UI (confirmation gate + connect-on-demand) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PR5b's governed chat tool-loop usable in chat — an in-message approve/deny card that resumes the turn, and an MCP connect-on-demand card — by consuming the two new terminal SSE events; then flip the 6a narrative's availability claims to "shipped."

**Architecture:** Frontend-only (SvelteKit `web/`). Extend the SSE parser/types with two terminal frames + callbacks; render an in-message `ToolGatePrompt` card (confirm | connect) matching the `RefusalMessageBubble` precedent; ChatPanel owns the pending-gate state and a shared stream-consumption helper used by both the initial send and the resume POST (so chained gates work); a same-tab OAuth redirect with a `?mcp_connected` return handler + a "Continue" re-send. Pure logic lives in a testable `chat/toolGate.ts`.

**Tech Stack:** TypeScript, SvelteKit (Svelte 5 / OpenWebUI fork), Vitest + @testing-library/svelte, Tailwind/design-system primitives.

## Global Constraints

- **Branch:** `feat/pr6b-chat-tool-loop-ui` off `main` (`205efd9`), already created. Push `origin` + `tucuxi`. `origin/main` is PROTECTED — PR + GitHub merge only; sync tucuxi after. **Not security-gated by CODEOWNERS** (frontend + narrative docs) → self-merge after CI green (maintainer may review the OAuth-redirect UX).
- **Frontend-only.** No `api/`/`gateway/` code, no new endpoints, no schema/migration. The resume endpoint `POST /api/v1/chats/{chat_id}/tool-calls/{pending_call_id}` and the OAuth endpoints already exist (PR5b / PR4c-d).
- **Two new terminal SSE frames** (verbatim shapes from PR5b):
  - `{"type":"tool_confirmation_required","lq_ai_message_id","pending_call_id","provider","tool","function_name","args_summary","tier","destructive"}`
  - `{"type":"mcp_authorization_required","lq_ai_message_id","server","authorize_url"}`
  Both are **terminal** (the parser `return`s after dispatch, exactly like `error`).
- **Resume reuses the same `assistant_message_id`** — the resume's fresh stream finalizes the SAME message bubble. One shared consumption helper handles initial send + resume + chained gates.
- **Connect = same-tab redirect** to `authorize_url?return_url=<chat URL>`; PR4d returns to the chat with `?mcp_connected` or `?mcp_error&server=`. No silent auto-resend — a "Continue" button re-sends the last user message.
- **D6 (required):** flip the centralized availability claims from "coming next" → "shipped" in the explorer `AVAILABILITY` block + station 5/7 markers, the Learn section-17 sentence, and the README sentence.
- **Web CI gate = `svelte-check` + Vitest.** The `web` container serves a pre-built static bundle — rebuild `web` to view a change.
- **Commit (every commit):** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Stage explicitly — never `git add -A`.

## TDD note

The pure units (parser, `toolGate.ts`, the `ToolGatePrompt` component) are Vitest-testable red/green. The ChatPanel/MessageBubble integration and the route return-handler are stateful Svelte — verified by `svelte-check`, the extracted testable helpers, and a build + manual/headless visual check. Tasks state their gate explicitly.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `web/src/lib/lq-ai/types.ts` | Modify (after line 391) | Add `ToolConfirmationRequiredFrame` + `McpAuthorizationRequiredFrame`; extend `MessageStreamEvent` union. |
| `web/src/lib/lq-ai/sse/parser.ts` | Modify | `normalizeFrame` accepts the two new `type`s; `consumeMessageStream` switch dispatches `onToolConfirmation`/`onMcpAuthorization` then `return`; extend `MessageStreamCallbacks`. |
| `web/src/lib/lq-ai/chat/toolGate.ts` | Create | Pure helpers: `parseOAuthReturn(searchParams)`, `buildAuthorizeUrl(authorizeUrl, returnUrl)`. |
| `web/src/lib/lq-ai/api/messages.ts` | Modify | `resumeToolCall(chatId, pendingCallId, decision, signal) → Promise<Response>` (fresh SSE stream). |
| `web/src/lib/lq-ai/components/ToolGatePrompt.svelte` | Create | The in-message card; `variant: 'confirm' \| 'connect'`; emits approve/deny/connect. |
| `web/src/lib/lq-ai/components/MessageBubble.svelte` | Modify | Render `ToolGatePrompt` below assistant content when a gate is pending for that message. |
| `web/src/lib/lq-ai/components/ChatPanel.svelte` | Modify | Pending-gate state; shared `consumeIntoMessage`; the two new callbacks; `resumeToolCall`; `connectMcp`; prop-drill to MessageBubble. |
| `web/src/routes/lq-ai/chats/+page.svelte` | Modify | OAuth-return handler: read `?mcp_connected`/`?mcp_error&server=`, toast, strip query, Continue re-send. |
| `web/static/learn/playgrounds/governed-tool-flow.html`, `web/src/routes/lq-ai/learn/how/+page.svelte`, `README.md` | Modify | D6 availability flip. |

---

## Task 1: SSE frame types + parser

**Files:**
- Modify: `web/src/lib/lq-ai/types.ts` (after line 391, before the `MessageStreamEvent` union at 393)
- Modify: `web/src/lib/lq-ai/sse/parser.ts` (`normalizeFrame` switch ~42-51; `MessageStreamCallbacks` 91-96; `consumeMessageStream` switch 133-146)
- Test: `web/src/lib/lq-ai/__tests__/sse-parser.test.ts` (extend)

**Interfaces:**
- Produces: `ToolConfirmationRequiredFrame`, `McpAuthorizationRequiredFrame` (types); `MessageStreamCallbacks.onToolConfirmation`/`.onMcpAuthorization` (consumed by ChatPanel in Task 4).

**Gate:** Vitest — both new bare frames normalize + dispatch to their callback + terminate the stream.

- [ ] **Step 1: Write failing parser tests.** In `__tests__/sse-parser.test.ts`, add:
```ts
it('dispatches onToolConfirmation and terminates the stream', async () => {
  const frame = { type: 'tool_confirmation_required', lq_ai_message_id: 'm1', pending_call_id: 'p1', provider: 'files', tool: 'delete_doc', function_name: 'mcp__files__delete_doc', args_summary: '{path:/x}', tier: 2, destructive: true };
  const body = sseBody([JSON.stringify(frame), JSON.stringify({ type: 'delta', delta: 'X', lq_ai_message_id: 'm1' })]);
  const calls: string[] = [];
  await consumeMessageStream(body, {
    onToolConfirmation: () => calls.push('confirm'),
    onDelta: () => calls.push('delta'),
  });
  expect(calls).toEqual(['confirm']); // terminal: the trailing delta is never dispatched
});

it('dispatches onMcpAuthorization and terminates the stream', async () => {
  const frame = { type: 'mcp_authorization_required', lq_ai_message_id: 'm1', server: 'files', authorize_url: '/api/v1/mcp/oauth/files/authorize' };
  const body = sseBody([JSON.stringify(frame), JSON.stringify({ type: 'delta', delta: 'X', lq_ai_message_id: 'm1' })]);
  const calls: string[] = [];
  await consumeMessageStream(body, {
    onMcpAuthorization: () => calls.push('auth'),
    onDelta: () => calls.push('delta'),
  });
  expect(calls).toEqual(['auth']);
});

it('normalizeFrame accepts the two new types', () => {
  expect(normalizeFrame({ type: 'tool_confirmation_required', pending_call_id: 'p1' })?.type).toBe('tool_confirmation_required');
  expect(normalizeFrame({ type: 'mcp_authorization_required', server: 's' })?.type).toBe('mcp_authorization_required');
});
```
Use the existing test's SSE-body helper (find how the current tests build a `ReadableStream` of `data:` lines — reuse it as `sseBody`; if it's inline, extract a small local helper). Import `normalizeFrame` + `consumeMessageStream` as the existing tests do.

- [ ] **Step 2: Run; expect FAIL.** `cd web && npx vitest run src/lib/lq-ai/__tests__/sse-parser.test.ts` → the two dispatch tests fail (callbacks never fire; the new types return null from `normalizeFrame`).

- [ ] **Step 3: Add the frame types** to `types.ts` after line 391:
```ts
export interface ToolConfirmationRequiredFrame {
	type: 'tool_confirmation_required';
	lq_ai_message_id: string;
	pending_call_id: string;
	provider: string;
	tool: string;
	function_name: string;
	args_summary: string;
	tier: number | null;
	destructive: boolean;
}

export interface McpAuthorizationRequiredFrame {
	type: 'mcp_authorization_required';
	lq_ai_message_id: string;
	server: string;
	authorize_url: string;
}
```
Extend the union (line 393):
```ts
export type MessageStreamEvent =
	| MessageStartFrame
	| MessageDeltaFrame
	| MessageCompleteFrame
	| MessageErrorFrame
	| ToolConfirmationRequiredFrame
	| McpAuthorizationRequiredFrame;
```

- [ ] **Step 4: Extend the parser.** In `parser.ts` `normalizeFrame` add the two cases to the `type`-discriminator switch (alongside `start`/`delta`/`complete`):
```ts
				case 'tool_confirmation_required':
				case 'mcp_authorization_required':
					return obj as unknown as MessageStreamEvent;
```
Add the two callbacks to `MessageStreamCallbacks`:
```ts
	onToolConfirmation?: (frame: import('../types').ToolConfirmationRequiredFrame) => void;
	onMcpAuthorization?: (frame: import('../types').McpAuthorizationRequiredFrame) => void;
```
Add the two cases to the `consumeMessageStream` switch (both terminal, like `error`):
```ts
				case 'tool_confirmation_required':
					callbacks.onToolConfirmation?.(frame);
					return;
				case 'mcp_authorization_required':
					callbacks.onMcpAuthorization?.(frame);
					return;
```

- [ ] **Step 5: Run; expect PASS.** Same vitest command → green.

- [ ] **Step 6: `svelte-check` the touched files clean.** `cd web && npm run check:lq-ai 2>&1 | tail -5` → no new errors.

- [ ] **Step 7: Commit.**
```bash
git add web/src/lib/lq-ai/types.ts web/src/lib/lq-ai/sse/parser.ts web/src/lib/lq-ai/__tests__/sse-parser.test.ts
git commit -s -m "feat(web): parse tool_confirmation_required + mcp_authorization_required SSE frames (PR6b)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `toolGate.ts` pure helpers + `resumeToolCall` api

**Files:**
- Create: `web/src/lib/lq-ai/chat/toolGate.ts`
- Modify: `web/src/lib/lq-ai/api/messages.ts`
- Test: `web/src/lib/lq-ai/__tests__/toolGate.test.ts` (new)

**Interfaces:**
- Produces (consumed by Tasks 4–5):
  - `parseOAuthReturn(params: URLSearchParams): { status: 'connected' | 'error' | 'none'; server: string | null }`
  - `buildAuthorizeUrl(authorizeUrl: string, returnUrl: string): string` — appends `?return_url=<encoded>` (handles an authorizeUrl that already has a query with `&`).
  - `resumeToolCall(chatId, pendingCallId, decision: 'approve' | 'deny', signal?: AbortSignal): Promise<Response>` (fresh SSE stream; throws `errorFor(status)` on non-2xx — a 409/410 means the pending expired/was replayed).

**Gate:** Vitest on the two pure helpers (the api fn is exercised in Task 4's integration; here just type-check it).

- [ ] **Step 1: Write failing tests** (`__tests__/toolGate.test.ts`):
```ts
import { parseOAuthReturn, buildAuthorizeUrl } from '../chat/toolGate';

describe('parseOAuthReturn', () => {
  it('detects connected', () => {
    expect(parseOAuthReturn(new URLSearchParams('mcp_connected=1'))).toEqual({ status: 'connected', server: null });
  });
  it('detects error with server', () => {
    expect(parseOAuthReturn(new URLSearchParams('mcp_error=1&server=files'))).toEqual({ status: 'error', server: 'files' });
  });
  it('none when absent', () => {
    expect(parseOAuthReturn(new URLSearchParams('foo=bar'))).toEqual({ status: 'none', server: null });
  });
});

describe('buildAuthorizeUrl', () => {
  it('appends return_url (no existing query)', () => {
    expect(buildAuthorizeUrl('/api/v1/mcp/oauth/files/authorize', 'https://app/lq-ai/chats?c=1'))
      .toBe('/api/v1/mcp/oauth/files/authorize?return_url=' + encodeURIComponent('https://app/lq-ai/chats?c=1'));
  });
  it('uses & when authorize_url already has a query', () => {
    expect(buildAuthorizeUrl('/x?a=1', 'https://app/c')).toBe('/x?a=1&return_url=' + encodeURIComponent('https://app/c'));
  });
});
```

- [ ] **Step 2: Run; expect FAIL** (module missing).

- [ ] **Step 3: Implement `chat/toolGate.ts`:**
```ts
/** Pure helpers for the chat tool-gate UI (PR6b). No Svelte, no network. */

export interface OAuthReturn {
	status: 'connected' | 'error' | 'none';
	server: string | null;
}

/** Parse the PR4d OAuth-callback return query (`?mcp_connected` / `?mcp_error&server=`). */
export function parseOAuthReturn(params: URLSearchParams): OAuthReturn {
	if (params.has('mcp_connected')) return { status: 'connected', server: params.get('server') };
	if (params.has('mcp_error')) return { status: 'error', server: params.get('server') };
	return { status: 'none', server: null };
}

/** Append `return_url` to an authorize URL, preserving any existing query. */
export function buildAuthorizeUrl(authorizeUrl: string, returnUrl: string): string {
	const sep = authorizeUrl.includes('?') ? '&' : '?';
	return `${authorizeUrl}${sep}return_url=${encodeURIComponent(returnUrl)}`;
}
```

- [ ] **Step 4: Run; expect PASS.**

- [ ] **Step 5: Add `resumeToolCall` to `api/messages.ts`** (mirror `sendMessageStream`):
```ts
/**
 * Resume a paused tool-loop turn after the user approves/denies a destructive
 * tool. POST /api/v1/chats/{chat_id}/tool-calls/{pending_call_id}; returns the
 * raw `Response` whose body is a fresh SSE stream (same frames as a send).
 * Throws (errorFor) on non-2xx — a 409/410 means the pending call expired or
 * was already resolved.
 */
export async function resumeToolCall(
	chatId: string,
	pendingCallId: string,
	decision: 'approve' | 'deny',
	signal?: AbortSignal
): Promise<Response> {
	return apiStreamRequest(
		`/chats/${encodeURIComponent(chatId)}/tool-calls/${encodeURIComponent(pendingCallId)}`,
		{ method: 'POST', body: { decision }, stream: true, signal }
	);
}
```

- [ ] **Step 6: `svelte-check` + vitest clean.** `cd web && npx vitest run src/lib/lq-ai/__tests__/toolGate.test.ts && npm run check:lq-ai 2>&1 | tail -5`.

- [ ] **Step 7: Commit** (`git add web/src/lib/lq-ai/chat/toolGate.ts web/src/lib/lq-ai/api/messages.ts web/src/lib/lq-ai/__tests__/toolGate.test.ts`).

---

## Task 3: `ToolGatePrompt.svelte` component

**Files:**
- Create: `web/src/lib/lq-ai/components/ToolGatePrompt.svelte`
- Reference (read first, mirror its card classes/design primitives): `web/src/lib/lq-ai/components/RefusalMessageBubble.svelte`
- Test: `web/src/lib/lq-ai/__tests__/ToolGatePrompt.test.ts` (new)

**Interfaces:**
- Produces (consumed by MessageBubble in Task 4): props `variant: 'confirm' | 'connect'`, `confirm?: ToolConfirmationRequiredFrame`, `connect?: McpAuthorizationRequiredFrame`, `busy?: boolean`, and callback props `onApprove?`, `onDeny?`, `onConnect?`.

**Gate:** Vitest @testing-library/svelte — confirm variant renders tool/args/tier/destructive + fires approve/deny; connect variant renders server + fires connect; buttons disabled when `busy`.

- [ ] **Step 1: Read `RefusalMessageBubble.svelte`** to copy the card chrome (the container classes, the heading/body/action-button styling using the project design-system primitives — per CLAUDE.md, do NOT use ad-hoc Tailwind where a primitive exists). Note its `data-testid` conventions.

- [ ] **Step 2: Write failing component test** (`__tests__/ToolGatePrompt.test.ts`), mirroring the existing component test pattern (`RefusalMessageBubble.test.ts`):
```ts
import { render, fireEvent } from '@testing-library/svelte';
import ToolGatePrompt from '../components/ToolGatePrompt.svelte';

const confirmFrame = { type: 'tool_confirmation_required', lq_ai_message_id: 'm1', pending_call_id: 'p1', provider: 'files', tool: 'delete_doc', function_name: 'mcp__files__delete_doc', args_summary: '{"path":"/x"}', tier: 2, destructive: true } as const;

it('confirm variant renders + fires approve/deny', async () => {
  const onApprove = vi.fn(), onDeny = vi.fn();
  const { getByTestId } = render(ToolGatePrompt, { variant: 'confirm', confirm: confirmFrame, onApprove, onDeny });
  await fireEvent.click(getByTestId('tool-gate-approve'));
  await fireEvent.click(getByTestId('tool-gate-deny'));
  expect(onApprove).toHaveBeenCalledOnce();
  expect(onDeny).toHaveBeenCalledOnce();
});

it('connect variant renders server + fires connect', async () => {
  const onConnect = vi.fn();
  const { getByTestId, getByText } = render(ToolGatePrompt, { variant: 'connect', connect: { type: 'mcp_authorization_required', lq_ai_message_id: 'm1', server: 'files', authorize_url: '/a' }, onConnect });
  expect(getByText(/files/)).toBeTruthy();
  await fireEvent.click(getByTestId('tool-gate-connect'));
  expect(onConnect).toHaveBeenCalledOnce();
});

it('buttons disabled while busy', () => {
  const { getByTestId } = render(ToolGatePrompt, { variant: 'confirm', confirm: confirmFrame, busy: true });
  expect((getByTestId('tool-gate-approve') as HTMLButtonElement).disabled).toBe(true);
});
```

- [ ] **Step 3: Run; expect FAIL** (component missing).

- [ ] **Step 4: Implement `ToolGatePrompt.svelte`.** Use Svelte 5 runes (match the codebase's component style — check `RefusalMessageBubble.svelte` for `$props()` vs `export let`). Skeleton (fill the chrome by mirroring RefusalMessageBubble's classes/primitives):
```svelte
<script lang="ts">
	import type { ToolConfirmationRequiredFrame, McpAuthorizationRequiredFrame } from '../types';
	let {
		variant,
		confirm = null,
		connect = null,
		busy = false,
		onApprove = () => {},
		onDeny = () => {},
		onConnect = () => {}
	}: {
		variant: 'confirm' | 'connect';
		confirm?: ToolConfirmationRequiredFrame | null;
		connect?: McpAuthorizationRequiredFrame | null;
		busy?: boolean;
		onApprove?: () => void;
		onDeny?: () => void;
		onConnect?: () => void;
	} = $props();
</script>

{#if variant === 'confirm' && confirm}
	<div class="<card classes mirrored from RefusalMessageBubble>" data-testid="tool-gate-confirm">
		<!-- heading: "Approval needed" + (confirm.destructive ? a destructive marker) -->
		<!-- body: the tool name (confirm.tool / confirm.function_name), provider (confirm.provider),
		     a tier chip (confirm.tier), and the args summary (confirm.args_summary). args_summary is
		     already redacted/bounded by the backend — render as plain text, do NOT @html it. -->
		<div class="<actions>">
			<button data-testid="tool-gate-approve" disabled={busy} onclick={onApprove}>Approve</button>
			<button data-testid="tool-gate-deny" disabled={busy} onclick={onDeny}>Deny</button>
		</div>
	</div>
{:else if variant === 'connect' && connect}
	<div class="<card classes>" data-testid="tool-gate-connect-card">
		<!-- body: "Connect your {connect.server} account to continue." -->
		<button data-testid="tool-gate-connect" disabled={busy} onclick={onConnect}>Connect {connect.server}</button>
	</div>
{/if}
```
Render `confirm.args_summary` as **plain text** (it is a backend-redacted summary; never `{@html}` it). Use the destructive marker only when `confirm.destructive`.

- [ ] **Step 5: Run; expect PASS.** `cd web && npx vitest run src/lib/lq-ai/__tests__/ToolGatePrompt.test.ts`.

- [ ] **Step 6: `svelte-check` clean** (`npm run check:lq-ai`).

- [ ] **Step 7: Commit.**

---

## Task 4: ChatPanel + MessageBubble wiring (the integration)

**Files:**
- Modify: `web/src/lib/lq-ai/components/ChatPanel.svelte` (the send/consume block ~534-621; state vars region; add `consumeIntoMessage`, `resumeToolCall`, `connectMcp`)
- Modify: `web/src/lib/lq-ai/components/MessageBubble.svelte` (assistant branch, after the content render ~150)
- Test: none new (integration; covered by build + the Task 1–3 unit tests + Task 7 visual)

**Interfaces:**
- Consumes: Task 1 callbacks; Task 2 `resumeToolCall`/`buildAuthorizeUrl`; Task 3 `ToolGatePrompt`.
- Produces: a `pendingGate` shape `{ assistantId: string; kind: 'confirm'; frame: ToolConfirmationRequiredFrame } | { assistantId: string; kind: 'connect'; frame: McpAuthorizationRequiredFrame } | null` prop-drilled to MessageBubble.

**Gate:** `svelte-check` clean; Task 7 build + visual confirms the cards render and the flows work.

- [ ] **Step 1: Factor the stream consumption.** Extract the existing `consumeMessageStream(res.body, {...callbacks})` block (ChatPanel ~563-613) into a local async function so both send and resume reuse it:
```ts
async function consumeIntoMessage(body: ReadableStream<Uint8Array>, assistantId0: string) {
	let assistantId = assistantId0;
	await consumeMessageStream(body, {
		onStart: (frame) => {
			// Reconcile: initial send started with a draft id; resume re-emits the
			// persisted id (already the message id). Keep the existing message.
			if (assistantId === draftAssistantId) {
				assistantId = frame.lq_ai_message_id;
				messagesStore.update(($m) => $m.map((m) => (m.id === draftAssistantId ? { ...m, id: assistantId } : m)));
			} else {
				assistantId = frame.lq_ai_message_id;
			}
			streamingMessageId = assistantId;
			pendingGate = null; // a new stream supersedes any prior gate card on this msg
		},
		onDelta: (frame) => { /* existing onDelta body, keyed on assistantId */ },
		onComplete: (frame) => { /* existing onComplete body */ },
		onError: (frame) => { /* existing onError body */ },
		onToolConfirmation: (frame) => {
			streamingMessageId = null;
			pendingGate = { assistantId, kind: 'confirm', frame };
		},
		onMcpAuthorization: (frame) => {
			streamingMessageId = null;
			pendingGate = { assistantId, kind: 'connect', frame };
		}
	});
}
```
Replace the inline `consumeMessageStream(...)` in the send path with `await consumeIntoMessage(res.body, draftAssistantId);` (passing the current `draftAssistantId`). Preserve the existing onDelta/onComplete/onError bodies verbatim — only move them into the helper and key them on the closed-over `assistantId`.

- [ ] **Step 2: Add state.** Near the other `let` state (~166-169) add:
```ts
let pendingGate:
	| { assistantId: string; kind: 'confirm'; frame: ToolConfirmationRequiredFrame }
	| { assistantId: string; kind: 'connect'; frame: McpAuthorizationRequiredFrame }
	| null = null;
let gateBusy = false;
```
Import the two frame types + `resumeToolCall` (via `messagesApi`) + `buildAuthorizeUrl`.

- [ ] **Step 3: Add `resumeToolCall` + `connectMcp` handlers** (in ChatPanel `<script>`):
```ts
async function decideToolCall(decision: 'approve' | 'deny') {
	if (!pendingGate || pendingGate.kind !== 'confirm') return;
	const { assistantId, frame } = pendingGate;
	gateBusy = true;
	try {
		const res = await messagesApi.resumeToolCall(chat.id, frame.pending_call_id, decision);
		if (!res.body) throw new Error('Empty stream body');
		pendingGate = null;
		await consumeIntoMessage(res.body, assistantId);
	} catch (e: unknown) {
		const status = (e as { status?: number })?.status;
		if (status === 409 || status === 410) {
			pendingGate = null;
			sendError = 'This confirmation expired — re-send your message to continue.';
		} else {
			sendError = e instanceof Error ? e.message : 'Could not resume the tool call.';
		}
	} finally {
		gateBusy = false;
	}
}

function connectMcp() {
	if (!pendingGate || pendingGate.kind !== 'connect') return;
	const returnUrl = window.location.href; // PR4d lands back here with ?mcp_connected
	window.location.href = buildAuthorizeUrl(pendingGate.frame.authorize_url, returnUrl);
}
```

- [ ] **Step 4: Prop-drill to MessageBubble.** Where ChatPanel renders each `MessageBubble` (find the `{#each}` over `$messagesStore`), pass the gate for that message + the handlers:
```svelte
<MessageBubble
	{message}
	... existing props ...
	gateForMessage={pendingGate && pendingGate.assistantId === message.id ? pendingGate : null}
	{gateBusy}
	onGateApprove={() => decideToolCall('approve')}
	onGateDeny={() => decideToolCall('deny')}
	onGateConnect={connectMcp}
/>
```

- [ ] **Step 5: Render in MessageBubble.** Add the props (`$props()` block) and render `ToolGatePrompt` in the assistant branch, right after the content render (after the `{#if isStreaming}…{/if}` ~line 150):
```svelte
{#if gateForMessage}
	<ToolGatePrompt
		variant={gateForMessage.kind}
		confirm={gateForMessage.kind === 'confirm' ? gateForMessage.frame : null}
		connect={gateForMessage.kind === 'connect' ? gateForMessage.frame : null}
		busy={gateBusy}
		onApprove={onGateApprove}
		onDeny={onGateDeny}
		onConnect={onGateConnect}
	/>
{/if}
```
Import `ToolGatePrompt` at the top (alongside `RefusalMessageBubble`). Add the new props with safe defaults so existing MessageBubble callers are unaffected.

- [ ] **Step 6: `svelte-check` clean.** `cd web && npm run check:lq-ai 2>&1 | tail -8` → no new errors. Fix any type mismatch in the prop wiring.

- [ ] **Step 7: Commit** (`git add` the two components).

---

## Task 5: OAuth-return handler (chats route) + Continue re-send

**Files:**
- Modify: `web/src/routes/lq-ai/chats/+page.svelte`
- Reference: `web/src/lib/lq-ai/chat/toolGate.ts` (`parseOAuthReturn`)

**Gate:** `svelte-check` clean; Task 7 confirms the return toast + Continue re-send works.

- [ ] **Step 1: Read the chats route** (`+page.svelte`) — how it mounts `ChatPanel`, how it accesses the active chat + the message store, and whether a toast utility is already imported (the OpenWebUI shell uses `svelte-sonner`'s `toast`; check the existing imports in this route or a sibling for the project's toast convention — reuse it; if none, use `svelte-sonner` `toast` which is already a shell dep).

- [ ] **Step 2: On mount, handle the OAuth return.** Using SvelteKit `$app/stores` `page` + `$app/navigation` (`goto` with `replaceState`):
```ts
import { page } from '$app/stores';
import { goto } from '$app/navigation';
import { parseOAuthReturn } from '$lib/lq-ai/chat/toolGate';
import { onMount } from 'svelte';

let mcpReturn: { status: 'connected' | 'error'; server: string | null } | null = null;

onMount(() => {
	const r = parseOAuthReturn(get(page).url.searchParams);
	if (r.status !== 'none') {
		mcpReturn = { status: r.status, server: r.server };
		// strip the query so a refresh doesn't re-trigger
		const url = new URL(get(page).url);
		url.searchParams.delete('mcp_connected');
		url.searchParams.delete('mcp_error');
		url.searchParams.delete('server');
		goto(url.pathname + url.search, { replaceState: true, noScroll: true, keepFocus: true });
	}
});
```

- [ ] **Step 3: Render a return banner/toast + Continue.** When `mcpReturn` is set, show a dismissible banner (or toast): connected → "Connected to {server}." with a **Continue** button; error → "Couldn't connect {server} — try again." The Continue button re-sends the last user message. Find how this route triggers a send (it owns or passes the send action to ChatPanel) — re-send by invoking the same send path with the **last user message's content** (from the message store: the last message with `role === 'user'`). If the send action lives inside ChatPanel, expose a minimal `resendLastUserMessage()` (bindable function or an event) on ChatPanel and call it. Keep it minimal — one affordance.
```svelte
{#if mcpReturn?.status === 'connected'}
	<div class="<banner classes>" data-testid="mcp-return-connected">
		Connected to {mcpReturn.server}.
		<button data-testid="mcp-continue" onclick={resendLastUserMessage}>Continue</button>
		<button onclick={() => (mcpReturn = null)}>Dismiss</button>
	</div>
{:else if mcpReturn?.status === 'error'}
	<div class="<banner classes>" data-testid="mcp-return-error">
		Couldn't connect {mcpReturn.server} — try again.
		<button onclick={() => (mcpReturn = null)}>Dismiss</button>
	</div>
{/if}
```
`resendLastUserMessage()`: read the message store, find the last `role === 'user'` message, and trigger the existing send with its `content`. If ChatPanel owns send, add a small exported/bindable method on ChatPanel and bind it here.

- [ ] **Step 4: `svelte-check` clean.**

- [ ] **Step 5: Commit.**

---

## Task 6: D6 narrative flip — "coming next" → "shipped"

**Files:**
- Modify: `web/static/learn/playgrounds/governed-tool-flow.html` (the `AVAILABILITY` block + the station 5/7 `<i>…next release…</i>` markers in the `TOGGLES` msgs)
- Modify: `web/src/routes/lq-ai/learn/how/+page.svelte` (section 17 availability sentence)
- Modify: `README.md` (the legal-research+MCP paragraph's availability sentence)

**Gate:** the three availability claims now say the in-chat confirmation/connect UI **ships**; nothing still says "coming next"; `svelte-check` clean.

- [ ] **Step 1: Explorer `AVAILABILITY` block.** In `governed-tool-flow.html`, change the availability panel so the in-chat confirmation prompt + connect-on-demand UI are in "Available today," and remove them from "Coming in the next release." If nothing remains under "coming next," replace that line with a forward pointer to the next sub-PR's surface (6c — rich case-law provenance), e.g.: "Coming next: rich case-law provenance + source-kinded citations (PR6c)." Keep it honest and centralized.

- [ ] **Step 2: Station 5 + 7 toggle messages.** In the `TOGGLES` object, update the `oauth` and `readonly` `msg` strings — remove the "<i>(That in-chat prompt ships in the next release…)</i>" hedge; they now describe the shipped in-chat prompt.

- [ ] **Step 3: Learn section 17 sentence.** In `how/+page.svelte` section 17, change the `<strong>Coming next:</strong> the in-chat confirmation and connect prompts…` clause — fold those into "Available today," and either drop "Coming next" or repoint it to 6c.

- [ ] **Step 4: README sentence.** In `README.md`, update the legal-research+MCP paragraph's italic availability sentence the same way (in-chat confirm/connect now shipped; repoint "next" to 6c provenance or drop).

- [ ] **Step 5: Grep to prove no stale "coming next" about the in-chat UI remains.**
```bash
cd /Users/kevinkeller/Code/lq-ai
grep -rn "next release\|coming next\|Coming next" web/static/learn/playgrounds/governed-tool-flow.html web/src/routes/lq-ai/learn/how/+page.svelte README.md
```
Confirm any remaining hit refers to 6c (provenance), not the in-chat confirm/connect UI.

- [ ] **Step 6: `svelte-check` clean; commit.**

---

## Task 7: Verification + ship

**Files:** none (verification + ship).

- [ ] **Step 1: Full web checks.**
```bash
cd /Users/kevinkeller/Code/lq-ai/web
npx vitest run src/lib/lq-ai/__tests__/sse-parser.test.ts src/lib/lq-ai/__tests__/toolGate.test.ts src/lib/lq-ai/__tests__/ToolGatePrompt.test.ts
npm run check:lq-ai 2>&1 | tail -8
```
Expected: vitest green; svelte-check no new errors.

- [ ] **Step 2: Build + visual check.** Rebuild the `web` container (pre-built bundle — a source change isn't visible until rebuild):
```bash
docker compose up -d --build web 2>&1 | tail -5
```
Then in a chat with an operator-enabled destructive tool (or by injecting the two SSE frames in a dev harness), confirm: the **confirm card** renders below the assistant turn with the tool + args summary + tier + destructive marker; Approve resumes into the same bubble; Deny finalizes; an expired pending shows the inline "re-send" notice; the **connect card** renders and its button redirects to the authorize URL; the `?mcp_connected` return shows the banner + Continue re-sends. Capture screenshots for the PR. (A static render of `ToolGatePrompt` in isolation — both variants — is an acceptable substitute screenshot if a live destructive tool isn't wired in the dev stack.)

- [ ] **Step 3: Push both remotes + open the PR.**
```bash
cd /Users/kevinkeller/Code/lq-ai
git push -u origin feat/pr6b-chat-tool-loop-ui
git push -u tucuxi feat/pr6b-chat-tool-loop-ui
gh pr create --repo LegalQuants/lq-ai --base main --head feat/pr6b-chat-tool-loop-ui \
  --title "PR6b/WS5: chat tool-loop UI — in-chat confirmation gate + connect-on-demand" \
  --body-file <(printf '%s\n' "<PR body: what it is; the two SSE events consumed; the resume + connect flows; chained-gate handling; the D6 availability flip; not security-gated (frontend); screenshots; case-law panel deferred to 6c>")
```
Frontend + narrative docs → **self-merge after CI green** (CI = Web svelte-check + Vitest + the api/gateway jobs which are unaffected). After merge, sync tucuxi main. The D6 obligation for 6b is discharged by Task 6.

---

## Self-Review (run before dispatching execution)

**Spec coverage:** Two SSE frames + callbacks (L1) → Task 1 ✓. Resume finalizes same message + chained gates via shared `consumeIntoMessage` (L3) → Task 4 ✓. In-message cards not modals, one `ToolGatePrompt` variant component (L2) → Task 3 + Task 4 ✓. Connect = same-tab redirect + `?mcp_connected` return + Continue (L4) → Task 2 (`buildAuthorizeUrl`) + Task 4 (`connectMcp`) + Task 5 ✓. D6 flip (L5) → Task 6 ✓. Error handling (resume 409, oauth error, chained gate) → Task 4 Step 3 + data-flow ✓. Tests (parser, toolGate, component) → Tasks 1–3 ✓. Non-goals respected (no case-law panel, no backend, no connections-management UI, no auto-resend) ✓.

**Placeholder scan:** Deterministic TS (parser, toolGate, api, the gate handlers) is provided verbatim. The Svelte component/route chrome is a concrete skeleton with explicit "mirror RefusalMessageBubble's classes / the route's toast convention" anchors (the house-style classes are best copied from the live files, exactly as 6a did) — not vague placeholders; each names the file to mirror and the exact data-testids/handlers. The PR body is a ship-time fill-in (Task 7).

**Consistency:** `pendingGate` shape (`{assistantId, kind:'confirm'|'connect', frame}`) is identical across ChatPanel (Task 4 Steps 2–4) and MessageBubble (`gateForMessage`, Task 4 Step 5). `resumeToolCall(chatId, pendingCallId, decision, signal)` signature matches between Task 2 (def) and Task 4 (call). `buildAuthorizeUrl`/`parseOAuthReturn` signatures match between Task 2 (def) and Tasks 4–5 (use). The two frame type names are consistent across Tasks 1, 3, 4.

**Execution note:** like 6a, the load-bearing verification is visual (the cards render + the flows work) plus the Vitest units — inline execution (controller can run vitest + build + headless-screenshot `ToolGatePrompt`) fits well, but the Task 1–3 units are clean TDD if dispatched subagent-driven.
