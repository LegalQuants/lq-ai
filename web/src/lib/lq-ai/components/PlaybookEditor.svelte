<script lang="ts">
	/**
	 * PlaybookEditor — full inline editor for a `PlaybookCreate`-shaped
	 * object (M3-A6 Phase 6 / Step 3). Decision §3.4 calls for surfacing
	 * every editable field per position + per fallback tier, with no
	 * "shallow vs full editor" toggle — this is the only edit surface
	 * the wizard offers before the operator saves.
	 *
	 * Usage: `<PlaybookEditor bind:playbook />` where `playbook` is a
	 * `PlaybookCreate`-shaped object. The wizard's Step 3 binds to
	 * `state.draft_playbook`; the M3-A6 detail page (post-merge) can
	 * reuse this for "edit existing playbook".
	 */
	import type { PlaybookCreate, PositionCreate } from '$lib/lq-ai/types';

	import PlaybookEditorPosition from './PlaybookEditorPosition.svelte';

	export let playbook: PlaybookCreate;
	export let disabled = false;

	$: positions = playbook.positions ?? [];

	function blankPosition(): PositionCreate {
		const nextOrder = positions.length;
		return {
			issue: '',
			description: '',
			standard_language: '',
			fallback_tiers: [],
			redline_strategy: '',
			severity_if_missing: 'medium',
			detection_keywords: [],
			detection_examples: [],
			position_order: nextOrder
		};
	}

	function addPosition(): void {
		playbook.positions = [...positions, blankPosition()];
	}

	function removePosition(i: number): void {
		playbook.positions = positions.filter((_, k) => k !== i);
	}

	function movePosition(i: number, dir: -1 | 1): void {
		const next = [...positions];
		const target = i + dir;
		if (target < 0 || target >= next.length) return;
		[next[i], next[target]] = [next[target], next[i]];
		// Keep position_order consistent with array index so the
		// backend doesn't have to rederive it.
		next.forEach((p, idx) => {
			p.position_order = idx;
		});
		playbook.positions = next;
	}
</script>

<section class="lq-playbook-editor" data-testid="lq-playbook-editor">
	<div class="lq-playbook-editor__header-grid">
		<label class="lq-playbook-editor__field">
			<span class="lq-playbook-editor__label">Name</span>
			<input
				type="text"
				bind:value={playbook.name}
				{disabled}
				class="lq-playbook-editor__input"
				placeholder="Playbook name shown in the library"
			/>
		</label>
		<label class="lq-playbook-editor__field">
			<span class="lq-playbook-editor__label">Contract type</span>
			<input
				type="text"
				bind:value={playbook.contract_type}
				{disabled}
				class="lq-playbook-editor__input"
				placeholder="e.g., NDA, MSA-SaaS, DPA"
			/>
		</label>
		<label class="lq-playbook-editor__field">
			<span class="lq-playbook-editor__label">Version</span>
			<input
				type="text"
				bind:value={playbook.version}
				{disabled}
				class="lq-playbook-editor__input"
				placeholder="1.0.0"
			/>
		</label>
		<label class="lq-playbook-editor__field lq-playbook-editor__field--wide">
			<span class="lq-playbook-editor__label">Description</span>
			<textarea
				rows="3"
				bind:value={playbook.description}
				{disabled}
				class="lq-playbook-editor__textarea"
				placeholder="Plain-language summary of when this playbook applies and how to read its results"
			></textarea>
		</label>
	</div>

	<div class="lq-playbook-editor__positions">
		<header class="lq-playbook-editor__positions-header">
			<h2>Positions</h2>
			<span class="lq-playbook-editor__positions-count">
				{positions.length} position{positions.length === 1 ? '' : 's'}
			</span>
		</header>

		{#if positions.length === 0}
			<div class="lq-playbook-editor__empty">
				No positions yet. Add one to start defining the team's standard.
			</div>
		{:else}
			<div class="lq-playbook-editor__position-list">
				{#each positions as _, i (i)}
					<PlaybookEditorPosition
						bind:position={playbook.positions![i]}
						index={i}
						total={positions.length}
						{disabled}
						on:moveup={() => movePosition(i, -1)}
						on:movedown={() => movePosition(i, 1)}
						on:remove={() => removePosition(i)}
					/>
				{/each}
			</div>
		{/if}

		<button
			type="button"
			class="lq-playbook-editor__add-position"
			on:click={addPosition}
			{disabled}
			data-testid="lq-playbook-editor-add-position"
		>
			Add position
		</button>
	</div>
</section>

<style>
	.lq-playbook-editor {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}
	.lq-playbook-editor__header-grid {
		display: grid;
		grid-template-columns: 2fr 1fr 1fr;
		gap: 0.75rem 1rem;
		padding: 1rem 1.125rem;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
	}
	.lq-playbook-editor__field--wide {
		grid-column: 1 / -1;
	}
	.lq-playbook-editor__field {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}
	.lq-playbook-editor__label {
		font-size: 0.8125rem;
		font-weight: 500;
		color: var(--lq-text-secondary);
	}
	.lq-playbook-editor__input,
	.lq-playbook-editor__textarea {
		padding: 0.5rem 0.625rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		background: var(--lq-surface);
		color: var(--lq-text-primary);
		font-size: 0.875rem;
		font-family: inherit;
		width: 100%;
		box-sizing: border-box;
	}
	.lq-playbook-editor__textarea {
		resize: vertical;
	}
	.lq-playbook-editor__positions {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.lq-playbook-editor__positions-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 0.5rem;
	}
	.lq-playbook-editor__positions-header h2 {
		margin: 0;
		font-size: 1.125rem;
	}
	.lq-playbook-editor__positions-count {
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
	}
	.lq-playbook-editor__empty {
		padding: 1.5rem;
		text-align: center;
		color: var(--lq-text-secondary);
		background: var(--lq-inset);
		border-radius: 0.5rem;
	}
	.lq-playbook-editor__position-list {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.lq-playbook-editor__add-position {
		align-self: flex-start;
		padding: 0.5rem 0.875rem;
		background: var(--lq-surface);
		border: 1px dashed var(--lq-border);
		border-radius: 0.375rem;
		color: var(--lq-text-primary);
		font-size: 0.875rem;
		cursor: pointer;
	}
	.lq-playbook-editor__add-position:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	@media (max-width: 600px) {
		.lq-playbook-editor__header-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
