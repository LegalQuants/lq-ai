<script lang="ts">
	/**
	 * /lq-ai/admin/audit-log — admin audit-log filter + paginated view (D3-coverage).
	 *
	 * Backed by ``GET /api/v1/admin/audit-log``. Admin-gated; non-admins
	 * see a flash error and are routed back to /lq-ai.
	 *
	 * Filters compose with AND on the server. Each filter has a sensible
	 * empty state — leaving a field blank means "any". The privilege
	 * dropdown is tri-state (any / privileged / non-privileged).
	 *
	 * Pagination is cursor-based; ``next_cursor`` carries forward into
	 * the next page request, and the table accumulates rows on
	 * "Load more" so an investigator can scroll a continuous timeline.
	 * Changing any filter resets the cursor + accumulation.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import { auditLogApi } from '$lib/lq-ai/api';
	import { auth } from '$lib/lq-ai/auth/store';
	import type { AuditLogEntry, AuditLogFilters } from '$lib/lq-ai/api/auditLog';
	import LqText from '$lib/lq-ai/components/shared/LqText.svelte';
	import LqTitle from '$lib/lq-ai/components/shared/LqTitle.svelte';

	let rows: AuditLogEntry[] = [];
	let nextCursor: string | null = null;
	let loading = false;
	let listError: string | null = null;

	// Filter form state. ``privilegeMarked`` is a tri-state string mapped
	// to boolean | null on submit; the rest are plain inputs.
	let privilegeMarked: 'any' | 'true' | 'false' = 'any';
	let routedTier: '' | '1' | '2' | '3' | '4' | '5' = '';
	let action = '';
	let userId = '';
	let since = '';
	let until = '';
	let limit = 50;

	$: filters = (): AuditLogFilters => ({
		privilege_marked: privilegeMarked === 'any' ? null : privilegeMarked === 'true',
		routed_inference_tier: routedTier === '' ? null : (Number(routedTier) as 1 | 2 | 3 | 4 | 5),
		action: action.trim() || null,
		user_id: userId.trim() || null,
		since: since ? new Date(since).toISOString() : null,
		until: until ? new Date(until).toISOString() : null,
		limit
	});

	async function load(reset: boolean) {
		loading = true;
		listError = null;
		try {
			const page = await auditLogApi.listAuditLog({
				...filters(),
				cursor: reset ? null : nextCursor
			});
			rows = reset ? page.items : [...rows, ...page.items];
			nextCursor = page.next_cursor;
		} catch (e) {
			console.error('audit-log: load failed', e);
			listError = e instanceof Error ? e.message : 'Failed to load audit log';
		} finally {
			loading = false;
		}
	}

	async function applyFilters() {
		await load(true);
	}

	async function loadMore() {
		await load(false);
	}

	function resetFilters() {
		privilegeMarked = 'any';
		routedTier = '';
		action = '';
		userId = '';
		since = '';
		until = '';
		limit = 50;
		applyFilters();
	}

	function formatTimestamp(iso: string): string {
		try {
			return new Date(iso).toLocaleString();
		} catch {
			return iso;
		}
	}

	function formatDetails(d: Record<string, unknown> | null): string {
		if (!d) return '';
		try {
			return JSON.stringify(d);
		} catch {
			return '';
		}
	}

	onMount(async () => {
		if (!$auth.user) {
			goto('/lq-ai/login');
			return;
		}
		if (!$auth.user.is_admin) {
			console.warn('non-admin attempted /lq-ai/admin/audit-log; redirecting');
			goto('/lq-ai');
			return;
		}
		await load(true);
	});
</script>

<svelte:head>
	<title>Audit log — LQ.AI admin</title>
</svelte:head>

<div class="p-4 max-w-7xl mx-auto" data-testid="lq-ai-admin-audit-log">
	<header class="mb-4">
		<LqTitle order={1} size="20" weight="bold" tone="primary">Audit log</LqTitle>
		<LqText as="p" size="12" tone="tertiary" class="mt-1">
			Every state-changing API call writes one row here (PRD §5.3). Filters compose with AND;
			leaving a field blank means "any". Most-recent rows first.
		</LqText>
	</header>

	<form
		class="lq-filter-bar grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4"
		on:submit|preventDefault={applyFilters}
		data-testid="lq-ai-admin-audit-log-filters"
	>
		<label class="flex flex-col">
			<LqText as="span" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="mb-1">Privilege</LqText>
			<select
				bind:value={privilegeMarked}
				class="rounded lq-t-border-strong text-sm"
				data-testid="lq-ai-audit-filter-privilege"
			>
				<option value="any">Any</option>
				<option value="true">Privileged only</option>
				<option value="false">Non-privileged only</option>
			</select>
		</label>

		<label class="flex flex-col">
			<LqText as="span" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="mb-1">Routed tier</LqText>
			<select
				bind:value={routedTier}
				class="rounded lq-t-border-strong text-sm"
				data-testid="lq-ai-audit-filter-tier"
			>
				<option value="">Any</option>
				<option value="1">Tier 1 — on-prem</option>
				<option value="2">Tier 2 — private cloud</option>
				<option value="3">Tier 3 — ZDR commercial</option>
				<option value="4">Tier 4 — standard commercial</option>
				<option value="5">Tier 5 — consumer</option>
			</select>
		</label>

		<label class="flex flex-col">
			<LqText as="span" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="mb-1">Action (exact)</LqText>
			<input
				type="text"
				placeholder="e.g. chat.message_sent"
				bind:value={action}
				class="rounded lq-t-border-strong text-sm"
				data-testid="lq-ai-audit-filter-action"
			/>
		</label>

		<label class="flex flex-col">
			<LqText as="span" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="mb-1">User ID (UUID)</LqText>
			<input
				type="text"
				placeholder="00000000-0000-…"
				bind:value={userId}
				class="rounded lq-t-border-strong text-sm font-mono"
				data-testid="lq-ai-audit-filter-user"
			/>
		</label>

		<label class="flex flex-col">
			<LqText as="span" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="mb-1">Since</LqText>
			<input
				type="datetime-local"
				bind:value={since}
				class="rounded lq-t-border-strong text-sm"
				data-testid="lq-ai-audit-filter-since"
			/>
		</label>

		<label class="flex flex-col">
			<LqText as="span" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="mb-1">Until</LqText>
			<input
				type="datetime-local"
				bind:value={until}
				class="rounded lq-t-border-strong text-sm"
				data-testid="lq-ai-audit-filter-until"
			/>
		</label>

		<div class="col-span-full flex items-center gap-2 justify-end">
			<button
				type="button"
				class="lq-btn-secondary"
				on:click={resetFilters}
				data-testid="lq-ai-audit-filter-reset"
			>
				Reset
			</button>
			<button
				type="submit"
				class="lq-btn-primary"
				disabled={loading}
				data-testid="lq-ai-audit-filter-apply"
			>
				{loading ? 'Loading…' : 'Apply filters'}
			</button>
		</div>
	</form>

	{#if listError}
		<div
			class="px-3 py-2 rounded border lq-t-error-border lq-t-error-bg lq-t-error-strong text-sm mb-3"
			data-testid="lq-ai-admin-audit-log-error"
		>
			{listError}
		</div>
	{/if}

	<div class="lq-table-wrap overflow-x-auto">
		<LqText as="table" size="14" tone="primary" class="min-w-full" data-testid="lq-ai-admin-audit-log-table">
			<thead class="lq-thead">
				<tr>
					<LqText as="th" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="px-2 py-1 text-left">Timestamp</LqText>
					<LqText as="th" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="px-2 py-1 text-left">Action</LqText>
					<LqText as="th" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="px-2 py-1 text-left">User</LqText>
					<LqText as="th" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="px-2 py-1 text-left">Resource</LqText>
					<LqText as="th" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="px-2 py-1 text-left">Priv</LqText>
					<LqText as="th" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="px-2 py-1 text-left">Tier</LqText>
					<LqText as="th" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="px-2 py-1 text-left">Provider</LqText>
					<LqText as="th" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="px-2 py-1 text-left">IP</LqText>
					<LqText as="th" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" class="px-2 py-1 text-left">Details</LqText>
				</tr>
			</thead>
			<tbody>
				{#each rows as r (r.id)}
					<tr
						class="lq-row align-top"
						class:lq-t-warning-bg={r.privilege_marked}
					>
						<LqText as="td" size="12" tone="tertiary" class="px-2 py-1 font-mono whitespace-nowrap">{formatTimestamp(r.timestamp)}</LqText>
						<LqText as="td" size="14" tone="primary" class="px-2 py-1 font-mono">{r.action}</LqText>
						<LqText as="td" size="14" tone="primary" class="px-2 py-1 font-mono truncate max-w-[12ch]" title={r.user_id ?? ''}>
							{r.user_id ?? '—'}
						</LqText>
						<LqText as="td" size="14" tone="primary" class="px-2 py-1">
							{r.resource_type}{r.resource_id ? `/${r.resource_id.slice(0, 8)}…` : ''}
						</LqText>
						<td class="px-2 py-1">
							{#if r.privilege_marked}
								<span class="px-1.5 py-0.5 rounded lq-t-warning-strong-bg lq-t-warning-text text-[10px]">
									{r.privilege_basis ?? 'yes'}
								</span>
							{:else}
								—
							{/if}
						</td>
						<LqText as="td" size="14" tone="primary" class="px-2 py-1">{r.routed_inference_tier ?? '—'}</LqText>
						<LqText as="td" size="14" tone="primary" class="px-2 py-1 font-mono">{r.routed_provider ?? '—'}</LqText>
						<LqText as="td" size="14" tone="primary" class="px-2 py-1 font-mono">{r.ip_address ?? '—'}</LqText>
						<LqText as="td" size="14" tone="primary" class="px-2 py-1 font-mono truncate max-w-[28ch]" title={formatDetails(r.details)}>
							{formatDetails(r.details)}
						</LqText>
					</tr>
				{:else}
					<tr>
						<LqText as="td" size="14" tone="tertiary" colspan="9" class="px-2 py-6 text-center">
							{loading ? 'Loading…' : 'No audit entries match.'}
						</LqText>
					</tr>
				{/each}
			</tbody>
		</LqText>
	</div>

	{#if nextCursor}
		<div class="flex justify-center mt-3">
			<button
				type="button"
				class="lq-btn-secondary"
				on:click={loadMore}
				disabled={loading}
				data-testid="lq-ai-admin-audit-log-load-more"
			>
				{loading ? 'Loading…' : 'Load more'}
			</button>
		</div>
	{/if}
</div>

<style>
	.lq-filter-bar {
		padding: var(--lq-space-3);
		border-radius: var(--lq-radius);
		border: 1px solid var(--lq-border);
		background: var(--lq-inset);
	}

	.lq-table-wrap {
		border-radius: var(--lq-radius);
		border: 1px solid var(--lq-border);
	}

	.lq-thead {
		background: var(--lq-inset);
		color: var(--lq-text-secondary);
	}

	.lq-row {
		border-top: 1px solid var(--lq-border);
	}

	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius-pill);
		padding: 6px 12px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

	.lq-btn-secondary {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: 6px 12px;
		font-size: 13.5px;
		cursor: pointer;
	}
	.lq-btn-secondary:hover { background: var(--lq-inset); }
	.lq-btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }

	/* Colour tokens replacing Tailwind palette utilities (S1-1b). */
	.lq-t-border-strong {
		border-color: var(--lq-border-strong);
	}
	.lq-t-error-bg {
		background-color: var(--lq-error-bg);
	}
	.lq-t-error-border {
		border-color: var(--lq-error-border);
	}
	.lq-t-error-strong {
		color: var(--lq-error-text);
	}
	.lq-t-warning-bg {
		background-color: var(--lq-warning-bg);
	}
	.lq-t-warning-strong-bg {
		background-color: var(--lq-warning-border);
	}
	.lq-t-warning-text {
		color: var(--lq-warning-text);
	}
</style>
