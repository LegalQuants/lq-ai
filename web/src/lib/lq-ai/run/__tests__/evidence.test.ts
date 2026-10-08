/**
 * The evidence line under a delivered answer: how far to rely on it.
 *
 * `evidence_result` is the count of the answer's quotations that were checked against
 * the documents the owner selected. The backend builds it from the fiduciary gate
 * (`checked` = total assertions, `matched` = pass + supported, `unmatched` = fail) and
 * leaves it out when no quotation could be checked.
 */
import { describe, expect, it } from 'vitest';

import type { EvidenceResult } from '../../api/orchestration';
import {
	evidenceGate,
	evidenceHint,
	evidenceState,
	evidenceStatement,
	showsEvidence,
	type EvidenceInput,
	type EvidenceState
} from '../evidence';
import { LEGACY_RUNS, allRuns, citations, ledger, legacyRun, run } from './fixtures';

const UNVERIFIED = 'Model-generated; unverified.';
const NOTHING_CHECKED =
	'No quotation in this answer could be checked against the selected documents. Treat it as unverified.';
const HINT = 'Open the citation chips and the ledger under the answer to see each result.';

function result(
	checked: number,
	matched: number,
	unmatched: number,
	gate = 'flagged'
): EvidenceResult {
	return { gate_status: gate, checked, matched, unmatched };
}

/** A delivered answer from a profile that checks quotations. */
function citationsRun(evidence_result: EvidenceResult | null | undefined): EvidenceInput {
	return { evidence: 'citations', evidence_result };
}

describe('a profile that checks quotations', () => {
	it('says every quotation matched when they all did', () => {
		// What the backend recorded for a clean answer: two quotations, both exact matches.
		const input = citationsRun(result(2, 2, 0, 'fiduciary_grade'));
		expect(evidenceState(input)).toBe('matched');
		expect(evidenceStatement(input)).toBe('2 of 2 checked quotations matched the selected documents.');
		expect(evidenceHint(input)).toBe(HINT);
		expect(evidenceGate(input)).toBe('fiduciary_grade');
	});

	it('speaks of one quotation in the singular', () => {
		expect(evidenceStatement(citationsRun(result(1, 1, 0, 'fiduciary_grade')))).toBe(
			'1 of 1 checked quotation matched the selected documents.'
		);
	});

	it('says how many could not be matched, on the recorded answer that had one', () => {
		const recorded = run('documents.completed');
		// The recorded answer had no unmarked passage and no marker outside the selection.
		expect(recorded.evidence_result).toEqual({
			...result(3, 2, 1, 'flagged'),
			unresolved: 0,
			unmarked: 0
		});
		expect(evidenceState(recorded)).toBe('unmatched');
		expect(evidenceStatement(recorded)).toBe(
			'2 of 3 checked quotations matched the selected documents. 1 could not be matched and is marked unverified.'
		);
		expect(evidenceHint(recorded)).toBe(HINT);
		expect(evidenceGate(recorded)).toBe('flagged');
	});

	it('says "are" when more than one could not be matched', () => {
		expect(evidenceStatement(citationsRun(result(3, 1, 2)))).toBe(
			'1 of 3 checked quotations matched the selected documents. 2 could not be matched and are marked unverified.'
		);
	});

	it('does not soften a check that matched nothing', () => {
		const input = citationsRun(result(2, 0, 2));
		expect(evidenceState(input)).toBe('unmatched');
		expect(evidenceStatement(input)).toBe(
			'0 of 2 checked quotations matched the selected documents. 2 could not be matched and are marked unverified.'
		);
	});

	it('says nothing could be checked, and not that anything matched, when the answer carried no checkable quotation', () => {
		// The backend omits `evidence_result` in that case (an answer with no quotation, or none naming a selected document).
		for (const missing of [null, undefined]) {
			const input = citationsRun(missing);
			expect(evidenceState(input)).toBe('unchecked');
			expect(evidenceStatement(input)).toBe(NOTHING_CHECKED);
			expect(evidenceHint(input)).toBeNull();
			expect(evidenceGate(input)).toBeNull();
		}
	});

	it('reads a count of zero checked as nothing checked, never as "0 of 0 matched"', () => {
		for (const zero of [
			result(0, 0, 0, 'fiduciary_grade'),
			result(-1, 0, 0),
			result(Number.NaN, 0, 0)
		]) {
			const input = citationsRun(zero);
			expect(evidenceState(input)).toBe('unchecked');
			expect(evidenceStatement(input)).toBe(NOTHING_CHECKED);
		}
	});

	it('reads a gate the answer was labelled with without changing the counts', () => {
		const input = citationsRun(result(3, 3, 0, 'supported_only'));
		expect(evidenceGate(input)).toBe('supported_only');
		expect(evidenceStatement(input)).toBe('3 of 3 checked quotations matched the selected documents.');
	});
});

describe('a profile that does not check quotations', () => {
	it('says the answer is model-generated and unverified', () => {
		const input: EvidenceInput = { evidence: 'unverified' };
		expect(evidenceState(input)).toBe('unverified');
		expect(evidenceStatement(input)).toBe(UNVERIFIED);
		expect(evidenceHint(input)).toBeNull();
		expect(evidenceGate(input)).toBeNull();
	});

	it('does not claim a match even if a count arrives with it', () => {
		const input: EvidenceInput = {
			evidence: 'unverified',
			evidence_result: result(2, 2, 0, 'fiduciary_grade')
		};
		expect(evidenceState(input)).toBe('unverified');
		expect(evidenceStatement(input)).toBe(UNVERIFIED);
		expect(evidenceHint(input)).toBeNull();
	});

	it('is what an older run, which has no evidence fields at all, reads as', () => {
		for (const name of LEGACY_RUNS) {
			const recorded = legacyRun(name);
			expect(recorded.evidence, name).toBeUndefined();
			expect(recorded.evidence_result, name).toBeUndefined();
			expect(evidenceState(recorded), name).toBe('unverified');
			expect(evidenceStatement(recorded), name).toBe(UNVERIFIED);
		}
		expect(evidenceStatement({})).toBe(UNVERIFIED);
	});

	it('reads a profile with a kind of evidence it does not know as unverified', () => {
		const input = { evidence: 'notarised', evidence_result: null } as unknown as EvidenceInput;
		expect(evidenceState(input)).toBe('unverified');
		expect(evidenceStatement(input)).toBe(UNVERIFIED);
	});

	it('reads the recorded fixed-document answers as unverified', () => {
		for (const name of ['completed', 'refusals-and-partial'] as const) {
			expect(evidenceState(run(name)), name).toBe('unverified');
			expect(evidenceStatement(run(name)), name).toBe(UNVERIFIED);
		}
	});
});

describe('an unmatched quotation never reads as a clean result', () => {
	// Every count the backend can produce: the three always add up (checked = matched + unmatched).
	const cases: { checked: number; matched: number; unmatched: number }[] = [];
	for (let checked = 1; checked <= 6; checked += 1) {
		for (let matched = 0; matched <= checked; matched += 1) {
			cases.push({ checked, matched, unmatched: checked - matched });
		}
	}

	it.each(cases.filter((c) => c.unmatched > 0))(
		'$matched of $checked matched: it is "unmatched", says how many could not be, and says unverified',
		({ checked, matched, unmatched }) => {
			const input = citationsRun(result(checked, matched, unmatched));
			const statement = evidenceStatement(input);
			expect(evidenceState(input)).toBe('unmatched');
			expect(statement).toContain(`${unmatched} could not be matched`);
			expect(statement).toMatch(/marked unverified\.$/);
			// It is not the all-clear sentence with something added to it: that sentence is not there.
			expect(statement).not.toMatch(/^\d+ of \d+ quotations? matched the selected documents\.$/);
		}
	);

	it.each(cases.filter((c) => c.unmatched === 0))(
		'$matched of $checked matched: only now is it "matched", and it says nothing about any that could not be',
		({ checked, matched }) => {
			const input = citationsRun(result(checked, matched, 0, 'fiduciary_grade'));
			expect(evidenceState(input)).toBe('matched');
			expect(evidenceStatement(input)).toMatch(
				new RegExp(`^${matched} of ${checked} checked quotations? matched the selected documents\\.$`)
			);
		}
	);

	it('is the only state that can be called matched', () => {
		const states = new Set<EvidenceState>();
		for (const { checked, matched, unmatched } of cases) {
			states.add(evidenceState(citationsRun(result(checked, matched, unmatched))));
		}
		expect([...states].sort()).toEqual(['matched', 'unmatched']);
	});

	// The backend always sends checked = matched + unmatched, so a count that does not add up is
	// not expected. If one arrives it must not read as clean either: a checked quotation that is
	// not reported as matched is one that could not be matched, whatever the unmatched figure says.
	it('reads a checked quotation that is not reported as matched as one that could not be matched', () => {
		const unaccountedFor = citationsRun(result(4, 3, 0));
		expect(evidenceState(unaccountedFor)).toBe('unmatched');
		expect(evidenceStatement(unaccountedFor)).toBe(
			'3 of 4 checked quotations matched the selected documents. 1 could not be matched and is marked unverified.'
		);
		expect(evidenceHint(unaccountedFor)).toBe(HINT);
	});

	it('does the same when there is no matched figure at all', () => {
		for (const matched of [undefined, null, '', 'many', Number.NaN]) {
			const input = citationsRun({
				gate_status: 'flagged',
				checked: 3,
				matched,
				unmatched: 0
			} as unknown as EvidenceResult);
			expect(evidenceState(input), String(matched)).toBe('unmatched');
			expect(evidenceStatement(input), String(matched)).toBe(
				'0 of 3 checked quotations matched the selected documents. 3 could not be matched and are marked unverified.'
			);
		}
	});

	it('says the larger of the number reported as unmatched and the number it works out', () => {
		// They agree.
		expect(evidenceStatement(citationsRun(result(5, 3, 2)))).toContain('2 could not be matched');
		// The report says more than the arithmetic: the report stands.
		expect(evidenceStatement(citationsRun(result(5, 4, 3)))).toContain('3 could not be matched');
		// The arithmetic says more than the report: the arithmetic stands.
		expect(evidenceStatement(citationsRun(result(5, 1, 1)))).toContain('4 could not be matched');
	});

	it('is the matched state only when every checked quotation is reported as matched and none as unmatched', () => {
		// Every combination of up to six checked, however the three figures disagree with each other.
		for (let checked = 1; checked <= 6; checked += 1) {
			for (let matched = 0; matched <= checked; matched += 1) {
				for (let unmatched = 0; unmatched <= checked; unmatched += 1) {
					const input = citationsRun(result(checked, matched, unmatched));
					const clean = matched === checked && unmatched === 0;
					const label = `${matched} matched, ${unmatched} unmatched, ${checked} checked`;
					expect(evidenceState(input), label).toBe(clean ? 'matched' : 'unmatched');
					if (!clean) {
						expect(evidenceStatement(input), label).toMatch(
							/ could not be matched and (?:is|are) marked unverified\.$/
						);
					}
				}
			}
		}
	});
});

describe('the words never claim more than was checked', () => {
	const everyStatement = (): [string, string][] => {
		const out: [string, string][] = [];
		for (const { label, run: value } of allRuns()) out.push([label, evidenceStatement(value)]);
		for (const [label, input] of [
			['clean', citationsRun(result(2, 2, 0, 'fiduciary_grade'))],
			['one unmatched', citationsRun(result(3, 2, 1))],
			['all unmatched', citationsRun(result(2, 0, 2))],
			['unchecked', citationsRun(null)],
			['unverified', { evidence: 'unverified' } as EvidenceInput]
		] as [string, EvidenceInput][]) {
			out.push([label, evidenceStatement(input)]);
		}
		return out;
	};

	it('never calls an answer verified, correct, accurate, reliable, safe or advice', () => {
		for (const [label, statement] of everyStatement()) {
			expect(statement, label).not.toMatch(
				/(?<!un)verified|\bcorrect|\baccurate|\breliable|\bsafe\b|advice|\bconfirmed\b/i
			);
		}
	});

	it('is plain sentences ending in a full stop, with no raw code or markup in it', () => {
		for (const [label, statement] of everyStatement()) {
			expect(statement, label).toMatch(/^[A-Z0-9][^_<>]*\.$/);
		}
	});
});

describe('showsEvidence', () => {
	it('is only for a run whose answer was delivered', () => {
		for (const { label, run: value } of allRuns()) {
			expect(showsEvidence(value), label).toBe(value.status === 'completed');
		}
		expect(showsEvidence({ status: 'completed' })).toBe(true);
		for (const status of [
			'planning',
			'awaiting_approval',
			'running',
			'uncertain',
			'failed',
			'halted',
			'closed',
			'rejected',
			'expired',
			'something_new'
		]) {
			expect(showsEvidence({ status }), status).toBe(false);
		}
	});

	it('has no line for a run that checks quotations but has not delivered an answer to check', () => {
		for (const name of ['documents.planning', 'documents.awaiting-approval'] as const) {
			const recorded = run(name);
			expect(recorded.evidence).toBe('citations');
			expect(showsEvidence(recorded), name).toBe(false);
		}
	});
});

describe('against the other recordings of the same answer', () => {
	it('agrees with the ledger’s gate for the answer', () => {
		const recorded = run('documents.completed').evidence_result!;
		const [gate] = ledger().gates;
		expect(recorded.checked).toBe(gate.total_assertions);
		expect(recorded.matched).toBe(gate.pass_count + gate.supported_count);
		expect(recorded.unmatched).toBe(gate.fail_count);
		expect(recorded.gate_status).toBe(gate.gate_status);
	});

	it('agrees with the citation rows the chips show: one quotation that could not be matched', () => {
		const recorded = run('documents.completed').evidence_result!;
		const rows = citations();
		expect(rows).toHaveLength(recorded.checked);
		expect(rows.filter((row) => row.verified)).toHaveLength(recorded.matched);
		expect(rows.filter((row) => !row.verified)).toHaveLength(recorded.unmatched);
	});
});

describe('shapes it was not promised', () => {
	it('never throws and always says something, whatever arrives in the counts', () => {
		const odd = [
			null,
			undefined,
			{},
			{ checked: '3', matched: '2', unmatched: '1', gate_status: 'flagged' },
			{ checked: 3 },
			{ checked: 3, matched: null, unmatched: null },
			{ checked: Infinity, matched: 1, unmatched: 0 },
			{ checked: 2.9, matched: 5, unmatched: -1 },
			[1, 2, 3]
		];
		for (const evidence_result of odd) {
			for (const evidence of ['citations', 'unverified', undefined, 7]) {
				const input = { evidence, evidence_result } as unknown as EvidenceInput;
				expect(() => evidenceStatement(input)).not.toThrow();
				expect(evidenceStatement(input).length).toBeGreaterThan(0);
				expect(['unverified', 'unchecked', 'matched', 'incomplete', 'unmatched']).toContain(
					evidenceState(input)
				);
			}
		}
	});

	it('counts whole quotations, and never more matched than were checked', () => {
		expect(evidenceStatement(citationsRun(result(2.9, 1, 1)))).toBe(
			'1 of 2 checked quotations matched the selected documents. 1 could not be matched and is marked unverified.'
		);
		expect(evidenceStatement(citationsRun(result(2, 5, 0)))).toBe(
			'2 of 2 checked quotations matched the selected documents.'
		);
	});

	it('works out how many could not be matched when the count of them is missing', () => {
		const input = citationsRun({
			gate_status: 'flagged',
			checked: 3,
			matched: 2
		} as unknown as EvidenceResult);
		expect(evidenceState(input)).toBe('unmatched');
		expect(evidenceStatement(input)).toContain('1 could not be matched');
	});
});

describe('quoted text that was not checked is said so', () => {
	const MATCHED = '2 of 2 checked quotations matched the selected documents.';

	function withUnseen(unresolved: number | undefined, unmarked: number | undefined, unmatched = 0) {
		return citationsRun({
			gate_status: unmatched > 0 ? 'flagged' : 'fiduciary_grade',
			checked: 2 + unmatched,
			matched: 2,
			unmatched,
			unresolved,
			unmarked
		} as EvidenceResult);
	}

	it('is the plain matched line when nothing went unchecked, or the server sent no such counts', () => {
		for (const input of [withUnseen(0, 0), withUnseen(undefined, undefined)]) {
			expect(evidenceState(input)).toBe('matched');
			expect(evidenceStatement(input)).toBe(MATCHED);
		}
	});

	it('names quoted passages with no source marker, as seen on a local model', () => {
		const input = withUnseen(0, 2);
		expect(evidenceState(input)).toBe('incomplete');
		expect(evidenceStatement(input)).toBe(
			`${MATCHED} 2 quoted passages have no source marker and were not checked.`
		);
		expect(evidenceStatement(withUnseen(0, 1))).toBe(
			`${MATCHED} 1 quoted passage has no source marker and was not checked.`
		);
		expect(evidenceHint(input)).toBe(HINT);
	});

	it('names a quotation that cites a document outside the selection', () => {
		expect(evidenceState(withUnseen(1, 0))).toBe('incomplete');
		expect(evidenceStatement(withUnseen(1, 0))).toBe(
			`${MATCHED} 1 quotation cites a document that is not in the selection and was not checked.`
		);
		expect(evidenceStatement(withUnseen(3, 0))).toBe(
			`${MATCHED} 3 quotations cite a document that is not in the selection and were not checked.`
		);
	});

	it('says both, after what could not be matched, and stays the unmatched state', () => {
		const input = withUnseen(1, 2, 1);
		expect(evidenceState(input)).toBe('unmatched');
		expect(evidenceStatement(input)).toBe(
			'2 of 3 checked quotations matched the selected documents. 1 could not be matched and is marked unverified. ' +
				'1 quotation cites a document that is not in the selection and was not checked. ' +
				'2 quoted passages have no source marker and were not checked.'
		);
	});

	it('is never the clean state while any quoted text went unchecked', () => {
		for (const unresolved of [0, 1, 4]) {
			for (const unmarked of [0, 1, 7]) {
				const state = evidenceState(withUnseen(unresolved, unmarked));
				expect(state, `${unresolved}/${unmarked}`).toBe(
					unresolved + unmarked === 0 ? 'matched' : 'incomplete'
				);
			}
		}
	});

	it('reads a count that is not a whole number of zero or more as none', () => {
		for (const odd of [-3, Number.NaN, Number.POSITIVE_INFINITY, '2', null, {}]) {
			const input = withUnseen(odd as never, odd as never);
			expect(evidenceState(input), String(odd)).toBe('matched');
			expect(evidenceStatement(input), String(odd)).toBe(MATCHED);
		}
		expect(evidenceStatement(withUnseen(0, 2.9))).toContain('2 quoted passages have no source marker');
	});

	it('never calls an answer verified, whatever was or was not checked', () => {
		for (const input of [withUnseen(0, 0), withUnseen(2, 3), withUnseen(1, 1, 2)]) {
			expect(evidenceStatement(input)).not.toMatch(/\bverified\b(?<!unverified)/i);
		}
	});
});
