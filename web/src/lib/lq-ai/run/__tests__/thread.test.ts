/**
 * Reading a chat's thread back, oldest first and a page at a time, to find a run message
 * that was just created or delivered; and swapping one message for its fresh copy.
 */
import { describe, expect, it, vi } from 'vitest';

import type { Message } from '../../types';
import {
	MAX_THREAD_PAGES,
	THREAD_TOO_LONG,
	fetchMessages,
	replaceMessage,
	type MessagePage
} from '../thread';
import { allRuns, thread } from './fixtures';

function message(id: string, patch: Partial<Message> = {}): Message {
	return {
		id,
		chat_id: 'chat-1',
		role: 'user',
		content: `message ${id}`,
		created_at: '2026-10-06T08:55:09Z',
		...patch
	};
}

const many = (count: number): Message[] =>
	Array.from({ length: count }, (_, i) => message(`m${i}`));

/** A server that serves `all`, oldest first, `size` to a page, with the next position as the cursor. */
function server(all: Message[], size: number) {
	const cursors: (string | undefined)[] = [];
	const listPage = vi.fn(async (cursor?: string): Promise<MessagePage> => {
		cursors.push(cursor);
		const start = cursor === undefined ? 0 : Number(cursor);
		const next = start + size;
		return { items: all.slice(start, next), next_cursor: next < all.length ? String(next) : null };
	});
	return { listPage, cursors };
}

describe('fetchMessages', () => {
	it('reads every page, oldest first, handing each page the cursor the last one gave', async () => {
		const recorded = thread('closed');
		const { listPage, cursors } = server(recorded, 1);
		const read = await fetchMessages(listPage);
		expect(read.map((item) => item.id)).toEqual(recorded.map((item) => item.id));
		expect(cursors).toEqual([undefined, '1', '2', '3']);
	});

	it('is one read for a thread that fits in a page, and none too many for an empty one', async () => {
		const small = server(many(3), 100);
		expect(await fetchMessages(small.listPage)).toHaveLength(3);
		expect(small.listPage).toHaveBeenCalledTimes(1);
		const empty = server([], 100);
		expect(await fetchMessages(empty.listPage)).toEqual([]);
		expect(empty.listPage).toHaveBeenCalledTimes(1);
	});

	it('keeps the messages as the server sent them, the very same objects', async () => {
		const sent = many(5);
		const read = await fetchMessages(server(sent, 2).listPage);
		read.forEach((item, position) => expect(item).toBe(sent[position]));
	});

	it('stops at the page that holds the message it was looking for, and reads no further', async () => {
		const all = many(10);
		const { listPage, cursors } = server(all, 3);
		const read = await fetchMessages(listPage, { stopAtId: 'm4' });
		// m4 is on the second page, which is read whole.
		expect(read.map((item) => item.id)).toEqual(['m0', 'm1', 'm2', 'm3', 'm4', 'm5']);
		expect(cursors).toEqual([undefined, '3']);
	});

	it('reads one page when the message is on the first', async () => {
		const { listPage } = server(many(10), 3);
		await fetchMessages(listPage, { stopAtId: 'm1' });
		expect(listPage).toHaveBeenCalledTimes(1);
	});

	it('reads the whole thread when the message is not there', async () => {
		const { listPage } = server(many(10), 3);
		const read = await fetchMessages(listPage, { stopAtId: 'not-in-this-thread' });
		expect(read).toHaveLength(10);
		expect(listPage).toHaveBeenCalledTimes(4);
	});

	it('reads the whole thread when it is not asked to look for anything', async () => {
		const { listPage } = server(many(10), 3);
		expect(await fetchMessages(listPage, { stopAtId: undefined })).toHaveLength(10);
		expect(await fetchMessages(listPage, {})).toHaveLength(10);
	});

	it('ends when there is no next cursor, whether it is null or empty', async () => {
		for (const next_cursor of [null, '']) {
			const listPage = vi.fn(async (): Promise<MessagePage> => ({ items: many(2), next_cursor }));
			expect(await fetchMessages(listPage)).toHaveLength(2);
			expect(listPage).toHaveBeenCalledTimes(1);
		}
	});

	it('does not loop on a server that keeps handing back the cursor it was just given', async () => {
		const listPage = vi.fn(
			async (): Promise<MessagePage> => ({ items: [message('x')], next_cursor: 'same' })
		);
		const read = await fetchMessages(listPage);
		expect(listPage).toHaveBeenCalledTimes(2);
		expect(read).toHaveLength(2);
	});

	describe('a thread longer than the page guard', () => {
		const endless = () => {
			let n = 0;
			return vi.fn(async (): Promise<MessagePage> => {
				n += 1;
				return { items: [message(`m${n}`)], next_cursor: `cursor-${n}` };
			});
		};

		it('is refused after exactly the number of pages the guard allows, on a server whose cursor never ends', async () => {
			const capped = endless();
			await expect(fetchMessages(capped, { maxPages: 3 })).rejects.toThrow(THREAD_TOO_LONG);
			expect(capped).toHaveBeenCalledTimes(3);
			const byDefault = endless();
			await expect(fetchMessages(byDefault)).rejects.toThrow(THREAD_TOO_LONG);
			expect(MAX_THREAD_PAGES).toBe(50);
			expect(byDefault).toHaveBeenCalledTimes(MAX_THREAD_PAGES);
		});

		it('is an error, not part of the thread handed back as if it were all of it', async () => {
			const error = await fetchMessages(endless(), { maxPages: 2 }).then(
				() => null,
				(caught: unknown) => caught
			);
			expect(error).toBeInstanceOf(Error);
			expect((error as Error).message).toBe(THREAD_TOO_LONG);
		});

		it('says in words what to do, with no markup in it', () => {
			expect(THREAD_TOO_LONG).toMatch(/^[A-Z].*\.$/);
			expect(THREAD_TOO_LONG).toMatch(/too long/i);
			expect(THREAD_TOO_LONG).toMatch(/reload/i);
			expect(THREAD_TOO_LONG).not.toMatch(/[<>_]/);
		});

		it('is refused only if pages are still to be read: a thread that ends on the last page allowed is read', async () => {
			for (const pages of [1, 2, 3]) {
				const { listPage } = server(many(pages), 1);
				const read = await fetchMessages(listPage, { maxPages: 3 });
				expect(read, `${pages} pages`).toHaveLength(pages);
				expect(listPage).toHaveBeenCalledTimes(pages);
			}
		});

		it('is refused as soon as there is one page more than the guard allows', async () => {
			const { listPage } = server(many(4), 1);
			await expect(fetchMessages(listPage, { maxPages: 3 })).rejects.toThrow(THREAD_TOO_LONG);
			expect(listPage).toHaveBeenCalledTimes(3);
		});

		it('is read when the message looked for is on the last page allowed, and refused when it is past it', async () => {
			const found = server(many(10), 1);
			const read = await fetchMessages(found.listPage, { maxPages: 3, stopAtId: 'm2' });
			expect(read.map((item) => item.id)).toEqual(['m0', 'm1', 'm2']);
			const past = server(many(10), 1);
			await expect(fetchMessages(past.listPage, { maxPages: 3, stopAtId: 'm3' })).rejects.toThrow(
				THREAD_TOO_LONG
			);
		});

		it('is refused without being asked to look for anything, however many messages a page holds', async () => {
			const { listPage } = server(many(50), 10);
			await expect(fetchMessages(listPage, { maxPages: 4 })).rejects.toThrow(THREAD_TOO_LONG);
			expect(listPage).toHaveBeenCalledTimes(4);
		});

		it('does not stop a cursor that repeats from ending the read quietly, as it always has', async () => {
			const listPage = vi.fn(
				async (): Promise<MessagePage> => ({ items: [message('x')], next_cursor: 'same' })
			);
			await expect(fetchMessages(listPage, { maxPages: 3 })).resolves.toHaveLength(2);
			expect(listPage).toHaveBeenCalledTimes(2);
		});
	});

	it('fails when a page fails, rather than returning part of a thread as if it were all of it', async () => {
		const failure = new Error('502 Bad Gateway');
		const listPage = vi
			.fn<[cursor?: string], Promise<MessagePage>>()
			.mockResolvedValueOnce({ items: many(2), next_cursor: 'next' })
			.mockRejectedValueOnce(failure);
		await expect(fetchMessages(listPage)).rejects.toBe(failure);
		expect(listPage).toHaveBeenCalledTimes(2);
	});
});

describe('replaceMessage', () => {
	it('puts the fresh copy where the old one was and keeps every other message exactly as it was', () => {
		const list = many(4);
		const fresh = message('m2', { content: 'the delivered answer' });
		const replaced = replaceMessage(list, fresh);
		expect(replaced).toHaveLength(4);
		expect(replaced[2]).toBe(fresh);
		for (const position of [0, 1, 3]) expect(replaced[position]).toBe(list[position]);
		expect(replaced.map((item) => item.id)).toEqual(['m0', 'm1', 'm2', 'm3']);
	});

	it('does not change the list it was given', () => {
		const list = many(3);
		const before = [...list];
		const replaced = replaceMessage(list, message('m1', { content: 'new' }));
		expect(replaced).not.toBe(list);
		expect(list).toEqual(before);
		list.forEach((item, position) => expect(item).toBe(before[position]));
	});

	it('adds nothing when the message is not in the thread', () => {
		const list = many(3);
		const replaced = replaceMessage(list, message('elsewhere'));
		expect(replaced).toHaveLength(3);
		replaced.forEach((item, position) => expect(item).toBe(list[position]));
	});

	it('works on an empty thread', () => {
		expect(replaceMessage([], message('m0'))).toEqual([]);
	});

	it('swaps a run message that held no answer for the one that does, in a recorded thread', () => {
		const started = thread('planning');
		const delivered = thread('completed');
		expect(started[1].id).toBe(delivered[1].id);
		expect(started[1].content).toBe('');
		const replaced = replaceMessage(started, delivered[1]);
		expect(replaced[0]).toBe(started[0]);
		expect(replaced[1]).toBe(delivered[1]);
		expect(replaced[1].content).toContain('Renewal requires 30 days');
		expect(replaced[1].kind).toBe('run');
	});
});

describe('the recorded threads and runs', () => {
	const NAMES = [
		'planning',
		'completed',
		'documents.completed',
		'partial',
		'closed',
		'stopped'
	] as const;

	it.each(NAMES)('thread.%s: only a run message names a run, and the run names it back', (name) => {
		const messages = thread(name);
		const runs = allRuns().map((entry) => entry.run);
		let named = 0;
		for (const item of messages) {
			if (item.kind !== 'run') {
				// An ordinary turn is bound to no run, and so can produce neither a link nor a read.
				expect(item.autonomous_session_id, `${item.role} ${item.id}`).toBeNull();
				continue;
			}
			named += 1;
			expect(typeof item.autonomous_session_id).toBe('string');
			expect(item.autonomous_session_id).toMatch(
				/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
			);
			const bound = runs.filter((candidate) => candidate.root_id === item.autonomous_session_id);
			expect(bound.length, item.id).toBeGreaterThan(0);
			for (const candidate of bound) {
				expect(candidate.message_id).toBe(item.id);
				expect(candidate.chat_id).toBe(item.chat_id);
			}
		}
		expect(named).toBeGreaterThan(0);
	});

	it('holds no answer in a run message until the run delivers one', () => {
		for (const name of ['planning', 'closed', 'stopped'] as const) {
			for (const item of thread(name).filter((entry) => entry.kind === 'run')) {
				expect(item.content, `${name} ${item.id}`).toBe('');
			}
		}
		for (const name of ['completed', 'documents.completed', 'partial'] as const) {
			for (const item of thread(name).filter((entry) => entry.kind === 'run')) {
				expect(item.content.length, `${name} ${item.id}`).toBeGreaterThan(0);
			}
		}
	});
});
