<script lang="ts">
	/**
	 * ColumnEditor — DE-297 table-mode column list for skill authoring.
	 *
	 * Used by `SkillWizard.svelte` (/lq-ai/skills/new) and the user-skill
	 * edit page when the author picks `output_format: table`. Each row is
	 * one backend `ColumnSpec`: name, per-document extraction query, and
	 * the two optional overrides (`ensemble_verification`,
	 * `minimum_inference_tier` 1-5, both defaulting to "inherit" = the
	 * backend's `None`).
	 *
	 * Contract with the parent:
	 * - `bind:columns` — the parent owns the array; every edit reassigns
	 *   it so Svelte reactivity (and the parent's validation gate)
	 *   re-runs.
	 * - `showErrors` — when true, all inline errors render regardless of
	 *   touch state (the parent flips it on a save attempt). Before
	 *   that, a field's error shows only after the user leaves the field
	 *   (matches the SkillWizard slash-alias validate-on-blur idiom).
	 *
	 * Validation mirrors — never widens — the backend schema; see the
	 * header of `../skills/tableColumns.ts`.
	 */
	import {
		newEditableColumn,
		moveColumn,
		validateColumns,
		type EditableColumn
	} from '../skills/tableColumns';

	export let columns: EditableColumn[] = [];
	export let showErrors = false;

	/** Per-row-index touch state; reset on structural changes because
	 * indices shift when rows move or vanish. */
	let touched: Record<number, { name?: boolean; query?: boolean }> = {};

	$: validation = validateColumns(columns);

	function addColumn(): void {
		columns = [...columns, newEditableColumn()];
	}

	function removeColumn(index: number): void {
		columns = columns.filter((_, i) => i !== index);
		touched = {};
	}

	function move(index: number, delta: -1 | 1): void {
		const next = moveColumn(columns, index, delta);
		if (next !== columns) {
			columns = next;
			touched = {};
		}
	}

	function setField(index: number, patch: Partial<EditableColumn>): void {
		columns = columns.map((col, i) => (i === index ? { ...col, ...patch } : col));
	}

	function markTouched(index: number, field: 'name' | 'query'): void {
		touched = { ...touched, [index]: { ...touched[index], [field]: true } };
	}

	function errorFor(index: number, field: 'name' | 'query'): string | null {
		if (!showErrors && !touched[index]?.[field]) return null;
		return validation.columnErrors[index]?.[field] ?? null;
	}
</script>

<div class="lq-column-editor" data-testid="lq-ai-column-editor">
	<!-- The min-one-column rule is structural, not field-level — surface it
	     immediately (there is no field to blur), matching the backend's
	     _table_mode_requires_columns rejection. -->
	{#if validation.listError}
		<p class="error list-error" data-testid="lq-ai-column-list-error">
			{validation.listError}
		</p>
	{/if}

	{#each columns as col, i (i)}
		<fieldset class="column-row" data-testid="lq-ai-column-row">
			<div class="row-head">
				<span class="row-index">Column {i + 1}</span>
				<span class="row-actions">
					<button
						type="button"
						class="ghost"
						disabled={i === 0}
						aria-label="move column {i + 1} up"
						data-testid="lq-ai-column-up"
						on:click={() => move(i, -1)}
					>
						↑
					</button>
					<button
						type="button"
						class="ghost"
						disabled={i === columns.length - 1}
						aria-label="move column {i + 1} down"
						data-testid="lq-ai-column-down"
						on:click={() => move(i, 1)}
					>
						↓
					</button>
					<button
						type="button"
						class="ghost danger"
						aria-label="remove column {i + 1}"
						data-testid="lq-ai-column-remove"
						on:click={() => removeColumn(i)}
					>
						Remove
					</button>
				</span>
			</div>

			<label>
				<span>Name <em class="required">*</em></span>
				<input
					type="text"
					value={col.name}
					placeholder="Governing law"
					aria-label="column {i + 1} name"
					data-testid="lq-ai-column-name"
					on:input={(e) => setField(i, { name: e.currentTarget.value })}
					on:blur={() => markTouched(i, 'name')}
				/>
				{#if errorFor(i, 'name')}
					<span class="error inline-error" data-testid="lq-ai-column-name-error">
						{errorFor(i, 'name')}
					</span>
				{/if}
			</label>

			<label>
				<span>Extraction query <em class="required">*</em></span>
				<textarea
					value={col.query}
					rows="3"
					placeholder="Which law governs this agreement? Quote the operative clause."
					aria-label="column {i + 1} query"
					data-testid="lq-ai-column-query"
					on:input={(e) => setField(i, { query: e.currentTarget.value })}
					on:blur={() => markTouched(i, 'query')}
				></textarea>
				{#if errorFor(i, 'query')}
					<span class="error inline-error" data-testid="lq-ai-column-query-error">
						{errorFor(i, 'query')}
					</span>
				{/if}
			</label>

			<div class="overrides">
				<label>
					<span>Ensemble verification</span>
					<select
						value={col.ensemble_verification === null
							? ''
							: String(col.ensemble_verification)}
						aria-label="column {i + 1} ensemble verification"
						data-testid="lq-ai-column-ensemble"
						on:change={(e) =>
							setField(i, {
								ensemble_verification:
									e.currentTarget.value === '' ? null : e.currentTarget.value === 'true'
							})}
					>
						<option value="">Inherit (default)</option>
						<option value="true">On</option>
						<option value="false">Off</option>
					</select>
				</label>
				<label>
					<span>Minimum inference tier</span>
					<select
						value={col.minimum_inference_tier === null
							? ''
							: String(col.minimum_inference_tier)}
						aria-label="column {i + 1} minimum inference tier"
						data-testid="lq-ai-column-tier"
						on:change={(e) =>
							setField(i, {
								minimum_inference_tier:
									e.currentTarget.value === '' ? null : Number(e.currentTarget.value)
							})}
					>
						<option value="">Inherit (default)</option>
						{#each [1, 2, 3, 4, 5] as tier}
							<option value={String(tier)}>Tier {tier}</option>
						{/each}
					</select>
				</label>
			</div>
		</fieldset>
	{/each}

	<button
		type="button"
		class="ghost add-column"
		data-testid="lq-ai-column-add"
		on:click={addColumn}
	>
		+ Add column
	</button>
</div>

<style>
	.lq-column-editor {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.column-row {
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: 6px;
		padding: 12px;
		margin: 0;
	}
	.row-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8px;
	}
	.row-index {
		font-size: 12px;
		font-weight: 600;
		color: var(--lq-text-tertiary, #9ca3af);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.row-actions {
		display: flex;
		gap: 4px;
	}
	label {
		display: block;
		margin-bottom: 8px;
	}
	label > span {
		display: block;
		font-size: 13px;
		font-weight: 600;
		margin-bottom: 4px;
	}
	.required {
		color: var(--lq-error, #b54848);
		font-style: normal;
	}
	input,
	textarea,
	select {
		width: 100%;
		padding: 8px;
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: 6px;
		font-size: 14px;
		font-family: inherit;
		box-sizing: border-box;
	}
	.overrides {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
	}
	.error {
		color: var(--lq-error, #b54848);
		font-size: 12px;
	}
	.inline-error {
		display: block;
		margin-top: 4px;
	}
	.list-error {
		margin: 0;
	}
	.ghost {
		background: transparent;
		border: 1px solid var(--lq-border, #e5e7eb);
		padding: 4px 10px;
		border-radius: 6px;
		cursor: pointer;
		font-size: 13px;
	}
	.ghost:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.ghost.danger {
		color: var(--lq-error, #b54848);
		border-color: var(--lq-error, #b54848);
	}
	.add-column {
		align-self: flex-start;
	}
</style>
