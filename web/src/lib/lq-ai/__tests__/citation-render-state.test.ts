/**
 * Unit tests for the M2-C2 citation render-state helpers.
 *
 * Mirrors the ProvenancePill / RefusalMessageBubble pattern: pure
 * helpers exported from a module, exercised here in vitest. DOM
 * rendering of the resulting visual states is covered separately
 * via Playwright (M2-C2 Decision D).
 */
import { describe, expect, it } from 'vitest';
import {
	CITATION_REGEX,
	citationRenderState,
	citationTooltip,
	iterCitationMarkers,
	matchMarkerState
} from '../citations/state';
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

describe('citationRenderState', () => {
	it('exact_match → verified-exact', () => {
		expect(
			citationRenderState(makeCitation({ verification_method: 'exact_match' }))
		).toBe('verified-exact');
	});

	it('tolerant_match → verified-tolerant', () => {
		expect(
			citationRenderState(makeCitation({ verification_method: 'tolerant_match' }))
		).toBe('verified-tolerant');
	});

	it('paraphrase_judge maps to verified-paraphrase regardless of partial flag (Decision G)', () => {
		expect(
			citationRenderState(
				makeCitation({ verification_method: 'paraphrase_judge', partial: false })
			)
		).toBe('verified-paraphrase');
		expect(
			citationRenderState(
				makeCitation({ verification_method: 'paraphrase_judge', partial: true })
			)
		).toBe('verified-paraphrase');
	});

	it('llm_judge → verified-paraphrase (semantic verification, same color)', () => {
		expect(
			citationRenderState(makeCitation({ verification_method: 'llm_judge' }))
		).toBe('verified-paraphrase');
	});

	it('ensemble_strict → verified-paraphrase (yellow, per M2-D1 Decision F)', () => {
		expect(
			citationRenderState(makeCitation({ verification_method: 'ensemble_strict' }))
		).toBe('verified-paraphrase');
	});

	it('ensemble_majority → verified-paraphrase regardless of partial flag', () => {
		expect(
			citationRenderState(
				makeCitation({ verification_method: 'ensemble_majority', partial: false })
			)
		).toBe('verified-paraphrase');
		expect(
			citationRenderState(
				makeCitation({ verification_method: 'ensemble_majority', partial: true })
			)
		).toBe('verified-paraphrase');
	});

	it('failed → unverified', () => {
		expect(
			citationRenderState(makeCitation({ verification_method: 'failed', verified: false }))
		).toBe('unverified');
	});

	it('null/absent method on a verified row → verified-tolerant (legacy-safe)', () => {
		expect(
			citationRenderState(makeCitation({ verification_method: null }))
		).toBe('verified-tolerant');
		expect(citationRenderState(makeCitation())).toBe('verified-tolerant');
	});

	it('verified=false → unverified regardless of method', () => {
		expect(
			citationRenderState(
				makeCitation({ verified: false, verification_method: 'exact_match' })
			)
		).toBe('unverified');
	});

	it('null citation → unverified', () => {
		expect(citationRenderState(null)).toBe('unverified');
	});

	it('unknown future method → degrades to verified-tolerant', () => {
		expect(
			citationRenderState(
				makeCitation({
					// Cast to bypass the union check — modeling an api that adds
					// a method we haven't seen yet.
					verification_method: 'multi_stage_super' as unknown as 'exact_match'
				})
			)
		).toBe('verified-tolerant');
	});
});

describe('CITATION_REGEX + iterCitationMarkers', () => {
	it('matches a straight-quote citation', () => {
		const text = 'The agreement says "no compete" (Source: [1]).';
		const markers = Array.from(iterCitationMarkers(text));
		expect(markers).toHaveLength(1);
		expect(markers[0].quote).toBe('no compete');
		expect(markers[0].sourceIndex).toBe(1);
		expect(text.slice(markers[0].quoteStart, markers[0].quoteEnd)).toBe('no compete');
	});

	it('matches a curly-quote citation', () => {
		const text = 'The agreement says “no compete” (Source: [2]).';
		const markers = Array.from(iterCitationMarkers(text));
		expect(markers).toHaveLength(1);
		expect(markers[0].quote).toBe('no compete');
		expect(markers[0].sourceIndex).toBe(2);
	});

	it('matches multiple citations in one message', () => {
		const text =
			'First "alpha" (Source: [1]) and second "beta" (Source: [2]) and third "gamma" (Source: [3]).';
		const markers = Array.from(iterCitationMarkers(text));
		expect(markers.map((m) => m.quote)).toEqual(['alpha', 'beta', 'gamma']);
		expect(markers.map((m) => m.sourceIndex)).toEqual([1, 2, 3]);
	});

	it('mixes straight and curly quotes in one message', () => {
		const text = 'A "first" (Source: [1]) and B “second” (Source: [2]).';
		const markers = Array.from(iterCitationMarkers(text));
		expect(markers).toHaveLength(2);
		expect(markers[0].quote).toBe('first');
		expect(markers[1].quote).toBe('second');
	});

	it('returns no markers for prose without citations', () => {
		expect(Array.from(iterCitationMarkers('Just prose with no markers.'))).toHaveLength(0);
	});

	it('does not match a bare quote without (Source: [N])', () => {
		expect(Array.from(iterCitationMarkers('Just "a quote" alone.'))).toHaveLength(0);
	});

	it('does not match Source marker without quoted prelude', () => {
		expect(
			Array.from(iterCitationMarkers('A bare reference (Source: [1]) without a quote.'))
		).toHaveLength(0);
	});

	it('handles quote bodies that span line breaks (dotAll)', () => {
		const text = 'See "first\nsecond" (Source: [1]).';
		const markers = Array.from(iterCitationMarkers(text));
		expect(markers).toHaveLength(1);
		expect(markers[0].quote).toBe('first\nsecond');
	});

	it('uses lazy matching so two citations on the same line stay distinct', () => {
		// Without lazy, the body would greedily span both quotes.
		const text = '"one" (Source: [1]) and "two" (Source: [2])';
		const markers = Array.from(iterCitationMarkers(text));
		expect(markers.map((m) => m.quote)).toEqual(['one', 'two']);
	});

	it('quoteStart + quoteEnd select exactly the quoted body in the source', () => {
		const text = 'Prefix "the body" (Source: [1]) suffix';
		const [marker] = Array.from(iterCitationMarkers(text));
		expect(text.slice(marker.quoteStart, marker.quoteEnd)).toBe('the body');
	});

	it('CITATION_REGEX is exported with the g + s flags (matchAll-safe)', () => {
		expect(CITATION_REGEX.flags).toContain('g');
		expect(CITATION_REGEX.flags).toContain('s');
	});
});

describe('matchMarkerState', () => {
	it('matches a marker to a citation row by source_text', () => {
		const citations = [
			makeCitation({
				id: 'cite-1',
				source_text: 'no compete',
				verification_method: 'exact_match'
			})
		];
		const [marker] = Array.from(
			iterCitationMarkers('The agreement says "no compete" (Source: [1]).')
		);
		const { state, citation } = matchMarkerState(marker, citations);
		expect(state).toBe('verified-exact');
		expect(citation?.id).toBe('cite-1');
	});

	it('a marker with no matching row → unverified (per api absence-of-row contract)', () => {
		const citations = [
			makeCitation({
				id: 'cite-1',
				source_text: 'something else',
				verification_method: 'exact_match'
			})
		];
		const [marker] = Array.from(
			iterCitationMarkers('"unverifiable" (Source: [1]).')
		);
		const { state, citation } = matchMarkerState(marker, citations);
		expect(state).toBe('unverified');
		expect(citation).toBeNull();
	});

	it('handles an empty citations array → all unverified', () => {
		const [marker] = Array.from(iterCitationMarkers('"any" (Source: [1]).'));
		const { state, citation } = matchMarkerState(marker, []);
		expect(state).toBe('unverified');
		expect(citation).toBeNull();
	});
});

describe('citationTooltip', () => {
	it('verified-exact tooltip is verbatim copy', () => {
		expect(citationTooltip('verified-exact', makeCitation())).toBe(
			'Verified verbatim against source.'
		);
	});

	it('verified-tolerant tooltip mentions formatting differences', () => {
		expect(citationTooltip('verified-tolerant', makeCitation())).toContain(
			'minor formatting differences'
		);
	});

	it('verified-paraphrase tooltip includes confidence label', () => {
		expect(
			citationTooltip(
				'verified-paraphrase',
				makeCitation({ verification_method: 'paraphrase_judge', verification_confidence: 0.9 })
			)
		).toContain('high confidence');
		expect(
			citationTooltip(
				'verified-paraphrase',
				makeCitation({ verification_method: 'paraphrase_judge', verification_confidence: 0.7 })
			)
		).toContain('medium confidence');
		expect(
			citationTooltip(
				'verified-paraphrase',
				makeCitation({ verification_method: 'paraphrase_judge', verification_confidence: 0.5 })
			)
		).toContain('low confidence');
	});

	it('partial=true alters the verified-paraphrase tooltip to flag partial support', () => {
		const tooltip = citationTooltip(
			'verified-paraphrase',
			makeCitation({ partial: true, verification_confidence: 0.7 })
		);
		expect(tooltip).toContain('partially');
	});

	it('unverified tooltip is verbatim and matches the plan copy', () => {
		const tooltip = citationTooltip('unverified', null);
		expect(tooltip).toContain('Could not verify');
		expect(tooltip).toContain("doesn't follow from the cited content");
	});

	it('ensemble_strict tooltip mentions all judges agreed (M2-D1)', () => {
		const tooltip = citationTooltip(
			'verified-paraphrase',
			makeCitation({
				verification_method: 'ensemble_strict',
				verification_confidence: 0.9
			})
		);
		expect(tooltip).toContain('ensemble');
		expect(tooltip).toContain('all judges agreed');
	});

	it('ensemble_strict tooltip with partial=true flags partial source support', () => {
		const tooltip = citationTooltip(
			'verified-paraphrase',
			makeCitation({
				verification_method: 'ensemble_strict',
				verification_confidence: 0.9,
				partial: true
			})
		);
		expect(tooltip).toContain('all judges agreed');
		expect(tooltip).toContain('partially supports');
	});

	it('ensemble_majority tooltip mentions majority of judges (M2-D1)', () => {
		const tooltip = citationTooltip(
			'verified-paraphrase',
			makeCitation({
				verification_method: 'ensemble_majority',
				verification_confidence: 0.8
			})
		);
		expect(tooltip).toContain('majority of judges verified');
	});

	it('ensemble_majority tooltip with partial=true flags disagreement', () => {
		const tooltip = citationTooltip(
			'verified-paraphrase',
			makeCitation({
				verification_method: 'ensemble_majority',
				verification_confidence: 0.8,
				partial: true
			})
		);
		expect(tooltip).toContain('majority of judges verified');
		expect(tooltip).toContain('some disagreed');
	});
});
