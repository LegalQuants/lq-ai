import { describe, expect, it } from 'vitest';
import { citationPassage } from '../components/tabular-citation';
import type { TabularCitation } from '../types';

function citation(overrides: Partial<TabularCitation> = {}): TabularCitation {
	return {
		citation_id: 'citation',
		document_id: 'document',
		confidence: 'high',
		source_text: 'Term: five years.',
		source_offset_start: 6,
		source_offset_end: 16,
		...overrides
	};
}

describe('citation passage highlighting', () => {
	it('preserves the surrounding passage and locates only the cited span', () => {
		expect(citationPassage(citation())).toEqual({
			before: 'Term: ',
			match: 'five years',
			after: '.'
		});
	});
	it('uses backend Unicode offsets when an emoji precedes the quote', () => {
		expect(
			citationPassage(
				citation({ source_text: '📄 five years.', source_offset_start: 2, source_offset_end: 12 })
			)
		).toEqual({ before: '📄 ', match: 'five years', after: '.' });
	});
	it.each([
		{ source_text: null },
		{ source_offset_start: null },
		{ source_offset_end: undefined },
		{ source_offset_start: -1 },
		{ source_offset_end: 6 },
		{ source_offset_end: 99 },
		{ source_offset_start: 0.5 }
	])('does not invent a highlight for unavailable or invalid locations: %j', (overrides) => {
		expect(citationPassage(citation(overrides))).toBeNull();
	});
	it('treats source markup as plain text for Svelte to escape', () => {
		expect(
			citationPassage(
				citation({
					source_text: '<script>x</script>',
					source_offset_start: 0,
					source_offset_end: 18
				})
			)?.match
		).toBe('<script>x</script>');
	});
});
