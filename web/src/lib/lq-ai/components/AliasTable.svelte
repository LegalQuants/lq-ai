<script lang="ts">
	/**
	 * AliasTable — the admin view of model_aliases (D0.5).
	 *
	 * Renders one row per configured alias with name / provider / model /
	 * fallback-count / Edit + Delete actions. Parent owns the data + handlers
	 * so this component is purely presentational.
	 */
	import type { Alias } from '../api/admin';

	export let aliases: Alias[] = [];
	export let onEdit: (alias: Alias) => void = () => undefined;
	export let onDelete: (alias: Alias) => void = () => undefined;
	export let busy: boolean = false;
</script>

<div class="border lq-t-border rounded-md overflow-hidden" data-testid="lq-ai-alias-table">
	<table class="w-full text-sm">
		<thead class="lq-t-inset text-xs uppercase tracking-wide lq-t-text2">
			<tr>
				<th class="text-left px-3 py-2">Alias</th>
				<th class="text-left px-3 py-2">Provider</th>
				<th class="text-left px-3 py-2">Model</th>
				<th class="text-left px-3 py-2">Fallback</th>
				<th class="text-right px-3 py-2">Actions</th>
			</tr>
		</thead>
		<tbody>
			{#if aliases.length === 0}
				<tr>
					<td colspan="5" class="px-3 py-6 text-center lq-t-text2" data-testid="lq-ai-alias-table-empty">
						No aliases configured.
					</td>
				</tr>
			{:else}
				{#each aliases as alias (alias.name)}
					<tr
						class="border-t lq-t-border"
						data-testid="lq-ai-alias-row"
						data-alias-name={alias.name}
					>
						<td class="px-3 py-2 font-medium">{alias.name}</td>
						<td class="px-3 py-2 lq-t-text2">{alias.provider}</td>
						<td class="px-3 py-2 lq-t-text2 font-mono text-xs">
							{alias.model}
						</td>
						<td class="px-3 py-2 lq-t-text2 text-xs">
							{alias.fallback.length > 0
								? `${alias.fallback.length} fallback${alias.fallback.length === 1 ? '' : 's'}`
								: '—'}
						</td>
						<td class="px-3 py-2 text-right space-x-2">
							<button
								type="button"
								class="text-xs px-2 py-1 rounded border lq-t-border-strong lq-t-hover"
								on:click={() => onEdit(alias)}
								disabled={busy}
								data-testid="lq-ai-alias-edit-btn"
							>
								Edit
							</button>
							<button
								type="button"
								class="text-xs px-2 py-1 rounded border lq-t-error-border lq-t-error lq-t-error-hover"
								on:click={() => onDelete(alias)}
								disabled={busy}
								data-testid="lq-ai-alias-delete-btn"
							>
								Delete
							</button>
						</td>
					</tr>
				{/each}
			{/if}
		</tbody>
	</table>
</div>

<style>
	/* Colour tokens replacing Tailwind palette utilities (S1-1b). */
	.lq-t-border {
		border-color: var(--lq-border);
	}
	.lq-t-border-strong {
		border-color: var(--lq-border-strong);
	}
	.lq-t-error {
		color: var(--lq-error);
	}
	.lq-t-error-border {
		border-color: var(--lq-error-border);
	}
	.lq-t-error-hover:hover {
		background-color: var(--lq-error-bg);
	}
	.lq-t-hover:hover {
		background-color: var(--lq-surface-hover);
	}
	.lq-t-inset {
		background-color: var(--lq-inset);
	}
	.lq-t-text2 {
		color: var(--lq-text-secondary);
	}
</style>
