/**
 * Unit tests for the M2Citations.svelte chip-builder helpers.
 *
 * The Svelte template is glue (per the project's pure-helper testing
 * convention); the chip-building logic is the testable surface. Full
 * DOM-level rendering of the five visual states is covered by the
 * Playwright visual-regression suite (M2-C2 Decision D).
 */
import { describe, expect, it } from 'vitest';
import { buildCitationChips, previewQuote } from '../components/M2Citations.svelte';
import type { Citation } from '../types';

function makeCitation(overrides: Partial<Citation> = {}): Citation {
	return {
		id: 'cite-1',
		source_file_id: 'file-1',
		source_offset_start: 0,
		source_offset_end: 10,
		source_text: '',
		verified: true,
		...overrides
	};
}

describe('previewQuote', () => {
	it('returns short quotes unchanged', () => {
		expect(previewQuote('short')).toBe('short');
	});

	it('trims leading/trailing whitespace', () => {
		expect(previewQuote('  trimmed  ')).toBe('trimmed');
	});

	it('truncates long quotes with an ellipsis at the configured max', () => {
		const long = 'a'.repeat(80);
		const preview = previewQuote(long, 20);
		expect(preview.length).toBeLessThanOrEqual(20);
		expect(preview.endsWith('…')).toBe(true);
	});
});

describe('buildCitationChips', () => {
	it('produces an empty list when the content has no markers', () => {
		expect(buildCitationChips('No citations here.', [])).toEqual([]);
	});

	it('produces one chip per marker', () => {
		const content = '"alpha" (Source: [1]) and "beta" (Source: [2]).';
		const chips = buildCitationChips(content, [
			makeCitation({ id: 'cite-1', source_text: 'alpha', verification_method: 'exact_match' }),
			makeCitation({ id: 'cite-2', source_text: 'beta', verification_method: 'tolerant_match' })
		]);
		expect(chips).toHaveLength(2);
		expect(chips[0].state).toBe('verified-exact');
		expect(chips[0].quote).toBe('alpha');
		expect(chips[0].citationId).toBe('cite-1');
		expect(chips[1].state).toBe('verified-tolerant');
		expect(chips[1].quote).toBe('beta');
		expect(chips[1].citationId).toBe('cite-2');
	});

	it('emits an unverified chip when a marker has no matching row', () => {
		const content = '"alpha" (Source: [1]) and "unmatched" (Source: [2]).';
		const chips = buildCitationChips(content, [
			makeCitation({ id: 'cite-1', source_text: 'alpha', verification_method: 'exact_match' })
		]);
		expect(chips).toHaveLength(2);
		expect(chips[0].state).toBe('verified-exact');
		expect(chips[1].state).toBe('unverified');
		expect(chips[1].citationId).toBeNull();
	});

	it('uses paraphrase_judge yellow regardless of partial flag (Decision G)', () => {
		const content = '"strict" (Source: [1]) and "partial" (Source: [2]).';
		const chips = buildCitationChips(content, [
			makeCitation({
				id: 'cite-1',
				source_text: 'strict',
				verification_method: 'paraphrase_judge',
				partial: false
			}),
			makeCitation({
				id: 'cite-2',
				source_text: 'partial',
				verification_method: 'paraphrase_judge',
				partial: true
			})
		]);
		expect(chips[0].state).toBe('verified-paraphrase');
		expect(chips[1].state).toBe('verified-paraphrase');
	});

	it('reflects partial=true in the tooltip wording', () => {
		const content = '"partial" (Source: [1]).';
		const chips = buildCitationChips(content, [
			makeCitation({
				id: 'cite-1',
				source_text: 'partial',
				verification_method: 'paraphrase_judge',
				partial: true,
				verification_confidence: 0.7
			})
		]);
		expect(chips[0].tooltip).toContain('partially');
	});

	it('preserves marker order even when citation rows are interleaved differently', () => {
		const content = '"first" (Source: [1]) and "second" (Source: [2]).';
		const chips = buildCitationChips(content, [
			makeCitation({
				id: 'cite-2',
				source_text: 'second',
				verification_method: 'exact_match'
			}),
			makeCitation({
				id: 'cite-1',
				source_text: 'first',
				verification_method: 'paraphrase_judge'
			})
		]);
		expect(chips.map((c) => c.quote)).toEqual(['first', 'second']);
	});

	it('truncates long quote previews for chip display', () => {
		const longQuote = 'this is a very long quote that goes well beyond the chip preview limit';
		const content = `"${longQuote}" (Source: [1]).`;
		const chips = buildCitationChips(content, [
			makeCitation({
				id: 'cite-1',
				source_text: longQuote,
				verification_method: 'exact_match'
			})
		]);
		expect(chips[0].quotePreview.length).toBeLessThan(longQuote.length);
		expect(chips[0].quotePreview.endsWith('…')).toBe(true);
		expect(chips[0].quote).toBe(longQuote);
	});

	it('renders all 4 currently-emitted states in one pass', () => {
		const content =
			'"exact" (Source: [1]) "tolerant" (Source: [2]) "judge" (Source: [3]) "missing" (Source: [4]).';
		const chips = buildCitationChips(content, [
			makeCitation({
				id: 'c1',
				source_text: 'exact',
				verification_method: 'exact_match'
			}),
			makeCitation({
				id: 'c2',
				source_text: 'tolerant',
				verification_method: 'tolerant_match'
			}),
			makeCitation({
				id: 'c3',
				source_text: 'judge',
				verification_method: 'paraphrase_judge'
			})
		]);
		expect(chips.map((c) => c.state)).toEqual([
			'verified-exact',
			'verified-tolerant',
			'verified-paraphrase',
			'unverified'
		]);
	});

	it('assigns stable keys for verified chips and unique synthetic keys for unverified ones', () => {
		const content = '"unmatched" (Source: [1]) and "unmatched" (Source: [2]).';
		const chips = buildCitationChips(content, []);
		expect(chips).toHaveLength(2);
		// Both unverified — keys must be distinct so Svelte's keyed-each
		// doesn't collapse them on render.
		expect(new Set(chips.map((c) => c.key)).size).toBe(2);
	});
});
