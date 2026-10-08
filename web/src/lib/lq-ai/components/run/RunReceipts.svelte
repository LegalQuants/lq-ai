<script lang="ts">
	/**
	 * The run-level receipts, folded by default and never removed: the run and
	 * profile, the model, what has been spent and reserved, the digests that bind the
	 * plan, the skill pins, and the orchestrator's own recorded steps. Each task's
	 * receipts sit inside its own card.
	 */
	import type { OrchestrationChatRun } from '$lib/lq-ai/api/orchestration';
	import { formatUsd } from '$lib/lq-ai/run/format';
	import RunEffectReceipt from './RunEffectReceipt.svelte';

	export let run: OrchestrationChatRun;

	$: tree = run.tree;
	$: effects = run.effects ?? [];
</script>

<details class="receipts" data-testid="lq-ai-run-receipts">
	<summary>Receipts, digests and accounting</summary>
	<dl>
		<div><dt>Run</dt><dd><code>{run.root_id}</code></dd></div>
		{#if run.profile}<div><dt>Profile</dt><dd>{run.profile}</dd></div>{/if}
		<div><dt>Model</dt><dd>{run.planning.model}</dd></div>
		<div>
			<dt>Accounting</dt>
			<dd>Spent {formatUsd(run.spent_usd)} · reserved {formatUsd(run.reserved_usd)}</dd>
		</div>
		{#if run.planning.packet_digest}
			<div><dt>Document packet digest</dt><dd><code>{run.planning.packet_digest}</code></dd></div>
		{/if}
		<div>
			<dt>Gateway configuration</dt>
			<dd><code>{run.planning.gateway_revision}</code></dd>
		</div>
		{#if tree}
			<div><dt>Plan digest</dt><dd><code>{tree.plan_hash}</code></dd></div>
			<div>
				<dt>Orchestrator skill</dt>
				<dd>
					{tree.plan.root.skill.name} v{run.planning.root_skill_version}
					<code>{tree.plan.root.skill.digest}</code>
				</dd>
			</div>
		{/if}
	</dl>
	{#if effects.length > 0}
		<h4>Orchestrator steps</h4>
		{#each effects as effect}
			<RunEffectReceipt {effect} />
		{/each}
	{/if}
</details>

<style>
	.receipts {
		margin: 0.75rem 0 0;
		border-top: 1px solid var(--lq-border);
		padding-top: 0.25rem;
	}
	summary {
		cursor: pointer;
		font-size: 0.8rem;
		padding: 0.35rem 0;
		color: var(--lq-text-secondary);
	}
	dl {
		margin: 0.25rem 0;
		display: grid;
		gap: 0.35rem;
	}
	dt {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
	dd {
		margin: 0;
		font-size: 0.8rem;
		overflow-wrap: anywhere;
	}
	h4 {
		margin: 0.5rem 0 0.1rem;
		font-size: 0.8rem;
		font-weight: 600;
	}
	code {
		font-size: 0.7rem;
		overflow-wrap: anywhere;
	}
</style>
