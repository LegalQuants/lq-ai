import { describe, expect, it } from 'vitest';
import {
	descriptionFor,
	iconFor,
	toneFor,
	type ProvenanceKind
} from '../components/ProvenancePill.svelte';

describe('ProvenancePill helpers', () => {
	it('maps each provenance kind to its icon', () => {
		expect(iconFor('skill')).toBe('🛠️');
		expect(iconFor('tier')).toBe('🔒');
		expect(iconFor('provider')).toBe('🧠');
		expect(iconFor('kb')).toBe('📎');
		expect(iconFor('audit')).toBe('📜');
		expect(iconFor('enhanced')).toBe('✨');
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
