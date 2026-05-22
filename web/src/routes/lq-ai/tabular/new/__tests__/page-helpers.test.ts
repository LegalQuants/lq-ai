/**
 * Pure-helper tests for the Tabular Review wizard (M3-C3).
 *
 * The wizard is a single-route, four-step flow (per session-start
 * AskUserQuestion + prep-doc Decision C-5/C-7). These helpers carry the
 * deterministic state-machine + validation + request-builder logic so
 * the Svelte +page.svelte stays presentational and the gating logic is
 * test-covered without a browser.
 */
import { describe, expect, it } from 'vitest';

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
} from '../page-helpers';
import type { TabularColumnSpec } from '$lib/lq-ai/types';

describe('tabular wizard page-helpers', () => {
	describe('step transitions', () => {
		it('orders the four steps documents → columns → preview → confirm', () => {
			expect(stepIndex('documents')).toBe(0);
			expect(stepIndex('columns')).toBe(1);
			expect(stepIndex('preview')).toBe(2);
			expect(stepIndex('confirm')).toBe(3);
		});

		it('nextStep advances; lastStep returns itself', () => {
			expect(nextStep('documents')).toBe('columns');
			expect(nextStep('columns')).toBe('preview');
			expect(nextStep('preview')).toBe('confirm');
			expect(nextStep('confirm')).toBe('confirm');
		});

		it('prevStep retreats; firstStep returns itself', () => {
			expect(prevStep('confirm')).toBe('preview');
			expect(prevStep('preview')).toBe('columns');
			expect(prevStep('columns')).toBe('documents');
			expect(prevStep('documents')).toBe('documents');
		});

		it('isFirstStep / isLastStep recognise the boundary', () => {
			const all: WizardStep[] = ['documents', 'columns', 'preview', 'confirm'];
			expect(all.filter(isFirstStep)).toEqual(['documents']);
			expect(all.filter(isLastStep)).toEqual(['confirm']);
		});
	});

	describe('TABULAR_MAX_DOCS', () => {
		it('exposes the 200-document cap from Decision C-7', () => {
			expect(TABULAR_MAX_DOCS).toBe(200);
		});
	});

	describe('COST_CONFIRMATION_THRESHOLD_USD', () => {
		it('exposes the $1.00 threshold from Decision C-5', () => {
			expect(COST_CONFIRMATION_THRESHOLD_USD).toBe(1.0);
		});
	});

	describe('validateDocumentsStep', () => {
		it('returns an error when zero documents are selected', () => {
			expect(validateDocumentsStep([])).toMatch(/select at least one document/i);
		});

		it('returns null when one document is selected', () => {
			expect(validateDocumentsStep(['d1'])).toBeNull();
		});

		it('returns null when fewer than the cap are selected', () => {
			expect(validateDocumentsStep(new Array(200).fill('d'))).toBeNull();
		});

		it('returns an error message naming the 200-cap when exceeded', () => {
			const err = validateDocumentsStep(new Array(201).fill('d'));
			expect(err).toMatch(/200/);
		});
	});

	describe('validateColumnsStep', () => {
		it('returns null when a skill_name is set', () => {
			expect(validateColumnsStep({ skillName: 'contract-snapshot', columns: [] })).toBeNull();
		});

		it('returns null when at least one ad-hoc column is fully populated', () => {
			expect(
				validateColumnsStep({
					skillName: null,
					columns: [{ name: 'Term', query: 'What is the term?' }]
				})
			).toBeNull();
		});

		it('returns an error when neither skill nor columns are set', () => {
			expect(validateColumnsStep({ skillName: null, columns: [] })).toMatch(
				/choose a skill or define at least one column/i
			);
		});

		it('rejects ad-hoc columns missing a name or query', () => {
			expect(
				validateColumnsStep({
					skillName: null,
					columns: [{ name: '', query: 'q' }]
				})
			).toMatch(/name and query/i);
			expect(
				validateColumnsStep({
					skillName: null,
					columns: [{ name: 'Term', query: '' }]
				})
			).toMatch(/name and query/i);
		});

		it('rejects duplicate column names (case-insensitive)', () => {
			expect(
				validateColumnsStep({
					skillName: null,
					columns: [
						{ name: 'Term', query: 'a' },
						{ name: 'term', query: 'b' }
					]
				})
			).toMatch(/duplicate column name/i);
		});
	});

	describe('requiresCostConfirmation', () => {
		it('returns true above the $1.00 threshold', () => {
			expect(requiresCostConfirmation('1.01')).toBe(true);
			expect(requiresCostConfirmation('5.0000')).toBe(true);
		});

		it('returns true at exactly the threshold', () => {
			expect(requiresCostConfirmation('1.00')).toBe(true);
		});

		it('returns false below the threshold', () => {
			expect(requiresCostConfirmation('0.99')).toBe(false);
			expect(requiresCostConfirmation('0.00')).toBe(false);
		});

		it('returns false defensively on invalid input', () => {
			expect(requiresCostConfirmation('not a number')).toBe(false);
		});
	});

	describe('buildPreviewRequest', () => {
		it('uses skill_name when supplied; omits columns', () => {
			const req = buildPreviewRequest({
				documentIds: ['d1', 'd2'],
				skillName: 'contract-snapshot',
				columns: []
			});
			expect(req).toEqual({
				document_ids: ['d1', 'd2'],
				skill_name: 'contract-snapshot'
			});
		});

		it('uses columns when no skill_name; omits skill_name', () => {
			const cols: TabularColumnSpec[] = [{ name: 'Term', query: 'What is the term?' }];
			const req = buildPreviewRequest({
				documentIds: ['d1'],
				skillName: null,
				columns: cols
			});
			expect(req).toEqual({
				document_ids: ['d1'],
				columns: cols
			});
		});
	});

	describe('buildExecuteRequest', () => {
		it('echoes the confirmed_cost_usd alongside skill_name', () => {
			const req = buildExecuteRequest({
				documentIds: ['d1'],
				skillName: 'contract-snapshot',
				columns: [],
				confirmedCostUsd: '0.0500'
			});
			expect(req).toEqual({
				document_ids: ['d1'],
				skill_name: 'contract-snapshot',
				confirmed_cost_usd: '0.0500'
			});
		});

		it('echoes the confirmed_cost_usd alongside ad-hoc columns', () => {
			const cols: TabularColumnSpec[] = [{ name: 'Term', query: 'What is the term?' }];
			const req = buildExecuteRequest({
				documentIds: ['d1'],
				skillName: null,
				columns: cols,
				confirmedCostUsd: '0.0100'
			});
			expect(req).toEqual({
				document_ids: ['d1'],
				columns: cols,
				confirmed_cost_usd: '0.0100'
			});
		});
	});
});
