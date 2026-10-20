<script lang="ts">
	/**
	 * /lq-ai/admin/research-sources — in-app enable/disable of the fiduciary-grade
	 * authority sources (CourtListener, GovInfo, EDGAR, EUR-Lex). Mirrors the
	 * Provider keys card one layer down: hot-applied, secrets write-only.
	 */
	import { onMount } from 'svelte';
	import { adminApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { ToolProviderStatus } from '$lib/lq-ai/api/admin';

	const LABELS: Record<string, string> = {
		courtlistener: 'CourtListener (U.S. case law)',
		govinfo: 'GovInfo (U.S. Code + CFR)',
		edgar: 'SEC EDGAR (company filings)',
		eurlex: 'EUR-Lex (EU law + CJEU)'
	};

	let rows: ToolProviderStatus[] = [];
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;

	let editing: string | null = null;
	let draftKey = '';
	let saving = false;
	let toggling: string | null = null;

	onMount(load);

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			rows = (await adminApi.listToolProviders()).tool_providers;
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need admin access to manage research sources.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	function label(type: string): string {
		return LABELS[type] ?? type;
	}

	function startEdit(type: string): void {
		editing = type;
		draftKey = '';
		actionError = null;
		actionSuccess = null;
	}

	function cancelEdit(): void {
		editing = null;
		draftKey = '';
	}

	function describeError(err: unknown): string {
		if (err instanceof LQAIApiError) {
			if (err.status === 403) return 'You need admin access to manage research sources.';
			if (err.status === 400)
				return 'This gateway has runtime key storage disabled (no master key set).';
			if (err.status === 404) return 'That source is not available on this gateway.';
			if (err.status === 409)
				return 'That source is configured via the environment; edit gateway.yaml to change it.';
		}
		return err instanceof Error ? err.message : String(err);
	}

	async function enableKeyless(type: string): Promise<void> {
		toggling = type;
		actionError = null;
		actionSuccess = null;
		try {
			await adminApi.setToolProvider(type);
			actionSuccess = `Enabled ${label(type)}. It is hot-applied — research uses it now.`;
			await load();
		} catch (err) {
			actionError = describeError(err);
		} finally {
			toggling = null;
		}
	}

	async function saveKey(type: string): Promise<void> {
		const key = draftKey.trim();
		if (!key) {
			actionError = 'Paste a key first.';
			return;
		}
		if (/\s/.test(key)) {
			actionError = 'That key contains a space — paste just the key.';
			return;
		}
		saving = true;
		actionError = null;
		actionSuccess = null;
		try {
			await adminApi.setToolProvider(type, key);
			actionSuccess = `Saved a key for ${label(type)}. It is hot-applied.`;
			cancelEdit();
			await load();
		} catch (err) {
			actionError = describeError(err);
		} finally {
			saving = false;
		}
	}

	async function disable(type: string): Promise<void> {
		if (!confirm(`Disable ${label(type)}? Research will stop using it.`)) return;
		toggling = type;
		actionError = null;
		actionSuccess = null;
		try {
			await adminApi.deleteToolProvider(type);
			actionSuccess = `Disabled ${label(type)}.`;
			await load();
		} catch (err) {
			actionError = describeError(err);
		} finally {
			toggling = null;
		}
	}

	$: busy = saving || toggling !== null;
</script>

<div class="research-sources-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Research sources</h1>
		<p class="page-intro">
			Enable the authority sources LQ.AI can cite. Keys are stored encrypted and never shown.
			Changes apply immediately — no restart.
		</p>
	</header>

	{#if listError}
		<div class="error-banner" role="alert">{listError}</div>
	{/if}
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if actionSuccess}
		<div class="success-banner" role="status">{actionSuccess}</div>
	{/if}

	{#if loading && rows.length === 0}
		<p class="loading">Loading research sources…</p>
	{/if}

	{#if rows.length > 0}
		<table class="keys-table">
			<thead>
				<tr>
					<th>Source</th>
					<th>Status</th>
					<th>Key</th>
					<th class="keys-table-actions">Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as row (row.type)}
					<tr>
						<td>{label(row.type)}</td>
						<td>
							{#if row.enabled}
								<span class="badge badge-runtime">Available</span>
							{:else}
								<span class="muted">Unavailable</span>
							{/if}
						</td>
						<td>
							{#if !row.key_required}
								<span class="muted">No key needed</span>
							{:else if row.has_key}
								<span class="badge badge-runtime">Key set</span>
							{:else}
								<span class="muted">No key</span>
							{/if}
						</td>
						<td class="keys-table-actions">
							{#if row.key_required}
								<button
									type="button"
									class="action-button"
									on:click={() => startEdit(row.type)}
									disabled={busy}
								>
									{row.has_key ? 'Replace key' : 'Set key'}
								</button>
							{:else if !row.enabled}
								<button
									type="button"
									class="action-button"
									on:click={() => enableKeyless(row.type)}
									disabled={busy}
								>
									{toggling === row.type ? 'Enabling…' : 'Enable'}
								</button>
							{/if}
							{#if row.enabled}
								<button
									type="button"
									class="action-button danger"
									on:click={() => disable(row.type)}
									disabled={busy}
								>
									{toggling === row.type ? 'Disabling…' : 'Disable'}
								</button>
							{/if}
						</td>
					</tr>
					{#if editing === row.type}
						<tr class="edit-row">
							<td colspan="4">
								<div class="edit-form">
									<label class="edit-label" for={`key-${row.type}`}>
										API key for {label(row.type)}
										<input
											id={`key-${row.type}`}
											type="password"
											autocomplete="off"
											placeholder="Paste the key"
											bind:value={draftKey}
											class="edit-input"
										/>
									</label>
									<div class="edit-actions">
										<button
											type="button"
											class="install-button"
											on:click={() => saveKey(row.type)}
											disabled={saving || !draftKey.trim()}
										>
											{saving ? 'Saving…' : 'Save key'}
										</button>
										<button
											type="button"
											class="action-button"
											on:click={cancelEdit}
											disabled={saving}
										>
											Cancel
										</button>
									</div>
								</div>
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.research-sources-page {
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-5);
	}

	.page-header {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.page-intro {
		color: var(--lq-text-secondary);
		max-width: 60rem;
		font-size: 14px;
		line-height: 1.5;
	}

	.error-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border-radius: 6px;
		border: 1px solid var(--lq-error-border, #fbb);
	}

	.success-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border-radius: 6px;
		border: 1px solid var(--lq-success-border, #bfb);
	}

	.loading {
		color: var(--lq-text-secondary);
		padding: var(--lq-space-3);
	}

	.empty-state {
		color: var(--lq-text-secondary);
		font-style: italic;
		margin: 0;
	}

	.keys-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 14px;
	}

	.keys-table th,
	.keys-table td {
		text-align: left;
		padding: var(--lq-space-2) var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
	}

	.keys-table th {
		font-weight: 600;
		color: var(--lq-text-secondary);
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.keys-table-actions {
		text-align: right;
		white-space: nowrap;
	}

	.badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 999px;
		font-size: 12px;
		font-weight: 500;
	}

	.badge-runtime {
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
	}

	.badge-env {
		background: var(--lq-surface);
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
	}

	.muted {
		color: var(--lq-text-secondary);
	}

	.edit-row td {
		background: var(--lq-surface);
	}

	.edit-form {
		display: flex;
		gap: var(--lq-space-3);
		align-items: flex-end;
		flex-wrap: wrap;
	}

	.edit-label {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
		flex: 1;
		min-width: 22rem;
		font-size: 13px;
		color: var(--lq-text-secondary);
	}

	.edit-input {
		padding: var(--lq-space-2) var(--lq-space-3);
		border: 1px solid var(--lq-border);
		border-radius: 6px;
		background: var(--lq-bg, #fff);
		font-size: 14px;
	}

	.edit-actions {
		display: flex;
		gap: var(--lq-space-2);
	}

	.install-button {
		padding: var(--lq-space-2) var(--lq-space-4);
		background: var(--lq-accent);
		color: white;
		border: none;
		border-radius: 6px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}

	.install-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.action-button {
		padding: var(--lq-space-1) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
		cursor: pointer;
		border: 1px solid var(--lq-border);
		background: transparent;
		color: var(--lq-text);
		margin-left: var(--lq-space-2);
	}

	.action-button:first-child {
		margin-left: 0;
	}

	.action-button.danger {
		color: var(--lq-error-text, #b00);
		border-color: var(--lq-error-border, #fbb);
	}

	.action-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
