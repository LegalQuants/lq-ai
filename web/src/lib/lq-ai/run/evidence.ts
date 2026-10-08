/**
 * What the owner is told about how far to rely on a delivered answer.
 *
 * Never describes an answer as verified, correct or legal advice. A profile either
 * produces model-generated text that nothing has checked (`unverified`), or an
 * answer whose quotations are matched against the documents the owner selected
 * (`citations`, ADR 0038 D5) and whose result is reported here in counts. The
 * citation chips and ledger under the answer show each individual result.
 *
 * Only a quotation written with a source marker for a selected document is
 * checked. Quoted text with no marker, and a marker that names no selected
 * document, are counted and said so, so that "every checked quotation matched"
 * is not read as "every quotation matched".
 */
import type { OrchestrationChatRun } from '../api/orchestration';
import { pluralise } from './format';

export type EvidenceInput = Pick<OrchestrationChatRun, 'evidence' | 'evidence_result'>;

/** For styling and scripts: how the answer's quotations fared. */
export type EvidenceState =
	/** The profile does not check quotations. */
	| 'unverified'
	/** The profile checks quotations, but none could be checked in this answer. */
	| 'unchecked'
	/** Every checked quotation matched, and no quoted text went unchecked. */
	| 'matched'
	/** Every checked quotation matched, but some quoted text was not checked. */
	| 'incomplete'
	/** At least one checked quotation could not be matched. */
	| 'unmatched';

/** Only a run whose answer was delivered has an evidence line. */
export function showsEvidence(run: Pick<OrchestrationChatRun, 'status'>): boolean {
	return run.status === 'completed';
}

interface Counts {
	checked: number;
	matched: number;
	unmatched: number;
	/** Markers that name no selected document, or past the checking cap. */
	unresolved: number;
	/** Quoted passages with no source marker. */
	unmarked: number;
}

/** A count from the server as a whole number of zero or more. */
function whole(value: unknown): number {
	return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
}

function counts(input: EvidenceInput): Counts | null {
	const result = input.evidence_result;
	if (!result || !Number.isFinite(result.checked) || result.checked <= 0) return null;
	const checked = Math.floor(result.checked);
	const matched = Math.min(checked, Math.max(0, Math.floor(Number(result.matched) || 0)));
	// A checked quotation that is not reported as matched is unmatched, whatever
	// the reported figure says: a count that does not add up must not read as clean.
	const reported = Number.isFinite(result.unmatched) ? Math.max(0, Math.floor(result.unmatched)) : 0;
	const unmatched = Math.max(reported, checked - matched);
	return {
		checked,
		matched,
		unmatched,
		unresolved: whole(result.unresolved),
		unmarked: whole(result.unmarked)
	};
}

export function evidenceState(input: EvidenceInput): EvidenceState {
	if (input.evidence !== 'citations') return 'unverified';
	const found = counts(input);
	if (!found) return 'unchecked';
	if (found.unmatched > 0) return 'unmatched';
	return found.unresolved > 0 || found.unmarked > 0 ? 'incomplete' : 'matched';
}

/** What was quoted but never checked, as sentences; empty when there is nothing to say. */
function uncheckedSentences(found: Counts): string {
	const parts: string[] = [];
	if (found.unresolved > 0) {
		parts.push(
			found.unresolved === 1
				? '1 quotation cites a document that is not in the selection and was not checked.'
				: `${found.unresolved} quotations cite a document that is not in the selection and were not checked.`
		);
	}
	if (found.unmarked > 0) {
		parts.push(
			found.unmarked === 1
				? '1 quoted passage has no source marker and was not checked.'
				: `${found.unmarked} quoted passages have no source marker and were not checked.`
		);
	}
	return parts.length > 0 ? ` ${parts.join(' ')}` : '';
}

/** The evidence line, in plain words. */
export function evidenceStatement(input: EvidenceInput): string {
	switch (evidenceState(input)) {
		case 'unverified':
			return 'Model-generated; unverified.';
		case 'unchecked':
			return 'No quotation in this answer could be checked against the selected documents. Treat it as unverified.';
		default: {
			const found = counts(input);
			if (!found) return 'Model-generated; unverified.';
			const matched = `${found.matched} of ${pluralise(found.checked, 'checked quotation')} matched the selected documents.`;
			const rest = uncheckedSentences(found);
			if (found.unmatched <= 0) return `${matched}${rest}`;
			const verb = found.unmatched === 1 ? 'is' : 'are';
			return `${matched} ${found.unmatched} could not be matched and ${verb} marked unverified.${rest}`;
		}
	}
}

/** Where to see each quotation's result, or null when there is nothing to open. */
export function evidenceHint(input: EvidenceInput): string | null {
	const state = evidenceState(input);
	return state === 'matched' || state === 'unmatched' || state === 'incomplete'
		? 'Open the citation chips and the ledger under the answer to see each result.'
		: null;
}

/** The ledger gate behind the counts (`fiduciary_grade`, `supported_only`, `flagged`), if reported. */
export function evidenceGate(input: EvidenceInput): string | null {
	return input.evidence_result?.gate_status ?? null;
}
