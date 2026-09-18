/**
 * Unit tests for the Web Speech API wrapper (DE-015).
 *
 * Runs in Vitest's default node environment (no jsdom dependency) — the
 * wrapper reads its constructor off `globalThis` rather than `window` so
 * a mock can be stubbed there directly, then driven by calling its
 * `onresult`/`onerror`/`onend` handlers to mimic the real Chrome/Safari
 * implementation's callbacks.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { isDictationSupported, startDictation } from '../components/Dictation/speechRecognition';

/** Every constructed instance is pushed here so tests can reach in and fire callbacks. */
const instances: MockSpeechRecognition[] = [];

class MockSpeechRecognition {
	continuous = false;
	interimResults = false;
	lang = '';
	onresult: ((event: unknown) => void) | null = null;
	onerror: ((event: unknown) => void) | null = null;
	onend: (() => void) | null = null;
	start = vi.fn();
	stop = vi.fn(() => this.onend?.());
	abort = vi.fn();

	constructor() {
		instances.push(this);
	}
}

function lastInstance(): MockSpeechRecognition {
	const instance = instances[instances.length - 1];
	if (!instance) throw new Error('no MockSpeechRecognition instance was constructed');
	return instance;
}

function makeResult(transcript: string, isFinal: boolean) {
	return Object.assign([{ transcript }], { isFinal });
}

afterEach(() => {
	delete (globalThis as unknown as Record<string, unknown>).SpeechRecognition;
	delete (globalThis as unknown as Record<string, unknown>).webkitSpeechRecognition;
	instances.length = 0;
	vi.restoreAllMocks();
});

describe('isDictationSupported', () => {
	it('returns false when neither constructor is present', () => {
		expect(isDictationSupported()).toBe(false);
	});

	it('returns true when the unprefixed SpeechRecognition constructor is present', () => {
		(globalThis as unknown as Record<string, unknown>).SpeechRecognition = MockSpeechRecognition;
		expect(isDictationSupported()).toBe(true);
	});

	it('returns true when only the webkit-prefixed constructor is present (Safari)', () => {
		(globalThis as unknown as Record<string, unknown>).webkitSpeechRecognition =
			MockSpeechRecognition;
		expect(isDictationSupported()).toBe(true);
	});
});

describe('startDictation', () => {
	it('reports unsupported via onError and returns null when no constructor exists', () => {
		const onError = vi.fn();
		const session = startDictation({
			onInterim: vi.fn(),
			onFinal: vi.fn(),
			onError,
			onEnd: vi.fn()
		});

		expect(session).toBeNull();
		expect(onError).toHaveBeenCalledWith('other', expect.any(String));
	});

	it('maps known SpeechRecognition error codes to typed reasons', () => {
		(globalThis as unknown as Record<string, unknown>).SpeechRecognition = MockSpeechRecognition;

		const onError = vi.fn();
		startDictation({
			onInterim: vi.fn(),
			onFinal: vi.fn(),
			onError,
			onEnd: vi.fn()
		});
		const instance = lastInstance();

		instance.onerror?.({ error: 'not-allowed' });
		expect(onError).toHaveBeenCalledWith('not-allowed', 'not-allowed');

		instance.onerror?.({ error: 'no-speech' });
		expect(onError).toHaveBeenCalledWith('no-speech', 'no-speech');

		instance.onerror?.({ error: 'weird-vendor-code' });
		expect(onError).toHaveBeenCalledWith('other', 'weird-vendor-code');
	});

	it('calls stop() on the underlying recognition instance when session.stop() is invoked', () => {
		(globalThis as unknown as Record<string, unknown>).SpeechRecognition = MockSpeechRecognition;

		const session = startDictation({
			onInterim: vi.fn(),
			onFinal: vi.fn(),
			onError: vi.fn(),
			onEnd: vi.fn()
		});

		session?.stop();
		expect(lastInstance().stop).toHaveBeenCalled();
	});

	it('emits final results via onFinal and interim via onInterim from onresult', () => {
		(globalThis as unknown as Record<string, unknown>).SpeechRecognition = MockSpeechRecognition;

		const onInterim = vi.fn();
		const onFinal = vi.fn();
		startDictation({
			onInterim,
			onFinal,
			onError: vi.fn(),
			onEnd: vi.fn()
		});

		lastInstance().onresult?.({
			resultIndex: 0,
			results: [makeResult('hello', false), makeResult('hello world', true)]
		});

		expect(onInterim).toHaveBeenCalledWith('hello');
		expect(onFinal).toHaveBeenCalledWith('hello world');
	});
});
