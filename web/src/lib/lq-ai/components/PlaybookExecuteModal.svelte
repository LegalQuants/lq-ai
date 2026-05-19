<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { goto } from '$app/navigation';

	import { executePlaybook } from '$lib/lq-ai/api/playbooks';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import {
		estimatePlaybookCost,
		formatCostUSD,
		DEFAULT_JUDGE_MODEL
	} from '$lib/lq-ai/playbookCost';
	import { listKnowledgeBases, listKnowledgeBaseFiles } from '$lib/lq-ai/api/knowledgeBases';
	import type { Playbook, KnowledgeBase, KnowledgeBaseFile } from '$lib/lq-ai/types';

	export let playbook: Playbook;

	const dispatch = createEventDispatcher<{ close: void }>();

	// KB list (loaded on mount)
	let kbs: KnowledgeBase[] = [];
	let kbsLoading = false;
	let kbsError: string | null = null;
	let selectedKbId = '';

	// File list (loaded when a KB is picked)
	let files: KnowledgeBaseFile[] = [];
	let filesLoading = false;
	let filesError: string | null = null;
	let selectedFileId = '';

	let executing = false;
	let executeError: string | null = null;

	// Client-side cost preview per §5.2 decision.
	$: cost = estimatePlaybookCost(playbook, DEFAULT_JUDGE_MODEL);

	// Only files whose parse pipeline has produced a `documents` row are
	// eligible — the execute endpoint takes `target_document_id` (a Document
	// UUID, not a File UUID). Files with `document_id == null` are still
	// parsing or failed parse; filter them out so users can't pick one.
	$: eligibleFiles = files.filter(
		(f): f is KnowledgeBaseFile & { document_id: string } =>
			typeof f.document_id === 'string' && f.document_id.length > 0
	);

	$: selectedFile = eligibleFiles.find((f) => f.id === selectedFileId) ?? null;
	$: selectedDocumentId = selectedFile?.document_id ?? '';

	async function loadKbs(): Promise<void> {
		kbsLoading = true;
		kbsError = null;
		try {
			kbs = await listKnowledgeBases();
		} catch (err) {
			kbsError = err instanceof LQAIApiError ? err.message : 'Failed to load knowledge bases.';
		} finally {
			kbsLoading = false;
		}
	}

	async function loadFilesForKb(kbId: string): Promise<void> {
		if (!kbId) {
			files = [];
			return;
		}
		filesLoading = true;
		filesError = null;
		try {
			files = await listKnowledgeBaseFiles(kbId);
		} catch (err) {
			filesError = err instanceof LQAIApiError ? err.message : 'Failed to load documents.';
			files = [];
		} finally {
			filesLoading = false;
		}
	}

	function handleKbChange(): void {
		// Reset file selection whenever the KB changes; the previously
		// selected file ID is meaningless under a different KB.
		selectedFileId = '';
		void loadFilesForKb(selectedKbId);
	}

	async function handleExecute(): Promise<void> {
		if (!selectedDocumentId) return;
		executing = true;
		executeError = null;
		try {
			const exec = await executePlaybook(playbook.id, {
				target_document_id: selectedDocumentId
			});
			dispatch('close');
			await goto(`/lq-ai/playbook-executions/${exec.id}`);
		} catch (err) {
			executeError =
				err instanceof LQAIApiError ? err.message : 'Failed to start playbook execution.';
			executing = false;
		}
	}

	function handleOverlayClick(): void {
		if (!executing) {
			dispatch('close');
		}
	}

	function handleCancel(): void {
		dispatch('close');
	}

	void loadKbs();
</script>

<div class="lq-modal-overlay" on:click={handleOverlayClick} role="presentation"></div>

<div
	class="lq-modal"
	role="dialog"
	aria-modal="true"
	aria-labelledby="lq-execute-title"
	data-testid="lq-playbook-execute-modal"
>
	<header class="lq-modal__header">
		<h2 id="lq-execute-title">Apply playbook: {playbook.name}</h2>
		<button
			type="button"
			class="lq-modal__close"
			on:click={handleCancel}
			disabled={executing}
			aria-label="Close"
		>
			×
		</button>
	</header>

	<div class="lq-modal__body">
		<div class="lq-modal__field">
			<label for="lq-execute-kb">Knowledge base</label>
			{#if kbsLoading}
				<div class="lq-modal__placeholder">Loading knowledge bases…</div>
			{:else if kbsError}
				<div class="lq-modal__placeholder" role="alert">{kbsError}</div>
			{:else if kbs.length === 0}
				<div class="lq-modal__placeholder">Upload a document to a knowledge base first.</div>
			{:else}
				<select
					id="lq-execute-kb"
					bind:value={selectedKbId}
					on:change={handleKbChange}
					data-testid="lq-playbook-execute-kb-picker"
					disabled={executing}
				>
					<option value="">Choose a knowledge base…</option>
					{#each kbs as kb (kb.id)}
						<option value={kb.id}>{kb.name}</option>
					{/each}
				</select>
			{/if}
		</div>

		{#if selectedKbId}
			<div class="lq-modal__field">
				<label for="lq-execute-doc">Target document</label>
				{#if filesLoading}
					<div class="lq-modal__placeholder">Loading documents…</div>
				{:else if filesError}
					<div class="lq-modal__placeholder" role="alert">{filesError}</div>
				{:else if eligibleFiles.length === 0}
					<div class="lq-modal__placeholder">
						No documents available in this knowledge base yet.
						{#if files.length > 0}
							({files.length} file{files.length === 1 ? '' : 's'} still processing.)
						{/if}
					</div>
				{:else}
					<select
						id="lq-execute-doc"
						bind:value={selectedFileId}
						data-testid="lq-playbook-execute-doc-picker"
						disabled={executing}
					>
						<option value="">Choose a document…</option>
						{#each eligibleFiles as f (f.id)}
							<option value={f.id}>{f.filename}</option>
						{/each}
					</select>
				{/if}
			</div>
		{/if}

		<div class="lq-modal__cost" data-testid="lq-playbook-cost-preview">
			<div class="lq-modal__cost-label">Estimated cost</div>
			<div class="lq-modal__cost-amount">{formatCostUSD(cost.estimated_cost_usd)}</div>
			<div class="lq-modal__cost-detail">
				{cost.position_count} position{cost.position_count === 1 ? '' : 's'} · model: {cost.judge_model}
			</div>
		</div>

		{#if executeError}
			<div class="lq-modal__error" role="alert" data-testid="lq-playbook-execute-error">
				{executeError}
			</div>
		{/if}
	</div>

	<footer class="lq-modal__footer">
		<button
			type="button"
			class="lq-modal__btn lq-modal__btn--secondary"
			on:click={handleCancel}
			disabled={executing}
		>
			Cancel
		</button>
		<button
			type="button"
			class="lq-modal__btn lq-modal__btn--primary"
			on:click={handleExecute}
			disabled={!selectedDocumentId || executing}
			data-testid="lq-playbook-execute-confirm"
		>
			{executing ? 'Starting…' : 'Run playbook'}
		</button>
	</footer>
</div>

<style>
	.lq-modal-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.4);
		z-index: 1000;
	}
	.lq-modal {
		position: fixed;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		width: min(90vw, 32rem);
		max-height: 90vh;
		overflow-y: auto;
		background: var(--lq-surface, #ffffff);
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: 0.5rem;
		z-index: 1001;
		display: flex;
		flex-direction: column;
		color: var(--lq-text-primary, #111827);
	}
	.lq-modal__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 1rem 1.25rem;
		border-bottom: 1px solid var(--lq-border, #e5e7eb);
	}
	.lq-modal__header h2 {
		margin: 0;
		font-size: 1.125rem;
	}
	.lq-modal__close {
		background: none;
		border: none;
		font-size: 1.5rem;
		line-height: 1;
		cursor: pointer;
		color: var(--lq-text-secondary, #6b7280);
		padding: 0 0.25rem;
	}
	.lq-modal__close:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.lq-modal__body {
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.lq-modal__field label {
		display: block;
		font-size: 0.875rem;
		font-weight: 500;
		margin-bottom: 0.375rem;
	}
	.lq-modal__field select {
		width: 100%;
		padding: 0.5rem 0.625rem;
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: 0.375rem;
		background: var(--lq-surface, #ffffff);
		color: var(--lq-text-primary, #111827);
		font-size: 0.9375rem;
	}
	.lq-modal__field select:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
	.lq-modal__placeholder {
		padding: 0.5rem 0.625rem;
		background: var(--lq-inset, #f3f4f6);
		border-radius: 0.375rem;
		font-size: 0.875rem;
		color: var(--lq-text-secondary, #6b7280);
	}
	.lq-modal__cost {
		padding: 0.875rem 1rem;
		background: var(--lq-inset, #f3f4f6);
		border-radius: 0.5rem;
	}
	.lq-modal__cost-label {
		font-size: 0.8125rem;
		color: var(--lq-text-secondary, #6b7280);
	}
	.lq-modal__cost-amount {
		font-size: 1.5rem;
		font-weight: 600;
		margin: 0.125rem 0;
	}
	.lq-modal__cost-detail {
		font-size: 0.8125rem;
		color: var(--lq-text-tertiary, var(--lq-text-secondary, #6b7280));
	}
	.lq-modal__error {
		padding: 0.625rem 0.875rem;
		background: var(--lq-error-soft, var(--lq-inset, #fef2f2));
		border: 1px solid var(--lq-error-border, var(--lq-border, #fecaca));
		color: var(--lq-error, #b91c1c);
		border-radius: 0.375rem;
		font-size: 0.875rem;
	}
	.lq-modal__footer {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		padding: 1rem 1.25rem;
		border-top: 1px solid var(--lq-border, #e5e7eb);
	}
	.lq-modal__btn {
		padding: 0.5rem 1rem;
		border-radius: 0.375rem;
		font-size: 0.875rem;
		cursor: pointer;
		border: 1px solid transparent;
	}
	.lq-modal__btn--secondary {
		background: var(--lq-surface, #ffffff);
		border-color: var(--lq-border, #e5e7eb);
		color: var(--lq-text-primary, #111827);
	}
	.lq-modal__btn--primary {
		background: var(--lq-accent, #4f46e5);
		color: var(--lq-on-accent, #ffffff);
	}
	.lq-modal__btn--primary:disabled,
	.lq-modal__btn--secondary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
