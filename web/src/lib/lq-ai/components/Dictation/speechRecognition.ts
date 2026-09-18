/**
 * Thin wrapper around the browser's Web Speech API (DE-015).
 *
 * Scope: browser-side dictation only (PRD §9 DE-015) — no server STT.
 * `SpeechRecognition` isn't part of TypeScript's DOM lib (still
 * vendor-prefixed/experimental), so this file owns the minimal ambient
 * shape it needs rather than pulling in a `@types/*` package for it.
 * Isolating the vendor branching here (instead of inline in
 * DictationButton.svelte) is what makes it mockable in Vitest, where
 * jsdom has no Speech API at all.
 */

interface SpeechRecognitionResultLike {
	readonly isFinal: boolean;
	readonly 0: { readonly transcript: string };
}

interface SpeechRecognitionEventLike {
	readonly resultIndex: number;
	readonly results: ArrayLike<SpeechRecognitionResultLike>;
}

interface SpeechRecognitionErrorEventLike {
	readonly error: string;
}

interface SpeechRecognitionLike {
	continuous: boolean;
	interimResults: boolean;
	lang: string;
	start(): void;
	stop(): void;
	abort(): void;
	onresult: ((event: SpeechRecognitionEventLike) => void) | null;
	onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
	onend: (() => void) | null;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
	// `globalThis` rather than `window` — identical in a real browser, but
	// lets this be exercised in Vitest's default node environment by
	// stubbing the constructor on `globalThis` (no jsdom dependency needed).
	const g = globalThis as unknown as {
		SpeechRecognition?: SpeechRecognitionCtor;
		webkitSpeechRecognition?: SpeechRecognitionCtor;
	};
	return g.SpeechRecognition ?? g.webkitSpeechRecognition ?? null;
}

/** Chrome and Safari (14.1+) expose one of these; Firefox exposes neither. */
export function isDictationSupported(): boolean {
	return getSpeechRecognitionCtor() !== null;
}

export type DictationErrorReason = 'no-speech' | 'not-allowed' | 'aborted' | 'other';

export interface DictationHandlers {
	/** Fired repeatedly with the best-guess transcript while speech is still being recognized. */
	onInterim: (transcript: string) => void;
	/** Fired once per completed utterance with its finalized transcript. */
	onFinal: (transcript: string) => void;
	onError: (reason: DictationErrorReason, rawError: string) => void;
	/** Recognition session ended, whether via stop(), silence, or error. */
	onEnd: () => void;
}

export interface DictationSession {
	stop: () => void;
}

function toErrorReason(rawError: string): DictationErrorReason {
	if (rawError === 'no-speech') return 'no-speech';
	if (rawError === 'not-allowed' || rawError === 'service-not-allowed') return 'not-allowed';
	if (rawError === 'aborted') return 'aborted';
	return 'other';
}

/**
 * Starts a recognition session. Returns null (and calls onError) if the
 * browser has no Web Speech API — callers should already be gating the
 * mic button on `isDictationSupported()`, so this is a defensive fallback.
 */
export function startDictation(
	handlers: DictationHandlers,
	language?: string
): DictationSession | null {
	const Ctor = getSpeechRecognitionCtor();
	if (!Ctor) {
		handlers.onError('other', 'SpeechRecognition is not supported in this browser');
		return null;
	}

	const recognition = new Ctor();
	recognition.continuous = true;
	recognition.interimResults = true;
	if (language) recognition.lang = language;

	recognition.onresult = (event) => {
		for (let i = event.resultIndex; i < event.results.length; i++) {
			const result = event.results[i];
			const transcript = result[0].transcript;
			if (result.isFinal) {
				handlers.onFinal(transcript);
			} else {
				handlers.onInterim(transcript);
			}
		}
	};

	recognition.onerror = (event) => {
		handlers.onError(toErrorReason(event.error), event.error);
	};

	recognition.onend = () => {
		handlers.onEnd();
	};

	recognition.start();

	return {
		stop: () => recognition.stop()
	};
}
