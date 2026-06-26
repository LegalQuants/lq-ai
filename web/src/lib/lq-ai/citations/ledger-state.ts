/**
 * Ledger entry status → CitationRenderState, and gate verdict → badge.
 *
 * Reuses the M2-C2 5-state palette (state.ts) so ledger entry chips pick up
 * the existing colors/labels/tooltips. Operates on the ledger's
 * `verification_status` string directly (the ledger mirrors the cascade
 * method onto the entry), so no Citation row is needed.
 *
 * TrustTone is defined locally (subset of TrustPill.svelte's union) to keep
 * `npm run check:lq-ai` clean — importing types from a `.svelte` module
 * context="module" block is awkward in pure TS files.
 */
import type { CitationRenderState } from './state';
import type { LedgerGate } from '../types';

// Local subset — matches TrustPill.svelte's TrustTone union exactly.
type TrustTone = 'sage' | 'slate' | 'amber' | 'red' | 'neutral';

export function ledgerEntryState(status: string): CitationRenderState {
	switch (status) {
		case 'exact_match':
			return 'verified-exact';
		case 'tolerant_match':
			return 'verified-tolerant';
		case 'paraphrase_judge':
		case 'llm_judge':
		case 'ensemble_strict':
		case 'ensemble_majority':
			return 'verified-paraphrase';
		default:
			// unverified | failed | provenance | unknown — conservative gray.
			return 'unverified';
	}
}

export interface GateBadge {
	tone: TrustTone;
	label: string;
	tip: string;
}

export function gateBadge(gate: LedgerGate | undefined): GateBadge | null {
	if (!gate) return null;
	switch (gate.gate_status) {
		case 'fiduciary_grade':
			return {
				tone: 'sage',
				label: 'Fiduciary-grade',
				tip: `Every cited assertion (${gate.pass_count}) is verified verbatim against its source.`
			};
		case 'supported_only':
			return {
				tone: 'amber',
				label: 'Supported — not all verbatim',
				tip: `${gate.supported_count} assertion(s) are supported (paraphrase), not verbatim; none failed.`
			};
		case 'flagged':
			return {
				tone: 'red',
				label: 'Unverified claims flagged',
				tip: `${gate.fail_count} cited assertion(s) could not be verified.`
			};
		default:
			return null;
	}
}
