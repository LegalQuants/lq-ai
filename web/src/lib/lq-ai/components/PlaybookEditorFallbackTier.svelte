<script lang="ts">
	/**
	 * PlaybookEditorFallbackTier — inline editor for one fallback tier
	 * inside a position (M3-A6 Phase 6 / Step 3).
	 *
	 * A position carries an ordered list of fallback tiers; the
	 * playbook executor walks them in `rank` order looking for a tier
	 * the contract satisfies if the position's standard language is
	 * absent. This component surfaces `rank` (int), `description`, and
	 * `language` (the canonical alternative phrasing the executor will
	 * cite).
	 *
	 * Bound via `bind:tier`. The parent (PlaybookEditorPosition) owns
	 * the array; reorder + remove happen at that level via on:moveup /
	 * on:movedown / on:remove events.
	 */
	import { createEventDispatcher } from 'svelte';

	import type { FallbackTier } from '$lib/lq-ai/types';

	export let tier: FallbackTier;
	export let index: number;
	export let total: number;
	export let disabled = false;

	const dispatch = createEventDispatcher<{
		moveup: void;
		movedown: void;
		remove: void;
	}>();

	$: canMoveUp = index > 0;
	$: canMoveDown = index < total - 1;
</script>

<div class="lq-playbook-editor-tier" data-testid="lq-playbook-editor-tier">
	<header class="lq-playbook-editor-tier__header">
		<div class="lq-playbook-editor-tier__title">Fallback tier {index + 1}</div>
		<div class="lq-playbook-editor-tier__controls">
			<button
				type="button"
				class="lq-playbook-editor-tier__btn"
				on:click={() => dispatch('moveup')}
				disabled={disabled || !canMoveUp}
				aria-label="Move tier up"
			>
				↑
			</button>
			<button
				type="button"
				class="lq-playbook-editor-tier__btn"
				on:click={() => dispatch('movedown')}
				disabled={disabled || !canMoveDown}
				aria-label="Move tier down"
			>
				↓
			</button>
			<button
				type="button"
				class="lq-playbook-editor-tier__btn lq-playbook-editor-tier__btn--danger"
				on:click={() => dispatch('remove')}
				{disabled}
				aria-label="Remove tier"
			>
				Remove
			</button>
		</div>
	</header>

	<div class="lq-playbook-editor-tier__grid">
		<label class="lq-playbook-editor-tier__field lq-playbook-editor-tier__field--rank">
			<span class="lq-playbook-editor-tier__label">Rank</span>
			<input
				type="number"
				min="1"
				step="1"
				bind:value={tier.rank}
				{disabled}
				class="lq-playbook-editor-tier__input"
			/>
		</label>
		<label class="lq-playbook-editor-tier__field lq-playbook-editor-tier__field--description">
			<span class="lq-playbook-editor-tier__label">Description</span>
			<textarea
				bind:value={tier.description}
				rows="2"
				{disabled}
				class="lq-playbook-editor-tier__textarea"
				placeholder="What this fallback covers (e.g., 'mutual NDA with a 3-year term')"
			></textarea>
		</label>
		<label class="lq-playbook-editor-tier__field lq-playbook-editor-tier__field--language">
			<span class="lq-playbook-editor-tier__label">Acceptable language</span>
			<textarea
				bind:value={tier.language}
				rows="4"
				{disabled}
				class="lq-playbook-editor-tier__textarea"
				placeholder="Verbatim clause language the executor will accept as a match for this tier"
			></textarea>
		</label>
	</div>
</div>

<style>
	.lq-playbook-editor-tier {
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		padding: 0.75rem 0.875rem;
		background: var(--lq-inset, transparent);
	}
	.lq-playbook-editor-tier__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
	}
	.lq-playbook-editor-tier__title {
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
	.lq-playbook-editor-tier__controls {
		display: flex;
		gap: 0.25rem;
	}
	.lq-playbook-editor-tier__btn {
		padding: 0.25rem 0.5rem;
		font-size: 0.75rem;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.25rem;
		cursor: pointer;
	}
	.lq-playbook-editor-tier__btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.lq-playbook-editor-tier__btn--danger {
		color: var(--lq-error, #b91c1c);
	}
	.lq-playbook-editor-tier__grid {
		display: grid;
		grid-template-columns: 5rem 1fr;
		gap: 0.5rem 0.75rem;
	}
	.lq-playbook-editor-tier__field--description,
	.lq-playbook-editor-tier__field--language {
		grid-column: 1 / -1;
	}
	.lq-playbook-editor-tier__field {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.lq-playbook-editor-tier__label {
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
		font-weight: 500;
	}
	.lq-playbook-editor-tier__input,
	.lq-playbook-editor-tier__textarea {
		padding: 0.375rem 0.5rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.25rem;
		background: var(--lq-surface);
		color: var(--lq-text-primary);
		font-size: 0.875rem;
		font-family: inherit;
	}
	.lq-playbook-editor-tier__textarea {
		resize: vertical;
	}
</style>
