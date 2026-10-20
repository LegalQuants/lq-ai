/**
 * Where the run components link to: a chat, and the receipt view of a run.
 */
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { chatHref, receiptHref, receiptHrefForSession } from '../links';
import { HOSTILE_STRINGS } from './hostile';
import { profiles, run } from './fixtures';

const ORIGIN = 'https://lq.example';
const parsed = (href: string) => new URL(href, ORIGIN);

describe('chatHref', () => {
	it('opens the chat page on that chat', () => {
		const id = profiles('active-run').active_run!.chat_id!;
		expect(chatHref(id)).toBe(`/lq-ai/chats?id=${id}`);
	});

	it('is the link the run read’s own chat gets', () => {
		const recorded = run('documents.completed');
		// The id is whatever the recording holds; a re-recording gives a new one.
		expect(recorded.chat_id).toMatch(/^[0-9a-f-]{36}$/);
		expect(chatHref(recorded.chat_id!)).toBe(`/lq-ai/chats?id=${recorded.chat_id}`);
	});

	it('escapes an id, so it can only ever be the value of `id`', () => {
		expect(chatHref('a b&c=d#e?f/g')).toBe('/lq-ai/chats?id=a%20b%26c%3Dd%23e%3Ff%2Fg');
	});

	it.each(HOSTILE_STRINGS.map((text) => [text]))(
		'keeps %s a value, on this site, in this page’s query',
		(hostile) => {
			const href = chatHref(hostile);
			const url = parsed(href);
			expect(href.startsWith('/lq-ai/chats?id=')).toBe(true);
			expect(url.origin).toBe(ORIGIN);
			expect(url.pathname).toBe('/lq-ai/chats');
			expect(url.hash).toBe('');
			expect([...url.searchParams.keys()]).toEqual(['id']);
			expect(url.searchParams.get('id')).toBe(hostile);
			expect(href).not.toMatch(/[<>"\s]/);
		}
	);
});

describe('receiptHref', () => {
	it('opens the receipt view of a run', () => {
		const id = run('completed').root_id;
		expect(receiptHref(id)).toBe(`/lq-ai/autonomous/orchestration/chat/${id}`);
	});

	it('escapes an id, so it can only ever be one part of the path', () => {
		expect(receiptHref('a/b?c#d e')).toBe('/lq-ai/autonomous/orchestration/chat/a%2Fb%3Fc%23d%20e');
	});

	it.each(HOSTILE_STRINGS.map((text) => [text]))(
		'keeps %s one path segment on this site, with no query or fragment',
		(hostile) => {
			const href = receiptHref(hostile);
			const url = parsed(href);
			expect(href.startsWith('/lq-ai/autonomous/orchestration/chat/')).toBe(true);
			expect(url.origin).toBe(ORIGIN);
			expect(url.search).toBe('');
			expect(url.hash).toBe('');
			const segments = url.pathname.split('/');
			expect(segments).toHaveLength(6);
			expect(decodeURIComponent(segments[5])).toBe(hostile);
			expect(href).not.toMatch(/[<>"\s]/);
		}
	);
});

describe('receiptHrefForSession', () => {
	const session = (profile: unknown, id = 'root-1') => ({
		id,
		params: { orchestration_profile: profile } as Record<string, unknown>
	});

	it('links the root session of a governed run to its receipts', () => {
		expect(receiptHrefForSession(session('model_demo_v1'))).toBe(receiptHref('root-1'));
		expect(receiptHrefForSession(session('new_harness_v1', 'root-2'))).toBe(receiptHref('root-2'));
	});

	it('links a root whose profile it has never heard of, since the registry grows faster than the client', () => {
		expect(receiptHrefForSession(session('a_profile_added_later'))).toBe(receiptHref('root-1'));
	});

	it('does not link a task’s session or the earlier demonstration, which have no run receipt', () => {
		expect(receiptHrefForSession(session('research'))).toBeNull();
		expect(receiptHrefForSession(session('demonstration'))).toBeNull();
	});

	it('does not link a session that is not the root of a governed run', () => {
		expect(receiptHrefForSession({ id: 'a' })).toBeNull();
		expect(receiptHrefForSession({ id: 'a', params: null })).toBeNull();
		expect(receiptHrefForSession({ id: 'a', params: {} })).toBeNull();
		for (const profile of [null, undefined, '', 0, 7, false, true, {}, [], ['model_demo_v1']]) {
			expect(receiptHrefForSession(session(profile)), JSON.stringify(profile)).toBeNull();
		}
	});

	it('never builds a link out of a profile that is not a string, however it prints', () => {
		for (const profile of [null, undefined, 7, {}, []]) {
			const href = receiptHrefForSession(session(profile));
			expect(href).toBeNull();
		}
	});

	it('escapes the session id like any other', () => {
		for (const hostile of HOSTILE_STRINGS) {
			const href = receiptHrefForSession(session('model_demo_v1', hostile));
			expect(href).toBe(receiptHref(hostile));
			expect(parsed(href!).origin).toBe(ORIGIN);
		}
	});

	it('has no link for a session with no id, rather than a link for "null"', () => {
		for (const id of [null, undefined, '', 7, {}, []]) {
			const withoutId = {
				id: id as unknown as string,
				params: { orchestration_profile: 'model_demo_v1' }
			};
			expect(receiptHrefForSession(withoutId), String(JSON.stringify(id))).toBeNull();
		}
	});
});

describe('a link for an id that is not there', () => {
	// The types forbid a missing id, but a run message with no `autonomous_session_id`, a run with no
	// chat and a session with no id exist, so the helpers do not trust their callers to have looked.
	const MISSING = [null, undefined, '', 0, 7, false, {}, []];

	it('is the list the id would have been picked from, never a link for "null" or "undefined"', () => {
		for (const id of MISSING) {
			expect(chatHref(id as unknown as string), String(JSON.stringify(id))).toBe('/lq-ai/chats');
			expect(receiptHref(id as unknown as string), String(JSON.stringify(id))).toBe(
				'/lq-ai/autonomous'
			);
		}
	});

	it('is a page that exists', () => {
		const routes = new URL('../../../../routes/lq-ai/', import.meta.url);
		for (const [href, page] of [
			[chatHref(null as unknown as string), 'chats/+page.svelte'],
			[receiptHref(undefined as unknown as string), 'autonomous/+page.svelte'],
			[chatHref('a-chat'), 'chats/+page.svelte'],
			[receiptHref('a-run'), 'autonomous/orchestration/chat/[id]/+page.svelte']
		]) {
			expect(existsSync(fileURLToPath(new URL(page, routes))), `${href} is ${page}`).toBe(true);
		}
	});

	it('is not a link with an id in it', () => {
		for (const id of MISSING) {
			for (const href of [
				chatHref(id as unknown as string),
				receiptHref(id as unknown as string)
			]) {
				expect(href).not.toMatch(/null|undefined|NaN|\[object|\?id=/);
			}
		}
	});
});
