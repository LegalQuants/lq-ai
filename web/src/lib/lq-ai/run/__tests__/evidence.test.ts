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
import { runActivity } from '../activity';
import {
	DIRECT_ANSWER_STATEMENT,
	DIRECT_DID_NOT_READ,
	NO_DOCUMENTS_STATEMENT,
	evidenceGate,
	evidenceHint,
	evidenceLine,
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
		expect(evidenceStatement(input)).toBe(
			'2 of 2 checked quotations matched the selected documents.'
		);
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
		expect(evidenceStatement(input)).toBe(
			'3 of 3 checked quotations matched the selected documents.'
		);
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
				new RegExp(
					`^${matched} of ${checked} checked quotations? matched the selected documents\\.$`
				)
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
		expect(evidenceStatement(withUnseen(0, 2.9))).toContain(
			'2 quoted passages have no source marker'
		);
	});

	it('never calls an answer verified, whatever was or was not checked', () => {
		for (const input of [withUnseen(0, 0), withUnseen(2, 3), withUnseen(1, 1, 2)]) {
			expect(evidenceStatement(input)).not.toMatch(/\bverified\b(?<!unverified)/i);
		}
	});
});

describe('an answer from a run that read no document', () => {
	const NONE =
		'No documents were selected, so nothing in this answer was checked against a source. It is model-generated.';
	const none = run('harness.no-documents.completed');

	it('says no documents were selected, that nothing was checked against a source, and that it is model-generated', () => {
		// The recording: the run's own evidence is "unverified" and its snapshot lists no documents.
		expect(none.evidence).toBe('unverified');
		expect(none.planning.documents).toEqual([]);
		expect(none.packet).toBeNull();
		expect(evidenceStatement(none)).toBe(NONE);
		expect(NO_DOCUMENTS_STATEMENT).toBe(NONE);
		expect(evidenceState(none)).toBe('unverified');
		expect(evidenceHint(none)).toBeNull();
		expect(showsEvidence(none)).toBe(true);
	});

	it('is said of the runs recorded with no documents, and of no other recorded run', () => {
		const said = allRuns()
			.filter(({ run: value }) => evidenceStatement(value) === NONE)
			.map(({ label }) => label);
		// Only a completed run shows this line; these are the runs that selected no document and
		// have not read one. A run the orchestrator answered itself says its own sentence instead
		// (below), and `run.knowledge.completed`, whose searches found a file, says what matched.
		expect(said).toEqual([
			'run.harness.follow-up.planning',
			'run.harness.no-documents.awaiting-approval',
			'run.harness.no-documents.completed',
			'run.direct.planning',
			'run.plan-not-handed-over',
			'run.plan-has-placeholders',
			'run.knowledge.planning',
			'run.knowledge.awaiting-approval'
		]);
	});

	it('keeps the existing wording for every other case', () => {
		// A run that read documents and had its quotations checked.
		expect(evidenceStatement(run('harness.completed'))).toBe(
			'1 of 1 checked quotation matched the selected documents.'
		);
		// A run on the fixed packet: its snapshot lists the packet, and it is unverified as ever.
		for (const name of ['completed', 'awaiting-approval', 'refusals-and-partial'] as const) {
			expect(evidenceStatement(run(name)), name).toBe(UNVERIFIED);
		}
		// Runs recorded before the snapshot listed documents say nothing about them.
		for (const name of LEGACY_RUNS)
			expect(evidenceStatement(legacyRun(name)), name).toBe(UNVERIFIED);
		// An unverified run whose snapshot has no list, or has documents, or read a packet.
		const unverified = (
			planning: EvidenceInput['planning'],
			packet?: string | null
		): EvidenceInput => ({
			evidence: 'unverified',
			evidence_result: null,
			planning,
			packet
		});
		expect(evidenceStatement(unverified(undefined))).toBe(UNVERIFIED);
		expect(evidenceStatement(unverified(null))).toBe(UNVERIFIED);
		expect(evidenceStatement(unverified({}))).toBe(UNVERIFIED);
		expect(evidenceStatement(unverified({ documents: null }))).toBe(UNVERIFIED);
		expect(evidenceStatement(unverified({ documents: [{}] }))).toBe(UNVERIFIED);
		expect(evidenceStatement(unverified({ documents: [] }, 'a fixed document'))).toBe(UNVERIFIED);
		expect(evidenceStatement(unverified({ documents: [] }, ''))).toBe(NONE);
		expect(evidenceStatement(unverified({ documents: [] }, null))).toBe(NONE);
	});

	it('is said only of a run whose own evidence is "unverified"', () => {
		const empty = { documents: [] as unknown[] };
		// A profile that checks quotations with nothing to check them against is its own case.
		expect(
			evidenceStatement({ evidence: 'citations', evidence_result: null, planning: empty })
		).toBe(NOTHING_CHECKED);
		for (const evidence of [undefined, 'something_new', '<img src=x onerror=alert(1)>']) {
			expect(
				evidenceStatement({ evidence: evidence as never, evidence_result: null, planning: empty }),
				String(evidence)
			).toBe(UNVERIFIED);
		}
	});

	it('does not claim a check, a source or advice, and is a plain sentence', () => {
		expect(NONE).not.toMatch(
			/(?<!un)verified|\bcorrect|\baccurate|\breliable|\bsafe\b|advice|\bconfirmed\b/i
		);
		expect(NONE).toMatch(/^[A-Z0-9][^_<>]*\.$/);
	});

	it('is the first thing the closed answer line says, up to its first sentence', () => {
		const answer = runActivity(none).find((row) => row.kind === 'answer')!;
		expect(answer.summary).toBe(
			'No documents were selected, so nothing in this answer was checked against a source'
		);
	});
});

describe('the evidence line on the closed answer line', () => {
	const read = (result: Record<string, number> | null, evidence = 'citations') =>
		({
			evidence,
			evidence_result: result === null ? null : { gate_status: 'flagged', ...result },
			planning: { documents: [{ number: 1 }] },
			packet: null
		}) as unknown as Parameters<typeof evidenceLine>[0];

	it('is the count alone when every quotation was checked and matched', () => {
		expect(
			evidenceLine(read({ checked: 3, matched: 3, unmatched: 0, unresolved: 0, unmarked: 0 }))
		).toBe('3 of 3 checked quotations matched the selected documents');
	});

	it('keeps what was never checked, which the first sentence of the statement drops', () => {
		const input = read({ checked: 2, matched: 2, unmatched: 0, unresolved: 0, unmarked: 1 });
		expect(evidenceLine(input)).toBe(
			'2 of 2 checked quotations matched the selected documents, 1 more was not checked'
		);
		// The statement under the answer says the same thing at length.
		expect(evidenceStatement(input)).toContain(
			'1 quoted passage has no source marker and was not checked.'
		);
		expect(
			evidenceLine(read({ checked: 8, matched: 8, unmatched: 0, unresolved: 1, unmarked: 8 }))
		).toBe('8 of 8 checked quotations matched the selected documents, 9 more were not checked');
	});

	it('keeps what did not match, with what was not checked after it', () => {
		expect(
			evidenceLine(read({ checked: 2, matched: 1, unmatched: 1, unresolved: 0, unmarked: 0 }))
		).toBe('1 of 2 checked quotations matched the selected documents, 1 did not match');
		expect(
			evidenceLine(read({ checked: 3, matched: 1, unmatched: 2, unresolved: 0, unmarked: 2 }))
		).toBe(
			'1 of 3 checked quotations matched the selected documents, 2 did not match, 2 more were not checked'
		);
	});

	it('is the first sentence of the statement when nothing could be checked', () => {
		expect(evidenceLine(read(null))).toBe(
			'No quotation in this answer could be checked against the selected documents'
		);
		expect(
			evidenceLine({ ...read(null, 'unverified'), planning: { documents: [] } } as never)
		).toBe('No documents were selected, so nothing in this answer was checked against a source');
	});

	it('never says less than the statement: every figure in the statement is in the line', () => {
		for (const result of [
			{ checked: 5, matched: 5, unmatched: 0, unresolved: 0, unmarked: 0 },
			{ checked: 5, matched: 4, unmatched: 1, unresolved: 2, unmarked: 3 },
			{ checked: 1, matched: 1, unmatched: 0, unresolved: 4, unmarked: 0 }
		]) {
			const input = read(result);
			const line = evidenceLine(input);
			const unchecked = result.unresolved + result.unmarked;
			expect(line.includes('not checked')).toBe(unchecked > 0);
			expect(line.includes('did not match')).toBe(result.unmatched > 0);
			expect(evidenceStatement(input).includes('not checked')).toBe(unchecked > 0);
		}
	});
});

describe('what the checked quotations were matched against', () => {
	const found = run('knowledge.completed');
	const DOCUMENTS = [{ number: 1 }, { number: 2 }];
	const FILES = [{ number: 3, filename: 'travel-policy.txt' }];
	const read = (
		documents: unknown[] | undefined,
		sources: unknown[] | null | undefined,
		counts: Partial<EvidenceResult> = {}
	): EvidenceInput => ({
		evidence: 'citations',
		evidence_result: {
			gate_status: 'fiduciary_grade',
			checked: 2,
			matched: 2,
			unmatched: 0,
			...counts
		},
		planning: { documents },
		sources
	});

	it('is the selected documents when documents were selected and no file was found: as it always was', () => {
		for (const sources of [undefined, null, []]) {
			const input = read(DOCUMENTS, sources);
			expect(evidenceStatement(input), String(sources)).toBe(
				'2 of 2 checked quotations matched the selected documents.'
			);
			expect(evidenceLine(input), String(sources)).toBe(
				'2 of 2 checked quotations matched the selected documents'
			);
		}
		// A run recorded before its snapshot listed documents has no sources either.
		expect(evidenceStatement(read(undefined, undefined))).toBe(
			'2 of 2 checked quotations matched the selected documents.'
		);
	});

	it('is the knowledge-base files they name when files were found and no document was selected', () => {
		const input = read([], FILES);
		expect(evidenceStatement(input)).toBe(
			'2 of 2 checked quotations matched the knowledge-base files they name.'
		);
		expect(evidenceLine(input)).toBe(
			'2 of 2 checked quotations matched the knowledge-base files they name'
		);
	});

	it('is the selected documents and knowledge-base files they name when there were both', () => {
		const input = read(DOCUMENTS, FILES);
		expect(evidenceStatement(input)).toBe(
			'2 of 2 checked quotations matched the selected documents and knowledge-base files they name.'
		);
		expect(evidenceLine(input)).toBe(
			'2 of 2 checked quotations matched the selected documents and knowledge-base files they name'
		);
		// A snapshot that does not say what was selected is not taken to have selected none.
		expect(evidenceStatement(read(undefined, FILES))).toBe(
			'2 of 2 checked quotations matched the selected documents and knowledge-base files they name.'
		);
	});

	it('says so on the recorded run whose search found a file, in the statement and on the closed line', () => {
		expect(found.planning.documents).toEqual([]);
		expect(found.sources).toHaveLength(1);
		expect(evidenceStatement(found)).toBe(
			'1 of 1 checked quotation matched the knowledge-base files they name.'
		);
		expect(evidenceLine(found)).toBe(
			'1 of 1 checked quotation matched the knowledge-base files they name'
		);
		const answer = runActivity(found).find((row) => row.kind === 'answer')!;
		expect(answer.summary).toBe(
			'1 of 1 checked quotation matched the knowledge-base files they name'
		);
	});

	it('leaves the rest of the sentence as it was: what did not match, and what was not checked', () => {
		const counts = { checked: 3, matched: 1, unmatched: 2, unresolved: 1, unmarked: 2 };
		const input = read([], FILES, counts);
		expect(evidenceStatement(input)).toBe(
			'1 of 3 checked quotations matched the knowledge-base files they name. ' +
				'2 could not be matched and are marked unverified. ' +
				"1 quotation cites a source that is not one of this run's and was not checked. " +
				'2 quoted passages have no source marker and were not checked.'
		);
		expect(evidenceLine(input)).toBe(
			'1 of 3 checked quotations matched the knowledge-base files they name, 2 did not match, 3 more were not checked'
		);
	});

	it('changes no other sentence: a profile that checks nothing reads as before', () => {
		const none = { ...read([], FILES), evidence_result: null, evidence: 'unverified' as const };
		expect(evidenceStatement(none)).toBe(NO_DOCUMENTS_STATEMENT);
	});

	it('is the same for every recorded run that selected documents and found no file', () => {
		for (const { label, run: value } of allRuns()) {
			if ((value.sources ?? []).length > 0) continue;
			expect(evidenceStatement(value), label).not.toMatch(/knowledge-base files/);
			expect(evidenceLine(value), label).not.toMatch(/knowledge-base files/);
		}
	});

	it('names the knowledge-base files only where the run found some', () => {
		const said = allRuns()
			.filter(({ run: value }) => /knowledge-base files/.test(evidenceStatement(value)))
			.map(({ label }) => label);
		expect(said).toEqual(['run.knowledge.completed']);
	});

	it('never says more than the application did: no "verified", no "confirmed"', () => {
		for (const input of [read([], FILES), read(DOCUMENTS, FILES), found]) {
			expect(evidenceStatement(input)).not.toMatch(/(?<!un)verified|\bconfirmed\b/i);
		}
	});
});

describe('what no quotation could be checked against, and what a marker may cite', () => {
	const DOCUMENTS = [{ number: 1 }, { number: 2 }];
	const FILES = [{ number: 3, filename: 'travel-policy.txt' }];
	const none = (documents: unknown[] | undefined, sources: unknown[] | null | undefined) =>
		({
			evidence: 'citations',
			evidence_result: null,
			planning: { documents },
			sources
		}) as EvidenceInput;
	const cited = (
		documents: unknown[] | undefined,
		sources: unknown[] | null | undefined,
		n: number
	) =>
		({
			evidence: 'citations',
			evidence_result: {
				gate_status: 'flagged',
				checked: 4,
				matched: 4,
				unmatched: 0,
				unresolved: n
			},
			planning: { documents },
			sources
		}) as EvidenceInput;

	it('is the selected documents when documents were selected and no file was found: as it always was', () => {
		for (const sources of [undefined, null, []]) {
			expect(evidenceStatement(none(DOCUMENTS, sources)), String(sources)).toBe(NOTHING_CHECKED);
			expect(evidenceLine(none(DOCUMENTS, sources)), String(sources)).toBe(
				'No quotation in this answer could be checked against the selected documents'
			);
		}
	});

	it('is the knowledge-base files its searches found when files were found and no document was selected', () => {
		const input = none([], FILES);
		expect(evidenceState(input)).toBe('unchecked');
		expect(evidenceStatement(input)).toBe(
			'No quotation in this answer could be checked against the knowledge-base files its searches found. Treat it as unverified.'
		);
		expect(evidenceLine(input)).toBe(
			'No quotation in this answer could be checked against the knowledge-base files its searches found'
		);
	});

	it('is the selected documents and knowledge-base files when there were both', () => {
		const input = none(DOCUMENTS, FILES);
		expect(evidenceStatement(input)).toBe(
			'No quotation in this answer could be checked against the selected documents and knowledge-base files. Treat it as unverified.'
		);
		expect(evidenceLine(input)).toBe(
			'No quotation in this answer could be checked against the selected documents and knowledge-base files'
		);
		// A snapshot that does not say what was selected is not taken to have selected none.
		expect(evidenceStatement(none(undefined, FILES))).toBe(evidenceStatement(input));
	});

	it('cites "a document that is not in the selection" of a marker, as before, where no file was found', () => {
		for (const sources of [undefined, null, []]) {
			expect(evidenceStatement(cited(DOCUMENTS, sources, 1)), String(sources)).toContain(
				'1 quotation cites a document that is not in the selection and was not checked.'
			);
			expect(evidenceStatement(cited(DOCUMENTS, sources, 3)), String(sources)).toContain(
				'3 quotations cite a document that is not in the selection and were not checked.'
			);
		}
	});

	it('cites "a source that is not one of this run’s" of a marker, singular and plural, where its searches found files', () => {
		for (const documents of [[], DOCUMENTS]) {
			const one = evidenceStatement(cited(documents, FILES, 1));
			expect(one).toContain(
				"1 quotation cites a source that is not one of this run's and was not checked."
			);
			const many = evidenceStatement(cited(documents, FILES, 3));
			expect(many).toContain(
				"3 quotations cite a source that is not one of this run's and were not checked."
			);
			expect(one).not.toContain('not in the selection');
			expect(many).not.toContain('not in the selection');
		}
	});

	it('says "selected documents" of a run only where it had documents, in every sentence', () => {
		for (const { label, run: value } of allRuns()) {
			const hadNone =
				Array.isArray(value.planning.documents) && value.planning.documents.length === 0;
			if (!hadNone || (value.sources ?? []).length === 0) continue;
			// A run that selected no document and found files never speaks of "the selected documents" alone.
			expect(evidenceStatement(value), label).not.toMatch(/the selected documents(?! and)/);
			expect(evidenceLine(value), label).not.toMatch(/the selected documents(?! and)/);
		}
	});
});

describe('an answer the orchestrator gave by itself', () => {
	const answered = run('direct.completed');
	const quoted = (
		overrides: Partial<EvidenceResult> = {},
		patch: Partial<EvidenceInput> = {}
	): EvidenceInput => ({
		...answered,
		evidence: 'citations',
		evidence_result: {
			gate_status: 'fiduciary_grade',
			checked: 1,
			matched: 1,
			unmatched: 0,
			...overrides
		},
		planning: { documents: [{ number: 1 }] },
		...patch
	});

	it('says it was answered by the orchestrator alone, that it read and searched nothing, and that nothing was checked', () => {
		expect(answered.answered_directly).toBe(true);
		expect(answered.evidence).toBe('unverified');
		expect(answered.evidence_result ?? null).toBeNull();
		expect(evidenceStatement(answered)).toBe(
			'Answered by the orchestrator alone. It read no document and searched nothing for this answer. Model-generated; not checked.'
		);
		expect(DIRECT_ANSWER_STATEMENT).toBe(evidenceStatement(answered));
		expect(evidenceState(answered)).toBe('unverified');
		expect(evidenceHint(answered)).toBeNull();
		expect(evidenceGate(answered)).toBeNull();
		expect(showsEvidence(answered)).toBe(true);
	});

	it('takes the place of "no documents were selected", though the run listed none', () => {
		expect(answered.planning.documents).toEqual([]);
		expect(evidenceStatement(answered)).not.toBe(NO_DOCUMENTS_STATEMENT);
		expect(evidenceStatement(answered)).not.toContain('No documents were selected');
	});

	it('says the same where documents were selected but none of its quotations were checked', () => {
		const selected = { ...answered, planning: { documents: [{ number: 1 }, { number: 2 }] } };
		expect(evidenceStatement(selected)).toBe(DIRECT_ANSWER_STATEMENT);
		// Nor does a fixed packet change it.
		expect(evidenceStatement({ ...answered, packet: 'a fixed document' })).toBe(
			DIRECT_ANSWER_STATEMENT
		);
	});

	it('says the same where a profile that checks quotations found none to check', () => {
		for (const missing of [null, undefined]) {
			const input = quoted({}, { evidence_result: missing });
			expect(evidenceState(input)).toBe('unchecked');
			expect(evidenceStatement(input)).toBe(DIRECT_ANSWER_STATEMENT);
		}
	});

	it('reports the checks when its quotations were checked, and then that it did not read these documents', () => {
		expect(DIRECT_DID_NOT_READ).toBe('The orchestrator did not read these documents in this run.');
		const input = quoted();
		expect(evidenceState(input)).toBe('matched');
		expect(evidenceStatement(input)).toBe(
			'1 of 1 checked quotation matched the selected documents. The orchestrator did not read these documents in this run.'
		);
		expect(evidenceHint(input)).toBe(HINT);
		// Not "Model-generated; not checked": some of it was checked, and the counts say how much.
		expect(evidenceStatement(input)).not.toContain('not checked');
	});

	it('puts that after whatever did not match and whatever was not checked', () => {
		const input = quoted({ checked: 3, matched: 1, unmatched: 2, unresolved: 1, unmarked: 1 });
		expect(evidenceStatement(input)).toBe(
			'1 of 3 checked quotations matched the selected documents. ' +
				'2 could not be matched and are marked unverified. ' +
				'1 quotation cites a document that is not in the selection and was not checked. ' +
				'1 quoted passage has no source marker and was not checked. ' +
				'The orchestrator did not read these documents in this run.'
		);
		expect(evidenceState(input)).toBe('unmatched');
	});

	it('closes the one-clause line on the first sentence, and leaves the counts alone', () => {
		expect(evidenceLine(answered)).toBe('Answered by the orchestrator alone');
		expect(evidenceLine(quoted())).toBe('1 of 1 checked quotation matched the selected documents');
	});

	it('is said only of the run that was answered directly, and no other statement is changed by it', () => {
		const said = allRuns()
			.filter(({ run: value }) => evidenceStatement(value) === DIRECT_ANSWER_STATEMENT)
			.map(({ label }) => label);
		expect(said).toEqual(['run.direct.completed']);
		for (const { label, run: value } of allRuns()) {
			if (value.answered_directly) continue;
			expect(evidenceStatement(value), label).not.toContain(DIRECT_DID_NOT_READ);
		}
	});

	it('never calls the answer verified or confirmed, and is plain sentences', () => {
		for (const statement of [
			evidenceStatement(answered),
			evidenceStatement(quoted()),
			evidenceStatement(quoted({ checked: 3, matched: 1, unmatched: 2 }))
		]) {
			expect(statement).not.toMatch(/(?<!un)verified|\bconfirmed\b|\bcorrect|\baccurate|advice/i);
			expect(statement).toMatch(/^[A-Z0-9][^_<>]*\.$/);
		}
	});
});
