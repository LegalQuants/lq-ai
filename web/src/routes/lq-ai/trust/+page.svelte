<script lang="ts">
	import TrustDataResidencyCard from '$lib/lq-ai/components/TrustDataResidencyCard.svelte';
	import TrustProvidersCard from '$lib/lq-ai/components/TrustProvidersCard.svelte';
	import TrustExternalTurnsCard from '$lib/lq-ai/components/TrustExternalTurnsCard.svelte';
	import TrustArtifactsCard from '$lib/lq-ai/components/TrustArtifactsCard.svelte';
	import LqText from '$lib/lq-ai/components/shared/LqText.svelte';
	import LqTitle from '$lib/lq-ai/components/shared/LqTitle.svelte';
</script>

<div class="trust-page">
	<div class="trust-header">
		<LqTitle order={1} size="20" weight="bold" tone="primary">Trust &amp; Privacy</LqTitle>
		<LqText as="p" size="14" tone="secondary" class="intro-body">
			This is what we know about your deployment. Every claim here links to an artifact you can
			verify in this repo or on your operator's machine.
		</LqText>
	</div>

	<div class="trust-grid">
		<TrustDataResidencyCard />
		<TrustProvidersCard />
		<TrustExternalTurnsCard />
		<TrustArtifactsCard />
	</div>
</div>

<style>
	.trust-page {
		padding: var(--lq-space-6);
		max-width: 1100px;
		margin: 0 auto;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-6);
	}

	.trust-header {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.trust-header :global(.intro-body) {
		max-width: 680px;
	}

	.trust-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--lq-space-6);
	}

	@media (max-width: 720px) {
		.trust-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
