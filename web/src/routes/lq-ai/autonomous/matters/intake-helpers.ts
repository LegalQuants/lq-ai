/**
 * Pure helpers for the matter-intake page (item 1.6).
 *
 * Extracted from `+page.svelte` so vitest can exercise them without the
 * SvelteKit / Svelte runtime (mirrors ../page-helpers.ts). No side-effects.
 */

import type { ManualRunRequest } from '$lib/lq-ai/api/autonomous';

/** Mirrors the backend bound (StringConstraints max_length=10_000). */
export const QUERY_MAX_LENGTH = 10_000;

/** The intake form's raw field state, as bound in the page. */
export interface IntakeFormState {
	/** Free-text matter description → ManualRunRequest.query. */
	query: string;
	targetKind: 'skill' | 'playbook';
	skillRef: string;
	playbookId: string;
	kbId: string;
	projectId: string;
	maxCostUsd: string;
}

/** Per-field validation errors; null = field is valid. */
export interface IntakeFormErrors {
	query: string | null;
	target: string | null;
}

/**
 * Validate the intake form. Returns per-field errors; both null ⇔ valid
 * (see isIntakeFormValid). The description is required on THIS page —
 * the API keeps `query` optional, but a matter-intake submission without
 * a description would silently fall back to the query-less path, which
 * is not what the user asked for.
 */
export function validateIntakeForm(form: IntakeFormState): IntakeFormErrors {
	const errors: IntakeFormErrors = { query: null, target: null };

	const trimmed = form.query.trim();
	if (!trimmed) {
		errors.query = 'Describe the matter — this is what the run works on.';
	} else if (trimmed.length > QUERY_MAX_LENGTH) {
		errors.query = `The description is too long (max ${QUERY_MAX_LENGTH.toLocaleString()} characters).`;
	}

	if (form.targetKind === 'skill' && !form.skillRef) {
		errors.target = 'Select a skill, or switch to the Playbook target.';
	} else if (form.targetKind === 'playbook' && !form.playbookId) {
		errors.target = 'Select a playbook, or switch to the Skill target.';
	}

	return errors;
}

/** True when validateIntakeForm produced no field errors. */
export function isIntakeFormValid(errors: IntakeFormErrors): boolean {
	return errors.query === null && errors.target === null;
}

/**
 * Build the POST /autonomous/run-now body from a validated form.
 *
 * Optional fields are OMITTED when blank (the API's non-null-subset
 * convention); the description is trimmed. `max_cost_usd` stays a string
 * (Decimal-as-string on the wire, matching the schedules form).
 */
export function buildIntakeRunRequest(form: IntakeFormState): ManualRunRequest {
	return {
		query: form.query.trim(),
		...(form.targetKind === 'skill'
			? { skill_ref: form.skillRef }
			: { playbook_id: form.playbookId }),
		...(form.kbId ? { target_kb_id: form.kbId } : {}),
		...(form.projectId ? { project_id: form.projectId } : {}),
		...(form.maxCostUsd.trim() !== '' ? { max_cost_usd: form.maxCostUsd.trim() } : {})
	};
}
