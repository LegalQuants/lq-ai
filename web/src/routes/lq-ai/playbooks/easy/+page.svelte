<script lang="ts">
	/**
	 * Easy Playbook wizard (M3-A6 Phase 6). Four-step flow:
	 *
	 *   1. Upload — multi-file dropzone, contract_type selector, optional
	 *      name. Uploads via POST /files; polls GET /files/{id} until
	 *      every uploaded file has a document_id (the C5 parse pipeline
	 *      has run); kicks off generation via POST /playbooks/easy.
	 *
	 *   2. Progress — polls GET /playbooks/easy/{id} every 5 seconds
	 *      until status reaches a terminal state (`completed` or
	 *      `error`). On `error`, surfaces `error_message` + a retry
	 *      button. NFR per PRD §3.7: up to 10 minutes for a 10-doc
	 *      corpus on the default model alias.
	 *
	 *   3. Review — renders `<PlaybookEditor bind:playbook>` against the
	 *      generation's `draft_playbook`. "Save" calls POST /playbooks.
	 *
	 *   4. Approve — success screen with a link to the saved playbook's
	 *      detail view. (Disclaimer + transparency banner on every step
	 *      per Decision F.)
	 *
	 * Decisions worth carrying forward (per the M3-A6 prep doc):
	 *
	 *  - Per Decision §3.4 the inline editor surfaces every editable
	 *    field — the operator's Step 3 edit is the user-attorney's
	 *    validation pass, not a structural sanity check.
	 *  - Per Decision F + the 2026-05-19 reframe, the wizard output is
	 *    itself a starting point; we do NOT verify legal soundness of
	 *    generated language. The verification bar is structural
	 *    correctness + gross sensibility.
	 */
	import { goto } from '$app/navigation';
	import { onDestroy } from 'svelte';

	import {
		getEasyPlaybookGeneration,
		startEasyPlaybookGeneration,
		createPlaybook
	} from '$lib/lq-ai/api/playbooks';
	import { uploadFile, getFile } from '$lib/lq-ai/api/files';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import PlaybookDisclaimerBanner from '$lib/lq-ai/components/PlaybookDisclaimerBanner.svelte';
	import PlaybookEditor from '$lib/lq-ai/components/PlaybookEditor.svelte';
	import type {
		EasyPlaybookGeneration,
		FileMeta,
		PlaybookCreate
	} from '$lib/lq-ai/types';

	import {
		type WizardStep,
		allDocumentsReady,
		collectReadyDocumentIds,
		defaultPlaybookName,
		nextStepFromGeneration,
		validateUploadStep
	} from './page-helpers';

	// ---------------------------------------------------------------
	// State
	// ---------------------------------------------------------------

	let step: WizardStep = 'upload';

	// Step 1 — upload form
	let selectedFiles: File[] = [];
	let uploadedFiles: FileMeta[] = [];
	let contractType = '';
	let playbookName = '';
	let uploading = false;
	let uploadError: string | null = null;

	// Step 2 — polling
	let generation: EasyPlaybookGeneration | null = null;
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let pollError: string | null = null;

	// Step 3 — review / save
	let draftPlaybook: PlaybookCreate | null = null;
	let saving = false;
	let saveError: string | null = null;

	// Step 4 — saved
	let savedPlaybookId: string | null = null;

	// Common
	const POLL_INTERVAL_MS = 5_000;
	const FILE_PARSE_POLL_INTERVAL_MS = 2_500;
	const FILE_PARSE_MAX_ATTEMPTS = 120; // ~5 minutes at 2.5s

	/**
	 * Common suggested values; users can still type a custom one
	 * because the backend `contract_type` is free-form. Mirrors the
	 * five built-ins shipped via migration 0032 + 0033.
	 */
	const CONTRACT_TYPE_SUGGESTIONS = [
		'NDA',
		'MSA-SaaS',
		'MSA-Commercial-Purchase',
		'DPA',
		'Other'
	];

	$: if (contractType && !playbookName.trim()) {
		playbookName = defaultPlaybookName(contractType);
	}

	// ---------------------------------------------------------------
	// Step 1 — upload + start generation
	// ---------------------------------------------------------------

	function handleFilesSelected(event: Event): void {
		const input = event.target as HTMLInputElement;
		if (!input.files) return;
		const incoming = Array.from(input.files);
		selectedFiles = [...selectedFiles, ...incoming];
		// Clear the input so the same file can be re-selected after removal.
		input.value = '';
	}

	function handleDrop(event: DragEvent): void {
		event.preventDefault();
		if (!event.dataTransfer) return;
		const incoming = Array.from(event.dataTransfer.files);
		selectedFiles = [...selectedFiles, ...incoming];
	}

	function handleDragOver(event: DragEvent): void {
		event.preventDefault();
	}

	function removeSelectedFile(i: number): void {
		selectedFiles = selectedFiles.filter((_, k) => k !== i);
	}

	async function pollFileUntilParsed(fileId: string): Promise<FileMeta> {
		for (let attempt = 0; attempt < FILE_PARSE_MAX_ATTEMPTS; attempt++) {
			const f = await getFile(fileId);
			if (f.ingestion_status === 'failed') {
				throw new LQAIApiError(
					422,
					'parse_failed',
					`Parsing failed for ${f.filename}: ${f.ingestion_error ?? 'unknown reason'}`
				);
			}
			if (f.document_id) {
				return f;
			}
			await new Promise((resolve) => setTimeout(resolve, FILE_PARSE_POLL_INTERVAL_MS));
		}
		throw new LQAIApiError(
			504,
			'parse_timeout',
			'Parsing timed out. Try again with smaller files or fewer documents.'
		);
	}

	async function handleStartGeneration(): Promise<void> {
		const validation = validateUploadStep({
			files: uploadedFiles.length ? uploadedFiles : ([] as FileMeta[]),
			contract_type: contractType
		});
		// Re-validate against either uploaded or still-selected files.
		if (selectedFiles.length === 0 && uploadedFiles.length === 0) {
			uploadError = 'Upload at least one contract before generating a playbook.';
			return;
		}
		if (!contractType.trim()) {
			uploadError = validation ?? 'Pick a contract type before generating a playbook.';
			return;
		}

		uploadError = null;
		uploading = true;
		try {
			// 1. Upload everything still pending. Run sequentially so
			//    the gateway's per-user upload rate-limit (if any)
			//    isn't tripped by an N-way fan-out.
			for (const file of selectedFiles) {
				const meta = await uploadFile(file);
				uploadedFiles = [...uploadedFiles, meta];
			}
			selectedFiles = [];

			// 2. Poll each uploaded file until its document_id surfaces
			//    (the C5 parse pipeline has run). Done in parallel.
			const parsed = await Promise.all(
				uploadedFiles.map((meta) =>
					meta.document_id ? Promise.resolve(meta) : pollFileUntilParsed(meta.id)
				)
			);
			uploadedFiles = parsed;

			if (!allDocumentsReady(uploadedFiles)) {
				uploadError = 'One or more files did not finish parsing. Please retry.';
				uploading = false;
				return;
			}

			// 3. Kick off generation.
			const documentIds = collectReadyDocumentIds(uploadedFiles);
			const gen = await startEasyPlaybookGeneration({
				document_ids: documentIds,
				contract_type: contractType.trim(),
				name: playbookName.trim() || null
			});
			generation = gen;
			step = 'progress';
			schedulePoll();
		} catch (err) {
			uploadError =
				err instanceof LQAIApiError
					? err.message
					: 'Something went wrong. Please try again.';
		} finally {
			uploading = false;
		}
	}

	// ---------------------------------------------------------------
	// Step 2 — poll the generation row
	// ---------------------------------------------------------------

	function schedulePoll(): void {
		clearPoll();
		pollTimer = setTimeout(pollGeneration, POLL_INTERVAL_MS);
	}

	function clearPoll(): void {
		if (pollTimer) {
			clearTimeout(pollTimer);
			pollTimer = null;
		}
	}

	async function pollGeneration(): Promise<void> {
		if (!generation) return;
		try {
			const row = await getEasyPlaybookGeneration(generation.id);
			generation = row;
			pollError = null;
			const nextStep = nextStepFromGeneration(row);
			if (nextStep === 'review') {
				clearPoll();
				draftPlaybook = row.draft_playbook;
				if (!draftPlaybook) {
					pollError =
						'Generation completed but no draft playbook was returned. Please retry.';
					return;
				}
				step = 'review';
				return;
			}
			// Still running OR terminal-error: keep polling on running
			// states, stop on error so the operator can retry.
			if (row.status === 'error') {
				clearPoll();
				return;
			}
			schedulePoll();
		} catch (err) {
			pollError =
				err instanceof LQAIApiError
					? err.message
					: 'Lost contact with the server. Retrying…';
			schedulePoll();
		}
	}

	function handleRetryFromError(): void {
		generation = null;
		pollError = null;
		step = 'upload';
	}

	// ---------------------------------------------------------------
	// Step 3 — save the (possibly edited) draft
	// ---------------------------------------------------------------

	async function handleSavePlaybook(): Promise<void> {
		if (!draftPlaybook) return;
		saveError = null;
		saving = true;
		try {
			const saved = await createPlaybook(draftPlaybook);
			savedPlaybookId = saved.id;
			step = 'approve';
		} catch (err) {
			saveError =
				err instanceof LQAIApiError
					? err.message
					: 'Failed to save the playbook. Please try again.';
		} finally {
			saving = false;
		}
	}

	function handleGoToPlaybook(): void {
		if (!savedPlaybookId) return;
		void goto(`/lq-ai/playbooks`);
	}

	// ---------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------

	onDestroy(clearPoll);
</script>

<svelte:head>
	<title>Generate playbook · LQ.AI</title>
</svelte:head>

<section class="lq-easy-wizard" data-testid="lq-easy-wizard">
	<header class="lq-easy-wizard__header">
		<h1>Generate playbook from prior agreements</h1>
		<p class="lq-easy-wizard__subtitle">
			Upload a corpus of contracts your team has signed; LQ.AI extracts the positions they
			contain and assembles them into a draft playbook for you to review and save.
		</p>
	</header>

	<PlaybookDisclaimerBanner />

	<ol class="lq-easy-wizard__steps" aria-label="Wizard progress">
		<li class:lq-easy-wizard__step--active={step === 'upload'}>1. Upload</li>
		<li class:lq-easy-wizard__step--active={step === 'progress'}>2. Generate</li>
		<li class:lq-easy-wizard__step--active={step === 'review'}>3. Review</li>
		<li class:lq-easy-wizard__step--active={step === 'approve'}>4. Save</li>
	</ol>

	{#if step === 'upload'}
		<div class="lq-easy-wizard__panel" data-testid="lq-easy-wizard-step-upload">
			<div class="lq-easy-wizard__field">
				<label for="lq-easy-wizard-contract-type" class="lq-easy-wizard__label">
					Contract type
				</label>
				<input
					id="lq-easy-wizard-contract-type"
					type="text"
					bind:value={contractType}
					list="lq-easy-wizard-contract-type-list"
					class="lq-easy-wizard__input"
					disabled={uploading}
					placeholder="e.g., NDA, MSA-SaaS, DPA"
				/>
				<datalist id="lq-easy-wizard-contract-type-list">
					{#each CONTRACT_TYPE_SUGGESTIONS as t}
						<option value={t}></option>
					{/each}
				</datalist>
			</div>

			<div class="lq-easy-wizard__field">
				<label for="lq-easy-wizard-name" class="lq-easy-wizard__label">
					Playbook name (optional)
				</label>
				<input
					id="lq-easy-wizard-name"
					type="text"
					bind:value={playbookName}
					class="lq-easy-wizard__input"
					disabled={uploading}
					placeholder="Auto-filled from contract type"
				/>
			</div>

			<div class="lq-easy-wizard__field">
				<div class="lq-easy-wizard__label">Documents</div>
				<div
					class="lq-easy-wizard__dropzone"
					role="region"
					aria-label="Contract upload dropzone"
					on:drop={handleDrop}
					on:dragover={handleDragOver}
				>
					<input
						type="file"
						multiple
						accept="application/pdf,.pdf"
						on:change={handleFilesSelected}
						disabled={uploading}
						data-testid="lq-easy-wizard-file-input"
					/>
					<div class="lq-easy-wizard__dropzone-hint">
						Drop PDFs here, or click to pick files. Up to 50 contracts per
						generation. Recommended: 5–20 examples for a coherent playbook.
					</div>
				</div>

				{#if selectedFiles.length > 0 || uploadedFiles.length > 0}
					<ul class="lq-easy-wizard__file-list" data-testid="lq-easy-wizard-file-list">
						{#each uploadedFiles as f (f.id)}
							<li class="lq-easy-wizard__file lq-easy-wizard__file--uploaded">
								<span>{f.filename}</span>
								<span class="lq-easy-wizard__file-status">
									{f.document_id ? 'parsed' : 'parsing…'}
								</span>
							</li>
						{/each}
						{#each selectedFiles as f, i (f.name + i)}
							<li class="lq-easy-wizard__file">
								<span>{f.name}</span>
								<button
									type="button"
									class="lq-easy-wizard__file-remove"
									on:click={() => removeSelectedFile(i)}
									disabled={uploading}
									aria-label="Remove file"
								>
									Remove
								</button>
							</li>
						{/each}
					</ul>
				{/if}
			</div>

			{#if uploadError}
				<div class="lq-easy-wizard__error" role="alert">{uploadError}</div>
			{/if}

			<div class="lq-easy-wizard__actions">
				<button
					type="button"
					class="lq-easy-wizard__btn lq-easy-wizard__btn--primary"
					on:click={handleStartGeneration}
					disabled={uploading || (selectedFiles.length === 0 && uploadedFiles.length === 0)}
					data-testid="lq-easy-wizard-start"
				>
					{uploading ? 'Working…' : 'Generate playbook'}
				</button>
			</div>
		</div>
	{:else if step === 'progress'}
		<div class="lq-easy-wizard__panel" data-testid="lq-easy-wizard-step-progress">
			{#if generation?.status === 'error'}
				<div class="lq-easy-wizard__error" role="alert">
					Generation failed: {generation.error_message ?? 'unknown error'}
				</div>
				<div class="lq-easy-wizard__actions">
					<button
						type="button"
						class="lq-easy-wizard__btn lq-easy-wizard__btn--primary"
						on:click={handleRetryFromError}
					>
						Try again
					</button>
				</div>
			{:else}
				<div class="lq-easy-wizard__progress">
					<div class="lq-easy-wizard__spinner" aria-hidden="true"></div>
					<div class="lq-easy-wizard__progress-text">
						<strong>Generating playbook…</strong>
						<span>
							This can take up to 10 minutes for a 10-document corpus. You can
							leave this page open; we'll keep polling.
						</span>
					</div>
				</div>
				{#if pollError}
					<div class="lq-easy-wizard__hint">{pollError}</div>
				{/if}
			{/if}
		</div>
	{:else if step === 'review' && draftPlaybook}
		<div class="lq-easy-wizard__panel" data-testid="lq-easy-wizard-step-review">
			<p class="lq-easy-wizard__hint">
				The draft below was assembled from your uploaded contracts. Review every
				position before saving — the generated language is a starting point, not
				a final answer.
			</p>

			<PlaybookEditor bind:playbook={draftPlaybook} disabled={saving} />

			{#if saveError}
				<div class="lq-easy-wizard__error" role="alert">{saveError}</div>
			{/if}

			<div class="lq-easy-wizard__actions">
				<button
					type="button"
					class="lq-easy-wizard__btn lq-easy-wizard__btn--primary"
					on:click={handleSavePlaybook}
					disabled={saving || !draftPlaybook.name.trim() || !draftPlaybook.contract_type.trim()}
					data-testid="lq-easy-wizard-save"
				>
					{saving ? 'Saving…' : 'Save playbook'}
				</button>
			</div>
		</div>
	{:else if step === 'approve'}
		<div class="lq-easy-wizard__panel" data-testid="lq-easy-wizard-step-approve">
			<div class="lq-easy-wizard__success">
				<strong>Playbook saved.</strong>
				It now appears in your playbooks library. Apply it to a contract to see
				how it scores.
			</div>
			<div class="lq-easy-wizard__actions">
				<button
					type="button"
					class="lq-easy-wizard__btn lq-easy-wizard__btn--primary"
					on:click={handleGoToPlaybook}
				>
					Back to playbooks
				</button>
			</div>
		</div>
	{/if}
</section>

<style>
	.lq-easy-wizard {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		max-width: 64rem;
		margin: 0 auto;
		padding: 1.5rem;
	}
	.lq-easy-wizard__header h1 {
		margin: 0 0 0.5rem;
		font-size: 1.5rem;
	}
	.lq-easy-wizard__subtitle {
		margin: 0;
		color: var(--lq-text-secondary);
	}
	.lq-easy-wizard__steps {
		display: flex;
		gap: 0.75rem;
		list-style: none;
		padding: 0;
		margin: 0;
		font-size: 0.875rem;
		color: var(--lq-text-secondary);
	}
	.lq-easy-wizard__steps li {
		padding: 0.25rem 0.5rem;
		border: 1px solid var(--lq-border);
		border-radius: 999px;
		background: var(--lq-surface);
	}
	.lq-easy-wizard__step--active {
		/* Hardcoded fallbacks — the OpenWebUI fork doesn't always
		   define `--lq-accent` on every theme, which collapsed the
		   background to inherit (white) while the text stayed
		   white-on-white. Matches the PlaybookExecuteModal pattern. */
		background: var(--lq-accent, #4f46e5);
		color: var(--lq-on-accent, #ffffff);
		border-color: var(--lq-accent, #4f46e5);
	}
	.lq-easy-wizard__panel {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding: 1.25rem;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
	}
	.lq-easy-wizard__field {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}
	.lq-easy-wizard__label {
		font-size: 0.8125rem;
		font-weight: 500;
		color: var(--lq-text-secondary);
	}
	.lq-easy-wizard__input {
		padding: 0.5rem 0.625rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		background: var(--lq-surface);
		color: var(--lq-text-primary);
		font-size: 0.9375rem;
	}
	.lq-easy-wizard__dropzone {
		border: 2px dashed var(--lq-border);
		border-radius: 0.5rem;
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		align-items: flex-start;
		background: var(--lq-inset);
	}
	.lq-easy-wizard__dropzone-hint {
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
	}
	.lq-easy-wizard__file-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}
	.lq-easy-wizard__file {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.5rem 0.625rem;
		background: var(--lq-inset);
		border-radius: 0.375rem;
		font-size: 0.875rem;
	}
	.lq-easy-wizard__file--uploaded {
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
	}
	.lq-easy-wizard__file-status {
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
	}
	.lq-easy-wizard__file-remove {
		background: none;
		border: none;
		color: var(--lq-error, #b91c1c);
		font-size: 0.8125rem;
		cursor: pointer;
	}
	.lq-easy-wizard__error {
		padding: 0.625rem 0.875rem;
		background: var(--lq-error-soft, var(--lq-inset));
		border: 1px solid var(--lq-error-border, var(--lq-border));
		color: var(--lq-error, #b91c1c);
		border-radius: 0.375rem;
		font-size: 0.875rem;
	}
	.lq-easy-wizard__success {
		padding: 1rem 1.125rem;
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		font-size: 0.9375rem;
	}
	.lq-easy-wizard__success strong {
		margin-right: 0.375rem;
	}
	.lq-easy-wizard__hint {
		font-size: 0.875rem;
		color: var(--lq-text-secondary);
	}
	.lq-easy-wizard__progress {
		display: flex;
		gap: 0.875rem;
		align-items: center;
	}
	.lq-easy-wizard__progress-text {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		font-size: 0.9375rem;
	}
	.lq-easy-wizard__progress-text span {
		color: var(--lq-text-secondary);
		font-size: 0.875rem;
	}
	.lq-easy-wizard__spinner {
		width: 1.5rem;
		height: 1.5rem;
		border: 3px solid var(--lq-border, #e5e7eb);
		border-top-color: var(--lq-accent, #4f46e5);
		border-radius: 50%;
		animation: lq-spin 1s linear infinite;
	}
	@keyframes lq-spin {
		to {
			transform: rotate(360deg);
		}
	}
	.lq-easy-wizard__actions {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
	}
	.lq-easy-wizard__btn {
		padding: 0.5rem 1rem;
		border-radius: 0.375rem;
		font-size: 0.875rem;
		cursor: pointer;
		border: 1px solid transparent;
	}
	.lq-easy-wizard__btn--primary {
		background: var(--lq-accent, #4f46e5);
		color: var(--lq-on-accent, #ffffff);
	}
	.lq-easy-wizard__btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
