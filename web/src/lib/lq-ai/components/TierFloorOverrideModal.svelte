<script context="module" lang="ts">
	/**
	 * Pure helpers exported for unit tests. Mirrors the AttachKBModal /
	 * NewMatterModal pattern: keep validation + display logic out of the
	 * Svelte template so we can verify it without @testing-library/svelte.
	 */

	/**
	 * Reason length contract — 10..500 chars — pinned to match the T4
	 * backend's `/inference/override-tier-floor` server-side validation
	 * (overrideTierFloor() in api/inferenceOverride.ts notes the same range
	 * and does not pre-validate). Client-side validation here is a UX
	 * affordance; the backend remains the source of truth.
	 */
	export function validateReason(reason: string): { valid: boolean; error?: string } {
		if (reason.length < 10) return { valid: false, error: 'Reason must be at least 10 characters' };
		if (reason.length > 500) return { valid: false, error: 'Reason must be at most 500 characters' };
		return { valid: true };
	}

	/** "N/500" counter under the textarea. */
	export function reasonCounterText(reason: string): string {
		return `${reason.length}/500`;
	}
</script>

<script lang="ts">
	import { overrideTierFloor } from '../api/inferenceOverride';
	import type { Message } from '../types';
	// validateReason / reasonCounterText are declared in the module-context
	// script above; Svelte merges the two blocks at compile time so re-
	// importing them here would duplicate-identifier under svelte-check
	// (mirrors the AttachKBModal pattern).

	/**
	 * Tier-floor override confirmation modal.
	 *
	 * Opened by RefusalMessageBubble (T13) when an admin clicks "Override
	 * for this turn". Required reason textarea (10..500 chars) with live
	 * counter; on Confirm calls inferenceOverride.ts which POSTs to T4's
	 * `/api/v1/inference/override-tier-floor`. On 200 fires
	 * `onSuccess(ai_message)`; on error shows inline banner. Backdrop click
	 * + Cancel button close when not submitting.
	 */
	export let open: boolean;
	export let messageId: string;
	export let originalTier: string;
	export let enforcedTier: string;
	export let onClose: () => void;
	export let onSuccess: (newMessage: Message) => void;

	let reason = '';
	let submitting = false;
	let error: string | null = null;

	$: validation = validateReason(reason);
	$: canSubmit = validation.valid && !submitting;

	async function handleSubmit() {
		if (!canSubmit) return;
		submitting = true;
		error = null;
		try {
			const result = await overrideTierFloor(messageId, reason);
			onSuccess(result.ai_message);
			reason = '';
		} catch (e: unknown) {
			error =
				e instanceof Error ? (e.message ?? 'Override failed. Try again.') : 'Override failed. Try again.';
		} finally {
			submitting = false;
		}
	}

	function handleClose() {
		if (submitting) return;
		reason = '';
		error = null;
		onClose();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') handleClose();
	}
</script>

{#if open}
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="backdrop"
		role="dialog"
		aria-modal="true"
		aria-labelledby="override-title"
		tabindex="-1"
		on:click={handleClose}
		on:keydown={handleKeydown}
	>
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div
			class="modal"
			on:click|stopPropagation
			on:keydown|stopPropagation
		>
			<h2 id="override-title">Override tier floor for this turn</h2>
			<p>
				This will route to a {originalTier} tier provider for this single turn instead of the
				enforced {enforcedTier}-floor. The override is logged in the audit trail.
			</p>
			<label for="override-reason">Reason</label>
			<textarea
				id="override-reason"
				bind:value={reason}
				rows="4"
				placeholder="State a reason (10–500 chars)"
				disabled={submitting}
			/>
			<div class="counter" data-testid="reason-counter">{reasonCounterText(reason)}</div>
			{#if error}
				<div class="error-banner" role="alert" data-testid="error-banner">{error}</div>
			{/if}
			<div class="actions">
				<button
					type="button"
					class="cancel"
					on:click={handleClose}
					disabled={submitting}
				>
					Cancel
				</button>
				<button
					type="button"
					class="primary"
					on:click={handleSubmit}
					disabled={!canSubmit}
					data-testid="confirm-button"
				>
					{submitting ? 'Submitting…' : 'Confirm'}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}
	.modal {
		background: var(--lq-canvas);
		padding: 24px;
		border-radius: 8px;
		width: min(500px, 90vw);
	}
	h2 {
		margin: 0 0 10px 0;
		font-size: 16px;
	}
	p {
		font-size: 13px;
		color: var(--lq-text-secondary);
		margin: 0 0 12px 0;
	}
	label {
		display: block;
		font-size: 12px;
		color: var(--lq-text);
		margin-bottom: 4px;
	}
	textarea {
		width: 100%;
		margin-top: 6px;
		font-family: inherit;
		font-size: 13px;
		padding: 8px;
		border: 1px solid var(--lq-border-strong);
		border-radius: var(--lq-radius-input);
		box-sizing: border-box;
	}
	.counter {
		font-size: 11px;
		color: var(--lq-text-tertiary);
		text-align: right;
		margin-top: 2px;
	}
	.error-banner {
		background: var(--lq-danger-soft);
		color: var(--lq-danger);
		padding: 8px;
		border-radius: 4px;
		margin: 8px 0;
		font-size: 13px;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 16px;
	}
	.primary {
		background: var(--lq-accent);
		color: var(--lq-on-accent);
		border: 0;
		padding: 6px 14px;
		border-radius: var(--lq-radius-pill);
		cursor: pointer;
		font-size: 13px;
	}
	.primary:disabled {
		background: var(--lq-text-tertiary);
		cursor: not-allowed;
	}
	.cancel {
		background: transparent;
		border: 1px solid var(--lq-border-strong);
		padding: 6px 14px;
		border-radius: var(--lq-radius-pill);
		cursor: pointer;
		font-size: 13px;
	}
	.cancel:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
</style>
