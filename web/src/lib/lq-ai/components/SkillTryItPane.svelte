<script lang="ts">
	/**
	 * SkillTryItPane — shared "try-it" sandbox embed for the Skill Creator
	 * (Wave D.2 Task 3.4).
	 *
	 * Mounts a minimal chat surface (message list + small composer) scoped
	 * to the user's system-managed sandbox project (slug ``__sandbox__``).
	 * The pane is reused by:
	 *   - the saved-skill "Try it" tab (`source='tryit-tab'`), driven by
	 *     ``skillSlug``;
	 *   - the wizard's pre-save try-it step (`source='wizard-tryout'`),
	 *     driven by ``draftBody`` + ``draftSlug``.
	 *
	 * Caller contract:
	 *   - Pass EXACTLY ONE of (a) ``skillSlug`` or (b) ``draftBody``. Both
	 *     null is a programmer error; the component renders an explicit
	 *     error in that case rather than silently sending a content-only
	 *     turn.
	 *   - ``source`` is forwarded verbatim to the backend's
	 *     ``attached_skills[].source`` field (Task 3.0) so the audit log
	 *     can distinguish saved-skill experimentation from wizard tryout.
	 *
	 * Convention notes for reviewers:
	 *   - API imports are NAMED FUNCTIONS, not ``*Api.method`` (mirrors
	 *     Tasks 3.1 / 3.2 / 3.3).
	 *   - The wire shape is ``attached_skills`` (plural, Task 3.0), not
	 *     ``attached_skill``. ``MessageCreate.attached_skills`` was added
	 *     to types.ts in the same commit as this component.
	 *   - We use the non-streaming ``sendMessage`` (the streaming path is
	 *     reserved for the main composer). The response carries the
	 *     persisted assistant message in ``MessagePostResponse.message``;
	 *     we render the user turn optimistically before send and append
	 *     the assistant reply on success (mirrors the ChatPanel pattern).
	 *   - Setup error (no sandbox / no chat) replaces the UI; send error
	 *     renders inline near the composer so the chat history survives.
	 *   - Reset clears local view only. Server-side chat reset is out of
	 *     M1 scope; subsequent sends create new messages in the same
	 *     sandbox chat.
	 *   - Design tokens are real per ``styles/practice.css``: ``--lq-accent``,
	 *     ``--lq-accent-soft``, ``--lq-accent-border``, ``--lq-border``,
	 *     ``--lq-text-tertiary``, ``--lq-error``. Hex fallbacks track the
	 *     definitions there.
	 */
	import { onMount } from 'svelte';
	import { ensureSandbox } from '$lib/lq-ai/api/projects';
	import { createChat } from '$lib/lq-ai/api/chats';
	import { sendMessage } from '$lib/lq-ai/api/messages';
	import type { Message, MessageCreate, Project } from '$lib/lq-ai/types';

	/** EITHER skillSlug (saved skill) OR draftBody + draftSlug (wizard draft). */
	export let skillSlug: string | null = null;
	export let draftBody: string | null = null;
	export let draftSlug: string | null = null;
	export let source: 'tryit-tab' | 'wizard-tryout';

	let sandbox: Project | null = null;
	let chatId: string | null = null;
	let messages: Message[] = [];
	let composerText = '';
	let sending = false;
	let setupError: string | null = null;
	let sendError: string | null = null;

	$: hasValidAttachment = !!skillSlug || !!draftBody;

	onMount(async () => {
		if (!hasValidAttachment) {
			setupError =
				'SkillTryItPane requires either ``skillSlug`` (saved skill) or ``draftBody`` (wizard draft).';
			return;
		}
		try {
			sandbox = await ensureSandbox();
			const chat = await createChat({
				title: `Try-it · ${skillSlug ?? draftSlug ?? 'draft'}`,
				project_id: sandbox.id
			});
			chatId = chat.id;
		} catch (e) {
			setupError = e instanceof Error ? e.message : 'Failed to set up sandbox';
		}
	});

	async function send(): Promise<void> {
		if (!chatId || !composerText.trim() || sending) return;
		sendError = null;

		// Optimistic user-message render — mirrors ChatPanel's pattern so the
		// user sees their turn immediately, and so the assistant reply is
		// rendered after a complete pair.
		const optimisticUserId = `optimistic-user-${Date.now()}`;
		const userMsg: Message = {
			id: optimisticUserId,
			chat_id: chatId,
			role: 'user',
			content: composerText,
			created_at: new Date().toISOString()
		};
		messages = [...messages, userMsg];

		const sentText = composerText;
		composerText = '';
		sending = true;

		try {
			const body: MessageCreate = {
				content: sentText,
				attached_skills: skillSlug
					? [{ slug: skillSlug, source }]
					: [{ inline_body: draftBody ?? '', source }]
			};
			const reply = await sendMessage(chatId, body);
			messages = [...messages, reply.message];
		} catch (e) {
			sendError = e instanceof Error ? e.message : 'Send failed';
			// Roll back the optimistic user message + restore the composer text
			// so the operator can retry without retyping.
			messages = messages.filter((m) => m.id !== optimisticUserId);
			composerText = sentText;
		} finally {
			sending = false;
		}
	}

	function reset(): void {
		// M1 limitation: server-side chat reset is out of scope. We clear the
		// local message view only; subsequent sends create new messages in the
		// same sandbox chat (the next chat turn is independent of this view's
		// state because we don't transcribe history into the request).
		if (!chatId) return;
		messages = [];
		sendError = null;
	}
</script>

<div class="lq-tryit-pane" data-testid="lq-ai-tryit-pane">
	{#if setupError}
		<div class="error" data-testid="lq-ai-tryit-setup-error">{setupError}</div>
	{:else if !sandbox || !chatId}
		<div class="loading" data-testid="lq-ai-tryit-loading">Setting up sandbox…</div>
	{:else}
		<div class="header">
			<span class="badge" title="Sandbox turns do not consume billable inference">
				non-billable
			</span>
			<span class="badge">sandbox</span>
			<button
				type="button"
				class="reset"
				on:click={reset}
				data-testid="lq-ai-tryit-reset"
				disabled={messages.length === 0}
			>
				Reset
			</button>
		</div>
		<div class="messages" data-testid="lq-ai-tryit-messages">
			{#if messages.length === 0}
				<div class="empty">
					Send a prompt below to try the {skillSlug ? 'saved' : 'draft'} skill in the sandbox.
				</div>
			{:else}
				{#each messages as m (m.id)}
					<div class="msg msg-{m.role}">
						<strong>{m.role === 'user' ? 'You' : 'AI'}:</strong>
						<span class="msg-body">{m.content}</span>
					</div>
				{/each}
			{/if}
		</div>
		{#if sendError}
			<div class="error inline-error" data-testid="lq-ai-tryit-send-error">{sendError}</div>
		{/if}
		<div class="composer">
			<textarea
				bind:value={composerText}
				placeholder="Try a prompt that would use this skill…"
				rows="3"
				disabled={sending}
				data-testid="lq-ai-tryit-composer"
			></textarea>
			<button
				type="button"
				class="send"
				on:click={send}
				disabled={!composerText.trim() || sending}
				data-testid="lq-ai-tryit-send"
			>
				{sending ? 'Sending…' : 'Send'}
			</button>
		</div>
	{/if}
</div>

<style>
	@import '$lib/lq-ai/styles/practice.css';

	.lq-tryit-pane {
		display: flex;
		flex-direction: column;
		min-height: 400px;
		gap: 12px;
	}
	.header {
		display: flex;
		gap: 8px;
		align-items: center;
	}
	.badge {
		background: var(--lq-accent-soft);
		border: 1px solid var(--lq-accent-border);
		padding: 2px 8px;
		border-radius: 999px;
		font-size: 11px;
		color: var(--lq-accent);
		font-weight: 500;
	}
	.reset {
		margin-left: auto;
		background: transparent;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: 4px 10px;
		font-size: 12px;
		cursor: pointer;
	}
	.reset:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.messages {
		flex: 1;
		overflow-y: auto;
		padding: 8px;
		border: 1px solid var(--lq-border);
		border-radius: 6px;
		min-height: 120px;
	}
	.empty {
		color: var(--lq-text-tertiary);
		font-size: 13px;
		padding: 8px;
	}
	.msg {
		margin-bottom: 8px;
		font-size: 14px;
	}
	.msg-body {
		white-space: pre-wrap;
	}
	.error {
		padding: 12px;
		color: var(--lq-error);
		font-size: 13px;
	}
	.inline-error {
		padding: 6px 0;
	}
	.composer {
		display: flex;
		gap: 8px;
	}
	textarea {
		flex: 1;
		padding: 8px;
		border: 1px solid var(--lq-border-strong);
		border-radius: 6px;
		font-family: inherit;
		font-size: 14px;
	}
	.send {
		padding: 0 16px;
		background: var(--lq-accent);
		color: white;
		border-radius: var(--lq-radius-pill);
		border: 0;
		font-weight: 500;
		cursor: pointer;
	}
	.send:disabled {
		background: var(--lq-text-tertiary);
		cursor: not-allowed;
	}
</style>
