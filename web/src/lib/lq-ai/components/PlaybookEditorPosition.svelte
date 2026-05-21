<script lang="ts">
	/**
	 * PlaybookEditorPosition — inline editor for one playbook position
	 * (M3-A6 Phase 6 / Step 3). Composes a list of
	 * PlaybookEditorFallbackTier components for the fallback tiers.
	 *
	 * Surfaces every editable field per Decision §3.4: issue,
	 * description, standard_language, redline_strategy,
	 * severity_if_missing, detection_keywords, detection_examples, plus
	 * the ordered fallback_tiers list. The parent (PlaybookEditor)
	 * owns the positions array; reorder + remove happen there via
	 * on:moveup / on:movedown / on:remove events.
	 */
	import { createEventDispatcher } from 'svelte';

	import type { PositionCreate, FallbackTier, PositionSeverity } from '$lib/lq-ai/types';

	import PlaybookEditorFallbackTier from './PlaybookEditorFallbackTier.svelte';

	export let position: PositionCreate;
	export let index: number;
	export let total: number;
	export let disabled = false;

	const dispatch = createEventDispatcher<{
		moveup: void;
		movedown: void;
		remove: void;
	}>();

	const SEVERITIES: PositionSeverity[] = ['critical', 'high', 'medium', 'low'];

	$: canMoveUp = index > 0;
	$: canMoveDown = index < total - 1;
	$: tiers = position.fallback_tiers ?? [];
	$: keywords = position.detection_keywords ?? [];
	$: examples = position.detection_examples ?? [];

	let keywordDraft = '';

	function addKeyword(): void {
		const v = keywordDraft.trim();
		if (!v) return;
		const next = [...keywords, v];
		position.detection_keywords = next;
		keywordDraft = '';
	}

	function removeKeyword(i: number): void {
		const next = keywords.filter((_, k) => k !== i);
		position.detection_keywords = next;
	}

	function addExample(): void {
		position.detection_examples = [...examples, ''];
	}

	function removeExample(i: number): void {
		position.detection_examples = examples.filter((_, k) => k !== i);
	}

	function addTier(): void {
		const nextRank = tiers.length === 0 ? 1 : Math.max(...tiers.map((t) => t.rank)) + 1;
		const newTier: FallbackTier = { rank: nextRank, description: '', language: '' };
		position.fallback_tiers = [...tiers, newTier];
	}

	function removeTier(i: number): void {
		position.fallback_tiers = tiers.filter((_, k) => k !== i);
	}

	function moveTier(i: number, dir: -1 | 1): void {
		const next = [...tiers];
		const target = i + dir;
		if (target < 0 || target >= next.length) return;
		[next[i], next[target]] = [next[target], next[i]];
		position.fallback_tiers = next;
	}

	$: issueInvalid = !position.issue.trim();
</script>

<article
	class="lq-playbook-editor-position"
	data-testid="lq-playbook-editor-position"
	data-position-index={index}
>
	<header class="lq-playbook-editor-position__header">
		<div class="lq-playbook-editor-position__index">Position {index + 1}</div>
		<div class="lq-playbook-editor-position__controls">
			<button
				type="button"
				class="lq-playbook-editor-position__btn"
				on:click={() => dispatch('moveup')}
				disabled={disabled || !canMoveUp}
				aria-label="Move position up"
			>
				↑
			</button>
			<button
				type="button"
				class="lq-playbook-editor-position__btn"
				on:click={() => dispatch('movedown')}
				disabled={disabled || !canMoveDown}
				aria-label="Move position down"
			>
				↓
			</button>
			<button
				type="button"
				class="lq-playbook-editor-position__btn lq-playbook-editor-position__btn--danger"
				on:click={() => dispatch('remove')}
				{disabled}
				aria-label="Remove position"
			>
				Remove
			</button>
		</div>
	</header>

	<div class="lq-playbook-editor-position__field">
		<label
			class="lq-playbook-editor-position__label"
			for="lq-pe-pos-{index}-issue"
		>
			Issue
		</label>
		<input
			id="lq-pe-pos-{index}-issue"
			type="text"
			bind:value={position.issue}
			{disabled}
			class="lq-playbook-editor-position__input"
			class:lq-playbook-editor-position__input--invalid={issueInvalid}
			placeholder="What this position covers (e.g., 'Definition of Confidential Information')"
		/>
		{#if issueInvalid}
			<div class="lq-playbook-editor-position__hint lq-playbook-editor-position__hint--error">
				Issue is required.
			</div>
		{/if}
	</div>

	<div class="lq-playbook-editor-position__field">
		<label
			class="lq-playbook-editor-position__label"
			for="lq-pe-pos-{index}-description"
		>
			Description
		</label>
		<textarea
			id="lq-pe-pos-{index}-description"
			rows="2"
			bind:value={position.description}
			{disabled}
			class="lq-playbook-editor-position__textarea"
			placeholder="Plain-language summary of the position the team takes on this issue"
		></textarea>
	</div>

	<div class="lq-playbook-editor-position__grid">
		<div class="lq-playbook-editor-position__field">
			<label
				class="lq-playbook-editor-position__label"
				for="lq-pe-pos-{index}-severity"
			>
				Severity if missing
			</label>
			<select
				id="lq-pe-pos-{index}-severity"
				bind:value={position.severity_if_missing}
				{disabled}
				class="lq-playbook-editor-position__input"
			>
				{#each SEVERITIES as s}
					<option value={s}>{s}</option>
				{/each}
			</select>
		</div>

		<div class="lq-playbook-editor-position__field">
			<label
				class="lq-playbook-editor-position__label"
				for="lq-pe-pos-{index}-redline"
			>
				Redline strategy
			</label>
			<input
				id="lq-pe-pos-{index}-redline"
				type="text"
				bind:value={position.redline_strategy}
				{disabled}
				class="lq-playbook-editor-position__input"
				placeholder="How to handle when the contract deviates (e.g., 'add standard carve-outs')"
			/>
		</div>
	</div>

	<div class="lq-playbook-editor-position__field">
		<label
			class="lq-playbook-editor-position__label"
			for="lq-pe-pos-{index}-standard"
		>
			Standard language
		</label>
		<textarea
			id="lq-pe-pos-{index}-standard"
			rows="5"
			bind:value={position.standard_language}
			{disabled}
			class="lq-playbook-editor-position__textarea"
			placeholder="Verbatim language the team prefers for this clause"
		></textarea>
	</div>

	<div class="lq-playbook-editor-position__field">
		<div class="lq-playbook-editor-position__label">Detection keywords</div>
		<div class="lq-playbook-editor-position__keywords">
			{#each keywords as kw, i (i)}
				<span class="lq-playbook-editor-position__keyword">
					{kw}
					<button
						type="button"
						class="lq-playbook-editor-position__keyword-remove"
						on:click={() => removeKeyword(i)}
						{disabled}
						aria-label="Remove keyword"
					>
						×
					</button>
				</span>
			{/each}
		</div>
		<div class="lq-playbook-editor-position__keyword-add">
			<input
				type="text"
				bind:value={keywordDraft}
				on:keydown={(e) => {
					if (e.key === 'Enter') {
						e.preventDefault();
						addKeyword();
					}
				}}
				{disabled}
				class="lq-playbook-editor-position__input"
				placeholder="Add a keyword and press Enter"
			/>
			<button
				type="button"
				class="lq-playbook-editor-position__btn"
				on:click={addKeyword}
				{disabled}
			>
				Add
			</button>
		</div>
	</div>

	<div class="lq-playbook-editor-position__field">
		<div class="lq-playbook-editor-position__label">Detection examples</div>
		{#each examples as _, i (i)}
			<div class="lq-playbook-editor-position__example-row">
				<textarea
					rows="2"
					bind:value={position.detection_examples![i]}
					{disabled}
					class="lq-playbook-editor-position__textarea"
					placeholder="Verbatim contract clause illustrating this issue"
				></textarea>
				<button
					type="button"
					class="lq-playbook-editor-position__btn lq-playbook-editor-position__btn--danger"
					on:click={() => removeExample(i)}
					{disabled}
					aria-label="Remove example"
				>
					Remove
				</button>
			</div>
		{/each}
		<button
			type="button"
			class="lq-playbook-editor-position__btn"
			on:click={addExample}
			{disabled}
		>
			Add example
		</button>
	</div>

	<div class="lq-playbook-editor-position__field">
		<div class="lq-playbook-editor-position__label">Fallback tiers</div>
		<div class="lq-playbook-editor-position__tiers">
			{#each tiers as tier, i (i)}
				<PlaybookEditorFallbackTier
					bind:tier={position.fallback_tiers![i]}
					index={i}
					total={tiers.length}
					{disabled}
					on:moveup={() => moveTier(i, -1)}
					on:movedown={() => moveTier(i, 1)}
					on:remove={() => removeTier(i)}
				/>
			{/each}
		</div>
		<button
			type="button"
			class="lq-playbook-editor-position__btn"
			on:click={addTier}
			{disabled}
		>
			Add fallback tier
		</button>
	</div>
</article>

<style>
	.lq-playbook-editor-position {
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		padding: 1rem 1.125rem;
		background: var(--lq-surface);
		display: flex;
		flex-direction: column;
		gap: 0.875rem;
	}
	.lq-playbook-editor-position__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
	}
	.lq-playbook-editor-position__index {
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
	.lq-playbook-editor-position__controls {
		display: flex;
		gap: 0.25rem;
	}
	.lq-playbook-editor-position__btn {
		padding: 0.375rem 0.625rem;
		font-size: 0.8125rem;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.25rem;
		cursor: pointer;
		color: var(--lq-text-primary);
	}
	.lq-playbook-editor-position__btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.lq-playbook-editor-position__btn--danger {
		color: var(--lq-error, #b91c1c);
	}
	.lq-playbook-editor-position__field {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}
	.lq-playbook-editor-position__label {
		font-size: 0.8125rem;
		font-weight: 500;
		color: var(--lq-text-secondary);
	}
	.lq-playbook-editor-position__input,
	.lq-playbook-editor-position__textarea {
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
	.lq-playbook-editor-position__textarea {
		resize: vertical;
	}
	.lq-playbook-editor-position__input--invalid {
		border-color: var(--lq-error, #b91c1c);
	}
	.lq-playbook-editor-position__hint--error {
		font-size: 0.75rem;
		color: var(--lq-error, #b91c1c);
	}
	.lq-playbook-editor-position__grid {
		display: grid;
		grid-template-columns: 12rem 1fr;
		gap: 0.875rem;
	}
	@media (max-width: 600px) {
		.lq-playbook-editor-position__grid {
			grid-template-columns: 1fr;
		}
	}
	.lq-playbook-editor-position__keywords {
		display: flex;
		flex-wrap: wrap;
		gap: 0.375rem;
	}
	.lq-playbook-editor-position__keyword {
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		padding: 0.25rem 0.5rem;
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: 999px;
		font-size: 0.8125rem;
	}
	.lq-playbook-editor-position__keyword-remove {
		background: none;
		border: none;
		font-size: 1rem;
		line-height: 1;
		color: var(--lq-text-secondary);
		cursor: pointer;
		padding: 0;
	}
	.lq-playbook-editor-position__keyword-add {
		display: flex;
		gap: 0.5rem;
		margin-top: 0.25rem;
	}
	.lq-playbook-editor-position__example-row {
		display: flex;
		gap: 0.5rem;
		align-items: flex-start;
	}
	.lq-playbook-editor-position__tiers {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
</style>
