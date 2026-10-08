<script lang="ts">
	/**
	 * The composer in run mode (ADR 0038 D1): what this run will use and what it may
	 * spend, shown before anything is sent. Proposing a plan authorizes one model call
	 * within the displayed total cap; the work itself needs approval of the exact plan
	 * afterwards. The planning call sees the request only, never earlier messages, and
	 * the profile's own notice says so.
	 *
	 * A slot below the facts takes the document picker for profiles that read a selection.
	 */
	import type { ProfileAvailability } from '$lib/lq-ai/api/orchestration';
	import { runModeFacts, toolLabelList, unavailableReason } from '$lib/lq-ai/run/composer';

	export let profile: ProfileAvailability;
	export let onClear: () => void = () => undefined;

	$: facts = runModeFacts(profile);
	$: tools = toolLabelList(profile.tools);
	$: unavailable = unavailableReason(profile);
</script>

<section class="mode" data-testid="lq-ai-run-mode-panel" aria-label="Run mode">
	<div class="head">
		<div>
			<p class="eyebrow">Governed run</p>
			<h3>{profile.title}</h3>
		</div>
		<button type="button" class="leave" data-testid="lq-ai-run-mode-clear" on:click={onClear}>
			Leave run mode
		</button>
	</div>
	<p class="summary">{profile.summary}</p>

	{#if unavailable}<p class="unavailable" role="alert">{unavailable}</p>{/if}

	{#if facts.length > 0}
		<dl class="facts">
			{#each facts as fact}
				<div><dt>{fact.label}</dt><dd>{fact.value}</dd></div>
			{/each}
		</dl>
	{/if}
	<dl class="facts wide">
		<div>
			<dt>Tools the tasks may use</dt>
			<dd>{#if tools.length > 0}{tools.join(', ')}{:else}none{/if}</dd>
		</div>
		<div>
			<dt>The run may read</dt>
			<dd>{profile.reads}</dd>
		</div>
	</dl>

	<p class="planning-notice" data-testid="lq-ai-run-planning-notice">{profile.planning_notice}</p>
	<p class="muted">
		The run uses the model and skills this profile pins. The model picker and the skills attached in
		this chat do not apply to it.
	</p>

	<slot />
</section>

<style>
	@import '../../styles/practice.css';

	.mode {
		padding: 0.6rem 0.75rem;
		border: 1px solid var(--lq-accent-border);
		border-left: 4px solid var(--lq-accent);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-inset-secure);
	}
	.head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.eyebrow {
		margin: 0;
		font-size: 0.7rem;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--lq-text-tertiary);
	}
	h3 {
		margin: 0;
		font-size: 0.95rem;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.summary {
		margin: 0.25rem 0 0.4rem;
		font-size: 0.82rem;
		line-height: 1.5;
		color: var(--lq-text-secondary);
	}
	.leave {
		background: var(--lq-canvas);
		color: var(--lq-text);
		border: 1px solid var(--lq-border-strong);
		border-radius: var(--lq-radius);
		padding: 0.25rem 0.6rem;
		font-size: 0.75rem;
		cursor: pointer;
	}
	.leave:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.unavailable {
		margin: 0.4rem 0;
		padding: 0.4rem 0.6rem;
		font-size: 0.8rem;
		color: var(--lq-warn);
		background: var(--lq-warn-soft);
		border: 1px solid var(--lq-warn-border);
		border-radius: var(--lq-radius);
	}
	dl {
		margin: 0.4rem 0;
	}
	.facts {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
		gap: 0.4rem 1rem;
	}
	.facts.wide {
		grid-template-columns: 1fr;
	}
	dt {
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
	dd {
		margin: 0;
		font-size: 0.82rem;
		overflow-wrap: anywhere;
	}
	.planning-notice {
		margin: 0.5rem 0 0.25rem;
		font-size: 0.8rem;
		line-height: 1.5;
	}
	.muted {
		margin: 0.25rem 0;
		font-size: 0.75rem;
		line-height: 1.5;
		color: var(--lq-text-secondary);
	}
</style>
