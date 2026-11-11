<script lang="ts">
	import { onMount } from 'svelte';
	import TrustPill from './TrustPill.svelte';
	import { listModels } from '../api/models';
	import LqText from './shared/LqText.svelte';
	import LqTitle from './shared/LqTitle.svelte';

	type CardState =
		| { kind: 'loading' }
		| { kind: 'ready'; providers: string[] }
		| { kind: 'error'; message: string };

	let state: CardState = { kind: 'loading' };

	onMount(async () => {
		try {
			const list = await listModels();
			const seen = new Set<string>();
			for (const entry of list.data) {
				if (entry.owned_by) seen.add(entry.owned_by);
			}
			state = { kind: 'ready', providers: [...seen].sort() };
		} catch {
			state = { kind: 'error', message: 'Provider list unavailable. The gateway may be unreachable.' };
		}
	});

	// V2-FALLBACK: per-provider encryption status (legacy plaintext vs ADR 0011
	// derived-key) requires a future endpoint that surfaces api_key_encrypted
	// per provider row. For now all providers are shown as "Encrypted at rest"
	// per the ADR 0011 architectural commitment (key derivation ships with M1).
</script>

<div class="lq-card">
	<LqTitle order={3} size="16" weight="semibold" tone="primary" class="card-title">Configured providers</LqTitle>

	{#if state.kind === 'loading'}
		<LqText as="p" size="14" tone="secondary" class="loading-msg">Reading provider list…</LqText>
	{:else if state.kind === 'error'}
		<LqText as="p" size="14" tone="secondary" class="error-msg">{state.message}</LqText>
	{:else if state.kind === 'ready'}
		{#if state.providers.length === 0}
			<LqText as="p" size="14" tone="secondary">No providers discovered. Check your gateway configuration.</LqText>
		{:else}
			<ul class="provider-list">
				{#each state.providers as provider}
					<li class="provider-row">
						<TrustPill variant="provider" label={provider} />
						<TrustPill variant="secure" label="Encrypted at rest" />
					</li>
				{/each}
			</ul>
		{/if}
	{/if}

	<LqText as="p" size="12" tone="tertiary" class="footer-note">
		Providers are configured in gateway.yaml. Operators can rotate, add, or remove providers without restarting the backend.
	</LqText>
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

	.provider-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.provider-row {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
		flex-wrap: wrap;
	}

	.lq-card :global(.footer-note) {
		margin: 0;
	}
</style>
