/**
 * Pure-helper tests for the matter-intake page (item 1.6).
 *
 * Mirrors the pattern from ../../__tests__/page-helpers.test.ts.
 */
import { describe, expect, it } from 'vitest';

import {
	QUERY_MAX_LENGTH,
	buildIntakeRunRequest,
	isIntakeFormValid,
	validateIntakeForm,
	type IntakeFormState
} from '../intake-helpers';

function baseForm(overrides: Partial<IntakeFormState> = {}): IntakeFormState {
	return {
		query: 'Review the Acme NDA for a mutual confidentiality carve-out.',
		targetKind: 'skill',
		skillRef: 'nda-review',
		playbookId: '',
		kbId: '',
		projectId: '',
		maxCostUsd: '',
		...overrides
	};
}

// ---------------------------------------------------------------------------
// validateIntakeForm / isIntakeFormValid
// ---------------------------------------------------------------------------

describe('validateIntakeForm', () => {
	it('accepts a description + skill target', () => {
		const errors = validateIntakeForm(baseForm());
		expect(errors).toEqual({ query: null, target: null });
		expect(isIntakeFormValid(errors)).toBe(true);
	});

	it('requires a non-blank description (empty and whitespace-only)', () => {
		for (const query of ['', '   ', '\n\t ']) {
			const errors = validateIntakeForm(baseForm({ query }));
			expect(errors.query).toBeTruthy();
			expect(isIntakeFormValid(errors)).toBe(false);
		}
	});

	it('rejects a description longer than QUERY_MAX_LENGTH after trimming', () => {
		const atLimit = validateIntakeForm(baseForm({ query: 'a'.repeat(QUERY_MAX_LENGTH) }));
		expect(atLimit.query).toBeNull();

		const overLimit = validateIntakeForm(baseForm({ query: 'a'.repeat(QUERY_MAX_LENGTH + 1) }));
		expect(overLimit.query).toBeTruthy();
	});

	it('requires a skill when targetKind=skill', () => {
		const errors = validateIntakeForm(baseForm({ skillRef: '' }));
		expect(errors.target).toBeTruthy();
		expect(isIntakeFormValid(errors)).toBe(false);
	});

	it('requires a playbook when targetKind=playbook', () => {
		const missing = validateIntakeForm(baseForm({ targetKind: 'playbook', playbookId: '' }));
		expect(missing.target).toBeTruthy();

		const chosen = validateIntakeForm(
			baseForm({ targetKind: 'playbook', playbookId: 'pb-1', skillRef: '' })
		);
		expect(chosen.target).toBeNull();
	});

	it('reports both errors independently', () => {
		const errors = validateIntakeForm(baseForm({ query: '', skillRef: '' }));
		expect(errors.query).toBeTruthy();
		expect(errors.target).toBeTruthy();
	});
});

// ---------------------------------------------------------------------------
// buildIntakeRunRequest
// ---------------------------------------------------------------------------

describe('buildIntakeRunRequest', () => {
	it('builds a minimal skill-targeted body: trimmed query + skill_ref only', () => {
		const body = buildIntakeRunRequest(baseForm({ query: '  Review the NDA.  ' }));
		expect(body).toEqual({ query: 'Review the NDA.', skill_ref: 'nda-review' });
	});

	it('uses playbook_id (not skill_ref) when targetKind=playbook', () => {
		const body = buildIntakeRunRequest(
			baseForm({ targetKind: 'playbook', playbookId: 'pb-1', skillRef: 'nda-review' })
		);
		expect(body.playbook_id).toBe('pb-1');
		expect(body).not.toHaveProperty('skill_ref');
	});

	it('includes optional scope fields only when set', () => {
		const body = buildIntakeRunRequest(
			baseForm({ kbId: 'kb-1', projectId: 'proj-1', maxCostUsd: ' 1.50 ' })
		);
		expect(body.target_kb_id).toBe('kb-1');
		expect(body.project_id).toBe('proj-1');
		// Decimal-as-string on the wire — never coerced to number.
		expect(body.max_cost_usd).toBe('1.50');
	});

	it('omits blank optional fields entirely (non-null-subset convention)', () => {
		const body = buildIntakeRunRequest(baseForm());
		expect(body).not.toHaveProperty('target_kb_id');
		expect(body).not.toHaveProperty('project_id');
		expect(body).not.toHaveProperty('max_cost_usd');
	});
});
