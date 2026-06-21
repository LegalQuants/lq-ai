<script lang="ts">
	/**
	 * /lq-ai/admin/provider-keys — in-app BYOK provider-key management.
	 *
	 * Lets an admin paste an OpenAI / Anthropic (etc.) API key for any configured
	 * provider. Keys are sent to the backend proxy (/api/v1/admin/provider-keys),
	 * which hands them to the gateway; the gateway encrypts them at rest with its
	 * master key (ADR 0011) and hot-applies the rebuilt adapter — no restart. No
	 * full key is ever returned: each row shows only the last 4 characters.
	 *
	 * Scope (release): list + add/replace + revoke. "Rotate" is just add/replace
	 * again (POST replaces in place). Revoke only applies to runtime keys — an
	 * env-sourced key (set in the launcher .env / first-run wizard) is owned by the
	 * operator and is removed there, so the gateway returns 409 and we say so.
	 */
	import { onMount } from 'svelte';

	import { adminApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { ProviderKeyStatus } from '$lib/lq-ai/api/admin';

	let rows: ProviderKeyStatus[] = [];
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;

	// Per-row UI state, keyed by provider name.
	let editing: string | null = null;
	let draftKey = '';
	let saving = false;
	let revoking: string | null = null;

	onMount(load);

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const res = await adminApi.listProviderKeys();
			rows = res.provider_keys;
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need admin access to manage provider keys.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	function startEdit(provider: string): void {
		editing = provider;
		draftKey = '';
		actionError = null;
		actionSuccess = null;
	}

	function cancelEdit(): void {
		editing = null;
		draftKey = '';
	}

	function describeSetError(err: unknown): string {
		if (err instanceof LQAIApiError) {
			if (err.status === 403) return 'You need admin access to manage provider keys.';
			if (err.status === 400) {
				return (
					'This gateway has runtime key storage disabled (no master key). ' +
					'Re-create the LQ.AI stack with the latest launcher, which mints one ' +
					'automatically, then try again.'
				);
			}
			if (err.status === 404) return 'That provider is not configured on this gateway.';
		}
		return err instanceof Error ? err.message : String(err);
	}

	async function saveKey(provider: string): Promise<void> {
		const key = draftKey.trim();
		if (!key) {
			actionError = 'Paste a key first.';
			return;
		}
		if (/\s/.test(key)) {
			actionError = 'That key contains a space — paste just the key (no quotes or extra text).';
			return;
		}
		saving = true;
		actionError = null;
		actionSuccess = null;
		try {
			await adminApi.setProviderKey(provider, key);
			actionSuccess = `Saved a key for ${provider}. It is hot-applied — your next chat uses it.`;
			cancelEdit();
			await load();
		} catch (err) {
			actionError = describeSetError(err);
		} finally {
			saving = false;
		}
	}

	async function revoke(provider: string): Promise<void> {
		const confirmed = confirm(
			`Revoke the runtime key for "${provider}"? Requests routed to it will fail ` +
				`until a new key is set. (A key set in the launcher .env is removed there, not here.)`
		);
		if (!confirmed) return;
		revoking = provider;
		actionError = null;
		actionSuccess = null;
		try {
			await adminApi.revokeProviderKey(provider);
			actionSuccess = `Revoked the runtime key for ${provider}.`;
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 409) {
				actionError =
					`"${provider}" uses a key from the environment (launcher .env / first-run ` +
					`wizard), not the runtime store. Remove it there instead.`;
			} else if (err instanceof LQAIApiError && err.status === 404) {
				actionError = 'That provider is not configured on this gateway.';
			} else if (err instanceof LQAIApiError && err.status === 403) {
				actionError = 'You need admin access to manage provider keys.';
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			revoking = null;
		}
	}

	function statusLabel(row: ProviderKeyStatus): string {
		if (row.last4) return `•••• ${row.last4}`;
		if (row.configured) return 'Configured';
		return 'Not set';
	}

	// A key is present if the gateway resolved one (last4) or built the adapter —
	// independent of `source`, so the button never says "Set key" over a real key.
	function hasKey(row: ProviderKeyStatus): boolean {
		return Boolean(row.last4) || row.configured;
	}

	// One mutation at a time: while any save/revoke is in flight, disable the other
	// rows' actions so their handlers can't clobber the shared status banner.
	$: busy = saving || revoking !== null;
</script>

<div class="provider-keys-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Provider keys</h1>
		<p class="page-intro">
			Add the API key for each AI provider you use (OpenAI, Anthropic, …). Keys are
			<strong>encrypted at rest</strong> by the on-device Inference Gateway and
			<strong>hot-applied with no restart</strong> — your next chat uses them immediately. Only the last
			four characters are ever shown back; the full key never leaves the gateway.
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
		<p class="loading">Loading provider keys…</p>
	{/if}

	{#if !loading && rows.length === 0 && !listError}
		<p class="empty-state">No providers are configured on this gateway.</p>
	{/if}

	{#if rows.length > 0}
		<table class="keys-table">
			<thead>
				<tr>
					<th>Provider</th>
					<th>Type</th>
					<th>Status</th>
					<th>Source</th>
					<th class="keys-table-actions">Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as row (row.provider)}
					<tr>
						<td><code>{row.provider}</code></td>
						<td>{row.type}</td>
						<td>{statusLabel(row)}</td>
						<td>
							{#if row.source === 'runtime'}
								<span class="badge badge-runtime">runtime</span>
							{:else if row.source === 'env'}
								<span class="badge badge-env">.env</span>
							{:else}
								<span class="muted">—</span>
							{/if}
						</td>
						<td class="keys-table-actions">
							<button
								type="button"
								class="action-button"
								on:click={() => startEdit(row.provider)}
								disabled={busy}
							>
								{hasKey(row) ? 'Replace key' : 'Set key'}
							</button>
							{#if row.source === 'runtime'}
								<button
									type="button"
									class="action-button danger"
									on:click={() => revoke(row.provider)}
									disabled={busy}
								>
									{revoking === row.provider ? 'Revoking…' : 'Revoke'}
								</button>
							{/if}
						</td>
					</tr>
					{#if editing === row.provider}
						<tr class="edit-row">
							<td colspan="5">
								<div class="edit-form">
									<label class="edit-label" for={`key-${row.provider}`}>
										API key for <code>{row.provider}</code>
										<input
											id={`key-${row.provider}`}
											type="password"
											autocomplete="off"
											placeholder="Paste the key (sk-ant-… / sk-…)"
											bind:value={draftKey}
											class="edit-input"
										/>
									</label>
									<div class="edit-actions">
										<button
											type="button"
											class="install-button"
											on:click={() => saveKey(row.provider)}
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
	.provider-keys-page {
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
