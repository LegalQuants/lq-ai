/**
 * Pure formatting for the WS-G citation-graph treatment signal (PR1-UI).
 *
 * Graph-only provenance ("cited by N later opinions; here are the most recent
 * few") — NOT an editorial validity verdict (ADR 0019 D1). Treatment
 * classification + any severity coloring arrive with WS-G PR2.
 */
import type { LedgerCitingRef, LedgerTreatment } from '../types';

export const PREVIEW_N = 5;

export interface TreatmentSummary {
	label: string;
	asOf: string;
	preview: LedgerCitingRef[];
	moreCount: number;
	capped: boolean;
	total: number;
	shown: number;
}

export function treatmentSummary(t: LedgerTreatment): TreatmentSummary {
	const citing = Array.isArray(t.citing) ? t.citing : [];
	const shown = citing.length;
	const total =
		typeof t.cited_by_count === 'number' && !Number.isNaN(t.cited_by_count)
			? t.cited_by_count
			: shown;
	const preview = citing.slice(0, PREVIEW_N);
	return {
		label: `Cited by ${total} later opinion${total === 1 ? '' : 's'}`,
		asOf: formatAsOf(t.as_of),
		preview,
		moreCount: shown - preview.length,
		capped: total > shown,
		total,
		shown
	};
}

function formatAsOf(as_of: string): string {
	// Stable, locale-independent date portion of the ISO timestamp.
	if (typeof as_of === 'string' && /^\d{4}-\d{2}-\d{2}/.test(as_of)) return as_of.slice(0, 10);
	return as_of ?? '';
}

export function formatCitingRef(ref: LedgerCitingRef): string {
	return [ref.case_name, ref.court, ref.date_filed].filter((p) => p != null && p !== '').join(', ');
}
