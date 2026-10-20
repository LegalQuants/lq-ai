<script lang="ts">
	/**
	 * One line of the run's activity column: a state mark, a label, what it says, and
	 * small trailing text such as spend. The same markup serves the plan, every task
	 * and the answer, so all rows look alike. Long text is cut with an ellipsis here
	 * and shown in full under the fold.
	 *
	 * The label (a task's topic) and the summary come from the run's records and the
	 * model; they are interpolated, never rendered as HTML.
	 */
	import type { ActivityState } from '$lib/lq-ai/run/activity';

	export let state: ActivityState;
	export let label: string;
	export let summary: string | null = null;
	export let meta: string | null = null;
	/** Draw the open/close mark (the line is a `<summary>`). */
	export let foldable = false;

	const GLYPH: Record<ActivityState, string> = {
		done: '✓',
		current: '●',
		pending: '○',
		stopped: '■',
		skipped: '–'
	};
	const WORD: Record<ActivityState, string> = {
		done: 'done',
		current: 'in progress',
		pending: 'not started',
		stopped: 'stopped here',
		skipped: 'did not run'
	};

	$: full = summary ? `${label} · ${summary}` : label;
</script>

<span class="line {state}">
	<span class="mark" aria-hidden="true">{GLYPH[state]}</span>
	<span class="text" title={full}>
		<span class="sr-only">({WORD[state]}) </span><span class="label">{label}</span
		>{#if summary}<span class="summary-text">{' · '}{summary}</span>{/if}
	</span>
	{#if meta}<span class="meta">{meta}</span>{/if}
	{#if foldable}<span class="caret" aria-hidden="true">›</span>{/if}
</span>

<style>
	.line {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		min-width: 0;
		font-size: 0.88rem;
		line-height: 1.5;
	}
	.mark {
		flex: none;
		width: 1.1rem;
		text-align: center;
		color: var(--lq-text-tertiary);
	}
	.text {
		flex: 1 1 auto;
		min-width: 0;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}
	.label {
		font-weight: 600;
	}
	.summary-text {
		color: var(--lq-text-secondary);
	}
	.meta {
		flex: none;
		font-size: 0.78rem;
		color: var(--lq-text-secondary);
		font-variant-numeric: tabular-nums;
	}
	.caret {
		flex: none;
		color: var(--lq-text-tertiary);
		transition: transform 0.12s;
	}
	:global(details[open] > summary) .caret {
		transform: rotate(90deg);
	}
	.done .mark {
		color: var(--lq-accent);
	}
	.current .mark,
	.current .label {
		color: var(--lq-accent);
	}
	.stopped .mark,
	.stopped .label {
		color: var(--lq-error);
	}
	/* A line that has not run, or did not: lighter in weight and mark, but still read. */
	.pending,
	.skipped {
		color: var(--lq-text-secondary);
	}
	.pending .label,
	.skipped .label {
		font-weight: 500;
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
