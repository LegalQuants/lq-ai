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
 * TierDetailsPanel's modal body, and MessageBubble's tier hover-popover.
 */
export const TIER_DESCRIPTIONS: Record<Tier, TierDescription> = {
	1: {
		label: 'Tier 1 — On-prem / air-gapped',
		blurb: 'Local-only inference — runs on this computer. Your data never leaves the deployment.',
		tone: 'sage'
	},
	2: {
		label: 'Tier 2 — Private cloud (no provider data retention)',
		blurb: 'Customer-hosted cloud inference — runs in your own cloud account.',
		tone: 'neutral'
	},
	3: {
		label: 'Tier 3 — Commercial enterprise (ZDR addendum)',
		blurb: 'Enterprise managed inference — provider has signed ZDR / no-training commitments.',
		tone: 'amber'
	},
	4: {
		label: 'Tier 4 — Standard commercial API',
		blurb: 'Standard cloud API — provider terms govern data handling.',
		tone: 'amber'
	},
	5: {
		label: 'Tier 5 — Consumer / free-tier API',
		blurb: 'Consumer or free tier — the provider may train on your data.',
		tone: 'red'
	}
};

export function tierDescriptionFor(tier: Tier | null | undefined): TierDescription | null {
	return tier ? (TIER_DESCRIPTIONS[tier] ?? null) : null;
}
