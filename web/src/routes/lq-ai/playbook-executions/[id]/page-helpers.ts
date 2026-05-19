import type {
	PlaybookPositionResult,
	PlaybookPositionVerdict,
	PositionSeverity
} from '$lib/lq-ai/types';

export type SeverityFilter = 'all' | PositionSeverity;
export type OutcomeFilter = 'all' | PlaybookPositionVerdict;

export function severityClass(s: PositionSeverity): string {
	return `lq-severity--${s}`;
}

export function outcomeClass(v: PlaybookPositionVerdict): string {
	// matches_standard → matches-standard for CSS-friendly slugs
	return `lq-outcome--${v.replace(/_/g, '-')}`;
}

export function severityLabel(s: PositionSeverity): string {
	return s.charAt(0).toUpperCase() + s.slice(1);
}

export function outcomeLabel(v: PlaybookPositionVerdict): string {
	switch (v) {
		case 'matches_standard':
			return 'Matches standard';
		case 'matches_fallback':
			return 'Matches fallback';
		case 'deviates':
			return 'Deviates';
		case 'missing':
			return 'Missing';
	}
}

export function filterPositions(
	positions: PlaybookPositionResult[],
	severity: SeverityFilter,
	outcome: OutcomeFilter
): PlaybookPositionResult[] {
	return positions.filter((p) => {
		if (severity !== 'all' && p.severity_if_missing !== severity) return false;
		if (outcome !== 'all' && p.verdict !== outcome) return false;
		return true;
	});
}
