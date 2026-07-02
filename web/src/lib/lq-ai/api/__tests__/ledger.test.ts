import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { getChatLedger } from '../ledger';

function jsonResponseLike(status: number, body: unknown) {
	return {
		ok: status >= 200 && status < 300,
		status,
		headers: {
			get: (n: string) => (n.toLowerCase() === 'content-type' ? 'application/json' : null)
		},
		json: async () => body
	};
}

describe('ledger API client', () => {
	const fetchMock = vi.fn();
	let originalFetch: typeof globalThis.fetch;
	beforeEach(() => {
		originalFetch = globalThis.fetch;
		globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
		fetchMock.mockReset();
	});
	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	it('GETs /chats/{id}/ledger with no message filter', async () => {
		fetchMock.mockResolvedValue(jsonResponseLike(200, { chat_id: 'c1', entries: [], gates: [] }));
		const out = await getChatLedger('c1');
		expect(out.chat_id).toBe('c1');
		const url = fetchMock.mock.calls[0][0] as string;
		expect(url).toContain('/chats/c1/ledger');
		expect(url).not.toContain('message_id');
	});

	it('appends ?message_id when given (encoded)', async () => {
		fetchMock.mockResolvedValue(jsonResponseLike(200, { chat_id: 'c1', entries: [], gates: [] }));
		await getChatLedger('c1', 'm 1');
		const url = fetchMock.mock.calls[0][0] as string;
		expect(url).toContain('/chats/c1/ledger?message_id=m%201');
	});
});
