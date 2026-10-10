/**
 * Pure-helper tests for the DE-323 context-proposal inbox banner on the
 * Matter detail page.
 *
 * Mirrors the pattern from:
 *   web/src/routes/lq-ai/autonomous/__tests__/page-helpers.test.ts
 */
import { describe, expect, it } from 'vitest';

import { bannerVisible, pendingProposalsFor, removeProposal } from '../proposal-helpers';
import type { ProjectContextProposalRead, ProposalState } from '$lib/lq-ai/api/autonomous';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PROJECT_ID = '11111111-1111-1111-1111-111111111111';
const OTHER_PROJECT_ID = '22222222-2222-2222-2222-222222222222';

function makeProposal(
	overrides: Partial<ProjectContextProposalRead> = {}
): ProjectContextProposalRead {
	return {
		id: 'prop-1',
		user_id: 'user-1',
		precedent_id: 'prec-1',
		project_id: PROJECT_ID,
		suggested_md: '- Counterparty prefers NY governing law.',
		state: 'proposed',
		accepted_at: null,
		rejected_at: null,
		created_at: '2026-07-01T00:00:00Z',
		updated_at: '2026-07-01T00:00:00Z',
		...overrides
	};
}

// ---------------------------------------------------------------------------
// pendingProposalsFor
// ---------------------------------------------------------------------------

describe('pendingProposalsFor', () => {
	it('keeps only proposed-state proposals for the given project', () => {
		const list = [
			makeProposal({ id: 'a' }),
			makeProposal({ id: 'b', state: 'accepted' }),
			makeProposal({ id: 'c', state: 'rejected' }),
			makeProposal({ id: 'd', project_id: OTHER_PROJECT_ID })
		];
		const result = pendingProposalsFor(list, PROJECT_ID);
		expect(result.map((p) => p.id)).toEqual(['a']);
	});

	it('filters out every non-proposed state', () => {
		const states: ProposalState[] = ['accepted', 'rejected'];
		for (const state of states) {
			expect(pendingProposalsFor([makeProposal({ state })], PROJECT_ID)).toEqual([]);
		}
	});

	it('returns an empty list when nothing targets the project', () => {
		const list = [makeProposal({ project_id: OTHER_PROJECT_ID })];
		expect(pendingProposalsFor(list, PROJECT_ID)).toEqual([]);
	});

	it('returns an empty list for an empty input', () => {
		expect(pendingProposalsFor([], PROJECT_ID)).toEqual([]);
	});

	it('preserves input order for multiple pending proposals', () => {
		const list = [makeProposal({ id: 'a' }), makeProposal({ id: 'b' }), makeProposal({ id: 'c' })];
		expect(pendingProposalsFor(list, PROJECT_ID).map((p) => p.id)).toEqual(['a', 'b', 'c']);
	});

	it('does not mutate the input list', () => {
		const list = [makeProposal({ id: 'a' }), makeProposal({ id: 'b', state: 'accepted' })];
		pendingProposalsFor(list, PROJECT_ID);
		expect(list).toHaveLength(2);
	});
});

// ---------------------------------------------------------------------------
// removeProposal — the accept/reject state transition
// ---------------------------------------------------------------------------

describe('removeProposal', () => {
	it('removes the accepted proposal and keeps the rest (accept transition)', () => {
		const list = [makeProposal({ id: 'a' }), makeProposal({ id: 'b' })];
		const result = removeProposal(list, 'a');
		expect(result.map((p) => p.id)).toEqual(['b']);
	});

	it('removes the rejected proposal and keeps the rest (reject transition)', () => {
		const list = [makeProposal({ id: 'a' }), makeProposal({ id: 'b' })];
		const result = removeProposal(list, 'b');
		expect(result.map((p) => p.id)).toEqual(['a']);
	});

	it('removing the last proposal yields an empty list (banner then hides)', () => {
		const list = [makeProposal({ id: 'a' })];
		const result = removeProposal(list, 'a');
		expect(result).toEqual([]);
		expect(bannerVisible(true, result.length)).toBe(false);
	});

	it('is a no-op for an unknown id', () => {
		const list = [makeProposal({ id: 'a' })];
		expect(removeProposal(list, 'nope')).toHaveLength(1);
	});

	it('returns a new array and does not mutate the input', () => {
		const list = [makeProposal({ id: 'a' }), makeProposal({ id: 'b' })];
		const result = removeProposal(list, 'a');
		expect(result).not.toBe(list);
		expect(list).toHaveLength(2);
	});
});

// ---------------------------------------------------------------------------
// bannerVisible — banner show/hide states
// ---------------------------------------------------------------------------

describe('bannerVisible', () => {
	it('is hidden when the user has not opted in, regardless of pending count', () => {
		expect(bannerVisible(false, 0)).toBe(false);
		expect(bannerVisible(false, 3)).toBe(false);
		expect(bannerVisible(false, 3, true)).toBe(false);
	});

	it('is hidden when opted in but zero pending and no message', () => {
		expect(bannerVisible(true, 0)).toBe(false);
		expect(bannerVisible(true, 0, false)).toBe(false);
	});

	it('is visible when opted in with pending proposals', () => {
		expect(bannerVisible(true, 1)).toBe(true);
		expect(bannerVisible(true, 5)).toBe(true);
	});

	it('stays visible with zero pending while an action message is showing', () => {
		// e.g. right after accepting/rejecting the last pending proposal.
		expect(bannerVisible(true, 0, true)).toBe(true);
	});

	it('hasMessage defaults to false', () => {
		expect(bannerVisible(true, 0)).toBe(false);
	});
});
