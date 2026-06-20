/**
 * /api/v1/chats/{chat_id}/messages — list + send.
 *
 * `sendMessageStream` returns the raw `Response` whose body is consumed by
 * `lq-ai/sse/parser.ts`. `sendMessage` is the non-streaming JSON shape.
 */
import { apiRequest, apiStreamRequest } from './client';
import type { MessageCreate, MessagePostResponse, PaginatedMessages } from '../types';

export interface ListMessagesOptions {
	cursor?: string;
	limit?: number;
}

/** GET /api/v1/chats/{chat_id}/messages — cursor-paginated, oldest-first. */
export async function listMessages(
	chatId: string,
	opts: ListMessagesOptions = {}
): Promise<PaginatedMessages> {
	const params = new URLSearchParams();
	if (opts.cursor) params.set('cursor', opts.cursor);
	if (opts.limit) params.set('limit', String(opts.limit));
	const qs = params.toString();
	return apiRequest<PaginatedMessages>(
		`/chats/${encodeURIComponent(chatId)}/messages${qs ? `?${qs}` : ''}`
	);
}

/**
 * Non-streaming POST /messages. Caller passes `stream: false` (or omits it).
 */
export async function sendMessage(
	chatId: string,
	body: MessageCreate
): Promise<MessagePostResponse> {
	return apiRequest<MessagePostResponse>(
		`/chats/${encodeURIComponent(chatId)}/messages`,
		{ method: 'POST', body: { ...body, stream: false } }
	);
}

/**
 * Streaming POST /messages. Returns the raw `Response`; caller pipes
 * `res.body` into `parseMessageStream` from `../sse/parser.ts`.
 */
export async function sendMessageStream(
	chatId: string,
	body: MessageCreate,
	signal?: AbortSignal
): Promise<Response> {
	return apiStreamRequest(`/chats/${encodeURIComponent(chatId)}/messages`, {
		method: 'POST',
		body: { ...body, stream: true },
		stream: true,
		signal
	});
}

/**
 * Resume a paused tool-loop turn after the user approves/denies a destructive
 * tool. POST /api/v1/chats/{chat_id}/tool-calls/{pending_call_id}; returns the
 * raw `Response` whose body is a fresh SSE stream (same frames as a send).
 * Throws (errorFor) on non-2xx — a 409/410 means the pending call expired or
 * was already resolved.
 */
export async function resumeToolCall(
	chatId: string,
	pendingCallId: string,
	decision: 'approve' | 'deny',
	signal?: AbortSignal
): Promise<Response> {
	return apiStreamRequest(
		`/chats/${encodeURIComponent(chatId)}/tool-calls/${encodeURIComponent(pendingCallId)}`,
		{ method: 'POST', body: { decision }, stream: true, signal }
	);
}
