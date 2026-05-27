<script lang="ts">
	import { onMount } from 'svelte';
	import { preferences, setPreference, initPreferences } from '$lib/lq-ai/stores/preferences';

	onMount(() => {
		initPreferences();
	});
</script>

<h2 class="lq-text-panel-h" style="margin-bottom: var(--lq-space-4);">Autonomous Layer</h2>
<p class="lq-text-body" style="color: var(--lq-text-secondary); margin-bottom: var(--lq-space-6);">
	When enabled, LQ.AI can run background agents that watch your knowledge bases, run scheduled
	scans, propose memory about your preferences, and surface cross-matter precedents — always under
	hard cost, halt, and per-phase tool limits, and always producing an inspectable receipt. Off by
	default. Turning it off stops new runs; you keep access to past receipts and can still halt
	anything running.
</p>

<div class="lq-autonomous-toggle" style="margin-top: var(--lq-space-6);">
	<label
		class="lq-text-body"
		style="display: flex; gap: var(--lq-space-2); align-items: flex-start;"
	>
		<input
			type="checkbox"
			checked={$preferences.autonomous_enabled}
			on:change={() => setPreference('autonomous_enabled', !$preferences.autonomous_enabled)}
			data-testid="lq-ai-autonomous-enabled-toggle"
		/>
		<span>
			<strong>Enable Autonomous Layer</strong>
			<span style="display: block; color: var(--lq-text-secondary); font-size: 12px;">
				Allow background agents to run on your behalf. All runs are gated by cost and halt limits
				and produce a full receipt you can inspect at any time.
			</span>
		</span>
	</label>
</div>
