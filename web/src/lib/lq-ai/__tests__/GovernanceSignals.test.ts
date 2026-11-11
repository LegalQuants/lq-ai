/**
 * ADR 0045 §1: colour means governance or error. The governance colour marks the
 * model tier, privileged matters and Trust & Privacy, and nothing else; every other
 * use of the old teal accent is now ink. These tests pin where governance is drawn.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { render } from 'svelte/server';

import { TIER_DESCRIPTIONS } from '../chat/tierDescriptions';
import { toneFor } from '../components/ProvenancePill.svelte';
import MatterCard from '../components/MatterCard.svelte';
import ProvenancePill from '../components/ProvenancePill.svelte';

const components = join(resolve(dirname(fileURLToPath(import.meta.url)), '..'), 'components');
const source = (name: string) => readFileSync(join(components, name), 'utf8');
const rule = (src: string, selector: string) => {
	const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const match = new RegExp(`(^|[\\s,}])${escaped}\\s*\\{([^}]*)\\}`).exec(src);
	expect(match, `${selector} is styled`).not.toBeNull();
	return match![2];
};

describe('governance signals (ADR 0045 §1)', () => {
	it('gives every tier the governance tone, not a risk colour', () => {
		for (const tier of [1, 2, 3, 4, 5] as const)
			expect(TIER_DESCRIPTIONS[tier].tone, `tier ${tier}`).toBe('slate');
	});

	it('draws the slate trust pill as a neutral outline with a governance dot', () => {
		const src = source('TrustPill.svelte');
		expect(rule(src, '.lq-pill-tone-slate')).toContain('color: var(--lq-text)');
		expect(
			rule(src, '.lq-pill-tone-slate:not(.lq-pill-dot):not(.lq-pill-locked)::before')
		).toContain('background: var(--lq-governance)');
		expect(rule(src, '.lq-pill-tone-sage')).not.toMatch(/--lq-(accent|governance|tier)/);
	});

	it('marks a privileged matter with the governance tone', () => {
		const matter = {
			id: 'm1',
			name: 'Larkspur',
			slug: 'larkspur',
			description: null,
			privileged: true,
			minimum_inference_tier: null,
			archived_at: null,
			updated_at: '2026-01-01T00:00:00Z'
		};
		const html = render(MatterCard, { props: { matter } as never }).body;
		expect(html).toMatch(
			/lq-pill-tone-slate[^>]*aria-label="Privileged"|aria-label="Privileged"[^>]*lq-pill-tone-slate/s
		);
	});

	it('keeps case law out of the governance tone and the tier in it', () => {
		expect(toneFor('caselaw', false)).toBe('sage');
		expect(toneFor('tier', false)).toBe('slate');
		expect(rule(source('ProvenancePill.svelte'), '.lq-prov-tone-slate::before')).toContain(
			'background: var(--lq-governance)'
		);
	});

	it('draws a tier mismatch in the governance colour, a matching tier with the dot', () => {
		const pill = (tierMismatch: boolean) =>
			render(ProvenancePill, { props: { kind: 'tier', summary: 'Tier 2', tierMismatch } }).body;
		expect(pill(true)).toContain('lq-prov-tone-governance');
		expect(pill(true)).not.toContain('lq-prov-tone-slate');
		expect(pill(false)).toContain('lq-prov-tone-slate');
		expect(pill(false)).not.toContain('lq-prov-tone-governance');
		const css = rule(source('ProvenancePill.svelte'), '.lq-prov-tone-governance');
		expect(css).toContain('color: var(--lq-governance)');
		expect(css).toContain('border-color: var(--lq-governance-border)');
		expect(css).not.toMatch(/--lq-(warn|text)\b/);
	});

	it('draws the model picker as a neutral control with a governance tier chip', () => {
		const src = source('ModelPicker.svelte');
		expect(rule(src, '.lq-model-pill')).not.toMatch(/--lq-(tier|governance)/);
		expect(rule(src, '.lq-tier-chip')).toContain('color: var(--lq-governance)');
	});

	it("draws the person's own message on the muted surface, not as an ink fill", () => {
		const src = source('MessageBubble.svelte');
		expect(src).toContain("? 'lq-t-user-bubble lq-t-text self-end'");
		expect(rule(src, '.lq-t-user-bubble')).toContain('background-color: var(--lq-surface-muted)');
	});

	it('colours the Trust & Privacy entry points and privileged matters, and nothing else in the sidebar', () => {
		const sidebar = source('ShellSidebar.svelte');
		expect(sidebar).toContain(".lq-sidebar-row[data-nav-id='trust'] :global(svg)");
		expect(rule(sidebar, '.lq-sidebar-row :global(.lq-sidebar-privileged)')).toContain(
			'color: var(--lq-governance)'
		);
		expect(sidebar.match(/--lq-governance/g)).toHaveLength(2);
		expect(source('GuidedDashboardTrustPanel.svelte')).toMatch(
			/<LqText\s+as="a"\s+size="14"\s+tone="governance"\s+href="\/lq-ai\/trust"/
		);
	});
});
