<script context="module" lang="ts">
	import { getAdminConfig, type SkillResourcePolicy } from '../api/admin';

	export type PolicyResult =
		| { policy: SkillResourcePolicy; error: null }
		| { policy: null; error: string };

	export async function loadSkillResourcePolicy(): Promise<PolicyResult> {
		try {
			const config = await getAdminConfig();
			if (!config.skill_resource_policy) {
				return { policy: null, error: 'This server did not report a skill reference policy.' };
			}
			return { policy: config.skill_resource_policy, error: null };
		} catch (e) {
			return { policy: null, error: e instanceof Error ? e.message : 'Failed to load policy.' };
		}
	}
</script>

<script lang="ts">
	import { onMount } from 'svelte';

	let policy: SkillResourcePolicy | null = null;
	let loading = true;
	let error: string | null = null;

	async function load(): Promise<void> {
		loading = true;
		const result = await loadSkillResourcePolicy();
		policy = result.policy;
		error = result.error;
		loading = false;
	}
	onMount(load);
</script>

<section class="dev-card" aria-label="Skill reference policy">
	<h2 class="lq-text-label">Skill reference policy</h2>
	{#if loading}
		<p role="status">Loading policy…</p>
	{:else if error}
		<p class="error" role="alert">{error}</p>
		<button type="button" on:click={load}>Retry</button>
	{:else if policy}
		<p><strong>Model reading: {policy.reference_read_enabled ? 'Enabled' : 'Disabled'}</strong></p>
		<p>
			Scope: {policy.scope}. Up to {policy.max_files} UTF-8 text files,
			{(policy.max_file_bytes / 1024).toLocaleString()} KiB per file.
		</p>
		<p>
			People can inspect eligible references in a skill's Source tab even when model reading is
			disabled.
		</p>
		<p>
			To disable model reading, set <code>LQ_AI_SKILL_REFERENCE_READ_ENABLED=false</code>
			in the deployment environment and restart the API and arq worker. This page reports the configuration;
			it does not change it.
		</p>
	{/if}
</section>

<style>
	.dev-card {
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-5);
	}
	p {
		font-size: 14px;
		line-height: 1.5;
		margin-top: var(--lq-space-3);
		color: var(--lq-text-secondary);
	}
	strong {
		color: var(--lq-text);
	}
	code {
		font-size: 12px;
		overflow-wrap: anywhere;
	}
	.error {
		color: var(--lq-error);
	}
	button {
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: 4px 10px;
		background: var(--lq-inset);
		color: var(--lq-text);
	}
</style>
