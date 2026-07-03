<script context="module" lang="ts">
	/**
	 * FilePickerDropdown — multi-select referenced-documents picker
	 * (referenced-files Phase 2). Checkbox-set pattern from AttachKBModal, search
	 * pattern from SkillPicker. Unlike MentionPopover this DOES render
	 * non-ready files — disabled, with a "Preparing…" badge — so the user
	 * can see why a document isn't offered yet (P4 made visible).
	 */
	import {
		MESSAGE_REFERENCED_FILES_MAX,
		filterReferenceable,
		type ReferencedFile
	} from '../files/referenceable';

	export function rowDisabled(
		file: ReferencedFile,
		selected: boolean,
		capReached: boolean
	): boolean {
		if (!file.ready) return true;
		return capReached && !selected;
	}
</script>

<script lang="ts">
	export let files: ReferencedFile[];
	export let loading: boolean = false;
	export let error: string | null = null;
	export let failedKbCount: number = 0;
	export let selectedIds: string[];
	export let capReached: boolean = false;
	export let onToggle: (file: ReferencedFile) => void;
	export let onClose: () => void;
	export let onRetry: () => void;

	let searchTerm = '';

	$: filtered = filterReferenceable(files, searchTerm);
	$: selectedSet = new Set(selectedIds);

	function onWindowKey(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			onClose();
		}
	}
</script>

<svelte:window on:keydown={onWindowKey} />

<div
	class="lq-file-picker"
	data-testid="lq-ai-file-picker"
	role="dialog"
	aria-label="Reference documents"
>
	<div class="lq-file-picker__head">
		<input
			type="search"
			class="lq-file-picker__search"
			placeholder="Search matter documents…"
			bind:value={searchTerm}
			data-testid="lq-ai-file-picker-search"
		/>
		<button
			type="button"
			class="lq-file-picker__done"
			on:click={onClose}
			data-testid="lq-ai-file-picker-done"
		>
			Done
		</button>
	</div>

	{#if loading}
		<div class="lq-file-picker__status">Loading documents…</div>
	{:else if error}
		<div class="lq-file-picker__status lq-file-picker__status--error">
			Couldn't load documents ·
			<button type="button" class="lq-file-picker__retry" on:click={onRetry}>retry</button>
		</div>
	{:else if files.length === 0}
		<div class="lq-file-picker__status" data-testid="lq-ai-file-picker-empty">
			No documents in this matter's knowledge bases yet.
		</div>
	{:else}
		{#if failedKbCount > 0}
			<div class="lq-file-picker__status lq-file-picker__status--error">
				{failedKbCount} knowledge base{failedKbCount === 1 ? '' : 's'} failed to load ·
				<button type="button" class="lq-file-picker__retry" on:click={onRetry}>retry</button>
			</div>
		{/if}
		{#if capReached}
			<div class="lq-file-picker__status" data-testid="lq-ai-file-picker-cap">
				Reference limit reached ({MESSAGE_REFERENCED_FILES_MAX} documents per message).
			</div>
		{/if}
		{#each filtered as f (f.id)}
			{@const disabled = rowDisabled(f, selectedSet.has(f.id), capReached)}
			<label class="lq-file-picker__row" class:disabled data-testid="lq-ai-file-picker-row">
				<input
					type="checkbox"
					checked={selectedSet.has(f.id)}
					{disabled}
					on:change={() => onToggle(f)}
				/>
				<span class="lq-file-picker__name" title={f.filename}>{f.filename}</span>
				{#if !f.ready}
					<span class="lq-file-picker__badge">Preparing…</span>
				{/if}
			</label>
		{:else}
			<div class="lq-file-picker__status">No documents match “{searchTerm}”.</div>
		{/each}
	{/if}
</div>

<style>
	.lq-file-picker {
		display: flex;
		flex-direction: column;
		min-width: 300px;
		max-width: clamp(300px, 90vw, 440px);
		max-height: 340px;
		overflow-y: auto;
		background: var(--lq-surface, var(--lq-canvas, #ffffff));
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius, 6px);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
		padding: var(--lq-space-1, 4px);
		font-family: var(--lq-font-sans);
		font-size: 13px;
		color: var(--lq-text, #1a1a1a);
	}

	.lq-file-picker__head {
		display: flex;
		gap: var(--lq-space-1, 4px);
		padding: var(--lq-space-1, 4px);
	}

	.lq-file-picker__search {
		flex: 1;
		font: inherit;
		padding: 4px var(--lq-space-2, 8px);
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius-sm, 4px);
	}

	.lq-file-picker__done {
		background: none;
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius-sm, 4px);
		padding: 4px var(--lq-space-2, 8px);
		font: inherit;
		cursor: pointer;
	}

	.lq-file-picker__status {
		padding: var(--lq-space-2, 8px) var(--lq-space-3, 12px);
		color: var(--lq-text-tertiary, #9ca3af);
		font-size: 12px;
	}

	.lq-file-picker__status--error {
		color: var(--lq-error, #b54848);
	}

	.lq-file-picker__retry {
		background: none;
		border: 0;
		padding: 0;
		color: inherit;
		font: inherit;
		text-decoration: underline;
		cursor: pointer;
	}

	.lq-file-picker__row {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2, 8px);
		padding: var(--lq-space-2, 8px) var(--lq-space-3, 12px);
		border-radius: var(--lq-radius-sm, 4px);
		cursor: pointer;
	}

	.lq-file-picker__row:hover:not(.disabled) {
		background: var(--lq-accent-soft, #e8f4ec);
	}

	.lq-file-picker__row.disabled {
		color: var(--lq-text-tertiary, #9ca3af);
		cursor: not-allowed;
	}

	.lq-file-picker__name {
		flex: 1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.lq-file-picker__badge {
		font-size: 11px;
		color: var(--lq-text-tertiary, #9ca3af);
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: 999px;
		padding: 0 6px;
	}
</style>
