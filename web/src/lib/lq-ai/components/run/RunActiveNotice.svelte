<script lang="ts">
	/**
	 * Names the run that is holding the owner's single active-run allowance, in any
	 * chat, so the composer can say what is blocking a new one (ADR 0038 D1, D6).
	 *
	 * A run in another chat can be opened from here. An uncertain run in another chat
	 * can be closed from here. A run in this chat already has its own controls in the
	 * thread, so the notice points there instead of repeating them.
	 *
	 * The chat title is the owner's own text and is rendered as text only.
	 */
	import type { ActiveRun } from '$lib/lq-ai/api/orchestration';
	import {
		CLOSE_RUN_NOTE,
		activeRunLabel,
		activeRunStatusText,
		canCloseActiveRun
	} from '$lib/lq-ai/run/composer';

	export let active: ActiveRun;
	export let currentChatId: string | null = null;
	export let busy = false;
	export let error: string | null = null;
	export let onOpen: () => void = () => undefined;
	export let onClose: () => void = () => undefined;

	$: here = currentChatId !== null && active.chat_id === currentChatId;
	$: label = activeRunLabel(active, currentChatId);
	$: statusText = activeRunStatusText(active.status);
	$: uncertain = canCloseActiveRun(active);
</script>

<div
	class="notice"
	class:uncertain
	role="status"
	data-testid="lq-ai-run-active-notice"
	data-status={active.status}
>
	<p class="line"><strong>{label}</strong> · {statusText}</p>
	{#if here}
		<p class="hint">
			{uncertain
				? 'Close it from its message in this thread to start another run.'
				: 'Its progress and controls are in its message in this thread.'}
		</p>
	{:else}
		<div class="actions">
			{#if active.chat_id}
				<button type="button" data-testid="lq-ai-run-active-open" on:click={onOpen}>
					Open that chat
				</button>
			{/if}
			{#if uncertain}
				<button
					type="button"
					class="close"
					data-testid="lq-ai-run-close"
					disabled={busy}
					on:click={onClose}
				>
					Close run
				</button>
				<span class="hint">{CLOSE_RUN_NOTE}</span>
			{/if}
		</div>
	{/if}
	{#if error}<p class="error" role="alert">{error}</p>{/if}
</div>

<style>
	@import '../../styles/practice.css';

	.notice {
		padding: 0.5rem 0.75rem;
		border: 1px solid var(--lq-tier-border);
		border-left: 4px solid var(--lq-tier);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-tier-soft);
		font-size: 0.82rem;
		line-height: 1.5;
	}
	.notice.uncertain {
		border-color: var(--lq-warn-border);
		border-left-color: var(--lq-warn);
		background: var(--lq-warn-soft);
	}
	p {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.hint {
		margin-top: 0.15rem;
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem 0.6rem;
		margin-top: 0.35rem;
	}
	.actions .hint {
		flex: 1 1 14rem;
		margin: 0;
	}
	button {
		background: var(--lq-canvas);
		color: var(--lq-text);
		border: 1px solid var(--lq-border-strong);
		border-radius: var(--lq-radius);
		padding: 0.25rem 0.65rem;
		font-size: 0.78rem;
		cursor: pointer;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
	button:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.close {
		background: var(--lq-accent);
		border-color: var(--lq-accent);
		color: white;
	}
	.error {
		margin-top: 0.35rem;
		color: var(--lq-error);
		font-size: 0.78rem;
	}
</style>
