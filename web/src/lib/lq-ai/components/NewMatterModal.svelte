<script context="module" lang="ts">
	/**
	 * Form validation helpers — exported for unit tests.
	 */
	export type TierFloor = 1 | 2 | 3 | 4 | 5;

	export interface NewMatterFields {
		name: string;
		description: string;
		privileged: boolean;
		minimum_inference_tier: TierFloor | null;
	}

	export interface ValidationResult {
		valid: boolean;
		nameError: string | null;
		tierError: string | null;
	}

	export function validateNewMatter(fields: NewMatterFields): ValidationResult {
		let nameError: string | null = null;
		let tierError: string | null = null;

		if (!fields.name.trim()) {
			nameError = 'Matter name is required.';
		} else if (fields.name.trim().length > 200) {
			nameError = 'Matter name must be 200 characters or fewer.';
		}

		if (fields.privileged && fields.minimum_inference_tier === null) {
			tierError = 'Privileged matters require a minimum tier floor — see PRD §5.x for why.';
		}

		return {
			valid: nameError === null && tierError === null,
			nameError,
			tierError
		};
	}
</script>

<script lang="ts">
	import { goto } from '$app/navigation';
	import { projectsApi } from '$lib/lq-ai/api';
	import type { Project } from '$lib/lq-ai/types';
	import InfoTip from './InfoTip.svelte';

	export let onClose: () => void;
	export let onCreated: (matter: Project) => void;

	// Form state
	let name = '';
	let description = '';
	let privileged = false;
	let tierFloor: TierFloor | null = null;

	// UI state
	let submitting = false;
	let nameError: string | null = null;
	let tierError: string | null = null;
	let submitError: string | null = null;

	// Reset tier floor when privileged is unchecked
	$: if (!privileged) tierFloor = null;

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onClose();
	}

	let nameInput: HTMLInputElement;

	// Focus the name input when modal opens
	$: if (nameInput) nameInput.focus();

	async function handleSubmit() {
		nameError = null;
		tierError = null;
		submitError = null;

		const result = validateNewMatter({
			name,
			description,
			privileged,
			minimum_inference_tier: tierFloor
		});
		nameError = result.nameError;
		tierError = result.tierError;
		if (!result.valid) return;

		submitting = true;
		try {
			const created = await projectsApi.createProject({
				name: name.trim(),
				description: description.trim() || undefined,
				privileged,
				minimum_inference_tier: tierFloor ?? undefined
			});
			onCreated(created);
			goto(`/lq-ai/matters/${created.id}`);
		} catch (e: unknown) {
			if (e instanceof Error) {
				submitError = e.message ?? "Couldn't reach the server. Try again.";
			} else {
				submitError = "Couldn't reach the server. Try again.";
			}
		} finally {
			submitting = false;
		}
	}

	// Under PRD §1.5.2, lower tier number = stronger security.
	// "Tier N or stronger" means the floor is N; tiers 1..N are all allowed.
	const TIER_OPTIONS: { value: TierFloor; label: string }[] = [
		{ value: 1, label: 'Tier 1 only' },
		{ value: 2, label: 'Tier 2 or stronger' },
		{ value: 3, label: 'Tier 3 or stronger' },
		{ value: 4, label: 'Tier 4 or stronger' },
		{ value: 5, label: 'Tier 5 or stronger (any tier)' }
	];
</script>

<div
	class="nmm-backdrop"
	role="dialog"
	aria-modal="true"
	aria-labelledby="nmm-title"
	tabindex="-1"
	on:click={onClose}
	on:keydown={handleKeydown}
>
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div class="nmm-panel" on:click|stopPropagation on:keydown|stopPropagation>
		<h2 id="nmm-title" class="lq-text-page-h nmm-title">New matter</h2>

		<form on:submit|preventDefault={handleSubmit} class="nmm-form" novalidate>
			<!-- Name -->
			<div class="nmm-field">
				<label class="nmm-label" for="nmm-name"
					>Matter name <span class="nmm-required" aria-hidden="true">*</span></label
				>
				<input
					id="nmm-name"
					type="text"
					bind:this={nameInput}
					bind:value={name}
					class="nmm-input"
					class:nmm-input--error={!!nameError}
					placeholder="e.g. Acme NDA Review"
					maxlength="200"
					required
					disabled={submitting}
					aria-describedby={nameError ? 'nmm-name-error' : undefined}
				/>
				{#if nameError}
					<p id="nmm-name-error" class="nmm-field-error" role="alert">{nameError}</p>
				{/if}
			</div>

			<!-- Description -->
			<div class="nmm-field">
				<label class="nmm-label" for="nmm-description"
					>Description <span class="nmm-optional">(optional)</span></label
				>
				<textarea
					id="nmm-description"
					bind:value={description}
					class="nmm-textarea"
					rows="4"
					maxlength="2000"
					placeholder="Brief description of this matter…"
					disabled={submitting}
				></textarea>
			</div>

			<!-- Privileged -->
			<div class="nmm-field nmm-field--inline">
				<input
					id="nmm-privileged"
					type="checkbox"
					bind:checked={privileged}
					disabled={submitting}
				/>
				<label class="nmm-label nmm-label--checkbox" for="nmm-privileged">
					Attorney-client privileged
				</label>
				<InfoTip
					content="Marks this matter as covered by attorney-client privilege. Forces a minimum inference tier (defaults to Tier 2 — enterprise managed inference with no-training commitments) so privileged content cannot accidentally route to weaker providers. Tags every chat and audit-log entry as privileged for e-discovery filtering. Recommended for client work."
				/>
			</div>

			<!-- Tier floor — shown always but required when privileged -->
			{#if privileged}
				<div class="nmm-field">
					<label class="nmm-label" for="nmm-tier">
						Minimum inference tier <span class="nmm-required" aria-hidden="true">*</span>
					</label>
					<select
						id="nmm-tier"
						class="nmm-select"
						class:nmm-input--error={!!tierError}
						bind:value={tierFloor}
						disabled={submitting}
						aria-describedby={tierError ? 'nmm-tier-error' : undefined}
					>
						<option value={null}>(none)</option>
						{#each TIER_OPTIONS as opt}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
					{#if tierError}
						<p id="nmm-tier-error" class="nmm-field-error" role="alert">{tierError}</p>
					{/if}
				</div>
			{/if}

			<!-- Submit error -->
			{#if submitError}
				<p class="nmm-submit-error" role="alert">{submitError}</p>
			{/if}

			<!-- Actions -->
			<div class="nmm-actions">
				<button type="button" class="nmm-btn-secondary" on:click={onClose} disabled={submitting}>
					Cancel
				</button>
				<button type="submit" class="nmm-btn-primary" disabled={submitting}>
					{submitting ? 'Creating matter…' : 'Create matter'}
				</button>
			</div>
		</form>
	</div>
</div>

<style>
	.nmm-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.35);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}

	.nmm-panel {
		background: var(--lq-canvas);
		border-radius: var(--lq-radius-lg);
		padding: var(--lq-space-6);
		max-width: 520px;
		width: calc(100% - 32px);
		box-shadow: 0 24px 64px rgba(0, 0, 0, 0.18);
		max-height: calc(100vh - 64px);
		overflow-y: auto;
	}

	.nmm-title {
		margin: 0 0 var(--lq-space-5);
	}

	.nmm-form {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4);
	}

	.nmm-field {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.nmm-field--inline {
		flex-direction: row;
		align-items: center;
		gap: var(--lq-space-2);
	}

	.nmm-label {
		font-size: 13px;
		font-weight: 500;
		color: var(--lq-text-primary);
	}

	.nmm-label--checkbox {
		cursor: pointer;
	}

	.nmm-required {
		color: var(--lq-error);
		margin-left: 2px;
	}

	.nmm-optional {
		font-weight: 400;
		color: var(--lq-text-tertiary);
		font-size: 12px;
	}

	.nmm-input,
	.nmm-textarea,
	.nmm-select {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border-strong);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		font-size: 14px;
		color: var(--lq-text-primary);
		width: 100%;
		box-sizing: border-box;
		transition: border-color 0.15s ease;
	}

	.nmm-input:focus,
	.nmm-textarea:focus,
	.nmm-select:focus {
		outline: none;
		border-color: var(--lq-accent);
		box-shadow: 0 0 0 2px var(--lq-accent-soft);
	}

	.nmm-input--error {
		border-color: var(--lq-error);
	}

	.nmm-input--error:focus {
		box-shadow: 0 0 0 2px var(--lq-error-soft);
	}

	.nmm-textarea {
		resize: vertical;
		min-height: 80px;
	}

	.nmm-field-error {
		font-size: 12px;
		color: var(--lq-error);
		margin: 0;
	}

	.nmm-submit-error {
		font-size: 13px;
		color: var(--lq-error);
		background: var(--lq-error-soft);
		border: 1px solid var(--lq-error-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		margin: 0;
	}

	.nmm-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--lq-space-3);
		padding-top: var(--lq-space-2);
		border-top: 1px solid var(--lq-border);
		margin-top: var(--lq-space-2);
	}

	.nmm-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-weight: 500;
		font-size: 14px;
		cursor: pointer;
	}

	.nmm-btn-primary:hover:not(:disabled) {
		opacity: 0.85;
	}

	.nmm-btn-primary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.nmm-btn-primary:disabled {
		opacity: 0.65;
		cursor: not-allowed;
	}

	.nmm-btn-secondary {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-weight: 500;
		font-size: 14px;
		cursor: pointer;
	}

	.nmm-btn-secondary:hover:not(:disabled) {
		background: var(--lq-inset);
	}

	.nmm-btn-secondary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.nmm-btn-secondary:disabled {
		opacity: 0.65;
		cursor: not-allowed;
	}
</style>
