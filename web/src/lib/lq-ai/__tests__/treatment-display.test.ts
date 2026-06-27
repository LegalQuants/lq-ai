import { describe, expect, it } from 'vitest';
import { treatmentSummary, formatCitingRef } from '../citations/treatment-display';
import type { LedgerTreatment, LedgerCitingRef } from '../types';

function ref(o: Partial<LedgerCitingRef> = {}): LedgerCitingRef {
	return {
		cluster_id: 1,
		opinion_id: 2,
		case_name: 'Allen v. Wright',
		court: 'scotus',
		date_filed: '1984-07-03',
		...o
	};
}
function treatment(o: Partial<LedgerTreatment> = {}): LedgerTreatment {
	return {
		cited_by_count: 412,
		as_of: '2026-06-26T12:00:00+00:00',
		derived_method: 'citation_graph',
		citing: Array.from({ length: 30 }, (_, i) => ref({ case_name: `Case ${i}` })),
		...o
	};
}

describe('treatmentSummary', () => {
	it('labels plural count and slices the preview to 5', () => {
		const s = treatmentSummary(treatment());
		expect(s.label).toBe('Cited by 412 later opinions');
		expect(s.asOf).toBe('2026-06-26');
		expect(s.preview).toHaveLength(5);
		expect(s.moreCount).toBe(25);
		expect(s.shown).toBe(30);
		expect(s.total).toBe(412);
		expect(s.capped).toBe(true); // 412 > 30
	});

	it('singularizes a count of 1', () => {
		const s = treatmentSummary(treatment({ cited_by_count: 1, citing: [ref()] }));
		expect(s.label).toBe('Cited by 1 later opinion');
		expect(s.capped).toBe(false); // 1 == 1
		expect(s.moreCount).toBe(0);
	});

	it('handles an empty citing list', () => {
		const s = treatmentSummary(treatment({ cited_by_count: 7, citing: [] }));
		expect(s.preview).toEqual([]);
		expect(s.moreCount).toBe(0);
		expect(s.shown).toBe(0);
		expect(s.capped).toBe(true); // 7 > 0
	});

	it('falls back to citing.length when cited_by_count is missing/NaN', () => {
		// @ts-expect-error simulate a malformed payload (non-partial, cited_by_count missing)
		const s = treatmentSummary({
			as_of: '2026-06-26T12:00:00+00:00',
			derived_method: 'citation_graph',
			citing: [ref(), ref()]
		});
		expect(s.label).toBe('Cited by 2 later opinions');
		expect(s.total).toBe(2);
		expect(s.capped).toBe(false);
	});

	it('is not capped when count equals the stored list length', () => {
		const s = treatmentSummary(treatment({ cited_by_count: 3, citing: [ref(), ref(), ref()] }));
		expect(s.capped).toBe(false);
		expect(s.moreCount).toBe(0); // 3 - 3
	});
});

describe('formatCitingRef', () => {
	it('joins present fields with commas', () => {
		expect(
			formatCitingRef(ref({ case_name: 'Roe v. Wade', court: 'scotus', date_filed: '1973-01-22' }))
		).toBe('Roe v. Wade, scotus, 1973-01-22');
	});
	it('omits missing fields without stray commas', () => {
		expect(formatCitingRef({ case_name: 'X v. Y', court: null, date_filed: undefined })).toBe(
			'X v. Y'
		);
		expect(formatCitingRef({ case_name: 'X v. Y', court: 'ca9' })).toBe('X v. Y, ca9');
	});
	it('returns empty string when all fields missing', () => {
		expect(formatCitingRef({})).toBe('');
	});
});
