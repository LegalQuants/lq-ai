<script lang="ts">
	/**
	 * Renders the inputs a skill declares in its frontmatter as a form.
	 *
	 * Required inputs are always visible; optional ones sit behind a
	 * collapsed disclosure so a skill with many of them does not take over
	 * the composer. Send-time validation lives in `chat/skillInputs.ts`
	 * (`resolveSkillInputsForSend`), which also binds ready attached files to
	 * a required document input the user left empty.
	 */
	import type { SkillInputDef } from '../types';
	import { isFormInput } from '../chat/skillInputs';
	import SkillInputField from './SkillInputField.svelte';

	export let skillName: string;
	export let inputs: SkillInputDef[] = [];
	export let values: Record<string, unknown> = {};
	export let readyFileNames: string[] = [];
	export let processingFileNames: string[] = [];
	export let onChange: (next: Record<string, unknown>) => void = () => undefined;

	$: formInputs = inputs.filter(isFormInput);
	$: requiredInputs = formInputs.filter((inp) => inp.required);
	$: optionalInputs = formInputs.filter((inp) => !inp.required);

	function update(name: string, value: unknown) {
		onChange({ ...values, [name]: value });
	}
</script>

{#if formInputs.length === 0}
	<p class="lq-form-empty text-xs italic">This skill has no inputs.</p>
{:else}
	<form class="space-y-2" data-testid="lq-ai-skill-input-form" on:submit|preventDefault>
		{#each requiredInputs as inp (inp.name)}
			<SkillInputField
				{skillName}
				input={inp}
				value={values[inp.name]}
				{readyFileNames}
				{processingFileNames}
				onChange={(value) => update(inp.name, value)}
			/>
		{/each}
		{#if optionalInputs.length > 0}
			<details data-testid="lq-ai-skill-input-optional">
				<summary class="lq-form-summary text-xs font-medium cursor-pointer">
					More options ({optionalInputs.length})
				</summary>
				<div class="mt-2 space-y-2">
					{#each optionalInputs as inp (inp.name)}
						<SkillInputField
							{skillName}
							input={inp}
							value={values[inp.name]}
							{readyFileNames}
							{processingFileNames}
							onChange={(value) => update(inp.name, value)}
						/>
					{/each}
				</div>
			</details>
		{/if}
	</form>
{/if}

<style>
	@import '../styles/practice.css';

	.lq-form-empty {
		color: var(--lq-text-tertiary);
	}

	.lq-form-summary {
		color: var(--lq-text-secondary);
	}
</style>
