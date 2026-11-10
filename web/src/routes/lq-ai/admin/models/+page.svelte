<script lang="ts">
	/**
	 * /lq-ai/admin/models — admin alias editor (D0.5).
	 *
	 * Route guard: redirects non-admins to /lq-ai with a flash error.
	 * Lists all configured aliases; supports create / edit / delete.
	 *
	 * After a successful mutation, the page refreshes BOTH the alias
	 * list AND the model picker's cache (via invalidating
	 * sessionStorage so the next /lq-ai navigation refetches /v1/models).
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import { adminApi, modelsApi } from '$lib/lq-ai/api';
	import { auth } from '$lib/lq-ai/auth/store';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { Alias, AliasFallback } from '$lib/lq-ai/api/admin';

	import AliasTable from '$lib/lq-ai/components/AliasTable.svelte';
	import AliasForm from '$lib/lq-ai/components/AliasForm.svelte';

	let aliases: Alias[] = [];
	let availableProviders: Array<{ name: string; type: string }> = [];
	let providerModels: Record<string, string[]> = {};
	let loading = true;
	let busy = false;
	let editing: Alias | null | 'new' = null;
	let serverError: string | null = null;
	let listError: string | null = null;

	async function bootstrap() {
		// Route guard. Non-admin users see a flash error and are routed back.
		if (!$auth.user) {
			goto('/lq-ai/login');
			return;
		}
		if (!$auth.user.is_admin) {
			console.warn('non-admin attempted /lq-ai/admin/models; redirecting');
			goto('/lq-ai');
			return;
		}

		loading = true;
		try {
			// Three sources, in parallel:
			//   1. listAliases — current admin alias config
			//   2. getAdminConfig — provider definitions (names + types,
			//      used for the provider dropdown)
			//   3. listModels — D0's *live* discovery from each provider
			//      (Ollama /api/tags + Anthropic /v1/models). This is the
			//      authoritative source for "what can this provider serve
			//      RIGHT NOW", not gateway.yaml's static curated list.
			const [list, cfg, models] = await Promise.all([
				adminApi.listAliases(),
				adminApi.getAdminConfig(),
				modelsApi.listModels()
			]);
			aliases = list.data;
			availableProviders = (cfg.providers ?? [])
				.filter((p) => p.enabled !== false)
				.map((p) => ({ name: p.name, type: p.type }));

			// Build providerModels from D0's live discovery. Each
			// `provider_native` row is `<provider>/<model>` owned_by the
			// provider name; collect them grouped by owned_by.
			const dynamic: Record<string, string[]> = {};
			for (const m of models.data) {
				if (m.lq_ai_kind !== 'provider_native') continue;
				const slash = m.id.indexOf('/');
				if (slash < 0) continue;
				const provider = m.owned_by;
				const model = m.id.slice(slash + 1);
				if (!dynamic[provider]) dynamic[provider] = [];
				if (!dynamic[provider].includes(model)) dynamic[provider].push(model);
			}

			// Fall back to gateway.yaml's static `providers[].models` ONLY for
			// providers where dynamic discovery returned nothing (e.g.,
			// provider with no live catalog endpoint, or the operator
			// running offline). The static list is the operator's
			// curated guidance; the dynamic list is reality.
			for (const p of cfg.providers ?? []) {
				if (!dynamic[p.name] && Array.isArray(p.models)) {
					dynamic[p.name] = p.models;
				}
			}
			providerModels = dynamic;
		} catch (e) {
			console.error('admin: bootstrap failed', e);
			listError = e instanceof Error ? e.message : 'Failed to load aliases';
		} finally {
			loading = false;
		}
	}

	function invalidateModelPickerCache() {
		// The picker reads /v1/models on shell-mount. Bump a sessionStorage
		// key so a navigation back to /lq-ai forces a fresh fetch on the
		// next page load. Belt-and-suspenders: even without this, the
		// shell remounts on goto('/lq-ai') and listModels runs again.
		try {
			if (typeof window !== 'undefined') {
				window.sessionStorage.setItem('lq-ai:models-stale', String(Date.now()));
			}
		} catch {
			// sessionStorage unavailable (private mode) — best effort.
		}
	}

	async function refreshList() {
		try {
			const list = await adminApi.listAliases();
			aliases = list.data;
		} catch (e) {
			console.error('admin: refresh failed', e);
		}
	}

	async function handleCreate(payload: {
		name: string;
		provider: string;
		model: string;
		fallback: AliasFallback[];
	}) {
		busy = true;
		serverError = null;
		try {
			await adminApi.createAlias(payload);
			editing = null;
			invalidateModelPickerCache();
			await refreshList();
		} catch (e) {
			serverError = describeError(e);
		} finally {
			busy = false;
		}
	}

	async function handleUpdate(
		original: Alias,
		payload: { provider: string; model: string; fallback: AliasFallback[] }
	) {
		busy = true;
		serverError = null;
		try {
			await adminApi.updateAlias(original.name, payload);
			editing = null;
			invalidateModelPickerCache();
			await refreshList();
		} catch (e) {
			serverError = describeError(e);
		} finally {
			busy = false;
		}
	}

	async function handleDelete(alias: Alias) {
		// eslint-disable-next-line no-alert
		if (!confirm(`Delete alias "${alias.name}"? This cannot be undone.`)) return;
		busy = true;
		serverError = null;
		try {
			await adminApi.deleteAlias(alias.name);
			invalidateModelPickerCache();
			await refreshList();
		} catch (e) {
			serverError = describeError(e);
		} finally {
			busy = false;
		}
	}

	function describeError(e: unknown): string {
		if (e instanceof LQAIApiError) {
			return `${e.code}: ${e.message}`;
		}
		return e instanceof Error ? e.message : 'Request failed';
	}

	onMount(bootstrap);
</script>

<div class="p-6 max-w-4xl mx-auto space-y-4" data-testid="lq-ai-admin-models">
	<div class="flex items-center justify-between">
		<div>
			<h1 class="lq-text-page-h">Settings — Models</h1>
			<p class="lq-text-body mt-1" style="color: var(--lq-text-secondary);">
				Edit the model aliases that skills and the chat picker use. Changes take effect
				immediately for new requests; in-flight requests finish on the prior config.
			</p>
		</div>
		{#if editing === null}
			<button
				type="button"
				class="lq-btn-primary lq-text-body-sm"
				on:click={() => (editing = 'new')}
				disabled={loading}
				data-testid="lq-ai-admin-new-alias"
			>
				+ new alias
			</button>
		{/if}
	</div>

	{#if listError}
		<div class="lq-text-body-sm" style="color: var(--lq-error); background: var(--lq-error-soft); border: 1px solid var(--lq-error); border-radius: var(--lq-radius); padding: var(--lq-space-2) var(--lq-space-3);">
			{listError}
		</div>
	{/if}

	{#if loading}
		<div class="lq-text-body" style="color: var(--lq-text-secondary);">Loading…</div>
	{:else}
		<AliasTable
			{aliases}
			{busy}
			onEdit={(alias) => (editing = alias)}
			onDelete={handleDelete}
		/>
	{/if}

	{#if editing === 'new'}
		<AliasForm
			alias={null}
			{availableProviders}
			{providerModels}
			submitting={busy}
			{serverError}
			onSubmit={handleCreate}
			onCancel={() => {
				editing = null;
				serverError = null;
			}}
		/>
	{:else if editing && typeof editing !== 'string'}
		<AliasForm
			alias={editing}
			{availableProviders}
			{providerModels}
			submitting={busy}
			{serverError}
			onSubmit={(p) => editing && typeof editing !== 'string' && handleUpdate(editing, p)}
			onCancel={() => {
				editing = null;
				serverError = null;
			}}
		/>
	{/if}
</div>

<style>
	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius-pill);
		padding: 8px 16px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
