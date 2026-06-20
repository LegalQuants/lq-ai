/**
 * Server-Sent Events parser for the `POST /api/v1/chats/{id}/messages`
 * streaming response.
 *
 * The wire format is OpenAI-style `data: <json>` lines terminated by
 * `data: [DONE]`. Each JSON payload is a `MessageStreamEvent` per the
 * backend OpenAPI sketch (`MessageStart` / `MessageDelta` / `MessageComplete`
 * / `Error`).
 *
 * We use `eventsource-parser/stream` which is already a transitive dep via
 * the OpenWebUI shell's `lib/apis/streaming/`. The wrapper below is typed
 * and emits `MessageStreamEvent`s rather than raw strings.
 */
import { EventSourceParserStream } from 'eventsource-parser/stream';
import type { ParsedEvent } from 'eventsource-parser';

import type { MessageStreamEvent, MessageErrorFrame } from '../types';

/** Hand-rolled minimal SSE line parser used as a fallback in tests. */
export function parseSseLineForTest(line: string): MessageStreamEvent | null {
	if (!line.startsWith('data:')) return null;
	const raw = line.slice('data:'.length).trim();
	if (raw === '' || raw === '[DONE]') return null;
	try {
		return normalizeFrame(JSON.parse(raw));
	} catch {
		return null;
	}
}

/**
 * Normalise a parsed JSON payload into a `MessageStreamEvent`. Backend
 * variations (e.g., `error` envelopes that lack the `type: 'error'` tag) are
 * coerced into the canonical `oneOf` shape so consumers can switch on `.type`.
 */
export function normalizeFrame(raw: unknown): MessageStreamEvent | null {
	if (typeof raw !== 'object' || raw === null) return null;
	const obj = raw as Record<string, unknown>;

	// Canonical `type` discriminator path.
	if (typeof obj.type === 'string') {
		switch (obj.type) {
			case 'start':
			case 'delta':
			case 'complete':
				return obj as unknown as MessageStreamEvent;
			case 'tool_confirmation_required':
			case 'mcp_authorization_required':
				return obj as unknown as MessageStreamEvent;
			case 'error':
				return obj as unknown as MessageErrorFrame;
			default:
				return null;
		}
	}

	// Bare `Error` envelope (per `Error` schema): { detail: { code, message, ... } }.
	if (obj.detail && typeof obj.detail === 'object') {
		const detail = obj.detail as Record<string, unknown>;
		return {
			type: 'error',
			error: {
				code: typeof detail.code === 'string' ? detail.code : 'unknown',
				message:
					typeof detail.message === 'string' ? detail.message : 'Stream ended in failure',
				details:
					typeof detail.details === 'object' && detail.details !== null
						? (detail.details as Record<string, unknown>)
						: undefined
			}
		};
	}

	// Some emitters use `error: {...}` directly.
	if (obj.error && typeof obj.error === 'object') {
		const err = obj.error as Record<string, unknown>;
		return {
			type: 'error',
			error: {
				code: typeof err.code === 'string' ? err.code : 'unknown',
				message:
					typeof err.message === 'string' ? err.message : 'Stream ended in failure',
				details:
					typeof err.details === 'object' && err.details !== null
						? (err.details as Record<string, unknown>)
						: undefined
			}
		};
	}

	return null;
}

export interface MessageStreamCallbacks {
	onStart?: (frame: import('../types').MessageStartFrame) => void;
	onDelta?: (frame: import('../types').MessageDeltaFrame) => void;
	onComplete?: (frame: import('../types').MessageCompleteFrame) => void;
	onError?: (frame: import('../types').MessageErrorFrame) => void;
	onToolConfirmation?: (frame: import('../types').ToolConfirmationRequiredFrame) => void;
	onMcpAuthorization?: (frame: import('../types').McpAuthorizationRequiredFrame) => void;
}

/**
 * Consume a streaming response body, dispatching typed callbacks per event.
 * The returned promise resolves when the stream ends (clean or `[DONE]`).
 *
 * Mid-stream errors (`type: error`) invoke `onError` and end the iteration;
 * the caller decides whether to surface the partial assistant content.
 */
export async function consumeMessageStream(
	body: ReadableStream<Uint8Array>,
	callbacks: MessageStreamCallbacks
): Promise<void> {
	// TextDecoderStream's writable is typed as WritableStream<BufferSource> in
	// the lib.dom types, not WritableStream<Uint8Array>; a single cast through
	// unknown is the standard workaround for this interop pinch.
	const reader = body
		.pipeThrough(new TextDecoderStream() as unknown as ReadableWritablePair<string, Uint8Array>)
		.pipeThrough(new EventSourceParserStream())
		.getReader();

	while (true) {
		const { value, done } = await reader.read();
		if (done) break;
		if (!value) continue;
		const event = value as ParsedEvent;
		const data = event.data;
		if (!data || data === '[DONE]') {
			break;
		}
		let frame: MessageStreamEvent | null = null;
		try {
			frame = normalizeFrame(JSON.parse(data));
		} catch {
			frame = null;
		}
		if (!frame) continue;
		switch (frame.type) {
			case 'start':
				callbacks.onStart?.(frame);
				break;
			case 'delta':
				callbacks.onDelta?.(frame);
				break;
			case 'complete':
				callbacks.onComplete?.(frame);
				break;
			case 'tool_confirmation_required':
				callbacks.onToolConfirmation?.(frame);
				return;
			case 'mcp_authorization_required':
				callbacks.onMcpAuthorization?.(frame);
				return;
			case 'error':
				callbacks.onError?.(frame);
				return;
		}
	}
}
