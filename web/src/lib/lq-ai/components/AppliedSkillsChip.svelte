<script lang="ts">
	/**
	 * Per ADR 0007 / Task C2: assistant messages surface the skills the
	 * gateway applied. Each chip is clickable and surfaces the explanation
	 * "this message used the [skill-name] skill" — the M1 experience; D2/M2
	 * may turn this into a richer skill-inspector panel.
	 */
	export let appliedSkills: string[] = [];
	export let onSkillClicked: ((name: string) => void) | undefined = undefined;
</script>

{#if appliedSkills.length > 0}
	<div class="flex flex-wrap gap-1 mt-1" data-testid="lq-ai-applied-skills">
		{#each appliedSkills as name}
			<button
				type="button"
				class="inline-flex items-center px-2 py-0.5 rounded-full border lq-t-accent-border lq-t-accent-soft lq-t-accent text-xs font-medium lq-t-accent-border-hover transition-colors"
				title={`This message used the ${name} skill`}
				on:click={() => onSkillClicked?.(name)}
			>
				<svg
					class="h-3 w-3 mr-1"
					viewBox="0 0 20 20"
					fill="currentColor"
					aria-hidden="true"
				>
					<path
						d="M10 2a1 1 0 0 1 .894.553l2.236 4.472 4.93.717a1 1 0 0 1 .555 1.706l-3.566 3.476.842 4.91a1 1 0 0 1-1.451 1.054L10 16.347l-4.44 2.541a1 1 0 0 1-1.451-1.054l.842-4.91L1.385 9.448a1 1 0 0 1 .555-1.706l4.93-.717L9.106 2.553A1 1 0 0 1 10 2z"
					/>
				</svg>
				{name}
			</button>
		{/each}
	</div>
{/if}

<style>
	/* Colour tokens replacing Tailwind palette utilities (S1-1b). */
	.lq-t-accent {
		color: var(--lq-accent);
	}
	.lq-t-accent-border {
		border-color: var(--lq-accent-border);
	}
	.lq-t-accent-border-hover:hover {
		background-color: var(--lq-accent-border);
	}
	.lq-t-accent-soft {
		background-color: var(--lq-accent-soft);
	}
</style>
