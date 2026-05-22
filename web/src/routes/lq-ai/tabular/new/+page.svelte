<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import {
		listKnowledgeBases,
		listKnowledgeBaseFiles
	} from '$lib/lq-ai/api/knowledgeBases';
	import { listSkills } from '$lib/lq-ai/api/skills';
	import { previewTabularCost, executeTabular } from '$lib/lq-ai/api/tabular';
	import type {
		KnowledgeBase,
		KnowledgeBaseFile,
		SkillSummary,
		TabularColumnSpec,
		TabularPreviewCostResponse
	} from '$lib/lq-ai/types';

	import {
		type WizardStep,
		stepIndex,
		nextStep,
		prevStep,
		isFirstStep,
		isLastStep,
		validateDocumentsStep,
		validateColumnsStep,
		requiresCostConfirmation,
		buildPreviewRequest,
		buildExecuteRequest,
		TABULAR_MAX_DOCS,
		COST_CONFIRMATION_THRESHOLD_USD
	} from './page-helpers';
	import { formatCellCount, formatCostUsd } from '../page-helpers';

	// --- Wizard state -------------------------------------------------------

	let currentStep: WizardStep = 'documents';
	let stepError: string | null = null;
	let submitError: string | null = null;

	const stepLabels: Record<WizardStep, string> = {
		documents: 'Documents',
		columns: 'Columns',
		preview: 'Cost preview',
		confirm: 'Confirm & run'
	};

	// --- Step 1: Documents (KB-scoped picker) -------------------------------
	// Decision C-7: KB / Project / free-pick — KB-only ships in v0.3.0; the
	// other two sources are deferred (filed at Phase C close).

	let kbs: KnowledgeBase[] = [];
	let kbFiles: KnowledgeBaseFile[] = [];
	let selectedKbId: string | null = null;
	let kbLoading = false;
	let filesLoading = false;
	let kbError: string | null = null;

	let selectedFiles: Map<string, KnowledgeBaseFile> = new Map();
	$: documentIds = [...selectedFiles.values()]
		.map((f) => f.document_id ?? null)
		.filter((id): id is string => id !== null);

	async function loadKBs(): Promise<void> {
		kbLoading = true;
		kbError = null;
		try {
			kbs = await listKnowledgeBases();
		} catch (err) {
			kbError = err instanceof LQAIApiError ? err.message : 'Failed to load knowledge bases.';
		} finally {
			kbLoading = false;
		}
	}

	async function onSelectKb(kbId: string): Promise<void> {
		selectedKbId = kbId;
		filesLoading = true;
		kbError = null;
		try {
			kbFiles = await listKnowledgeBaseFiles(kbId);
		} catch (err) {
			kbError = err instanceof LQAIApiError ? err.message : 'Failed to load KB files.';
		} finally {
			filesLoading = false;
		}
	}

	function toggleFile(file: KnowledgeBaseFile): void {
		const next = new Map(selectedFiles);
		if (next.has(file.id)) {
			next.delete(file.id);
		} else {
			// Only files with a document_id are usable — the C5 parse pipeline
			// needs to have produced a documents row before tabular extraction
			// can attach to it.
			if (file.document_id) {
				next.set(file.id, file);
			}
		}
		selectedFiles = next;
	}

	// --- Step 2: Columns (saved skill OR ad-hoc) ----------------------------

	type ColumnsMode = 'skill' | 'adhoc';
	let columnsMode: ColumnsMode = 'skill';
	let allTableSkills: SkillSummary[] = [];
	let selectedSkillName: string | null = null;
	let skillsLoading = false;
	let skillsError: string | null = null;
	let adhocColumns: TabularColumnSpec[] = [{ name: '', query: '' }];

	async function loadTableSkills(): Promise<void> {
		skillsLoading = true;
		skillsError = null;
		try {
			const all = await listSkills();
			allTableSkills = all.filter((s) => s.output_format === 'table');
			// Pre-select the first available skill so the dropdown isn't
			// stuck on "Choose..." when only one is present.
			if (allTableSkills.length === 1 && !selectedSkillName) {
				selectedSkillName = allTableSkills[0].name;
			}
		} catch (err) {
			skillsError = err instanceof LQAIApiError ? err.message : 'Failed to load skills.';
		} finally {
			skillsLoading = false;
		}
	}

	function addAdhocColumn(): void {
		adhocColumns = [...adhocColumns, { name: '', query: '' }];
	}

	function removeAdhocColumn(idx: number): void {
		adhocColumns = adhocColumns.filter((_, i) => i !== idx);
		if (adhocColumns.length === 0) {
			adhocColumns = [{ name: '', query: '' }];
		}
	}

	function updateAdhocColumn(idx: number, patch: Partial<TabularColumnSpec>): void {
		adhocColumns = adhocColumns.map((col, i) => (i === idx ? { ...col, ...patch } : col));
	}

	$: columnsState = {
		skillName: columnsMode === 'skill' ? selectedSkillName : null,
		columns: columnsMode === 'adhoc' ? adhocColumns.filter((c) => c.name.trim() || c.query.trim()) : []
	};

	// --- Step 3: Cost preview ----------------------------------------------

	let preview: TabularPreviewCostResponse | null = null;
	let previewLoading = false;
	let previewError: string | null = null;
	$: gateRequiresConfirmation = preview ? requiresCostConfirmation(preview.estimated_cost_usd) : false;
	let confirmationChecked = false;

	async function fetchPreview(): Promise<void> {
		preview = null;
		previewError = null;
		previewLoading = true;
		try {
			const body = buildPreviewRequest({
				documentIds,
				skillName: columnsState.skillName,
				columns: columnsState.columns
			});
			preview = await previewTabularCost(body);
		} catch (err) {
			previewError = err instanceof LQAIApiError ? err.message : 'Failed to load cost preview.';
		} finally {
			previewLoading = false;
		}
	}

	// --- Step 4: Confirm + execute ------------------------------------------

	let submitting = false;

	async function executeAndRedirect(): Promise<void> {
		if (!preview) return;
		submitError = null;
		submitting = true;
		try {
			const body = buildExecuteRequest({
				documentIds,
				skillName: columnsState.skillName,
				columns: columnsState.columns,
				confirmedCostUsd: preview.estimated_cost_usd
			});
			const exec = await executeTabular(body);
			goto(`/lq-ai/tabular/${exec.id}`);
		} catch (err) {
			submitError = err instanceof LQAIApiError ? err.message : 'Failed to start tabular run.';
		} finally {
			submitting = false;
		}
	}

	// --- Step navigation ----------------------------------------------------

	// Reactive — referencing the dependent state directly so Svelte's
	// compiler tracks `documentIds`, `columnsState`, `preview`, etc.
	// A previous `canAdvanceFrom(step)` helper hid those deps inside a
	// function call; Svelte does not trace into function bodies, so the
	// button's `disabled` binding never re-evaluated when the selection
	// changed and the Next button stayed disabled (DE-XXX, M3-C3).
	$: canAdvance = ((): boolean => {
		switch (currentStep) {
			case 'documents':
				return validateDocumentsStep(documentIds) === null;
			case 'columns':
				return validateColumnsStep(columnsState) === null;
			case 'preview':
				return preview !== null && !previewLoading;
			case 'confirm':
				return !gateRequiresConfirmation || confirmationChecked;
		}
	})();

	async function advance(): Promise<void> {
		stepError = null;
		switch (currentStep) {
			case 'documents': {
				const err = validateDocumentsStep(documentIds);
				if (err) {
					stepError = err;
					return;
				}
				currentStep = nextStep(currentStep);
				return;
			}
			case 'columns': {
				const err = validateColumnsStep(columnsState);
				if (err) {
					stepError = err;
					return;
				}
				currentStep = nextStep(currentStep);
				await fetchPreview();
				return;
			}
			case 'preview':
				if (!preview) return;
				currentStep = nextStep(currentStep);
				return;
			case 'confirm':
				await executeAndRedirect();
				return;
		}
	}

	function retreat(): void {
		stepError = null;
		if (!isFirstStep(currentStep)) {
			currentStep = prevStep(currentStep);
		}
	}

	onMount(async () => {
		await Promise.all([loadKBs(), loadTableSkills()]);
	});
</script>

<svelte:head>
	<title>New Tabular Review · LQ.AI</title>
</svelte:head>

<section class="lq-tabwiz">
	<header class="lq-tabwiz__header">
		<h1>New Tabular Review</h1>
		<p class="lq-tabwiz__subtitle">
			Run a column spec across multiple documents. Each cell is grounded by the Citation Engine.
		</p>
	</header>

	<!-- Step indicator -->
	<ol class="lq-tabwiz__steps" aria-label="Wizard steps" data-testid="lq-tabwiz-steps">
		{#each ['documents', 'columns', 'preview', 'confirm'] as step (step)}
			{@const stepWiz = step as WizardStep}
			{@const idx = stepIndex(stepWiz)}
			{@const curIdx = stepIndex(currentStep)}
			<li
				class="lq-tabwiz__step"
				data-active={stepWiz === currentStep}
				data-done={idx < curIdx}
				data-testid="lq-tabwiz-step-pill"
				data-step={stepWiz}
			>
				<span class="lq-tabwiz__step-num">{idx + 1}</span>
				<span class="lq-tabwiz__step-label">{stepLabels[stepWiz]}</span>
			</li>
		{/each}
	</ol>

	<div class="lq-tabwiz__body" data-testid="lq-tabwiz-body" data-current-step={currentStep}>
		{#if currentStep === 'documents'}
			<!-- ---------------- Step 1: Documents ---------------- -->
			<h2>Pick documents</h2>
			<p class="lq-tabwiz__hint">
				Up to {TABULAR_MAX_DOCS} documents. Currently selected:
				<strong data-testid="lq-tabwiz-doc-count">{documentIds.length}</strong>.
			</p>

			{#if kbLoading}
				<div class="lq-tabwiz__state">Loading knowledge bases…</div>
			{:else if kbError}
				<div class="lq-tabwiz__error" role="alert">{kbError}</div>
			{:else if kbs.length === 0}
				<div class="lq-tabwiz__state">
					You don't have any knowledge bases yet. Create one from
					<a href="/lq-ai/knowledge">Knowledge</a> to enable tabular review.
				</div>
			{:else}
				<label class="lq-tabwiz__field">
					<span>Knowledge base</span>
					<select
						data-testid="lq-tabwiz-kb-select"
						bind:value={selectedKbId}
						on:change={(e) => onSelectKb((e.target as HTMLSelectElement).value)}
					>
						<option value={null} disabled>Choose a KB…</option>
						{#each kbs as kb (kb.id)}
							<option value={kb.id}>{kb.name}</option>
						{/each}
					</select>
				</label>

				{#if selectedKbId}
					{#if filesLoading}
						<div class="lq-tabwiz__state">Loading files…</div>
					{:else if kbFiles.length === 0}
						<div class="lq-tabwiz__state">No files in this KB.</div>
					{:else}
						<ul class="lq-tabwiz__files" data-testid="lq-tabwiz-files">
							{#each kbFiles as f (f.id)}
								<li>
									<label class="lq-tabwiz__file" data-disabled={!f.document_id}>
										<input
											type="checkbox"
											data-testid="lq-tabwiz-file-checkbox"
											data-file-id={f.id}
											disabled={!f.document_id}
											checked={selectedFiles.has(f.id)}
											on:change={() => toggleFile(f)}
										/>
										<span class="lq-tabwiz__file-name">{f.filename}</span>
										{#if !f.document_id}
											<span class="lq-tabwiz__file-warn">Not yet parsed</span>
										{/if}
									</label>
								</li>
							{/each}
						</ul>
					{/if}
				{/if}
			{/if}
		{:else if currentStep === 'columns'}
			<!-- ---------------- Step 2: Columns ---------------- -->
			<h2>Define columns</h2>
			<p class="lq-tabwiz__hint">
				Pick a saved table-mode skill or define columns inline.
			</p>

			<fieldset class="lq-tabwiz__mode" data-testid="lq-tabwiz-columns-mode">
				<label>
					<input type="radio" value="skill" bind:group={columnsMode} />
					Saved skill
				</label>
				<label>
					<input type="radio" value="adhoc" bind:group={columnsMode} />
					Ad-hoc columns
				</label>
			</fieldset>

			{#if columnsMode === 'skill'}
				{#if skillsLoading}
					<div class="lq-tabwiz__state">Loading skills…</div>
				{:else if skillsError}
					<div class="lq-tabwiz__error" role="alert">{skillsError}</div>
				{:else if allTableSkills.length === 0}
					<div class="lq-tabwiz__state">
						No table-mode skills are available. Switch to ad-hoc mode to define columns inline.
						Reference table-mode skills (e.g.
						<code>contract-snapshot</code>) ship as built-ins — see the
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/skill-authoring-guide.md">
							skill authoring guide
						</a>
						to add your own.
					</div>
				{:else}
					<label class="lq-tabwiz__field">
						<span>Table-mode skill</span>
						<select bind:value={selectedSkillName} data-testid="lq-tabwiz-skill-select">
							<option value={null} disabled>Choose…</option>
							{#each allTableSkills as s (s.name)}
								<option value={s.name}>{s.title} ({s.name})</option>
							{/each}
						</select>
					</label>
					{#if selectedSkillName}
						{@const s = allTableSkills.find((sk) => sk.name === selectedSkillName)}
						{#if s?.description}
							<p class="lq-tabwiz__skill-desc">{s.description}</p>
						{/if}
					{/if}
				{/if}
			{:else}
				<table class="lq-tabwiz__adhoc" data-testid="lq-tabwiz-adhoc-table">
					<thead>
						<tr>
							<th>Name</th>
							<th>Query</th>
							<th class="lq-tabwiz__adhoc-actions">&nbsp;</th>
						</tr>
					</thead>
					<tbody>
						{#each adhocColumns as col, idx (idx)}
							<tr data-testid="lq-tabwiz-adhoc-row">
								<td>
									<input
										type="text"
										placeholder="e.g. Term"
										value={col.name}
										on:input={(e) =>
											updateAdhocColumn(idx, {
												name: (e.target as HTMLInputElement).value
											})}
									/>
								</td>
								<td>
									<input
										type="text"
										placeholder="e.g. What is the term of this agreement?"
										value={col.query}
										on:input={(e) =>
											updateAdhocColumn(idx, {
												query: (e.target as HTMLInputElement).value
											})}
									/>
								</td>
								<td class="lq-tabwiz__adhoc-actions">
									<button
										type="button"
										class="lq-tabwiz__adhoc-remove"
										on:click={() => removeAdhocColumn(idx)}
										aria-label="Remove column">×</button
									>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
				<button
					type="button"
					class="lq-tabwiz__adhoc-add"
					data-testid="lq-tabwiz-adhoc-add"
					on:click={addAdhocColumn}>+ Add column</button
				>
			{/if}
		{:else if currentStep === 'preview'}
			<!-- ---------------- Step 3: Cost preview ---------------- -->
			<h2>Cost preview</h2>

			{#if previewLoading}
				<div class="lq-tabwiz__state">Computing cost preview…</div>
			{:else if previewError}
				<div class="lq-tabwiz__error" role="alert">{previewError}</div>
				<button type="button" on:click={fetchPreview}>Retry preview</button>
			{:else if preview}
				<dl class="lq-tabwiz__preview" data-testid="lq-tabwiz-preview">
					<div>
						<dt>Cells</dt>
						<dd data-testid="lq-tabwiz-preview-cells">{preview.cells_count}</dd>
					</div>
					<div>
						<dt>Estimated tokens</dt>
						<dd>{preview.estimated_tokens.toLocaleString()}</dd>
					</div>
					<div>
						<dt>Estimated cost</dt>
						<dd data-testid="lq-tabwiz-preview-cost">
							{formatCostUsd(preview.estimated_cost_usd)}
						</dd>
					</div>
				</dl>

				{#if Object.keys(preview.per_tier_breakdown).length > 0}
					<details class="lq-tabwiz__tier-detail">
						<summary>Per-tier breakdown</summary>
						<ul>
							{#each Object.entries(preview.per_tier_breakdown) as [tier, count] (tier)}
								<li><strong>{tier}:</strong> {count} cells</li>
							{/each}
						</ul>
					</details>
				{/if}
			{/if}
		{:else if currentStep === 'confirm'}
			<!-- ---------------- Step 4: Confirm + execute ---------------- -->
			<h2>Confirm and run</h2>

			{#if preview}
				<p>
					About to run
					<strong>{formatCellCount(documentIds.length, preview.cells_count / documentIds.length)}</strong>
					at an estimated cost of
					<strong>{formatCostUsd(preview.estimated_cost_usd)}</strong>.
				</p>

				{#if gateRequiresConfirmation}
					<label class="lq-tabwiz__gate" data-testid="lq-tabwiz-confirm-gate">
						<input
							type="checkbox"
							bind:checked={confirmationChecked}
							data-testid="lq-tabwiz-confirm-checkbox"
						/>
						I understand this will cost approximately
						{formatCostUsd(preview.estimated_cost_usd)} and is at or above the
						{formatCostUsd(String(COST_CONFIRMATION_THRESHOLD_USD))} confirmation threshold.
					</label>
				{/if}

				{#if submitError}
					<div class="lq-tabwiz__error" role="alert">{submitError}</div>
				{/if}
			{/if}
		{/if}

		{#if stepError}
			<div class="lq-tabwiz__error" role="alert" data-testid="lq-tabwiz-step-error">
				{stepError}
			</div>
		{/if}
	</div>

	<footer class="lq-tabwiz__nav">
		<button
			type="button"
			class="lq-tabwiz__back"
			data-testid="lq-tabwiz-back"
			on:click={retreat}
			disabled={isFirstStep(currentStep) || submitting}
		>
			Back
		</button>
		<button
			type="button"
			class="lq-tabwiz__next"
			data-testid="lq-tabwiz-next"
			on:click={advance}
			disabled={!canAdvance || submitting}
		>
			{#if isLastStep(currentStep)}
				{submitting ? 'Starting…' : 'Run'}
			{:else}
				Next
			{/if}
		</button>
	</footer>
</section>

<style>
	.lq-tabwiz {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
		max-width: 56rem;
		margin: 0 auto;
		padding: 1.5rem;
	}
	.lq-tabwiz__header h1 {
		margin: 0;
		font-size: 1.5rem;
	}
	.lq-tabwiz__subtitle {
		margin: 0.25rem 0 0;
		color: var(--lq-text-secondary);
	}
	.lq-tabwiz__steps {
		display: flex;
		gap: 0.5rem;
		padding: 0;
		margin: 0;
		list-style: none;
	}
	.lq-tabwiz__step {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.625rem 0.875rem;
		background: var(--lq-inset);
		border-radius: 0.5rem;
		font-size: 0.875rem;
		color: var(--lq-text-secondary);
	}
	.lq-tabwiz__step[data-active='true'] {
		background: var(--lq-accent-soft, var(--lq-inset));
		color: var(--lq-text);
		font-weight: 500;
		border: 1px solid var(--lq-accent, var(--lq-border));
	}
	.lq-tabwiz__step[data-done='true'] {
		opacity: 0.85;
	}
	.lq-tabwiz__step-num {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.5rem;
		height: 1.5rem;
		border-radius: 999px;
		background: var(--lq-surface);
		font-weight: 600;
		font-size: 0.8125rem;
	}
	.lq-tabwiz__body {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		min-height: 18rem;
		padding: 1.25rem;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
	}
	.lq-tabwiz__body h2 {
		margin: 0;
		font-size: 1.125rem;
	}
	.lq-tabwiz__hint {
		margin: 0;
		color: var(--lq-text-secondary);
	}
	.lq-tabwiz__field {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}
	.lq-tabwiz__field select {
		padding: 0.5rem 0.625rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		background: var(--lq-surface);
		color: var(--lq-text);
	}
	.lq-tabwiz__files {
		list-style: none;
		padding: 0;
		margin: 0;
		max-height: 24rem;
		overflow-y: auto;
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
	}
	.lq-tabwiz__files li {
		border-bottom: 1px solid var(--lq-border);
	}
	.lq-tabwiz__files li:last-child {
		border-bottom: none;
	}
	.lq-tabwiz__file {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		padding: 0.625rem 0.875rem;
		cursor: pointer;
	}
	.lq-tabwiz__file[data-disabled='true'] {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.lq-tabwiz__file-warn {
		font-size: 0.75rem;
		color: var(--lq-warning, var(--lq-text-secondary));
		margin-left: auto;
	}
	.lq-tabwiz__mode {
		border: none;
		padding: 0;
		display: flex;
		gap: 1rem;
	}
	.lq-tabwiz__mode label {
		display: flex;
		gap: 0.375rem;
		align-items: center;
		cursor: pointer;
	}
	.lq-tabwiz__skill-desc {
		margin: 0.25rem 0 0;
		color: var(--lq-text-secondary);
		font-size: 0.875rem;
	}
	.lq-tabwiz__adhoc {
		width: 100%;
		border-collapse: collapse;
		background: var(--lq-surface);
	}
	.lq-tabwiz__adhoc th,
	.lq-tabwiz__adhoc td {
		padding: 0.5rem;
		border-bottom: 1px solid var(--lq-border);
		vertical-align: top;
	}
	.lq-tabwiz__adhoc input {
		width: 100%;
		padding: 0.375rem 0.5rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.25rem;
		background: var(--lq-surface);
		color: var(--lq-text);
	}
	.lq-tabwiz__adhoc-actions {
		width: 2rem;
		text-align: center;
	}
	.lq-tabwiz__adhoc-remove {
		background: none;
		border: none;
		font-size: 1.25rem;
		color: var(--lq-text-secondary);
		cursor: pointer;
	}
	.lq-tabwiz__adhoc-add {
		align-self: flex-start;
		padding: 0.375rem 0.625rem;
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		font-size: 0.875rem;
		cursor: pointer;
	}
	.lq-tabwiz__preview {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 1rem;
	}
	.lq-tabwiz__preview > div {
		padding: 0.875rem;
		background: var(--lq-inset);
		border-radius: 0.5rem;
	}
	.lq-tabwiz__preview dt {
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.lq-tabwiz__preview dd {
		margin: 0.25rem 0 0;
		font-size: 1.25rem;
		font-weight: 600;
	}
	.lq-tabwiz__tier-detail {
		padding: 0.625rem 0.875rem;
		background: var(--lq-inset);
		border-radius: 0.375rem;
	}
	.lq-tabwiz__tier-detail summary {
		cursor: pointer;
		font-size: 0.875rem;
	}
	.lq-tabwiz__tier-detail ul {
		margin: 0.5rem 0 0;
		padding-left: 1.25rem;
	}
	.lq-tabwiz__gate {
		display: flex;
		gap: 0.5rem;
		padding: 0.875rem;
		background: var(--lq-warning-soft, var(--lq-inset));
		border: 1px solid var(--lq-warning-border, var(--lq-border));
		border-radius: 0.375rem;
		cursor: pointer;
		font-size: 0.875rem;
	}
	.lq-tabwiz__state {
		padding: 1rem;
		background: var(--lq-inset);
		border-radius: 0.375rem;
		color: var(--lq-text-secondary);
		text-align: center;
	}
	.lq-tabwiz__error {
		padding: 0.875rem;
		background: var(--lq-error-soft, var(--lq-inset));
		border: 1px solid var(--lq-error-border, var(--lq-border));
		border-radius: 0.375rem;
		color: var(--lq-error, inherit);
	}
	.lq-tabwiz__nav {
		display: flex;
		justify-content: space-between;
		gap: 0.75rem;
	}
	.lq-tabwiz__back,
	.lq-tabwiz__next {
		padding: 0.5rem 1rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		font-size: 0.875rem;
		font-weight: 500;
		cursor: pointer;
		background: var(--lq-surface);
	}
	.lq-tabwiz__next {
		background: var(--lq-accent, #4f46e5);
		color: var(--lq-on-accent, #ffffff);
		border-color: transparent;
	}
	.lq-tabwiz__next:disabled,
	.lq-tabwiz__back:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
