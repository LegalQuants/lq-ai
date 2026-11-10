/**
 * Pure helpers for the DE-323 context-proposal inbox banner on the Matter
 * detail page.
 *
 * Extracted from `+page.svelte` so vitest can exercise the banner state
 * logic without the SvelteKit / Svelte runtime. Mirrors the pattern from:
 *   web/src/routes/lq-ai/autonomous/__tests__/page-helpers.test.ts
 *
 * The banner is the matter-local surface of the proposal review loop that
 * lives at /lq-ai/autonomous/proposals (M4-C2 Task 14). ADR 0013 D5 still
 * holds: accepting here is the same user-authorized write path — the agent
 * never writes Project context directly.
 */

import type { ProjectContextProposalRead } from '$lib/lq-ai/api/autonomous';

/**
 * Narrow a proposal list to the pending ('proposed') proposals that target
 * the given project.
 *
 * The server already filters by state + project_id when asked, but the
 * banner re-filters defensively so a stale or over-broad response can never
 * surface another matter's proposals (or already-resolved ones) here.
 */
export function pendingProposalsFor(
	proposals: ProjectContextProposalRead[],
	projectId: string
): ProjectContextProposalRead[] {
	return proposals.filter((p) => p.state === 'proposed' && p.project_id === projectId);
}

/**
 * Return a new list without the proposal `id` (used after accept/reject).
 * Unknown ids are a no-op; the input list is never mutated.
 */
export function removeProposal(
	proposals: ProjectContextProposalRead[],
	id: string
): ProjectContextProposalRead[] {
	return proposals.filter((p) => p.id !== id);
}

/**
 * Whether the proposal banner region should render at all.
 *
 * Hidden when the user has not opted in to autonomous mode, and hidden when
 * there is nothing to show: zero pending proposals AND no lingering
 * action message (`hasMessage` keeps a success/error visible right after
 * the last pending proposal was resolved).
 */
export function bannerVisible(
	optedIn: boolean,
	pendingCount: number,
	hasMessage = false
): boolean {
	return optedIn && (pendingCount > 0 || hasMessage);
}
