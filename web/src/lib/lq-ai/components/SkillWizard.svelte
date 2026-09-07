<script context="module" lang="ts">
	/**
	 * SkillWizard — 4-section guided authoring surface for the Skill Creator
	 * (Wave D.2 Task 4.2). Used by `/lq-ai/skills/new` (Task 4.3) and by the
	 * "fork-from-existing" path (Task 4.4). Both routes wire ``onSave`` to
	 * ``createUserSkill`` and ``onDiscard`` to a navigate-back.
	 *
	 * Caller contract:
	 *   - ``initial`` seeds every field; missing keys default to empty / null.
	 *     ``initial.scope`` / ``initial.ownerTeamId`` come from the parent
	 *     route (the wizard does NOT render a scope/team picker — see
	 *     plan-text NOTE in Task 4.2).
	 *   - ``draftKey`` enables localStorage autosave at
	 *     ``lq-ai:wizard-draft:${draftKey}``. When null, no persistence.
	 *   - ``onSave(payload)`` is called with the backend-shaped
	 *     ``UserSkillCreate`` body; it returns the new skill's id/slug. On
	 *     422 mentioning ``slash_alias``, the error is surfaced inline near
	 *     the alias input rather than via the banner.
	 *   - ``onDiscard()`` fires after the user confirms; the wizard
	 *     clears its localStorage draft before invoking the callback.
	 *
	 * Convention notes for reviewers:
	 *   - Pure helpers exported from <script context="module"> so vitest
	 *     can exercise them without @testing-library/svelte (which is not
	 *     installed; see AttachKBModal.test.ts header).
	 *   - Backend shape per ``api/app/api/user_skills.py:118-153``:
	 *     ``display_name`` / ``body`` (NOT ``title`` / ``body_md``). The
	 *     plan-text used the legacy names; we follow the real API.
	 *   - There is NO top-level ``jurisdiction`` field on the backend; we
	 *     drop the plan's jurisdiction input. If a future spec needs it,
	 *     it can ride ``frontmatter_extra.jurisdiction``.
	 *   - Design tokens: ``--lq-border``, ``--lq-accent``, ``--lq-text-tertiary``,
	 *     ``--lq-error`` are real per ``styles/practice.css``. The error
	 *     banner background uses the same #b54848 rgba so the tint matches.
	 *   - The "Draft saved" toast replaces the plan-text ``alert()`` —
	 *     there is no toast primitive in this codebase, so we use a small
	 *     transient in-component status row.
	 */
	import type { UserSkillCreate } from '../types';
	import { kebab } from '../util/slug';
	import {
		buildFrontmatterExtra,
		columnsFromRaw,
		newEditableColumn,
		validateColumns,
		type EditableColumn,
		type SkillOutputMode
	} from '../skills/tableColumns';

	/**
	 * DE-297 — fallback body persisted for a table-mode skill when the
	 * author leaves the (hidden) prose body empty. The backend requires a
	 * non-empty ``body``; for table mode the columns are the work product,
	 * so a documented placeholder satisfies the contract honestly.
	 */
	export const DEFAULT_TABLE_BODY =
		'Table-mode skill: each column in the frontmatter `columns` list defines a ' +
		'per-document extraction query. Run it from the Tabular Review wizard.';

	/** Mutable form state — every input bound in the template, plus ``saving``. */
	export interface WizardFormState {
		slug: string;
		displayName: string;
		description: string;
		body: string;
		tagsInput: string;
		slashAlias: string;
		version: string;
		scope: 'user' | 'team';
		ownerTeamId: string;
		/** DE-297 — 'prose' keeps the body editor; 'table' swaps in the column list. */
		outputMode: SkillOutputMode;
		/** DE-297 — table-mode column rows; ignored in prose mode. */
		columns: EditableColumn[];
		saving: boolean;
	}

	/** Serialized snapshot persisted in localStorage (no transient flags). */
	export interface WizardDraftSnapshot {
		slug: string;
		displayName: string;
		description: string;
		body: string;
		tagsInput: string;
		slashAlias: string;
		version: string;
		scope: 'user' | 'team';
		ownerTeamId: string;
		outputMode: SkillOutputMode;
		columns: EditableColumn[];
	}

	const SLUG_RE = /^[a-z0-9]([a-z0-9-]{0,78}[a-z0-9])?$|^[a-z0-9]$/;
	const SLASH_RE = /^\/[a-z0-9-]{1,32}$/;

	/** Slug matches the backend's slug pattern (1-80 chars, lowercase, no leading/trailing dash). */
	export function isSlugValid(slug: string): boolean {
		if (!slug) return false;
		if (slug.length > 80) return false;
		return SLUG_RE.test(slug);
	}

	/**
	 * Slash-alias validity. Empty / null / undefined is "no alias" and
	 * passes; a non-empty value must match the backend's
	 * ``^/[a-z0-9-]{1,32}$`` regex.
	 */
	export function isSlashAliasValid(alias: string | null | undefined): boolean {
		if (alias === null || alias === undefined || alias === '') return true;
		return SLASH_RE.test(alias);
	}

	/**
	 * Pure submit-gate: returns true when the wizard has enough state to
	 * call ``onSave``. Mirrors the reactive expression bound to the Save
	 * button's ``disabled`` attribute.
	 */
	export function canSave(state: WizardFormState): boolean {
		if (state.saving) return false;
		if (!state.slug || !isSlugValid(state.slug)) return false;
		if (!state.displayName.trim()) return false;
		if (!state.description.trim()) return false;
		if (state.outputMode === 'table') {
			// DE-297 — the column list replaces the body as the work
			// product; it must mirror the backend's table-mode rules
			// (min one column, non-empty name + query, tier 1-5).
			if (!validateColumns(state.columns).valid) return false;
		} else if (!state.body.trim()) {
			return false;
		}
		if (!isSlashAliasValid(state.slashAlias)) return false;
		if (state.scope === 'team' && !state.ownerTeamId) return false;
		return true;
	}

	/**
	 * Build the POST body for ``createUserSkill``. The output matches the
	 * backend ``UserSkillCreate`` schema exactly — display_name / body
	 * (NOT title / body_md), no top-level jurisdiction, slash_alias=null
	 * when the user left it blank.
	 */
	export function buildPayload(
		state: WizardFormState,
		forkedFrom: string | null
	): UserSkillCreate {
		const tags = state.tagsInput
			.split(',')
			.map((t) => t.trim())
			.filter(Boolean);
		const slashAlias = state.slashAlias.trim();
		const isTable = state.outputMode === 'table';
		const payload: UserSkillCreate = {
			slug: state.slug,
			display_name: state.displayName.trim(),
			description: state.description.trim(),
			// Table mode hides the body editor; the backend still requires
			// a non-empty body, so fall back to the documented placeholder
			// when the author never wrote one (DE-297).
			body: isTable && !state.body.trim() ? DEFAULT_TABLE_BODY : state.body,
			version: state.version,
			tags,
			slash_alias: slashAlias === '' ? null : slashAlias,
			scope: state.scope,
			owner_team_id: state.scope === 'team' ? state.ownerTeamId : null,
			forked_from: forkedFrom
		};
		if (isTable) {
			payload.frontmatter_extra = buildFrontmatterExtra({}, 'table', state.columns);
		}
		return payload;
	}

	/** Snapshot the persistable subset of the form state. */
	export function serializeDraft(state: WizardFormState): WizardDraftSnapshot {
		return {
			slug: state.slug,
			displayName: state.displayName,
			description: state.description,
			body: state.body,
			tagsInput: state.tagsInput,
			slashAlias: state.slashAlias,
			version: state.version,
			scope: state.scope,
			ownerTeamId: state.ownerTeamId,
			outputMode: state.outputMode,
			columns: state.columns
		};
	}

	/**
	 * Parse a raw JSON string from localStorage into a partial snapshot.
	 * Returns null when the input is missing, malformed, or not a plain
	 * object — the caller leaves the current state untouched in that case.
	 */
	export function loadDraft(raw: string | null): Partial<WizardDraftSnapshot> | null {
		if (!raw) return null;
		let parsed: unknown;
		try {
			parsed = JSON.parse(raw);
		} catch {
			return null;
		}
		if (
			parsed === null ||
			typeof parsed !== 'object' ||
			Array.isArray(parsed)
		) {
			return null;
		}
		return parsed as Partial<WizardDraftSnapshot>;
	}
</script>

<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import SkillWizardSection from './SkillWizardSection.svelte';
	import SkillTryItPane from './SkillTryItPane.svelte';
	import ColumnEditor from './ColumnEditor.svelte';
	import { LQAIApiError } from '$lib/lq-ai/api/client';

	export let initial: {
		slug?: string;
		displayName?: string;
		description?: string;
		body?: string;
		tags?: string[];
		slashAlias?: string | null;
		version?: string;
		scope?: 'user' | 'team';
		ownerTeamId?: string;
		forkedFrom?: string | null;
	} = {};
	export let draftKey: string | null = null;
	export let onSave: (payload: UserSkillCreate) => Promise<string>;
	export let onDiscard: () => void = () => {};

	// Form state — seeded from `initial` then potentially overridden by the
	// localStorage draft (onMount). The wizard owns the state; the parent
	// route is responsible only for the initial seed and the save / discard
	// callbacks.
	let slug = initial.slug ?? '';
	let displayName = initial.displayName ?? '';
	let description = initial.description ?? '';
	let body = initial.body ?? '';
	let tagsInput = (initial.tags ?? []).join(', ');
	let slashAlias = initial.slashAlias ?? '';
	let version = initial.version ?? '1.0.0';
	let scope: 'user' | 'team' = initial.scope ?? 'user';
	let ownerTeamId = initial.ownerTeamId ?? '';
	// DE-297 — output mode + table columns. New drafts start in prose;
	// choosing 'table' swaps the body editor for the column list.
	let outputMode: SkillOutputMode = 'prose';
	let columns: EditableColumn[] = [newEditableColumn()];
	// `forked_from` is write-once at create time per ADR 0012; we capture
	// it from `initial` and pass it through buildPayload verbatim.
	const forkedFrom: string | null = initial.forkedFrom ?? null;

	let slugTouched = false;
	let slashAliasError: string | null = null;
	let advancedOpen = false;
	let saving = false;
	let saveError: string | null = null;
	let draftSaved = false;
	let draftSavedTimer: ReturnType<typeof setTimeout> | null = null;

	// Reactive derivations -------------------------------------------------
	// Auto-derive slug from displayName until the user types in the slug
	// box. Once `slugTouched` flips true, the auto-derive stops — the user
	// owns the slug from that point on.
	$: if (!slugTouched && displayName) slug = kebab(displayName);
	$: slugValid = isSlugValid(slug);
	$: slashAliasValid = isSlashAliasValid(slashAlias);
	$: formState = {
		slug,
		displayName,
		description,
		body,
		tagsInput,
		slashAlias,
		version,
		scope,
		ownerTeamId,
		outputMode,
		columns,
		saving
	} as WizardFormState;
	$: saveable = canSave(formState);

	function validateSlashAlias() {
		slashAliasError =
			slashAlias && !isSlashAliasValid(slashAlias)
				? 'Slash alias must start with / and use lowercase letters, digits, and dashes (max 32 chars).'
				: null;
	}

	// localStorage autosave ------------------------------------------------
	// Debounced (300ms after the LAST keystroke). The reactive `$:` block
	// re-runs on any state change; we clear and re-arm the timer so a
	// rapid run of keystrokes results in exactly one write.
	let saveTimer: ReturnType<typeof setTimeout> | null = null;
	let restored = false;

	function scheduleAutosave() {
		if (!draftKey) return;
		if (!restored) return; // don't autosave before the restore pass
		if (saveTimer) clearTimeout(saveTimer);
		saveTimer = setTimeout(() => {
			try {
				localStorage.setItem(
					`lq-ai:wizard-draft:${draftKey}`,
					JSON.stringify(serializeDraft(formState))
				);
			} catch {
				// Storage quota / disabled — non-fatal; the user can still
				// hit the primary Save button.
			}
		}, 300);
	}

	// Tracking deps explicitly so Svelte's reactivity picks up every field
	// (including scope/ownerTeamId in the advanced section).
	$: {
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		slug;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		displayName;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		description;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		body;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		tagsInput;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		slashAlias;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		version;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		scope;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		ownerTeamId;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		outputMode;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		columns;
		scheduleAutosave();
	}

	onMount(() => {
		if (draftKey) {
			let raw: string | null = null;
			try {
				raw = localStorage.getItem(`lq-ai:wizard-draft:${draftKey}`);
			} catch {
				raw = null;
			}
			const d = loadDraft(raw);
			if (d) {
				if (typeof d.slug === 'string') {
					slug = d.slug;
					// Restoring a draft means the user already touched the slug
					// (otherwise the restored slug would be the kebab of the
					// restored displayName — same result). Set the touched flag
					// to be safe so the auto-derive doesn't clobber a manually
					// crafted slug on the next display-name keystroke.
					slugTouched = true;
				}
				if (typeof d.displayName === 'string') displayName = d.displayName;
				if (typeof d.description === 'string') description = d.description;
				if (typeof d.body === 'string') body = d.body;
				if (typeof d.tagsInput === 'string') tagsInput = d.tagsInput;
				if (typeof d.slashAlias === 'string') slashAlias = d.slashAlias;
				if (typeof d.version === 'string') version = d.version;
				if (d.scope === 'user' || d.scope === 'team') scope = d.scope;
				if (typeof d.ownerTeamId === 'string') ownerTeamId = d.ownerTeamId;
				if (d.outputMode === 'prose' || d.outputMode === 'table') outputMode = d.outputMode;
				const restoredColumns = columnsFromRaw(d.columns);
				if (restoredColumns && restoredColumns.length > 0) columns = restoredColumns;
			}
		}
		restored = true;
	});

	async function save(): Promise<void> {
		if (!saveable) return;
		saving = true;
		saveError = null;
		slashAliasError = null;
		try {
			const payload = buildPayload(formState, forkedFrom);
			await onSave(payload);
			if (draftKey) {
				try {
					localStorage.removeItem(`lq-ai:wizard-draft:${draftKey}`);
				} catch {
					// non-fatal
				}
			}
		} catch (e) {
			// A 422 on this endpoint comes from the slash_alias partial-unique
			// constraint (the only 422-yielding validator on POST /user-skills,
			// per api/app/api/user_skills.py:556-560). Surface it inline near
			// the alias input so the operator can correct it without reading
			// the banner; do NOT also paint the banner red (the two are
			// mutually exclusive by intent).
			if (e instanceof LQAIApiError && e.status === 422) {
				// Backend returns FastAPI's default string-shaped detail
				// (``HTTPException(status_code=422, detail="slash_alias ...")``),
				// which the typed client maps to a generic message. Look in
				// every string field we have access to so a future client
				// fix that preserves the raw detail will be picked up
				// automatically.
				const detailVals = e.details ? Object.values(e.details) : [];
				const detailStr = detailVals.find((v): v is string => typeof v === 'string') ?? '';
				const hintFromError =
					(detailStr && detailStr.toLowerCase().includes('slash_alias') && detailStr) ||
					(e.message.toLowerCase().includes('slash_alias') && e.message) ||
					'';
				slashAliasError =
					hintFromError ||
					`That slash alias is already used by another of your skills (slash_alias /${slashAlias.trim() || '?'}).`;
				saveError = null;
			} else {
				saveError = e instanceof Error ? e.message : 'Save failed';
			}
		} finally {
			saving = false;
		}
	}

	function saveDraft(): void {
		if (!draftKey) {
			// Nothing to persist to — surface the same toast for symmetry
			// so the user gets feedback that the click registered.
			showDraftSavedToast();
			return;
		}
		// Force an immediate write (skip the 300ms debounce) so the user
		// sees the "Draft saved" toast that matches a real write.
		if (saveTimer) {
			clearTimeout(saveTimer);
			saveTimer = null;
		}
		try {
			localStorage.setItem(
				`lq-ai:wizard-draft:${draftKey}`,
				JSON.stringify(serializeDraft(formState))
			);
		} catch {
			// non-fatal — show the toast anyway so the user knows the
			// click registered. Persistence is best-effort.
		}
		showDraftSavedToast();
	}

	function showDraftSavedToast(): void {
		draftSaved = true;
		if (draftSavedTimer) clearTimeout(draftSavedTimer);
		draftSavedTimer = setTimeout(() => {
			draftSaved = false;
			draftSavedTimer = null;
		}, 2000);
	}

	function discard(): void {
		if (!confirm('Discard this draft? This cannot be undone.')) return;
		if (draftKey) {
			try {
				localStorage.removeItem(`lq-ai:wizard-draft:${draftKey}`);
			} catch {
				// non-fatal
			}
		}
		onDiscard();
	}

	onDestroy(() => {
		if (saveTimer) clearTimeout(saveTimer);
		if (draftSavedTimer) clearTimeout(draftSavedTimer);
	});
</script>

<form
	class="lq-skill-wizard"
	data-testid="lq-ai-skill-wizard"
	on:submit|preventDefault={save}
>
	<SkillWizardSection
		index={1}
		title="What does this skill do?"
		hint="A name + one-line description. What triggers the skill is in section 2."
	>
		<label>
			<span>Display name <em class="required">*</em></span>
			<input
				type="text"
				bind:value={displayName}
				aria-label="display name"
				data-testid="lq-ai-wizard-display-name"
				maxlength="200"
			/>
		</label>
		<label>
			<span>Slug <em class="required">*</em></span>
			<input
				type="text"
				bind:value={slug}
				on:input={() => (slugTouched = true)}
				aria-label="slug"
				data-testid="lq-ai-wizard-slug"
				maxlength="80"
			/>
			{#if slug && !slugValid}
				<span class="error inline-error">
					Lowercase letters, digits, and dashes; 1-80 chars; no leading or trailing dash.
				</span>
			{/if}
		</label>
		<label>
			<span>Description <em class="required">*</em></span>
			<textarea
				bind:value={description}
				aria-label="description"
				data-testid="lq-ai-wizard-description"
				rows="2"
			></textarea>
		</label>
	</SkillWizardSection>

	<SkillWizardSection
		index={2}
		title="When should it run?"
		hint="A slash alias triggers the skill explicitly; tags help users discover it."
	>
		<label>
			<span>Slash alias (optional)</span>
			<input
				type="text"
				bind:value={slashAlias}
				on:blur={validateSlashAlias}
				placeholder="/nda-review"
				aria-label="slash alias"
				data-testid="lq-ai-wizard-slash-alias"
			/>
			{#if slashAliasError}
				<span class="error inline-error">{slashAliasError}</span>
			{/if}
		</label>
		<label>
			<span>Tags (comma-separated)</span>
			<input
				type="text"
				bind:value={tagsInput}
				placeholder="contracts, nda"
				aria-label="tags"
				data-testid="lq-ai-wizard-tags"
			/>
		</label>
	</SkillWizardSection>

	<SkillWizardSection
		index={3}
		title="What does it produce?"
		hint={outputMode === 'table'
			? 'A row-per-document grid — each column defines one extraction query.'
			: 'The skill body — instructions the model follows.'}
	>
		<div class="mode-selector" role="radiogroup" aria-label="output mode">
			<label class="mode-option">
				<input
					type="radio"
					name="lq-ai-wizard-output-mode"
					value="prose"
					bind:group={outputMode}
					data-testid="lq-ai-wizard-mode-prose"
				/>
				<span>Prose (default)</span>
			</label>
			<label class="mode-option">
				<input
					type="radio"
					name="lq-ai-wizard-output-mode"
					value="table"
					bind:group={outputMode}
					data-testid="lq-ai-wizard-mode-table"
				/>
				<span>Table</span>
			</label>
		</div>

		{#if outputMode === 'table'}
			<ColumnEditor bind:columns />
		{:else}
			<textarea
				class="body-textarea"
				bind:value={body}
				aria-label="body"
				data-testid="lq-ai-wizard-body"
				rows="14"
				placeholder={'# NDA Review\nApply this skill when the user shares an NDA…'}
			></textarea>
		{/if}
	</SkillWizardSection>

	<SkillWizardSection
		index={4}
		title="Try it out"
		hint="Test against the sandbox. This conversation is non-billable."
	>
		{#if outputMode === 'table'}
			<p class="hint" data-testid="lq-ai-wizard-tryout-table-hint">
				Table-mode skills run from the Tabular Review wizard against a document
				set — save the skill, then pick it at /lq-ai/tabular/new.
			</p>
		{:else if body.trim()}
			<SkillTryItPane
				draftBody={body}
				draftSlug={slug || 'draft'}
				source="wizard-tryout"
			/>
		{:else}
			<p class="hint" data-testid="lq-ai-wizard-tryout-hint">
				Add a body in section 3 to enable the sandbox.
			</p>
		{/if}
	</SkillWizardSection>

	<details class="advanced" bind:open={advancedOpen}>
		<summary>Advanced</summary>
		<label>
			<span>Version</span>
			<input
				type="text"
				bind:value={version}
				aria-label="version"
				data-testid="lq-ai-wizard-version"
			/>
		</label>
	</details>

	{#if saveError}
		<div class="error banner" data-testid="lq-ai-wizard-save-error">
			{saveError}
		</div>
	{/if}

	<footer class="actions">
		<span class="status-slot" aria-live="polite">
			{#if draftSaved}
				<span class="status" data-testid="lq-ai-wizard-draft-saved">
					Draft saved.
				</span>
			{/if}
		</span>
		<button
			type="button"
			class="ghost"
			on:click={discard}
			data-testid="lq-ai-wizard-discard"
		>
			Discard
		</button>
		<button
			type="button"
			class="ghost"
			on:click={saveDraft}
			data-testid="lq-ai-wizard-save-draft"
		>
			Save draft
		</button>
		<button
			type="submit"
			class="primary"
			disabled={!saveable}
			data-testid="lq-ai-wizard-save"
		>
			{saving ? 'Saving…' : 'Save'}
		</button>
	</footer>
</form>

<style>
	@import '$lib/lq-ai/styles/practice.css';

	.lq-skill-wizard {
		max-width: 760px;
		margin: 0 auto;
		padding: 24px;
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
		color: var(--lq-error, #b54848);
		font-style: normal;
	}
	input,
	textarea {
		width: 100%;
		padding: 8px;
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: 6px;
		font-size: 14px;
		font-family: inherit;
		box-sizing: border-box;
	}
	.body-textarea {
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
	}
	.mode-selector {
		display: flex;
		gap: 16px;
		margin-bottom: 12px;
	}
	.mode-option {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 0;
		cursor: pointer;
	}
	.mode-option > input {
		width: auto;
	}
	.mode-option > span {
		display: inline;
		font-size: 14px;
		font-weight: 400;
		margin-bottom: 0;
	}
	.error {
		color: var(--lq-error, #b54848);
		font-size: 12px;
	}
	.inline-error {
		display: block;
		margin-top: 4px;
	}
	.banner {
		margin: 16px 0;
		padding: 8px 12px;
		border-radius: 6px;
		background: rgba(181, 72, 72, 0.08);
		font-size: 13px;
	}
	.hint {
		color: var(--lq-text-tertiary, #9ca3af);
		font-size: 13px;
		margin: 0;
	}
	.advanced {
		margin: 16px 0;
	}
	.advanced summary {
		cursor: pointer;
		font-size: 13px;
		color: var(--lq-text-tertiary, #9ca3af);
		padding: 8px 0;
	}
	.actions {
		display: flex;
		gap: 8px;
		align-items: center;
		justify-content: flex-end;
		margin-top: 24px;
		padding-top: 16px;
		border-top: 1px solid var(--lq-border, #e5e7eb);
	}
	.status-slot {
		margin-right: auto;
		min-height: 1.2em;
		font-size: 13px;
		color: var(--lq-text-tertiary, #9ca3af);
	}
	.status {
		color: var(--lq-accent, #1f7a6b);
	}
	.ghost {
		background: transparent;
		border: 1px solid var(--lq-border, #e5e7eb);
		padding: 8px 16px;
		border-radius: 6px;
		cursor: pointer;
		font-size: 14px;
	}
	.primary {
		background: var(--lq-accent, #1f7a6b);
		color: white;
		border: 0;
		padding: 8px 16px;
		border-radius: 6px;
		cursor: pointer;
		font-size: 14px;
		font-weight: 500;
	}
	.primary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
