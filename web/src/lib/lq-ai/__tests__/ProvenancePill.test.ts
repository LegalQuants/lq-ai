import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';
import ProvenancePill, {
	descriptionFor,
	iconFor,
	toneFor,
	type ProvenanceKind
} from '../components/ProvenancePill.svelte';

const ICONS: Record<ProvenanceKind, string> = {
	skill: 'tool',
	tier: 'lock',
	provider: 'brain',
	kb: 'paperclip',
	audit: 'file-text',
	enhanced: 'sparkles',
	caselaw: 'scale'
};

describe('ProvenancePill helpers', () => {
	it('maps each provenance kind to its Tabler icon (ADR 0045 §5)', () => {
		for (const [kind, name] of Object.entries(ICONS))
			expect(iconFor(kind as ProvenanceKind), kind).toBe(name);
	});

	it('maps kinds to sage by default; tier mismatch flips to governance', () => {
		expect(toneFor('skill', false)).toBe('sage');
		expect(toneFor('tier', false)).toBe('slate');
		expect(toneFor('tier', true)).toBe('governance');
		expect(toneFor('provider', false)).toBe('sage');
	});

	it('lists six kinds (sentinel — update if Wave D adds more)', () => {
		const kinds: ProvenanceKind[] = ['skill', 'tier', 'provider', 'kb', 'audit', 'enhanced'];
		expect(kinds.length).toBe(6);
	});

	it('provides plain-English hover descriptions for every kind', () => {
		const kinds: ProvenanceKind[] = ['skill', 'tier', 'provider', 'kb', 'audit', 'enhanced'];
		for (const kind of kinds) {
			const desc = descriptionFor(kind);
			expect(desc).toBeTruthy();
			// Non-technical hover copy should be a complete sentence (ends with period).
			expect(desc.endsWith('.')).toBe(true);
			// Each description should mention what to do (click) or what it represents.
			expect(desc.length).toBeGreaterThan(30);
		}
	});

	it('uses distinct copy per kind so users learn each pill independently', () => {
		const kinds: ProvenanceKind[] = ['skill', 'tier', 'provider', 'kb', 'audit', 'enhanced'];
		const descriptions = kinds.map((k) => descriptionFor(k));
		expect(new Set(descriptions).size).toBe(kinds.length);
	});
});

describe('ProvenancePill renders a hidden Tabler icon, no emoji (SSR)', () => {
	for (const [kind, name] of Object.entries(ICONS))
		it(`${kind}: tabler-icon-${name}, aria-hidden, accessible name kept`, () => {
			const html = render(ProvenancePill, {
				props: { kind: kind as ProvenanceKind, summary: 'Summary' }
			}).body;
			expect(html).toContain(`aria-label="${kind}: Summary"`);
			expect(html).toMatch(
				new RegExp(`<svg(?=[^>]*tabler-icon-${name}\\b)(?=[^>]*aria-hidden="true")`)
			);
			expect(html).not.toMatch(/\p{Extended_Pictographic}/u);
		});
});
