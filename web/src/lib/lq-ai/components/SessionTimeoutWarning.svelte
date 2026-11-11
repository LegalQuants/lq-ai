<script lang="ts">
	import { sessionActivity, noteActivity } from '$lib/lq-ai/stores/sessionActivity';
	import LqText from './shared/LqText.svelte';
</script>

{#if $sessionActivity.showWarning}
	<div
		role="alert"
		class="lq-session-toast"
	>
		<LqText as="p" size="14" tone="primary"><strong>Session expires in 5 minutes.</strong></LqText>
		<LqText as="p" size="12" tone="tertiary" style="margin-top: var(--lq-space-1);">
			You'll need to log in again if you stay idle.
		</LqText>
		<button type="button" on:click={noteActivity} class="lq-btn-primary" style="margin-top: var(--lq-space-3);">
			Continue working
		</button>
	</div>
{/if}

<style>
	.lq-session-toast {
		position: fixed;
		bottom: var(--lq-space-4);
		right: var(--lq-space-4);
		background: var(--lq-canvas);
		border: 1px solid var(--lq-warn-border);
		border-left: 3px solid var(--lq-warn);
		border-radius: var(--lq-radius-lg);
		padding: var(--lq-space-4);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1);
		max-width: 360px;
		z-index: 60;
	}
</style>
