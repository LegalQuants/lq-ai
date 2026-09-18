/**
 * Unit tests for SkillWizard helpers (Wave D.2, Task 4.2).
 *
 * Convention note: this codebase does not install @testing-library/svelte
 * (see AttachKBModal.test.ts / SlashPopover.test.ts headers). CLAUDE.md
 * forbids adding libraries without justification. So we follow the
 * established pattern: the .svelte file exports its pure logic from
 * <script context="module">, and we exercise those helpers here. The
 * template glue (the form, the localStorage timer, etc.) is exercised
 * in Cypress e2e once Task 7.x wires the page.
 *
 * Coverage:
 *   - kebab(s)                       — slug auto-derivation
 *   - isSlugValid(slug)              — slug regex
 *   - isSlashAliasValid(alias)       — slash-alias regex (null/empty OK)
 *   - canSave(state)                 — submit-button gate
 *   - buildPayload(state, forkedFrom) — POST body shape
 *   - serializeDraft(state) / loadDraft(raw) — localStorage round-trip
 */
import { describe, expect, it } from 'vitest';

import {
	isSlugValid,
	isSlashAliasValid,
	canSave,
	buildPayload,
	serializeDraft,
	loadDraft,
	DEFAULT_TABLE_BODY,
	type WizardFormState
} from '../components/SkillWizard.svelte';
import type { EditableColumn } from '../skills/tableColumns';
import { kebab } from '../util/slug';

function makeColumn(overrides: Partial<EditableColumn> = {}): EditableColumn {
	return {
		name: 'Term',
		query: 'What is the term of this agreement?',
		ensemble_verification: null,
		minimum_inference_tier: null,
		...overrides
	};
}

function makeState(overrides: Partial<WizardFormState> = {}): WizardFormState {
	return {
		slug: 'nda-review',
		displayName: 'NDA Review',
		description: 'Reviews NDA documents',
		body: '# NDA Review\nApply this skill when the user shares an NDA.',
		tagsInput: 'contracts, nda',
		slashAlias: '',
		version: '1.0.0',
		scope: 'user',
		ownerTeamId: '',
		outputMode: 'prose',
		columns: [makeColumn()],
		saving: false,
		...overrides
	};
}

describe('SkillWizard.kebab', () => {
	it('converts spaces to dashes and lowercases', () => {
		expect(kebab('NDA Review')).toBe('nda-review');
		expect(kebab('a b c')).toBe('a-b-c');
	});

	it('collapses runs of non-alphanumeric chars to a single dash', () => {
		expect(kebab('Foo  Bar')).toBe('foo-bar');
		expect(kebab('foo___bar')).toBe('foo-bar');
		expect(kebab('Hello, World!')).toBe('hello-world');
	});

	it('trims leading and trailing dashes', () => {
		expect(kebab('  hello  ')).toBe('hello');
		expect(kebab('---hello---')).toBe('hello');
		expect(kebab('!!!hello!!!')).toBe('hello');
	});

	it('returns an empty string for empty / all-non-alphanumeric input', () => {
		expect(kebab('')).toBe('');
		expect(kebab('   ')).toBe('');
		expect(kebab('---')).toBe('');
	});

	it('caps output at 80 characters', () => {
		const input = 'a'.repeat(100);
		expect(kebab(input)).toHaveLength(80);
	});

	it('preserves digits', () => {
		expect(kebab('MSA Review 2024')).toBe('msa-review-2024');
	});
});

describe('SkillWizard.isSlugValid', () => {
	it('accepts simple lowercase slugs', () => {
		expect(isSlugValid('nda-review')).toBe(true);
		expect(isSlugValid('msa')).toBe(true);
		expect(isSlugValid('a')).toBe(true);
		expect(isSlugValid('foo-bar-baz')).toBe(true);
		expect(isSlugValid('skill2024')).toBe(true);
	});

	it('rejects uppercase characters', () => {
		expect(isSlugValid('NDA-Review')).toBe(false);
		expect(isSlugValid('Foo')).toBe(false);
	});

	it('rejects leading dash', () => {
		expect(isSlugValid('-foo')).toBe(false);
	});

	it('rejects trailing dash', () => {
		expect(isSlugValid('foo-')).toBe(false);
	});

	it('rejects empty string', () => {
		expect(isSlugValid('')).toBe(false);
	});

	it('rejects spaces and special chars', () => {
		expect(isSlugValid('foo bar')).toBe(false);
		expect(isSlugValid('foo_bar')).toBe(false);
		expect(isSlugValid('foo.bar')).toBe(false);
	});

	it('accepts at the 80-char boundary and rejects past it', () => {
		expect(isSlugValid('a'.repeat(80))).toBe(true);
		expect(isSlugValid('a'.repeat(81))).toBe(false);
	});
});

describe('SkillWizard.isSlashAliasValid', () => {
	it('accepts empty / null / undefined (the "no alias" case)', () => {
		expect(isSlashAliasValid('')).toBe(true);
		expect(isSlashAliasValid(null)).toBe(true);
		expect(isSlashAliasValid(undefined)).toBe(true);
	});

	it('accepts simple slash aliases', () => {
		expect(isSlashAliasValid('/foo')).toBe(true);
		expect(isSlashAliasValid('/nda-review')).toBe(true);
		expect(isSlashAliasValid('/a')).toBe(true);
		expect(isSlashAliasValid('/foo-bar-2024')).toBe(true);
	});

	it('rejects missing leading slash', () => {
		expect(isSlashAliasValid('foo')).toBe(false);
		expect(isSlashAliasValid('nda-review')).toBe(false);
	});

	it('rejects "/" alone (need at least one char after the slash)', () => {
		expect(isSlashAliasValid('/')).toBe(false);
	});

	it('rejects uppercase and underscores', () => {
		expect(isSlashAliasValid('/Foo')).toBe(false);
		expect(isSlashAliasValid('/foo_bar')).toBe(false);
		expect(isSlashAliasValid('/foo bar')).toBe(false);
	});

	it('accepts at the 32-char boundary and rejects past it', () => {
		expect(isSlashAliasValid('/' + 'a'.repeat(32))).toBe(true);
		expect(isSlashAliasValid('/' + 'a'.repeat(33))).toBe(false);
	});
});

describe('SkillWizard.canSave', () => {
	it('is true when all required fields are valid', () => {
		expect(canSave(makeState())).toBe(true);
	});

	it('is false when display name is missing or whitespace', () => {
		expect(canSave(makeState({ displayName: '' }))).toBe(false);
		expect(canSave(makeState({ displayName: '   ' }))).toBe(false);
	});

	it('is false when description is missing or whitespace', () => {
		expect(canSave(makeState({ description: '' }))).toBe(false);
		expect(canSave(makeState({ description: '   ' }))).toBe(false);
	});

	it('is false when body is missing or whitespace', () => {
		expect(canSave(makeState({ body: '' }))).toBe(false);
		expect(canSave(makeState({ body: '   ' }))).toBe(false);
	});

	it('is false when slug is missing', () => {
		expect(canSave(makeState({ slug: '' }))).toBe(false);
	});

	it('is false when slug is invalid (e.g. uppercase / trailing dash)', () => {
		expect(canSave(makeState({ slug: 'Foo' }))).toBe(false);
		expect(canSave(makeState({ slug: 'foo-' }))).toBe(false);
	});

	it('is false when slash_alias is invalid', () => {
		expect(canSave(makeState({ slashAlias: 'foo' }))).toBe(false);
		expect(canSave(makeState({ slashAlias: '/' }))).toBe(false);
	});

	it('allows an empty slash_alias (the "no alias" case)', () => {
		expect(canSave(makeState({ slashAlias: '' }))).toBe(true);
	});

	it('is false when scope=team and ownerTeamId is missing', () => {
		expect(canSave(makeState({ scope: 'team', ownerTeamId: '' }))).toBe(false);
	});

	it('is true when scope=team and ownerTeamId is provided', () => {
		expect(
			canSave(makeState({ scope: 'team', ownerTeamId: 'team-uuid-1' }))
		).toBe(true);
	});

	it('is false while saving is in flight', () => {
		expect(canSave(makeState({ saving: true }))).toBe(false);
	});

	// --- DE-297 table mode -------------------------------------------------

	it('table mode: valid columns satisfy the gate even with an empty body', () => {
		expect(canSave(makeState({ outputMode: 'table', body: '' }))).toBe(true);
	});

	it('table mode: false with zero columns (backend min-one-column parity)', () => {
		expect(canSave(makeState({ outputMode: 'table', columns: [] }))).toBe(false);
	});

	it('table mode: false when a column query is empty', () => {
		expect(
			canSave(makeState({ outputMode: 'table', columns: [makeColumn({ query: '  ' })] }))
		).toBe(false);
	});

	it('table mode: false when a column tier is out of range', () => {
		expect(
			canSave(
				makeState({
					outputMode: 'table',
					columns: [makeColumn({ minimum_inference_tier: 6 })]
				})
			)
		).toBe(false);
	});

	it('prose mode ignores invalid columns state entirely', () => {
		expect(canSave(makeState({ outputMode: 'prose', columns: [] }))).toBe(true);
	});
});

describe('SkillWizard.buildPayload', () => {
	it('produces a UserSkillCreate-shaped payload (display_name / body, NOT title / body_md)', () => {
		const payload = buildPayload(makeState(), null);
		expect(payload).toMatchObject({
			slug: 'nda-review',
			display_name: 'NDA Review',
			description: 'Reviews NDA documents',
			body: '# NDA Review\nApply this skill when the user shares an NDA.',
			version: '1.0.0',
			tags: ['contracts', 'nda'],
			slash_alias: null,
			scope: 'user',
			owner_team_id: null,
			forked_from: null
		});
		// Should not include the plan-text legacy keys.
		const asRecord = payload as unknown as Record<string, unknown>;
		expect(asRecord.title).toBeUndefined();
		expect(asRecord.body_md).toBeUndefined();
		expect(asRecord.jurisdiction).toBeUndefined();
	});

	it('trims display_name and description before sending', () => {
		const payload = buildPayload(
			makeState({ displayName: '  Padded Name  ', description: '  Padded desc  ' }),
			null
		);
		expect(payload.display_name).toBe('Padded Name');
		expect(payload.description).toBe('Padded desc');
	});

	it('parses the tags input: trims, drops empties, preserves order', () => {
		const payload = buildPayload(
			makeState({ tagsInput: ' foo , , bar ,baz, ' }),
			null
		);
		expect(payload.tags).toEqual(['foo', 'bar', 'baz']);
	});

	it('emits tags: [] for an empty tagsInput', () => {
		const payload = buildPayload(makeState({ tagsInput: '' }), null);
		expect(payload.tags).toEqual([]);
	});

	it('sets slash_alias=null when the input is empty; passes the string through otherwise', () => {
		expect(buildPayload(makeState({ slashAlias: '' }), null).slash_alias).toBe(
			null
		);
		expect(
			buildPayload(makeState({ slashAlias: '/nda' }), null).slash_alias
		).toBe('/nda');
	});

	it('sets owner_team_id=null when scope=user (even if ownerTeamId is populated)', () => {
		const payload = buildPayload(
			makeState({ scope: 'user', ownerTeamId: 'team-uuid' }),
			null
		);
		expect(payload.scope).toBe('user');
		expect(payload.owner_team_id).toBe(null);
	});

	it('forwards owner_team_id when scope=team', () => {
		const payload = buildPayload(
			makeState({ scope: 'team', ownerTeamId: 'team-uuid' }),
			null
		);
		expect(payload.scope).toBe('team');
		expect(payload.owner_team_id).toBe('team-uuid');
	});

	it('passes forked_from through (separately from form state)', () => {
		expect(buildPayload(makeState(), null).forked_from).toBe(null);
		expect(buildPayload(makeState(), 'nda-review').forked_from).toBe(
			'nda-review'
		);
	});

	it('forwards version verbatim', () => {
		const payload = buildPayload(makeState({ version: '2.1.0' }), null);
		expect(payload.version).toBe('2.1.0');
	});

	// --- DE-297 table mode -------------------------------------------------

	it('prose mode sends no frontmatter_extra', () => {
		expect(buildPayload(makeState(), null).frontmatter_extra).toBeUndefined();
	});

	it('table mode persists frontmatter_extra.output_format=table + serialized columns', () => {
		const payload = buildPayload(
			makeState({
				outputMode: 'table',
				columns: [
					makeColumn(),
					makeColumn({
						name: 'Governing law',
						query: 'Which law governs?',
						ensemble_verification: true,
						minimum_inference_tier: 4
					})
				]
			}),
			null
		);
		expect(payload.frontmatter_extra).toEqual({
			output_format: 'table',
			columns: [
				{ name: 'Term', query: 'What is the term of this agreement?' },
				{
					name: 'Governing law',
					query: 'Which law governs?',
					ensemble_verification: true,
					minimum_inference_tier: 4
				}
			]
		});
	});

	it('table mode falls back to the documented placeholder body when body is blank', () => {
		const payload = buildPayload(makeState({ outputMode: 'table', body: '   ' }), null);
		expect(payload.body).toBe(DEFAULT_TABLE_BODY);
	});

	it('table mode keeps an author-written body verbatim', () => {
		const payload = buildPayload(
			makeState({ outputMode: 'table', body: '# My grid notes' }),
			null
		);
		expect(payload.body).toBe('# My grid notes');
	});
});

describe('SkillWizard.serializeDraft / loadDraft (round-trip)', () => {
	it('serializeDraft returns the JSON-serializable form snapshot (no `saving`)', () => {
		const state = makeState({ saving: true });
		const draft = serializeDraft(state);
		expect(draft).toMatchObject({
			slug: 'nda-review',
			displayName: 'NDA Review',
			description: 'Reviews NDA documents',
			body: state.body,
			tagsInput: 'contracts, nda',
			slashAlias: '',
			version: '1.0.0',
			scope: 'user',
			ownerTeamId: ''
		});
		// Transient flags must not be persisted.
		expect((draft as unknown as Record<string, unknown>).saving).toBeUndefined();
	});

	it('loadDraft parses valid JSON and returns a partial state', () => {
		const state = makeState();
		const raw = JSON.stringify(serializeDraft(state));
		const restored = loadDraft(raw);
		expect(restored).toMatchObject({
			slug: 'nda-review',
			displayName: 'NDA Review',
			description: 'Reviews NDA documents',
			body: state.body,
			tagsInput: 'contracts, nda',
			slashAlias: '',
			version: '1.0.0',
			scope: 'user',
			ownerTeamId: ''
		});
	});

	it('round-trips the DE-297 table-mode state (outputMode + columns)', () => {
		const state = makeState({
			outputMode: 'table',
			columns: [makeColumn({ minimum_inference_tier: 3 })]
		});
		const restored = loadDraft(JSON.stringify(serializeDraft(state)));
		expect(restored).toMatchObject({
			outputMode: 'table',
			columns: [makeColumn({ minimum_inference_tier: 3 })]
		});
	});

	it('loadDraft returns null on invalid JSON (caller leaves state untouched)', () => {
		expect(loadDraft('not-json')).toBe(null);
		expect(loadDraft('{')).toBe(null);
	});

	it('loadDraft returns null on null / empty input', () => {
		expect(loadDraft(null)).toBe(null);
		expect(loadDraft('')).toBe(null);
	});

	it('loadDraft returns null when payload is not an object', () => {
		expect(loadDraft('42')).toBe(null);
		expect(loadDraft('"string"')).toBe(null);
		expect(loadDraft('[]')).toBe(null);
	});
});
