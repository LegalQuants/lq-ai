/**
 * referenced-files Phase 2 - @-mention detection + completion helpers. Same convention as
 * ChatPanel-slash-detect.test.ts: pure module-scope helpers exported from
 * ChatPanel.svelte, tested without mounting the component.
 */
import { describe, expect, it } from 'vitest';

import { completeMentionAt, detectMentionAt } from '../components/ChatPanel.svelte';

describe('detectMentionAt', () => {
	it('does not open when caret position is 0', () => {
		expect(detectMentionAt('', 0)).toEqual({ open: false });
		expect(detectMentionAt('@foo', 0)).toEqual({ open: false });
	});

	it('opens on empty query when text is just "@"', () => {
		expect(detectMentionAt('@', 1)).toEqual({ open: true, query: '', atIndex: 0 });
	});

	it('opens on start of textarea query', () => {
		expect(detectMentionAt('@nda', 4)).toEqual({ open: true, query: 'nda', atIndex: 0 });
	});

	it('opens mid-line after a space (unlike slash detection)', () => {
		expect(detectMentionAt('summarize @exh', 14)).toEqual({
			open: true,
			query: 'exh',
			atIndex: 10
		});
	});

	it('opens after a newline', () => {
		expect(detectMentionAt('line one\n@doc', 13)).toEqual({
			open: true,
			query: 'doc',
			atIndex: 9
		});
	});

	it('does NOT open on email-like text (@ is not at a word start)', () => {
		expect(detectMentionAt('a@b', 3)).toEqual({ open: false });
		expect(detectMentionAt('user@example.com', 16)).toEqual({ open: false });
	});

	it('accepts dots, hyphens, underscores, and uppercase in the query', () => {
		expect(detectMentionAt('@Master-Agreement_v2.pdf', 25)).toEqual({
			open: true,
			query: 'Master-Agreement_v2.pdf',
			atIndex: 0
		});
	});

	it('closes when the query is interrupted by a space', () => {
		expect(detectMentionAt('@exh ibit', 9)).toEqual({ open: false });
	});

	it('does not open when the caret sits before @', () => {
		expect(detectMentionAt('hi @doc', 2)).toEqual({ open: false });
	});

	it('does not treat @@ as a mention', () => {
		expect(detectMentionAt('@@', 2)).toEqual({ open: false });
	});
});

describe('completeMentionAt', () => {
	it('completes "@query" at the start of the text', () => {
		expect(completeMentionAt('@nda tell me', 0, 3, 'NDA-2024.pdf')).toBe('@NDA-2024.pdf tell me');
	});

	it('completes "@query" mid-text without doubling spaces', () => {
		expect(completeMentionAt('summarize @exh please', 10, 3, 'exhibit-a.pdf')).toBe(
			'summarize @exhibit-a.pdf please'
		);
	});

	it('appends a separating space at the end of the text', () => {
		expect(completeMentionAt('summarize @exh', 10, 3, 'exhibit-a.pdf')).toBe(
			'summarize @exhibit-a.pdf '
		);
	});

	it('completes a bare "@" (empty query)', () => {
		expect(completeMentionAt('hello @', 6, 0, 'a.pdf')).toBe('hello @a.pdf ');
	});

	it('keeps filenames containing spaces inline', () => {
		expect(completeMentionAt('@ber', 0, 3, 'BERGE SISAR.HL.2002.pdf')).toBe(
			'@BERGE SISAR.HL.2002.pdf '
		);
	});
});
