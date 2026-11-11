import type { TrustTone } from '../components/TrustPill.svelte';

export type Tier = 1 | 2 | 3 | 4 | 5;

export interface TierDescription {
	label: string;
	blurb: string;
	tone: TrustTone;
}

/**
 * Single source of truth for "what does Tier N mean" — was previously
 * duplicated (with drifting wording) across TierBadge's hover title,
 * TierDetailsPanel's modal body. The tone here adapts the existing
 * TrustPill vocabulary; shared primitives use the semantic LqTone roles.
 * Every tier is slate, the governance tone (ADR 0045 §1): colour marks the
 * tier as a governance signal, and the label and blurb carry its level.
 */
export const TIER_DESCRIPTIONS: Record<Tier, TierDescription> = {
	1: {
		label: 'Tier 1 — On-prem / air-gapped',
		blurb: 'Local-only inference — runs on this computer. Your data never leaves the deployment.',
		tone: 'slate'
	},
	2: {
		label: 'Tier 2 — Private cloud (no provider data retention)',
		blurb: 'Customer-hosted cloud inference — runs in your own cloud account.',
		tone: 'slate'
	},
	3: {
		label: 'Tier 3 — Commercial enterprise (ZDR addendum)',
		blurb: 'Enterprise managed inference — provider has signed ZDR / no-training commitments.',
		tone: 'slate'
	},
	4: {
		label: 'Tier 4 — Standard commercial API',
		blurb: 'Standard cloud API — provider terms govern data handling.',
		tone: 'slate'
	},
	5: {
		label: 'Tier 5 — Consumer / free-tier API',
		blurb: 'Consumer or free tier — the provider may train on your data.',
		tone: 'slate'
	}
};

export function tierDescriptionFor(tier: Tier | null | undefined): TierDescription | null {
	return tier ? (TIER_DESCRIPTIONS[tier] ?? null) : null;
}
