<script lang="ts">
	import { onMount } from 'svelte';
	import { get } from 'svelte/store';
	import TrustPill from './TrustPill.svelte';
	import { auth } from '../auth/store';
	import { getUsage } from '../api/admin';
	import { LQAIApiError } from '../api/client';
	import type { TrustVariant } from './TrustPill.svelte';
	import LqText from './shared/LqText.svelte';
	import LqTitle from './shared/LqTitle.svelte';

	// Providers whose turns count as self-hosted (not external).
	const SELF_HOSTED_MARKERS = new Set(['ollama', 'localhost', 'ollama-localhost']);

	type CardState =
		| { kind: 'not-admin' }
		| { kind: 'loading' }
		| { kind: 'ready'; today: number; sevenDay: number }
		| { kind: 'error'; message: string };

	let state: CardState = { kind: 'loading' };

	function isAdmin(): boolean {
		const user = get(auth).user;
		// Spec §4.1.1: prefer role === 'admin'; fall back to is_admin boolean.
		return user?.role === 'admin' || user?.is_admin === true;
	}

	function todayMidnightISO(): string {
		const d = new Date();
		d.setHours(0, 0, 0, 0);
		return d.toISOString();
	}

	function sevenDaysAgoISO(): string {
		const d = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
		d.setHours(0, 0, 0, 0);
		return d.toISOString();
	}

	function sumExternal(rows: { group_key: string; request_count: number }[]): number {
		return rows
			.filter((r) => !SELF_HOSTED_MARKERS.has(r.group_key.toLowerCase()))
			.reduce((acc, r) => acc + r.request_count, 0);
	}

	onMount(async () => {
		if (!isAdmin()) {
			state = { kind: 'not-admin' };
			return;
		}

		try {
			const [todayRes, sevenDayRes] = await Promise.all([
				getUsage({ group_by: 'provider', date_from: todayMidnightISO() }),
				getUsage({ group_by: 'provider', date_from: sevenDaysAgoISO() })
			]);
			state = {
				kind: 'ready',
				today: sumExternal(todayRes.rows),
				sevenDay: sumExternal(sevenDayRes.rows)
			};
		} catch (e) {
			// Race: user token expired or role changed since page load.
			if (e instanceof LQAIApiError && e.status === 403) {
				state = { kind: 'not-admin' };
			} else {
				state = { kind: 'error', message: 'Usage data unavailable. Try refreshing.' };
			}
		}
	});

	function pillVariant(count: number): TrustVariant {
		return count > 100 ? 'warn' : 'audit';
	}
</script>

<div class="lq-card">
	<LqTitle order={3} size="16" weight="semibold" tone="primary" class="card-title"
		>External-turn usage</LqTitle
	>

	{#if state.kind === 'not-admin'}
		<LqText as="p" size="14" tone="secondary" class="gated-msg"
			>External-turn counts are visible to admins only.</LqText
		>
		<LqText as="p" size="12" tone="tertiary" class="gated-why">
			These figures come from /admin/usage, which is admin-gated for cost-disclosure reasons.
		</LqText>
	{:else if state.kind === 'loading'}
		<LqText as="p" size="14" tone="secondary" class="loading-msg">Loading usage data…</LqText>
	{:else if state.kind === 'error'}
		<LqText as="p" size="14" tone="secondary" class="error-msg">{state.message}</LqText>
	{:else if state.kind === 'ready'}
		<div class="stats-row">
			<div class="stat-block">
				<span class="stat-count">{state.today}</span>
				<LqText as="span" size="12" tone="secondary" class="stat-label">Today</LqText>
				<TrustPill variant={pillVariant(state.today)} label="external turns" />
			</div>
			<div class="stat-divider" aria-hidden="true"></div>
			<div class="stat-block">
				<span class="stat-count">{state.sevenDay}</span>
				<LqText as="span" size="12" tone="secondary" class="stat-label">Last 7 days</LqText>
				<TrustPill variant={pillVariant(state.sevenDay)} label="external turns" />
			</div>
		</div>
		<LqText as="p" size="12" tone="tertiary" class="footer-note">
			"External" = any turn routed to a non-self-hosted provider (excludes ollama / localhost).
		</LqText>
	{/if}
</div>

<style>
	.lq-card {
		background: var(--lq-canvas);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.lq-card :global(.card-title) {
		margin: 0;
	}

	.stats-row {
		display: flex;
		align-items: flex-start;
		gap: var(--lq-space-6);
	}

	.stat-block {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.stat-count {
		font-size: 28px;
		font-weight: 600;
		color: var(--lq-text);
		line-height: 1.1;
	}

	.stat-divider {
		width: 1px;
		background: var(--lq-border);
		align-self: stretch;
		margin-top: 4px;
	}

	.lq-card :global(.footer-note) {
		margin: 0;
	}
</style>
