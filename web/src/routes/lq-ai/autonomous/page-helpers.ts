/**
 * Pure helpers for the M4-C2 autonomous sessions list page.
 *
 * Extracted from `+page.svelte` so vitest can exercise them without the
 * SvelteKit / Svelte runtime. No side-effects; all functions are referentially
 * transparent (or explicitly accept a `now` parameter for deterministic tests).
 */

import type { SessionStatus } from '$lib/lq-ai/api/autonomous';

/**
 * Map a SessionStatus to a design-system pill class.
 *
 * Real SessionStatus union: 'running' | 'completed' | 'halted' | 'failed'
 * There is NO 'paused' status; 'paused' lives on the orthogonal HaltState.
 */
export function statusPillClass(status: SessionStatus): string {
	switch (status) {
		case 'running':
			return 'lq-status--running';
		case 'completed':
			return 'lq-status--completed';
		case 'halted':
			return 'lq-status--halted';
		case 'failed':
			return 'lq-status--failed';
	}
}

/**
 * Format cost fields as a dollar string.
 *
 * cost_total_usd and max_cost_usd arrive as STRINGS from the API
 * (Pydantic Decimal → string). Coerce with Number() before formatting.
 *
 * Examples:
 *   formatCost('0.10', '0.50')  → '$0.10 / $0.50'
 *   formatCost('0.10', null)    → '$0.10'
 *   formatCost(0.10, null)      → '$0.10'   (number inputs also accepted)
 */
export function formatCost(
	total: string | number,
	cap: string | number | null | undefined
): string {
	const t = `$${Number(total).toFixed(2)}`;
	if (cap != null && cap !== '') {
		return `${t} / $${Number(cap).toFixed(2)}`;
	}
	return t;
}

/**
 * Determine whether a session can be halted via POST /halt.
 *
 * A session is haltable while it is actively running. The POST /halt endpoint
 * is idempotent — sending it to a non-running session is harmless server-side,
 * but we hide the button to avoid user confusion.
 *
 * There is NO 'paused' SessionStatus; 'paused' lives on HaltState (a separate
 * orthogonal field). isHaltable is therefore solely: status === 'running'.
 */
export function isHaltable(status: SessionStatus): boolean {
	return status === 'running';
}

/**
 * Format a created_at ISO string into a short human-readable form.
 *
 * Mirrors the formatInstalledAt helper in the intake-bridges page-helpers,
 * adjusted to the sessions use case. Pass `now` for deterministic testing.
 */
export function formatCreatedAt(iso: string, now: Date = new Date()): string {
	const created = new Date(iso);
	if (Number.isNaN(created.getTime())) {
		return iso;
	}
	const deltaMs = now.getTime() - created.getTime();
	const deltaHours = Math.floor(deltaMs / (60 * 60 * 1000));
	if (deltaHours < 1) return 'just now';
	if (deltaHours < 24) return `${deltaHours} hour${deltaHours === 1 ? '' : 's'} ago`;
	const deltaDays = Math.floor(deltaHours / 24);
	if (deltaDays < 14) return `${deltaDays} day${deltaDays === 1 ? '' : 's'} ago`;
	return created.toISOString().slice(0, 10);
}
