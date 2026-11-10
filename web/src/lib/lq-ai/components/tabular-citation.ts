import type { TabularCitation } from '../types';

/** Backend offsets count Unicode code points, rather than UTF-16 code units. */
export function citationPassage(citation: TabularCitation) {
	const text = citation.source_text;
	const start = citation.source_offset_start;
	const end = citation.source_offset_end;
	if (!text || typeof start !== 'number' || typeof end !== 'number') return null;
	const characters = Array.from(text);
	if (
		!Number.isInteger(start) ||
		!Number.isInteger(end) ||
		start < 0 ||
		end <= start ||
		end > characters.length
	)
		return null;
	return {
		before: characters.slice(0, start).join(''),
		match: characters.slice(start, end).join(''),
		after: characters.slice(end).join('')
	};
}
