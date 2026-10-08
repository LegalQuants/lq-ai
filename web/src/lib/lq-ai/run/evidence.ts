/**
 * What the owner is told about how far to rely on a delivered answer.
 *
 * Never describes an answer as verified, correct or legal advice. A profile either
 * produces model-generated text that nothing has checked (`unverified`), or an
 * answer whose quotations are matched against the documents the owner selected
 * (`citations`, ADR 0038 D5) and whose result is reported here in counts. The
 * citation chips and ledger under the answer show each individual result.
 *
 * Only a quotation written with a source marker for a selected document, or for a
 * knowledge-base file one of the run's searches found, is checked. Quoted text with
 * no marker, and a marker that names neither, are counted and said so, so that "every
 * checked quotation matched" is not read as "every quotation matched".
 *
 * An answer the orchestrator gave by itself read nothing and searched nothing. It says
 * so in place of "unverified"; and where its quotations were checked all the same
 * (it repeated an earlier answer's, with the markers) the checks are reported and it
 * says, after them, that the orchestrator did not read those documents in this run.
 */
import type { OrchestrationChatRun } from '../api/orchestration';
import { pluralise } from './format';

export type EvidenceInput = Pick<OrchestrationChatRun, 'evidence' | 'evidence_result'> & {
	/** The planning snapshot. Its `documents` say what the run was allowed to read. */
	planning?: { documents?: readonly unknown[] | null } | null;
	/** The fixed document a packet profile reads, when it reads one. */
	packet?: string | null;
	/** True when the orchestrator answered by itself, having read and searched nothing. */
	answered_directly?: boolean;
	/** The knowledge-base files the run's searches found. Their numbers follow the selected documents'. */
	sources?: readonly unknown[] | null;
};

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
	const reported = Number.isFinite(result.unmatched)
		? Math.max(0, Math.floor(result.unmatched))
		: 0;
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

/**
 * What was quoted but never checked, as sentences; empty when there is nothing to say. A marker that
 * names none of a run's sources cites "a document that is not in the selection" where the run has
 * only the documents it was given, and "a source that is not one of this run's" where its searches
 * found files too, since the marker may then be one of either kind.
 */
function uncheckedSentences(found: Counts, hasSources: boolean): string {
	const parts: string[] = [];
	if (found.unresolved > 0) {
		const cites = hasSources
			? "a source that is not one of this run's"
			: 'a document that is not in the selection';
		parts.push(
			found.unresolved === 1
				? `1 quotation cites ${cites} and was not checked.`
				: `${found.unresolved} quotations cite ${cites} and were not checked.`
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

/** Said under the answer of a run that read no document, so nothing could be checked. */
export const NO_DOCUMENTS_STATEMENT =
	'No documents were selected, so nothing in this answer was checked against a source. It is model-generated.';

/** Said under an answer the orchestrator gave by itself, when none of its quotations were checked. */
export const DIRECT_ANSWER_STATEMENT =
	'Answered by the orchestrator alone. It read no document and searched nothing for this answer. Model-generated; not checked.';

/** Said after the counts for an answer the orchestrator gave by itself, whose quotations were checked. */
export const DIRECT_DID_NOT_READ = 'The orchestrator did not read these documents in this run.';

function directly(input: EvidenceInput): boolean {
	return input.answered_directly === true;
}

/**
 * What a run's quotations can be checked against: the documents the owner selected, the
 * knowledge-base files its searches found, or both. A run whose snapshot lists no documents but
 * found files has only the files; a run that found none is as it always was. Every sentence below
 * that names the target takes it from here, so that none of them says "selected documents" of a
 * run that had no document selected.
 */
type Targets = 'documents' | 'files' | 'both';

function targets(input: EvidenceInput): Targets {
	const listed = input.planning?.documents;
	const noDocuments = Array.isArray(listed) && listed.length === 0;
	const found = Array.isArray(input.sources) && input.sources.length > 0;
	if (!found) return 'documents';
	return noDocuments ? 'files' : 'both';
}

/** What the checked quotations were matched against, in the words that end the line. */
function matchedAgainst(input: EvidenceInput): string {
	switch (targets(input)) {
		case 'files':
			return 'the knowledge-base files they name';
		case 'both':
			return 'the selected documents and knowledge-base files they name';
		default:
			return 'the selected documents';
	}
}

/** What no quotation could be checked against. */
function checkedAgainst(input: EvidenceInput): string {
	switch (targets(input)) {
		case 'files':
			return 'the knowledge-base files its searches found';
		case 'both':
			return 'the selected documents and knowledge-base files';
		default:
			return 'the selected documents';
	}
}

/**
 * Whether a run read no document at all. That is said only when the record says it: the
 * run's own evidence is `unverified`, its planning snapshot lists documents and the list
 * is empty, and no fixed packet was read. A snapshot recorded before documents were
 * listed carries no list, and says nothing about it.
 */
function readNoDocuments(input: EvidenceInput): boolean {
	if (input.evidence !== 'unverified') return false;
	const listed = input.planning?.documents;
	return Array.isArray(listed) && listed.length === 0 && !input.packet;
}

/** The evidence line, in plain words. */
export function evidenceStatement(input: EvidenceInput): string {
	switch (evidenceState(input)) {
		case 'unverified':
			if (directly(input)) return DIRECT_ANSWER_STATEMENT;
			return readNoDocuments(input) ? NO_DOCUMENTS_STATEMENT : 'Model-generated; unverified.';
		case 'unchecked':
			// A reply to nothing it read has no quotation to be checked: it says what it is.
			if (directly(input)) return DIRECT_ANSWER_STATEMENT;
			return `No quotation in this answer could be checked against ${checkedAgainst(input)}. Treat it as unverified.`;
		default: {
			const found = counts(input);
			if (!found) return 'Model-generated; unverified.';
			const matched = `${found.matched} of ${pluralise(found.checked, 'checked quotation')} matched ${matchedAgainst(input)}.`;
			const rest = uncheckedSentences(found, targets(input) !== 'documents');
			const caveat = directly(input) ? ` ${DIRECT_DID_NOT_READ}` : '';
			if (found.unmatched <= 0) return `${matched}${rest}${caveat}`;
			const verb = found.unmatched === 1 ? 'is' : 'are';
			return `${matched} ${found.unmatched} could not be matched and ${verb} marked unverified.${rest}${caveat}`;
		}
	}
}

/**
 * The evidence line for a closed line of the run column: one clause, and never less than
 * the statement under the answer says. What did not match and what was never checked are
 * in it, so that "2 of 2 checked quotations matched" is not read alone when a third
 * quotation was not checked at all.
 */
export function evidenceLine(input: EvidenceInput): string {
	const state = evidenceState(input);
	const found = state === 'unverified' || state === 'unchecked' ? null : counts(input);
	if (!found) {
		const statement = evidenceStatement(input);
		const end = statement.indexOf('. ');
		return (end === -1 ? statement : statement.slice(0, end)).replace(/\.$/, '');
	}
	const parts = [
		`${found.matched} of ${pluralise(found.checked, 'checked quotation')} matched ${matchedAgainst(input)}`
	];
	if (found.unmatched > 0) parts.push(`${found.unmatched} did not match`);
	const unchecked = found.unresolved + found.unmarked;
	if (unchecked > 0) {
		parts.push(`${unchecked} more ${unchecked === 1 ? 'was' : 'were'} not checked`);
	}
	return parts.join(', ');
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
