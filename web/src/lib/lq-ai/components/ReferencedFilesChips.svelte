<script lang="ts">
	/**
	 * referenced-files Phase 2 — the authoritative referenced-files set, rendered
	 * as removable chips above the composer. Both entry affordances
	 * (FilePickerDropdown, MentionPopover) converge on this one row.
	 */
	import type { ReferencedFile } from '../files/referenceable';

	export let files: ReferencedFile[];
	export let notice: string | null = null;
	export let onRemove: (id: string) => void;
</script>

{#if files.length > 0 || notice}
	<div class="lq-ref-chips" data-testid="lq-ai-referenced-chips">
		{#each files as f (f.id)}
			<span class="lq-ref-chip" data-testid="lq-ai-referenced-chip">
				<span class="lq-ref-chip__icon" aria-hidden="true">📄</span>
				<span class="lq-ref-chip__name" title={f.filename}>{f.filename}</span>
				<button
					type="button"
					class="lq-ref-chip__remove"
					aria-label={`Remove ${f.filename}`}
					on:click={() => onRemove(f.id)}
				>
					×
				</button>
			</span>
		{/each}
		{#if notice}
			<span class="lq-ref-chips__notice" data-testid="lq-ai-referenced-notice">{notice}</span>
		{/if}
	</div>
{/if}

<style>
	.lq-ref-chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--lq-space-1, 4px);
		padding: var(--lq-space-1, 4px) 0;
		font-family: var(--lq-font-sans);
		font-size: 12px;
	}

	.lq-ref-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		max-width: 220px;
		padding: 2px var(--lq-space-2, 8px);
		border: 1px solid var(--lq-accent-border, #cfe4d8);
		border-radius: 999px;
		background: var(--lq-accent-soft, #e8f4ec);
		color: var(--lq-text, #1a1a1a);
	}

	.lq-ref-chip__name {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.lq-ref-chip__remove {
		background: none;
		border: 0;
		padding: 0 2px;
		font: inherit;
		color: var(--lq-text-tertiary, #9ca3af);
		cursor: pointer;
	}

	.lq-ref-chip__remove:hover {
		color: var(--lq-text, #1a1a1a);
	}

	.lq-ref-chips__notice {
		color: var(--lq-text-tertiary, #9ca3af);
	}
</style>
