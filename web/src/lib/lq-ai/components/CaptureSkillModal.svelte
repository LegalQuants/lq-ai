<script context="module" lang="ts">
	/**
	 * CaptureSkillModal — Mode-A "capture as a skill" thin modal opened from
	 * an AI message bubble (Wave D.2 Task 5.2). Pre-populates name / slug /
	 * description from the message body and surfaces three actions: Save
	 * (POST /user-skills with ``source_message_id``), Edit-in-wizard (stash
	 * to localStorage + navigate to ``/lq-ai/skills/new?capture=<key>``),
	 * and Cancel.
	 *
	 * Convention notes for reviewers:
	 *   - Pure helpers exported from <script context="module"> so vitest can
	 *     exercise them without @testing-library/svelte (which is not
	 *     installed; see SkillWizard.test.ts header for the established
	 *     pattern). The Svelte template is glue.
	 *   - Backend shape per ``api/app/api/user_skills.py`` and
	 *     ``UserSkillCreate`` in ``types.ts``: ``display_name`` / ``body``
	 *     (NOT ``title`` / ``body_md`` — the plan-text used the legacy
	 *     names; we follow the real API). ``source_message_id`` rides the
	 *     create-time audit row (Wave D.2).
	 *   - The capture-stash localStorage shape MUST match the reader in
	 *     ``/lq-ai/skills/new`` (``+page.svelte:139-145``), which casts the
	 *     parsed object directly to ``WizardInitial``. Field names here are
	 *     therefore camelCase (``displayName``, ``slashAlias``, ``forkedFrom``,
	 *     ``ownerTeamId``) — NOT the snake_case API names.
	 *   - ``LQAIApiError.message`` is safe to read; the error-detail
	 *     ergonomics gap (FastAPI string-shaped detail not propagated) is
	 *     known tech debt queued for the polish PR — same workaround
	 *     SkillWizard uses today.
	 *   - Design tokens: ``--lq-canvas``, ``--lq-border``, ``--lq-accent``,
	 *     ``--lq-text-tertiary``, ``--lq-error`` per ``styles/practice.css``.
	 *     No ``--lq-surface`` token exists — surface is ``--lq-canvas``.
	 */
	import type { Message, UserSkillCreate } from '../types';
	import { kebab } from '../util/slug';

	/** Mutable modal form state — every field bound in the template, plus ``saving``. */
	export interface CaptureFormState {
		name: string;
		slug: string;
		description: string;
		body: string;
		saving: boolean;
	}

	/**
	 * Capture-stash snapshot persisted at ``lq-ai:capture-stash:<key>`` for
	 * the Edit-in-wizard handoff. Field names match ``WizardInitial`` in
	 * ``/lq-ai/skills/new/+page.svelte`` so the reader can cast directly.
	 */
	export interface CaptureStash {
		slug: string;
		displayName: string;
		description: string;
		body: string;
		scope: 'user' | 'team';
		version: string;
		forkedFrom: string | null;
	}

	/**
	 * Derive a sensible (name, slug, description) triple from a captured
	 * message body. Heuristics:
	 *   - Name: first markdown heading line (``#``, ``##``, ...) if any,
	 *     else the first non-list / non-heading sentence trimmed to 60 chars,
	 *     else the literal string ``"Captured skill"``.
	 *   - Description: same first-sentence (regardless of whether the name
	 *     came from a heading).
	 *   - Slug: ``kebab(name)`` with a deterministic fallback that uses the
	 *     leading 6 chars of the message id when the name produces an empty
	 *     slug (all-symbol heading, etc).
	 */
	export function derive(message: Message): {
		name: string;
		slug: string;
		description: string;
	} {
		const lines = message.content
			.split('\n')
			.map((l) => l.trim())
			.filter(Boolean);
		const headingLine = lines.find((l) => l.startsWith('#'));
		const heading = headingLine ? headingLine.replace(/^#+\s*/, '').trim() : '';
		const firstSentenceLine = lines.find((l) => !l.startsWith('#') && !l.startsWith('-'));
		const firstSentence = firstSentenceLine
			? firstSentenceLine.split(/(?<=[.!?])\s/)[0]
			: '';
		const name = heading || firstSentence.slice(0, 60) || 'Captured skill';
		const slugFromName = kebab(name);
		const slug =
			slugFromName || `captured-skill-${(message.id ?? '').slice(0, 6) || 'unknown'}`;
		return { name, slug, description: firstSentence };
	}

	/**
	 * Pure submit-gate: returns true when the modal has enough state to call
	 * ``createUserSkill``. Mirrors the reactive expression bound to the Save
	 * button's ``disabled`` attribute. Looser than ``SkillWizard.canSave``
	 * by intent — the capture flow is a thin "save as draft" path; the
	 * wizard is where slug-format + slash-alias validation happen.
	 */
	export function canSave(state: CaptureFormState): boolean {
		if (state.saving) return false;
		if (!state.name.trim()) return false;
		if (!state.slug.trim()) return false;
		if (!state.body.trim()) return false;
		return true;
	}

	/**
	 * Build the POST body for ``createUserSkill``. The output matches the
	 * backend ``UserSkillCreate`` schema exactly — display_name / body
	 * (NOT title / body_md), scope=user, source_message_id forwarded from
	 * the captured message. ``description`` falls back to the trimmed name
	 * when the user cleared it (the backend requires a non-empty value;
	 * the wizard mirrors this fallback for the same reason).
	 */
	export function buildPayload(
		state: CaptureFormState,
		sourceMessage: Message
	): UserSkillCreate {
		const trimmedName = state.name.trim();
		const trimmedDescription = state.description.trim();
		return {
			scope: 'user',
			slug: state.slug.trim(),
			display_name: trimmedName,
			description: trimmedDescription || trimmedName,
			body: state.body,
			source_message_id: sourceMessage.id
		};
	}

	/**
	 * Build the localStorage snapshot stashed for the Edit-in-wizard handoff.
	 * The shape MUST match ``WizardInitial`` in
	 * ``/lq-ai/skills/new/+page.svelte`` — that route reads the stash, casts
	 * it to WizardInitial, and seeds the wizard's ``initial`` prop. Renaming
	 * any field here breaks the handoff silently (no type error at the cast
	 * site). Defaults: scope=user, version=1.0.0, forkedFrom=null.
	 *
	 * ``sourceMessage`` is consulted only as a fallback for ``body``: if the
	 * user blanked the body field before clicking "Edit in wizard", we
	 * preserve their original intent ("refine this exchange in the wizard")
	 * by stashing the captured message content instead of an empty string.
	 */
	export function stashForWizard(
		state: CaptureFormState,
		sourceMessage: Message
	): CaptureStash {
		const body = state.body.trim() ? state.body : sourceMessage.content;
		return {
			slug: state.slug.trim(),
			displayName: state.name.trim(),
			description: state.description.trim(),
			body,
			scope: 'user',
			version: '1.0.0',
			forkedFrom: null
		};
	}

	/** localStorage key for a given capture stash id. Single source of truth. */
	export function stashStorageKey(captureId: string): string {
		return `lq-ai:capture-stash:${captureId}`;
	}
</script>

<script lang="ts">
	import { goto } from '$app/navigation';
	import { createUserSkill } from '$lib/lq-ai/api/userSkills';

	export let sourceMessage: Message;
	export let onClose: () => void;

	// Derive once on open. Modal is mounted per-message; reopen to re-derive.
	const derived = derive(sourceMessage);

	let name = derived.name;
	let slug = derived.slug;
	let description = derived.description;
	let body = sourceMessage.content;
	let saving = false;
	let error: string | null = null;

	// Auto-focus the Name input on open (mirrors NewMatterModal pattern).
	let nameInput: HTMLInputElement;
	$: if (nameInput) nameInput.focus();

	$: formState = { name, slug, description, body, saving } as CaptureFormState;
	$: saveable = canSave(formState);

	async function save(): Promise<void> {
		if (!saveable) return;
		saving = true;
		error = null;
		try {
			const created = await createUserSkill(buildPayload(formState, sourceMessage));
			onClose();
			await goto(`/lq-ai/skills/${encodeURIComponent(created.slug)}?just_saved=1`);
		} catch (e) {
			// LQAIApiError.message is safe; the FastAPI string-detail propagation
			// gap is known tech debt (root-cause fix queued for polish PR).
			error = e instanceof Error ? e.message : 'Save failed';
		} finally {
			saving = false;
		}
	}

	function newCaptureId(): string {
		if (typeof globalThis !== 'undefined' && globalThis.crypto?.randomUUID) {
			return globalThis.crypto.randomUUID();
		}
		return `capture-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
	}

	async function editInWizard(): Promise<void> {
		const captureId = newCaptureId();
		try {
			localStorage.setItem(
				stashStorageKey(captureId),
				JSON.stringify(stashForWizard(formState, sourceMessage))
			);
		} catch {
			// Storage quota / disabled — the wizard route falls through to a
			// blank wizard when the stash is missing, so this is non-fatal.
		}
		onClose();
		await goto(`/lq-ai/skills/new?capture=${captureId}`);
	}

	// Window-level keydown so Escape works regardless of focus location.
	// (The panel uses on:click|stopPropagation so click-outside still closes,
	// but we deliberately do NOT stop keydown propagation on the panel —
	// doing so previously swallowed Escape when focus was inside an input.)
	function handleWindowKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape') {
			onClose();
		}
	}
</script>

<svelte:window on:keydown={handleWindowKeydown} />

<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div
	class="csm-backdrop"
	role="dialog"
	aria-modal="true"
	aria-labelledby="csm-title"
	tabindex="-1"
	on:click={onClose}
>
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="csm-panel"
		on:click|stopPropagation
		data-testid="lq-ai-capture-skill-modal"
	>
		<header class="csm-header">
			<h2 id="csm-title" class="csm-title">Capture as a skill</h2>
			<button type="button" class="csm-close" aria-label="Close" on:click={onClose}
				>×</button
			>
		</header>

		<p class="csm-hint">
			Save this exchange as a personal skill. You can refine triggers later in the editor.
		</p>

		<label>
			<span>Name <em class="required">*</em></span>
			<input
				type="text"
				bind:value={name}
				bind:this={nameInput}
				aria-label="name"
				data-testid="lq-ai-capture-name"
				maxlength="200"
			/>
		</label>
		<label>
			<span>Slug <em class="required">*</em></span>
			<input
				type="text"
				bind:value={slug}
				aria-label="slug"
				data-testid="lq-ai-capture-slug"
				maxlength="80"
			/>
		</label>
		<label>
			<span>Description</span>
			<textarea
				bind:value={description}
				aria-label="description"
				data-testid="lq-ai-capture-description"
				rows="2"
			></textarea>
		</label>
		<label>
			<span>Body <em class="required">*</em></span>
			<textarea
				class="csm-body"
				bind:value={body}
				aria-label="body"
				data-testid="lq-ai-capture-body"
				rows="10"
			></textarea>
		</label>

		{#if error}
			<div class="csm-error" role="alert" data-testid="lq-ai-capture-error">
				{error}
			</div>
		{/if}

		<footer class="csm-actions">
			<button
				type="button"
				class="ghost"
				on:click={onClose}
				data-testid="lq-ai-capture-cancel">Cancel</button
			>
			<button
				type="button"
				class="ghost"
				on:click={editInWizard}
				data-testid="lq-ai-capture-edit-in-wizard">Edit in wizard</button
			>
			<button
				type="button"
				class="primary"
				on:click={save}
				disabled={!saveable}
				data-testid="lq-ai-capture-save"
			>
				{saving ? 'Saving…' : 'Save'}
			</button>
		</footer>
	</div>
</div>

<style>
	@import '$lib/lq-ai/styles/practice.css';

	.csm-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.35);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}
	.csm-panel {
		background: var(--lq-canvas);
		border: 1px solid var(--lq-border);
		border-radius: 8px;
		padding: 24px;
		width: 560px;
		max-width: 90vw;
		max-height: 90vh;
		overflow-y: auto;
		box-sizing: border-box;
	}
	.csm-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin: 0 0 8px;
	}
	.csm-title {
		font-size: 18px;
		font-weight: 600;
		margin: 0;
	}
	.csm-close {
		background: transparent;
		border: 0;
		font-size: 24px;
		line-height: 1;
		cursor: pointer;
		color: var(--lq-text-tertiary);
		padding: 0 4px;
	}
	.csm-hint {
		color: var(--lq-text-tertiary);
		font-size: 13px;
		margin: 0 0 16px;
	}
	label {
		display: block;
		margin-bottom: 12px;
	}
	label > span {
		display: block;
		font-size: 13px;
		font-weight: 600;
		margin-bottom: 4px;
	}
	.required {
		color: var(--lq-error);
		font-style: normal;
	}
	input,
	textarea {
		width: 100%;
		padding: 8px;
		border: 1px solid var(--lq-border-strong);
		border-radius: 6px;
		font-size: 14px;
		font-family: inherit;
		box-sizing: border-box;
	}
	.csm-body {
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
	}
	.csm-error {
		margin: 12px 0 0;
		padding: 8px 12px;
		border-radius: 6px;
		background: var(--lq-danger-soft);
		color: var(--lq-error);
		font-size: 13px;
	}
	.csm-actions {
		display: flex;
		gap: 8px;
		justify-content: flex-end;
		margin-top: 16px;
		padding-top: 16px;
		border-top: 1px solid var(--lq-border);
	}
	.ghost {
		background: transparent;
		border: 1px solid var(--lq-border);
		padding: 8px 16px;
		border-radius: var(--lq-radius-pill);
		cursor: pointer;
		font-size: 14px;
	}
	.primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		padding: 8px 16px;
		border-radius: var(--lq-radius-pill);
		cursor: pointer;
		font-size: 14px;
		font-weight: 500;
	}
	.primary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
