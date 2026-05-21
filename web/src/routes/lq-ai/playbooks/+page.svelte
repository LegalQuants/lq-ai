<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import { listPlaybooks } from '$lib/lq-ai/api/playbooks';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import PlaybookDisclaimerBanner from '$lib/lq-ai/components/PlaybookDisclaimerBanner.svelte';
	import PlaybookExecuteModal from '$lib/lq-ai/components/PlaybookExecuteModal.svelte';
	import type { Playbook } from '$lib/lq-ai/types';

	import { sortPlaybooksByName, formatVersion } from './page-helpers';

	let playbooks: Playbook[] = [];
	let loading = false;
	let listError: string | null = null;

	let selectedPlaybook: Playbook | null = null;

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const fetched = await listPlaybooks();
			playbooks = sortPlaybooksByName(fetched);
		} catch (err) {
			listError = err instanceof LQAIApiError ? err.message : 'Failed to load playbooks.';
		} finally {
			loading = false;
		}
	}

	function openExecute(p: Playbook): void {
		selectedPlaybook = p;
	}

	function closeExecute(): void {
		selectedPlaybook = null;
	}

	onMount(load);
</script>

<svelte:head>
	<title>Playbooks · LQ.AI</title>
</svelte:head>

<section class="lq-playbooks-page">
	<header class="lq-playbooks-page__header">
		<div class="lq-playbooks-page__heading">
			<h1>Playbooks</h1>
			<button
				type="button"
				class="lq-playbooks-page__cta"
				data-testid="lq-playbooks-generate-cta"
				on:click={() => goto('/lq-ai/playbooks/easy')}
			>
				Generate from prior agreements
			</button>
		</div>
		<p class="lq-playbooks-page__subtitle">
			Apply a playbook to review a contract against your standard positions. The executor walks each
			position, classifies how the contract compares, and drafts redlines where it deviates.
		</p>
	</header>

	<PlaybookDisclaimerBanner />

	{#if loading}
		<div class="lq-playbooks-page__state" data-testid="lq-playbooks-loading">Loading…</div>
	{:else if listError}
		<div class="lq-playbooks-page__error" role="alert" data-testid="lq-playbooks-error">
			{listError}
		</div>
	{:else if playbooks.length === 0}
		<div class="lq-playbooks-page__state" data-testid="lq-playbooks-empty">
			No playbooks available yet.
		</div>
	{:else}
		<table class="lq-playbooks-table" data-testid="lq-playbooks-table">
			<thead>
				<tr>
					<th scope="col">Name</th>
					<th scope="col" class="lq-playbooks-table__compact">Contract type</th>
					<th scope="col" class="lq-playbooks-table__compact">Version</th>
					<th scope="col" class="lq-playbooks-table__actions">&nbsp;</th>
				</tr>
			</thead>
			<tbody>
				{#each playbooks as p (p.id)}
					<tr data-testid="lq-playbook-row" data-playbook-id={p.id}>
						<td class="lq-playbooks-table__name">
							<div class="lq-playbooks-table__name-text">{p.name}</div>
							{#if p.description}
								<div class="lq-playbooks-table__desc">{p.description}</div>
							{/if}
						</td>
						<td class="lq-playbooks-table__compact">{p.contract_type}</td>
						<td class="lq-playbooks-table__compact">{formatVersion(p.version)}</td>
						<td class="lq-playbooks-table__actions">
							<button
								type="button"
								class="lq-playbooks-table__apply"
								data-testid="lq-playbook-apply"
								on:click={() => openExecute(p)}
							>
								Apply
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}

	{#if selectedPlaybook}
		<PlaybookExecuteModal playbook={selectedPlaybook} on:close={closeExecute} />
	{/if}
</section>

<style>
	.lq-playbooks-page {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		max-width: 64rem;
		margin: 0 auto;
		padding: 1.5rem;
	}
	.lq-playbooks-page__heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		margin-bottom: 0.5rem;
	}
	.lq-playbooks-page__header h1 {
		margin: 0;
		font-size: 1.5rem;
	}
	.lq-playbooks-page__cta {
		padding: 0.5rem 0.875rem;
		background: var(--lq-accent, #4f46e5);
		color: var(--lq-on-accent, #ffffff);
		border: none;
		border-radius: 0.375rem;
		font-size: 0.875rem;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-playbooks-page__cta:hover {
		opacity: 0.9;
	}
	.lq-playbooks-page__subtitle {
		margin: 0;
		color: var(--lq-text-secondary);
	}
	.lq-playbooks-page__state,
	.lq-playbooks-page__error {
		padding: 1.5rem;
		text-align: center;
		color: var(--lq-text-secondary);
		background: var(--lq-inset);
		border-radius: 0.5rem;
	}
	.lq-playbooks-page__error {
		color: var(--lq-error);
		background: var(--lq-error-soft, var(--lq-inset));
		border: 1px solid var(--lq-error-border, var(--lq-border));
	}
	.lq-playbooks-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		overflow: hidden;
	}
	.lq-playbooks-table th,
	.lq-playbooks-table td {
		padding: 0.75rem 1rem;
		text-align: left;
		border-bottom: 1px solid var(--lq-border);
	}
	.lq-playbooks-table tbody tr:last-child td {
		border-bottom: none;
	}
	.lq-playbooks-table__name-text {
		font-weight: 600;
	}
	.lq-playbooks-table__desc {
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
		margin-top: 0.25rem;
		/* Cap the description so it doesn't crowd the compact columns
		   on long YAML descriptions (the seed playbooks have multi-
		   paragraph descriptions including the not-legal-advice line). */
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.lq-playbooks-table__compact {
		width: 1%;
		white-space: nowrap;
		vertical-align: top;
	}
	.lq-playbooks-table__actions {
		text-align: right;
		width: 1%;
		white-space: nowrap;
		vertical-align: top;
	}
	.lq-playbooks-table__apply {
		padding: 0.375rem 0.75rem;
		background: var(--lq-accent);
		color: var(--lq-on-accent, white);
		border: none;
		border-radius: 0.375rem;
		cursor: pointer;
		font-size: 0.875rem;
		font-weight: 500;
	}
	.lq-playbooks-table__apply:hover {
		opacity: 0.9;
	}
</style>
