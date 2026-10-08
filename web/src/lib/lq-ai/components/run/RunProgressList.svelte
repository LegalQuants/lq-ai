<script lang="ts">
	/**
	 * The run's progress in plain words: four stages, one of them current while the
	 * run is active, and beneath it the step each running task is on. The run
	 * message opens on this list.
	 */
	import type { NowLine, ProgressItem, ProgressState } from '$lib/lq-ai/run/progress';

	export let items: ProgressItem[] = [];
	export let now: NowLine[] = [];

	const GLYPH: Record<ProgressState, string> = {
		done: '✓',
		current: '●',
		pending: '○',
		stopped: '■',
		skipped: '–'
	};
	const WORD: Record<ProgressState, string> = {
		done: 'done',
		current: 'in progress',
		pending: 'not started',
		stopped: 'stopped here',
		skipped: 'did not run'
	};
</script>

<ol class="progress" data-testid="lq-ai-run-progress" aria-label="Run progress">
	{#each items as item (item.id)}
		<li
			class="item {item.state}"
			data-stage={item.id}
			data-state={item.state}
			aria-current={item.state === 'current' ? 'step' : undefined}
		>
			<span class="mark" aria-hidden="true">{GLYPH[item.state]}</span>
			<span class="body">
				<span class="label">{item.label} <span class="sr-only">({WORD[item.state]})</span></span>
				{#if item.detail}<span class="detail">{item.detail}</span>{/if}
				{#if item.state === 'current' && now.length > 0}
					<ul class="now" aria-label="Latest steps">
						{#each now as line}
							<li class={line.tone}>
								{#if line.who}<strong>{line.who}:</strong>{' '}{/if}{line.text}
							</li>
						{/each}
					</ul>
				{/if}
			</span>
		</li>
	{/each}
</ol>

<style>
	.progress {
		list-style: none;
		margin: 0.5rem 0;
		padding: 0;
	}
	.item {
		display: flex;
		gap: 0.6rem;
		padding: 0.3rem 0;
		font-size: 0.85rem;
		line-height: 1.5;
	}
	.mark {
		flex: none;
		width: 1.1rem;
		text-align: center;
		color: var(--lq-text-tertiary);
	}
	.body {
		display: flex;
		flex-direction: column;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.detail {
		color: var(--lq-text-secondary);
		font-size: 0.8rem;
	}
	.done .mark {
		color: var(--lq-accent);
	}
	.current .mark,
	.current .label {
		color: var(--lq-accent);
		font-weight: 600;
	}
	.stopped .mark,
	.stopped .label {
		color: var(--lq-error);
		font-weight: 600;
	}
	.pending,
	.skipped {
		color: var(--lq-text-tertiary);
	}
	.now {
		list-style: none;
		margin: 0.25rem 0 0;
		padding: 0 0 0 0.75rem;
		border-left: 2px solid var(--lq-accent-border);
		font-size: 0.8rem;
		color: var(--lq-text);
		font-weight: 400;
	}
	.now li {
		padding: 0.1rem 0;
	}
	.now .refused {
		color: var(--lq-warn);
	}
	.now .uncertain {
		color: var(--lq-error);
	}
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		margin: -1px;
		padding: 0;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}
</style>
