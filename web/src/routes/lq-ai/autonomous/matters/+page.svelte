<script lang="ts">
	/**
	 * /lq-ai/autonomous/matters — matter-intake page (item 1.6).
	 *
	 * "Describe your matter": a full-page intake form that spawns a one-off
	 * governed autonomous session via POST /autonomous/run-now with the new
	 * optional `query` field. The description lands in
	 * session.params["query"], which the executor reads into the ADR-0020
	 * matter loop as the planner goal. On 201 we redirect to the session
	 * detail page, which already renders the plan trace and live receipt.
	 *
	 * Structure mirrors the run-now modal on ../+page.svelte (picker
	 * Promise.allSettled load, LQAIApiError handling, goto on success);
	 * gating is inherited from ../+layout.svelte, which redirects users
	 * without autonomous_enabled to the opt-in settings page.
	 *
	 * Pure form logic (validation + request building) lives in
	 * ./intake-helpers.ts so vitest can cover it without the Svelte runtime.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import { autonomousApi, skillsApi, knowledgeBasesApi, projectsApi } from '$lib/lq-ai/api';
	import * as playbooksApi from '$lib/lq-ai/api/playbooks';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { Playbook } from '$lib/lq-ai/types';
	import type { SkillSummary } from '$lib/lq-ai/types';
	import type { KnowledgeBase, Project } from '$lib/lq-ai/types';
	import {
		QUERY_MAX_LENGTH,
		buildIntakeRunRequest,
		isIntakeFormValid,
		validateIntakeForm,
		type IntakeFormState
	} from './intake-helpers';

	// ---------------------------------------------------------------------------
	// Form state
	// ---------------------------------------------------------------------------

	let formQuery = '';
	let formTargetKind: 'skill' | 'playbook' = 'skill';
	let formSkillRef = '';
	let formPlaybookId = '';
	let formKbId = '';
	let formProjectId = '';
	let formMaxCostUsd = '';

	let submitting = false;
	let queryError: string | null = null;
	let targetError: string | null = null;
	let submitError: string | null = null;

	// Picker lists (loaded on mount)
	let playbooks: Playbook[] = [];
	let skillSummaries: SkillSummary[] = [];
	let kbs: KnowledgeBase[] = [];
	let projects: Project[] = [];
	let pickerLoading = false;
	let pickerError: string | null = null;

	onMount(() => {
		loadPickerData();
	});

	async function loadPickerData(): Promise<void> {
		pickerLoading = true;
		pickerError = null;
		try {
			const [pb, sk, kb, pr] = await Promise.allSettled([
				playbooksApi.listPlaybooks(),
				skillsApi.listSkills(),
				knowledgeBasesApi.listKnowledgeBases(),
				projectsApi.listProjects()
			]);
			if (pb.status === 'fulfilled') playbooks = pb.value;
			if (sk.status === 'fulfilled') skillSummaries = sk.value;
			if (kb.status === 'fulfilled') kbs = kb.value;
			if (pr.status === 'fulfilled') projects = pr.value;
			// If all failed, surface a brief error; partial failure is silently degraded.
			if ([pb, sk, kb, pr].every((r) => r.status === 'rejected')) {
				pickerError = 'Could not load picker data. Check your connection.';
			}
		} finally {
			pickerLoading = false;
		}
	}

	function currentFormState(): IntakeFormState {
		return {
			query: formQuery,
			targetKind: formTargetKind,
			skillRef: formSkillRef,
			playbookId: formPlaybookId,
			kbId: formKbId,
			projectId: formProjectId,
			maxCostUsd: formMaxCostUsd
		};
	}

	async function handleSubmit(): Promise<void> {
		submitError = null;

		const form = currentFormState();
		const errors = validateIntakeForm(form);
		queryError = errors.query;
		targetError = errors.target;
		if (!isIntakeFormValid(errors)) return;

		submitting = true;
		try {
			const session = await autonomousApi.runNow(buildIntakeRunRequest(form));
			await goto(`/lq-ai/autonomous/sessions/${session.id}`);
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 422) {
				submitError = `The server rejected this request (422): ${err.message}`;
			} else if (err instanceof LQAIApiError) {
				submitError = `Run failed (${err.status}): ${err.message}`;
			} else {
				submitError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			submitting = false;
		}
	}
</script>

<div class="matters-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Describe your matter</h1>
		<p class="page-intro">
			Describe what you need done and pick the skill or playbook to run. LQVern runs once, plans
			against your description, and stops at the cost cap (R4). You are redirected to the session's
			receipt — review the plan trace and findings there; nothing is applied anywhere on your
			behalf.
		</p>
	</header>

	<form on:submit|preventDefault={handleSubmit} class="intake-form" novalidate>
		<!-- Matter description (required → ManualRunRequest.query) -->
		<div class="intake-field">
			<label class="intake-label" for="matter-query">
				Matter description <span class="intake-required" aria-hidden="true">*</span>
			</label>
			<textarea
				id="matter-query"
				class="intake-textarea"
				class:intake-input--error={!!queryError}
				bind:value={formQuery}
				rows="6"
				maxlength={QUERY_MAX_LENGTH}
				placeholder="e.g. Review the Acme NDA for a mutual confidentiality carve-out and flag any survival terms longer than 3 years."
				disabled={submitting}
				aria-invalid={queryError ? 'true' : undefined}
			></textarea>
			<p class="intake-hint">
				This becomes the run's goal. Be specific — the agent only sees what you write here plus the
				selected knowledge base.
			</p>
			{#if queryError}
				<p class="intake-field-error" role="alert">{queryError}</p>
			{/if}
		</div>

		<!-- Target kind radio -->
		<div class="intake-field">
			<span class="intake-label">
				Target <span class="intake-required" aria-hidden="true">*</span>
			</span>
			<div class="radio-group">
				<label class="radio-label">
					<input
						type="radio"
						name="matter-target-kind"
						value="skill"
						bind:group={formTargetKind}
						disabled={submitting}
					/>
					Skill
				</label>
				<label class="radio-label">
					<input
						type="radio"
						name="matter-target-kind"
						value="playbook"
						bind:group={formTargetKind}
						disabled={submitting}
					/>
					Playbook
				</label>
			</div>

			{#if formTargetKind === 'skill'}
				{#if pickerLoading}
					<p class="picker-loading">Loading skills…</p>
				{:else}
					<select
						class="intake-select"
						class:intake-input--error={!!targetError}
						bind:value={formSkillRef}
						disabled={submitting}
						aria-label="Select skill"
					>
						<option value="">— Select a skill —</option>
						{#each skillSummaries as sk (sk.name)}
							<option value={sk.name}>{sk.title || sk.name}</option>
						{/each}
					</select>
				{/if}
			{:else if pickerLoading}
				<p class="picker-loading">Loading playbooks…</p>
			{:else}
				<select
					class="intake-select"
					class:intake-input--error={!!targetError}
					bind:value={formPlaybookId}
					disabled={submitting}
					aria-label="Select playbook"
				>
					<option value="">— Select a playbook —</option>
					{#each playbooks as pb (pb.id)}
						<option value={pb.id}>{pb.name}</option>
					{/each}
				</select>
			{/if}

			{#if targetError}
				<p class="intake-field-error" role="alert">{targetError}</p>
			{/if}
		</div>

		<!-- Optional matter / project -->
		<div class="intake-field">
			<label class="intake-label" for="matter-project">
				Matter / project <span class="intake-optional">(optional)</span>
			</label>
			{#if pickerLoading}
				<p class="picker-loading">Loading projects…</p>
			{:else}
				<select
					id="matter-project"
					class="intake-select"
					bind:value={formProjectId}
					disabled={submitting}
				>
					<option value="">— None —</option>
					{#each projects as proj (proj.id)}
						<option value={proj.id}>{proj.name}</option>
					{/each}
				</select>
			{/if}
		</div>

		<!-- Optional KB scope -->
		<div class="intake-field">
			<label class="intake-label" for="matter-kb">
				Knowledge base <span class="intake-optional">(optional)</span>
			</label>
			{#if pickerLoading}
				<p class="picker-loading">Loading knowledge bases…</p>
			{:else}
				<select id="matter-kb" class="intake-select" bind:value={formKbId} disabled={submitting}>
					<option value="">— None —</option>
					{#each kbs as kb (kb.id)}
						<option value={kb.id}>{kb.name}</option>
					{/each}
				</select>
			{/if}
			<p class="intake-hint">
				The documents the run retrieves from. Without one, the run has only your description to work
				with.
			</p>
		</div>

		<!-- Cost cap (optional) -->
		<div class="intake-field">
			<label class="intake-label" for="matter-cost-cap">
				Cost cap (USD) <span class="intake-optional">(optional)</span>
			</label>
			<input
				id="matter-cost-cap"
				type="number"
				min="0"
				step="0.01"
				class="intake-input"
				bind:value={formMaxCostUsd}
				placeholder="e.g. 1.00 — defaults to the system cap if blank"
				disabled={submitting}
			/>
			<p class="intake-hint">
				The most this run may spend before it halts (R4). Blank uses the system default.
			</p>
		</div>

		{#if pickerError}
			<p class="picker-error" role="alert">{pickerError}</p>
		{/if}

		{#if submitError}
			<p class="submit-error" role="alert">{submitError}</p>
		{/if}

		<div class="intake-actions">
			<button type="submit" class="intake-btn-primary" disabled={submitting}>
				{submitting ? 'Starting run…' : 'Run on this matter'}
			</button>
		</div>
	</form>
</div>

<style>
	.matters-page {
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-5);
		max-width: 44rem;
	}

	.page-header {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.page-intro {
		color: var(--lq-text-secondary);
		max-width: 60rem;
		font-size: 14px;
		line-height: 1.5;
	}

	.intake-form {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4);
	}

	.intake-field {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.intake-label {
		font-size: 13px;
		font-weight: 500;
		color: var(--lq-text-primary);
	}

	.intake-required {
		color: var(--lq-error);
		margin-left: 2px;
	}

	.intake-optional {
		font-weight: 400;
		color: var(--lq-text-tertiary);
		font-size: 12px;
	}

	.intake-hint {
		font-size: 12px;
		color: var(--lq-text-tertiary);
		margin: 0;
		line-height: 1.4;
	}

	.intake-input,
	.intake-select,
	.intake-textarea {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		font-size: 14px;
		color: var(--lq-text-primary);
		width: 100%;
		box-sizing: border-box;
		transition: border-color 0.15s ease;
	}

	.intake-textarea {
		resize: vertical;
		font-family: inherit;
		line-height: 1.5;
	}

	.intake-input:focus,
	.intake-select:focus,
	.intake-textarea:focus {
		outline: none;
		border-color: var(--lq-accent);
		box-shadow: 0 0 0 2px var(--lq-accent-soft);
	}

	.intake-input:disabled,
	.intake-select:disabled,
	.intake-textarea:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.intake-input--error {
		border-color: var(--lq-error);
	}

	.intake-field-error {
		font-size: 12px;
		color: var(--lq-error);
		margin: 0;
	}

	.radio-group {
		display: flex;
		gap: var(--lq-space-4);
		padding: var(--lq-space-1) 0;
	}

	.radio-label {
		display: flex;
		align-items: center;
		gap: var(--lq-space-1);
		font-size: 14px;
		cursor: pointer;
		color: var(--lq-text);
	}

	.picker-loading {
		font-size: 13px;
		color: var(--lq-text-tertiary);
		font-style: italic;
		margin: 0;
	}

	.picker-error {
		font-size: 13px;
		color: var(--lq-error);
		margin: 0;
	}

	.submit-error {
		font-size: 13px;
		color: var(--lq-error);
		background: var(--lq-error-soft, rgba(176, 0, 0, 0.06));
		border: 1px solid var(--lq-error-border, var(--lq-error));
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		margin: 0;
	}

	.intake-actions {
		display: flex;
		justify-content: flex-start;
		gap: var(--lq-space-3);
		padding-top: var(--lq-space-2);
		border-top: 1px solid var(--lq-border);
		margin-top: var(--lq-space-2);
	}

	.intake-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-weight: 500;
		font-size: 14px;
		cursor: pointer;
	}

	.intake-btn-primary:hover:not(:disabled) {
		filter: brightness(0.95);
	}

	.intake-btn-primary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.intake-btn-primary:disabled {
		opacity: 0.65;
		cursor: not-allowed;
	}
</style>
