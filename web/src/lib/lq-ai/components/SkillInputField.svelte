<script lang="ts">
	/**
	 * One declared skill input, rendered by type:
	 * - `enum` with options → <select>.
	 * - `boolean` → <input type=checkbox>.
	 * - `integer` → <input type=number>.
	 * - `document` / `file` → <textarea> for pasted text; when required and
	 *   left empty, the chat's ready attached files stand in for it.
	 * - anything else → <input type=text>.
	 */
	import type { SkillInputDef } from '../types';
	import {
		documentInputPlaceholder,
		enumOptions,
		isDocumentInput,
		skillInputFieldId
	} from '../chat/skillInputs';

	export let skillName: string;
	export let input: SkillInputDef;
	export let value: unknown = undefined;
	/** Attached files whose text is ready to send. */
	export let readyFileNames: string[] = [];
	/** Attached files still being ingested. */
	export let processingFileNames: string[] = [];
	export let onChange: (value: unknown) => void = () => undefined;

	$: options = enumOptions(input);
	$: fieldId = skillInputFieldId(skillName, input.name);
	$: bindsAttachedFiles = isDocumentInput(input) && input.required === true;
	$: isEmpty = !String(value ?? '').trim();
</script>

<div>
	<label for={fieldId} class="lq-field-label block text-xs font-medium">
		{input.name}
		{#if input.required}
			<span class="lq-field-required">*</span>
		{/if}
	</label>
	{#if input.description}
		<p class="lq-field-help text-xs">{input.description}</p>
	{/if}

	{#if options.length > 0}
		<select
			id={fieldId}
			class="lq-field-control mt-1 block w-full text-sm"
			value={value ?? input.default ?? ''}
			on:change={(e) => onChange((e.target as HTMLSelectElement).value)}
			data-testid={fieldId}
		>
			<option value="" disabled>— select —</option>
			{#each options as opt}
				<option value={opt}>{opt}</option>
			{/each}
		</select>
	{:else if input.type === 'boolean'}
		<input
			id={fieldId}
			type="checkbox"
			class="mt-1"
			checked={Boolean(value ?? input.default ?? false)}
			on:change={(e) => onChange((e.target as HTMLInputElement).checked)}
			data-testid={fieldId}
		/>
	{:else if input.type === 'integer'}
		<input
			id={fieldId}
			type="number"
			class="lq-field-control mt-1 block w-full text-sm"
			value={value ?? input.default ?? ''}
			on:input={(e) => onChange(parseInt((e.target as HTMLInputElement).value, 10))}
			data-testid={fieldId}
		/>
	{:else if isDocumentInput(input)}
		<textarea
			id={fieldId}
			rows="2"
			class="lq-field-control mt-1 block w-full text-sm"
			placeholder={documentInputPlaceholder(input, readyFileNames)}
			value={String(value ?? '')}
			on:input={(e) => onChange((e.target as HTMLTextAreaElement).value)}
			data-testid={fieldId}
		></textarea>
		{#if bindsAttachedFiles && isEmpty}
			{#if readyFileNames.length > 0}
				<p class="lq-field-help mt-1 text-xs" data-testid={`${fieldId}-attached`}>
					Using attached: {readyFileNames.join(', ')}
				</p>
			{:else if processingFileNames.length > 0}
				<p class="lq-field-help mt-1 text-xs" data-testid={`${fieldId}-processing`}>
					Waiting for {processingFileNames.join(', ')} to finish processing.
				</p>
			{/if}
		{/if}
	{:else}
		<input
			id={fieldId}
			type="text"
			class="lq-field-control mt-1 block w-full text-sm"
			value={String(value ?? input.default ?? '')}
			on:input={(e) => onChange((e.target as HTMLInputElement).value)}
			data-testid={fieldId}
		/>
	{/if}
</div>

<style>
	@import '../styles/practice.css';

	.lq-field-label {
		color: var(--lq-text-secondary);
	}

	.lq-field-required {
		color: var(--lq-error);
	}

	.lq-field-help {
		color: var(--lq-text-tertiary);
	}

	.lq-field-control {
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-sm);
		background: var(--lq-canvas);
		color: var(--lq-text);
		padding: 4px 8px;
	}
	.lq-field-control:focus {
		border-color: var(--lq-accent);
		outline: none;
	}
</style>
