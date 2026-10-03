/**
 * Pure-helper tests for the DE-263 admin community-skills page.
 *
 * The helpers are extracted into a sibling `page-helpers.ts` so vitest
 * can exercise them without the svelte transformer (the intake-bridges
 * convention).
 */
import { describe, expect, it } from 'vitest';

import type {
	CommunityCatalogResponse,
	CommunitySkillDetail,
	CommunitySkillSummary
} from '$lib/lq-ai/api/communitySkills';
import {
	attestationLabel,
	catalogEmptyMessage,
	filterCatalog,
	installButtonState,
	installConfirmMessage,
	shortSha
} from '../page-helpers';

function summary(over: Partial<CommunitySkillSummary> = {}): CommunitySkillSummary {
	return {
		slug: 'lease-review',
		title: 'Lease Review',
		description: 'First-pass review of commercial leases.',
		version: '1.0.0',
		author: 'Jane Attorney',
		tags: ['real-estate', 'review'],
		jurisdiction: 'us',
		attested_by: null,
		installed: false,
		body_preview: 'You are reviewing a lease…',
		...over
	};
}

function detail(over: Partial<CommunitySkillDetail> = {}): CommunitySkillDetail {
	return {
		...summary(),
		output_format: 'report',
		minimum_inference_tier: null,
		content_yaml: 'name: lease-review',
		content_md: '# Lease review body',
		install_ref: 'lq-skills:lease-review@abc123def456',
		...over
	};
}

function catalog(
	items: CommunitySkillSummary[],
	hint: string | null = null
): CommunityCatalogResponse {
	return {
		items,
		source: {
			path: '/repo/skills/community/skills',
			sha: 'abc123def4567890abc123def4567890abc123de',
			submodule_present: items.length > 0,
			operator_hint: hint
		},
		load_errors: []
	};
}

describe('filterCatalog', () => {
	const items = [
		summary(),
		summary({
			slug: 'nda-triage',
			title: 'NDA Triage',
			description: 'Quick NDA pass',
			tags: ['nda']
		})
	];

	it('returns everything for a blank query', () => {
		expect(filterCatalog(items, '')).toHaveLength(2);
		expect(filterCatalog(items, '   ')).toHaveLength(2);
	});

	it('matches slug, title, description, and tags case-insensitively', () => {
		expect(filterCatalog(items, 'LEASE').map((i) => i.slug)).toEqual(['lease-review']);
		expect(filterCatalog(items, 'triage').map((i) => i.slug)).toEqual(['nda-triage']);
		expect(filterCatalog(items, 'quick nda').map((i) => i.slug)).toEqual(['nda-triage']);
		expect(filterCatalog(items, 'Quick').map((i) => i.slug)).toEqual(['nda-triage']);
		expect(filterCatalog(items, 'real-estate').map((i) => i.slug)).toEqual(['lease-review']);
	});

	it('returns empty on no match', () => {
		expect(filterCatalog(items, 'zzz-no-such')).toEqual([]);
	});
});

describe('attestationLabel', () => {
	it('renders the declared attestation verbatim', () => {
		expect(attestationLabel('Jane Attorney, NY Bar #12345')).toBe(
			'Attested at source repo by: Jane Attorney, NY Bar #12345'
		);
	});

	it('states plainly when none is declared — never claims attestation', () => {
		expect(attestationLabel(null)).toBe('No attestation declared in SKILL.md');
	});
});

describe('shortSha', () => {
	it('truncates a full sha to 12 chars', () => {
		expect(shortSha('abc123def4567890abc123def4567890abc123de')).toBe('abc123def456');
	});

	it('degrades to "unknown" when the sha is unresolvable', () => {
		expect(shortSha(null)).toBe('unknown');
	});
});

describe('installConfirmMessage', () => {
	it('names the skill, the provenance ref, and the attestation state', () => {
		const msg = installConfirmMessage(detail());
		expect(msg).toContain('Lease Review');
		expect(msg).toContain('lq-skills:lease-review@abc123def456');
		expect(msg).toContain('No attestation declared in SKILL.md');
		expect(msg).toContain('does not auto-update');
	});

	it('carries a declared attestation through', () => {
		const msg = installConfirmMessage(detail({ attested_by: 'Jane Attorney' }));
		expect(msg).toContain('Attested at source repo by: Jane Attorney');
	});
});

describe('catalogEmptyMessage', () => {
	it('is null before the catalog loads', () => {
		expect(catalogEmptyMessage(null, 0, '')).toBeNull();
	});

	it('surfaces the server operator hint for an absent/empty submodule', () => {
		const hint = 'run `git submodule update --init skills/community`';
		expect(catalogEmptyMessage(catalog([], hint), 0, '')).toBe(hint);
	});

	it('falls back to a plain empty message without a hint', () => {
		expect(catalogEmptyMessage(catalog([], null), 0, '')).toBe('The community catalog is empty.');
	});

	it('reports a no-match search against a non-empty catalog', () => {
		expect(catalogEmptyMessage(catalog([summary()]), 0, 'zzz')).toBe(
			'No community skills match "zzz".'
		);
	});

	it('is null when rows are visible', () => {
		expect(catalogEmptyMessage(catalog([summary()]), 1, '')).toBeNull();
	});
});

describe('installButtonState', () => {
	it('disables with "Installed" for an already-installed skill', () => {
		expect(installButtonState(summary({ installed: true }), null)).toEqual({
			label: 'Installed',
			disabled: true
		});
	});

	it('shows progress for the pending slug', () => {
		expect(installButtonState(summary(), 'lease-review')).toEqual({
			label: 'Installing…',
			disabled: true
		});
	});

	it('disables other rows while an install is pending', () => {
		expect(installButtonState(summary(), 'other-slug')).toEqual({
			label: 'Install',
			disabled: true
		});
	});

	it('is enabled when idle and not installed', () => {
		expect(installButtonState(summary(), null)).toEqual({ label: 'Install', disabled: false });
	});
});
