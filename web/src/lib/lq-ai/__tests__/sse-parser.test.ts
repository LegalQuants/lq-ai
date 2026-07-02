/**
 * Unit tests for the LQ.AI SSE consumer.
 *
 * Covers:
 * - Each frame variant (start / delta / complete / error) parses to the
 *   right discriminator.
 * - `data: [DONE]` terminates the stream cleanly.
 * - Malformed JSON is dropped silently.
 * - Bare `Error` envelopes (no `type` field) are coerced to error frames.
 */
import { describe, it, expect, vi } from 'vitest';

import { consumeMessageStream, normalizeFrame, parseSseLineForTest } from '../sse/parser';
import type {
	MessageCompleteFrame,
	MessageDeltaFrame,
	MessageErrorFrame,
	MessageStartFrame
} from '../types';

function streamFromLines(lines: string[]): ReadableStream<Uint8Array> {
	const enc = new TextEncoder();
	return new ReadableStream<Uint8Array>({
		start(controller) {
			for (const line of lines) {
				controller.enqueue(enc.encode(line + '\n'));
			}
			controller.close();
		}
	});
}

describe('parseSseLineForTest', () => {
	it('parses a typed start frame', () => {
		const f = parseSseLineForTest(
			'data: {"type":"start","lq_ai_message_id":"abc","chat_id":"c1"}'
		) as MessageStartFrame | null;
		expect(f).not.toBeNull();
		expect(f!.type).toBe('start');
		expect(f!.lq_ai_message_id).toBe('abc');
	});

	it('parses a delta frame with applied_skills', () => {
		const f = parseSseLineForTest(
			'data: {"type":"delta","delta":"hi","lq_ai_message_id":"abc","applied_skills":["nda-review"],"routed_inference_tier":4}'
		) as MessageDeltaFrame | null;
		expect(f!.type).toBe('delta');
		expect(f!.delta).toBe('hi');
		expect(f!.applied_skills).toEqual(['nda-review']);
		expect(f!.routed_inference_tier).toBe(4);
	});

	it('returns null on [DONE]', () => {
		expect(parseSseLineForTest('data: [DONE]')).toBeNull();
	});

	it('returns null on malformed JSON', () => {
		expect(parseSseLineForTest('data: {oops')).toBeNull();
	});

	it('returns null on non-data lines', () => {
		expect(parseSseLineForTest('event: ping')).toBeNull();
	});
});

describe('normalizeFrame', () => {
	it('coerces a bare detail-envelope error', () => {
		const f = normalizeFrame({
			detail: { code: 'gateway_timeout', message: 'gw timed out' }
		}) as MessageErrorFrame | null;
		expect(f).not.toBeNull();
		expect(f!.type).toBe('error');
		expect(f!.error.code).toBe('gateway_timeout');
		expect(f!.error.message).toBe('gw timed out');
	});

	it('coerces a bare error envelope (no detail wrapper)', () => {
		const f = normalizeFrame({
			error: { code: 'provider_unavailable', message: 'no key' }
		}) as MessageErrorFrame | null;
		expect(f!.type).toBe('error');
		expect(f!.error.code).toBe('provider_unavailable');
	});

	it('returns null on unrecognised payloads', () => {
		expect(normalizeFrame({ random: 'payload' })).toBeNull();
		expect(normalizeFrame(null)).toBeNull();
	});
});

describe('consumeMessageStream', () => {
	it('dispatches start → delta → complete in order and stops at [DONE]', async () => {
		const onStart = vi.fn();
		const onDelta = vi.fn();
		const onComplete = vi.fn();

		const body = streamFromLines([
			'data: {"type":"start","lq_ai_message_id":"a","chat_id":"c"}',
			'',
			'data: {"type":"delta","delta":"hello ","lq_ai_message_id":"a"}',
			'',
			'data: {"type":"delta","delta":"world","lq_ai_message_id":"a"}',
			'',
			'data: {"type":"complete","lq_ai_message_id":"a","message":{"id":"a","chat_id":"c","role":"assistant","content":"hello world","created_at":"2025-01-01T00:00:00Z"}}',
			'',
			'data: [DONE]',
			''
		]);

		await consumeMessageStream(body, { onStart, onDelta, onComplete });
		expect(onStart).toHaveBeenCalledTimes(1);
		expect(onDelta).toHaveBeenCalledTimes(2);
		expect(onComplete).toHaveBeenCalledTimes(1);
		const completeFrame = onComplete.mock.calls[0][0] as MessageCompleteFrame;
		expect(completeFrame.message.content).toBe('hello world');
	});

	it('dispatches an onError and stops on a mid-stream error frame', async () => {
		const onDelta = vi.fn();
		const onError = vi.fn();
		const onComplete = vi.fn();

		const body = streamFromLines([
			'data: {"type":"delta","delta":"partial ","lq_ai_message_id":"a"}',
			'',
			'data: {"type":"error","error":{"code":"provider_unavailable","message":"down"}}',
			'',
			'data: {"type":"delta","delta":"never","lq_ai_message_id":"a"}',
			'',
			'data: [DONE]',
			''
		]);
		await consumeMessageStream(body, { onDelta, onError, onComplete });
		expect(onDelta).toHaveBeenCalledTimes(1);
		expect(onError).toHaveBeenCalledTimes(1);
		expect(onComplete).not.toHaveBeenCalled();
	});

	it('drops malformed lines without throwing', async () => {
		const onDelta = vi.fn();
		const body = streamFromLines([
			'data: not-json',
			'',
			'data: {"type":"delta","delta":"x","lq_ai_message_id":"a"}',
			'',
			'data: [DONE]',
			''
		]);
		await consumeMessageStream(body, { onDelta });
		expect(onDelta).toHaveBeenCalledTimes(1);
	});

	it('dispatches onToolConfirmation and terminates the stream', async () => {
		const frame = {
			type: 'tool_confirmation_required',
			lq_ai_message_id: 'm1',
			pending_call_id: 'p1',
			provider: 'files',
			tool: 'delete_doc',
			function_name: 'mcp__files__delete_doc',
			args_summary: '{path:/x}',
			tier: 2,
			destructive: true
		};
		const body = streamFromLines([
			'data: ' + JSON.stringify(frame),
			'',
			'data: {"type":"delta","delta":"X","lq_ai_message_id":"m1"}',
			'',
			'data: [DONE]',
			''
		]);
		const calls: string[] = [];
		await consumeMessageStream(body, {
			onToolConfirmation: () => calls.push('confirm'),
			onDelta: () => calls.push('delta')
		});
		expect(calls).toEqual(['confirm']); // terminal: the trailing delta is never dispatched
	});

	it('dispatches onMcpAuthorization and terminates the stream', async () => {
		const frame = {
			type: 'mcp_authorization_required',
			lq_ai_message_id: 'm1',
			server: 'files',
			authorize_url: '/api/v1/mcp/oauth/files/authorize'
		};
		const body = streamFromLines([
			'data: ' + JSON.stringify(frame),
			'',
			'data: {"type":"delta","delta":"X","lq_ai_message_id":"m1"}',
			'',
			'data: [DONE]',
			''
		]);
		const calls: string[] = [];
		await consumeMessageStream(body, {
			onMcpAuthorization: () => calls.push('auth'),
			onDelta: () => calls.push('delta')
		});
		expect(calls).toEqual(['auth']);
	});

	it('normalizeFrame accepts the two new types', () => {
		expect(normalizeFrame({ type: 'tool_confirmation_required', pending_call_id: 'p1' })?.type).toBe(
			'tool_confirmation_required'
		);
		expect(normalizeFrame({ type: 'mcp_authorization_required', server: 's' })?.type).toBe(
			'mcp_authorization_required'
		);
	});
});
