/**
 * Reading a chat's thread back from the server.
 *
 * The messages list is oldest-first and cursor-paginated, with no read of a single
 * message, so to see a run message that was just created or just delivered the
 * pages are read until it turns up.
 */
import type { Message } from '../types';

export interface MessagePage {
	items: Message[];
	next_cursor: string | null;
}

/** A guard against a misbehaving cursor; 100 messages a page. */
export const MAX_THREAD_PAGES = 50;

/** Thrown when the guard is reached with pages still to read. */
export const THREAD_TOO_LONG =
	'This thread is too long to read in full here. Reload the chat to see its latest messages.';

/**
 * Read a chat's messages. With `stopAtId`, stop as soon as that message has been
 * read; otherwise read every page.
 */
export async function fetchMessages(
	listPage: (cursor?: string) => Promise<MessagePage>,
	options: { stopAtId?: string; maxPages?: number } = {}
): Promise<Message[]> {
	const limit = options.maxPages ?? MAX_THREAD_PAGES;
	const all: Message[] = [];
	let cursor: string | undefined;
	for (let page = 0; ; page += 1) {
		// The newest messages are on the last pages, so a part of the thread is not
		// returned as if it were all of it.
		if (page >= limit) throw new Error(THREAD_TOO_LONG);
		const result = await listPage(cursor);
		all.push(...result.items);
		if (options.stopAtId && result.items.some((item) => item.id === options.stopAtId)) break;
		if (!result.next_cursor || result.next_cursor === cursor) break;
		cursor = result.next_cursor;
	}
	return all;
}

/** The thread with one message swapped for its fresh copy. Other messages keep their identity. */
export function replaceMessage(list: Message[], fresh: Message): Message[] {
	return list.map((message) => (message.id === fresh.id ? fresh : message));
}
