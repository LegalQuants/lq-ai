import { describe, it, expect } from 'vitest';

import {
	severityClass,
	outcomeClass,
	severityLabel,
	outcomeLabel,
	filterPositions
} from '../page-helpers';
import type { PlaybookPositionResult } from '$lib/lq-ai/types';

describe('severityClass', () => {
	it('maps each severity to a unique class', () => {
		expect(severityClass('critical')).toBe('lq-severity--critical');
		expect(severityClass('high')).toBe('lq-severity--high');
		expect(severityClass('medium')).toBe('lq-severity--medium');
		expect(severityClass('low')).toBe('lq-severity--low');
	});
});

describe('outcomeClass', () => {
	it('maps each verdict to a unique class', () => {
		expect(outcomeClass('matches_standard')).toBe('lq-outcome--matches-standard');
		expect(outcomeClass('matches_fallback')).toBe('lq-outcome--matches-fallback');
		expect(outcomeClass('deviates')).toBe('lq-outcome--deviates');
		expect(outcomeClass('missing')).toBe('lq-outcome--missing');
	});
});

describe('severityLabel + outcomeLabel', () => {
	it('returns short human-readable labels', () => {
		expect(severityLabel('critical')).toBe('Critical');
		expect(severityLabel('high')).toBe('High');
		expect(outcomeLabel('matches_standard')).toBe('Matches standard');
		expect(outcomeLabel('matches_fallback')).toBe('Matches fallback');
		expect(outcomeLabel('deviates')).toBe('Deviates');
		expect(outcomeLabel('missing')).toBe('Missing');
	});
});

describe('filterPositions', () => {
	const positions: PlaybookPositionResult[] = [
		{
			position_id: '1',
			issue: 'A',
			severity_if_missing: 'critical',
			verdict: 'deviates',
			confidence: 0.9,
			matched_fallback_rank: null,
			cited_chunk_ids: [],
			matched_text: '',
			redline: null,
			justification: ''
		},
		{
			position_id: '2',
			issue: 'B',
			severity_if_missing: 'low',
			verdict: 'matches_standard',
			confidence: 0.9,
			matched_fallback_rank: null,
			cited_chunk_ids: [],
			matched_text: '',
			redline: null,
			justification: ''
		},
		{
			position_id: '3',
			issue: 'C',
			severity_if_missing: 'high',
			verdict: 'missing',
			confidence: 0.7,
			matched_fallback_rank: null,
			cited_chunk_ids: [],
			matched_text: '',
			redline: null,
			justification: ''
		}
	];

	it('returns all when filters are "all"', () => {
		expect(filterPositions(positions, 'all', 'all')).toHaveLength(3);
	});

	it('filters by severity', () => {
		const out = filterPositions(positions, 'critical', 'all');
		expect(out.map((p) => p.position_id)).toEqual(['1']);
	});

	it('filters by outcome', () => {
		const out = filterPositions(positions, 'all', 'missing');
		expect(out.map((p) => p.position_id)).toEqual(['3']);
	});

	it('filters by both', () => {
		expect(filterPositions(positions, 'high', 'missing').map((p) => p.position_id)).toEqual(['3']);
		expect(filterPositions(positions, 'critical', 'matches_standard')).toEqual([]);
	});
});
