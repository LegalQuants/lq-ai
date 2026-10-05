<script lang="ts">
	import DevApiDocsCard from '$lib/lq-ai/components/DevApiDocsCard.svelte';
	import DevApiPlaygroundCard from '$lib/lq-ai/components/DevApiPlaygroundCard.svelte';
	import DevRoleManagementCard from '$lib/lq-ai/components/DevRoleManagementCard.svelte';
	import DevForkCallout from '$lib/lq-ai/components/DevForkCallout.svelte';
	import DevSkillResourcePolicyCard from '$lib/lq-ai/components/DevSkillResourcePolicyCard.svelte';
</script>

<div class="dev-page">
	<div class="dev-page-header">
		<h1 class="lq-text-page-h">Developer Support</h1>
		<p class="dev-page-intro">
			Operator and ecosystem-developer-facing tools for working with the LQ.AI API directly. Bring
			your own frontend — this is where you start.
		</p>
	</div>

	<div class="dev-grid">
		<DevApiDocsCard />
		<DevApiPlaygroundCard />
		<DevRoleManagementCard />
		<DevSkillResourcePolicyCard />
		<DevForkCallout />
	</div>
</div>

<style>
	.dev-page {
		padding: var(--lq-space-6) var(--lq-space-5);
		max-width: 1080px;
		margin: 0 auto;
		width: 100%;
	}

	.dev-page-header {
		margin-bottom: var(--lq-space-6);
	}

	.dev-page-intro {
		font-size: 14px;
		color: var(--lq-text-secondary);
		margin: var(--lq-space-2) 0 0;
		max-width: 600px;
		line-height: 1.5;
	}

	.dev-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--lq-space-5);
	}

	@media (max-width: 680px) {
		.dev-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
