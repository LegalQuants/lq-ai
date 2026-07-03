/**
 * referenced-files Phase 2 — MentionPopover pure helpers (module-block exports,
 * SlashPopover convention: no component mount).
 */
import { describe, expect, it } from 'vitest';

import {
	decideMentionKeyAction,
	mentionResults,
	mentionStateKind,
	type MentionPopoverState
} from '../components/MentionPopover.svelte';
import type { ReferencedFile } from '../files/referenceable';

function ref(id: string, filename = `${id}.pdf`, ready = true): ReferencedFile {
	return { id, filename, ready };
}

function state(overrides: Partial<MentionPopoverState> = {}): MentionPopoverState {
	return { results: [], activeIndex: 0, loading: false, error: null, query: '', ...overrides };
}

describe('mentionResults', () => {
	it('filters by query and drops non-ready files', () => {
		const files = [ref('1', 'alpha.pdf'), ref('2', 'beta.pdf', false), ref('3', 'gamma.pdf')];
		expect(mentionResults(files, 'a').map((f) => f.id)).toEqual(['1', '3']);
	});

	it('returns all ready files for an empty query', () => {
		const files = [ref('1'), ref('2', '2.pdf', false)];
		expect(mentionResults(files, '').map((f) => f.id)).toEqual(['1']);
	});
});

describe('mentionStateKind', () => {
	it('orders loading > error > empty > results', () => {
		expect(mentionStateKind(state({ loading: true, error: 'x' }))).toBe('loading');
		expect(mentionStateKind(state({ error: 'x' }))).toBe('error');
		expect(mentionStateKind(state({ query: 'q' }))).toBe('empty-with-query');
		expect(mentionStateKind(state())).toBe('empty-no-query');
		expect(mentionStateKind(state({ results: [ref('1')] }))).toBe('results');
	});
});

describe('decideMentionKeyAction', () => {
	const two = state({ results: [ref('1'), ref('2')], activeIndex: 0 });

	it('Escape dismisses even with no results', () => {
		expect(decideMentionKeyAction('Escape', state())).toEqual({ kind: 'dismiss' });
	});

	it('Enter selects the active row', () => {
		expect(decideMentionKeyAction('Enter', two)).toEqual({ kind: 'select', result: ref('1') });
	});

	it('ArrowDown/ArrowUp wrap around', () => {
		expect(decideMentionKeyAction('ArrowDown', { ...two, activeIndex: 1 })).toEqual({
			kind: 'move',
			nextIndex: 0
		});
		expect(decideMentionKeyAction('ArrowUp', two)).toEqual({ kind: 'move', nextIndex: 1 });
	});

	it('is a noop for other keys and for Enter with no results', () => {
		expect(decideMentionKeyAction('a', two)).toEqual({ kind: 'noop' });
		expect(decideMentionKeyAction('Enter', state())).toEqual({ kind: 'noop' });
	});
});
