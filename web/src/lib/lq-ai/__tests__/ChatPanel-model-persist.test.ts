/**
 * Regression test for the model-selection-persist-refresh bugfix.
 *
 * Convention note: mirrors ReceiptsDrawer.test.ts exactly — pure
 * localStorage helpers exported from <script context="module"> in the
 * .svelte file, exercised here with an injectable MockStorage, without
 * mounting the (large) component (@testing-library/svelte is unavailable
 * for this file — see ChatPanel-slash-detect.test.ts header).
 *
 * Bug: modelByChat was a component-local Record with no persistence, so a
 * full page refresh remounted the component, reset modelByChat to {}, and
 * currentModelId's reactive fallback silently picked the picker's default
 * — discarding the user's chosen model for that chat.
 */
import { describe, it, expect } from 'vitest';
import {
	modelStorageKeyForChat,
	readPersistedModel,
	writePersistedModel,
	readAvailablePersistedModel
} from '../components/ChatPanel.svelte';

class MockStorage implements Storage {
	private map = new Map<string, string>();
	get length() {
		return this.map.size;
	}
	key(i: number): string | null {
		return Array.from(this.map.keys())[i] ?? null;
	}
	getItem(k: string): string | null {
		return this.map.get(k) ?? null;
	}
	setItem(k: string, v: string): void {
		this.map.set(k, v);
	}
	removeItem(k: string): void {
		this.map.delete(k);
	}
	clear(): void {
		this.map.clear();
	}
}

/**
 * A Storage whose getItem/setItem throw, modelling Safari private mode, a
 * disabled-storage policy, or a quota-exceeded write. The helpers must
 * swallow the exception so chat selection keeps working.
 */
class ThrowingStorage implements Storage {
	get length(): number {
		return 0;
	}
	key(): string | null {
		return null;
	}
	getItem(): string | null {
		throw new DOMException('getItem blocked', 'SecurityError');
	}
	setItem(): void {
		throw new DOMException('QuotaExceededError', 'QuotaExceededError');
	}
	removeItem(): void {
		throw new DOMException('removeItem blocked', 'SecurityError');
	}
	clear(): void {
		throw new DOMException('clear blocked', 'SecurityError');
	}
}

describe('modelStorageKeyForChat', () => {
	it('namespaces by chat ID', () => {
		expect(modelStorageKeyForChat('c1')).toBe('lq_ai_chat_model_c1');
		expect(modelStorageKeyForChat('uuid-here')).toBe('lq_ai_chat_model_uuid-here');
	});
});

describe('readPersistedModel', () => {
	it('returns null for an unset chat', () => {
		const s = new MockStorage();
		expect(readPersistedModel('c1', s)).toBeNull();
	});

	it('returns the persisted model id', () => {
		const s = new MockStorage();
		s.setItem(modelStorageKeyForChat('c1'), 'anthropic-prod/claude-opus-4-8');
		expect(readPersistedModel('c1', s)).toBe('anthropic-prod/claude-opus-4-8');
	});

	it('scopes reads per chat id (no cross-chat bleed)', () => {
		const s = new MockStorage();
		s.setItem(modelStorageKeyForChat('c1'), 'model-a');
		s.setItem(modelStorageKeyForChat('c2'), 'model-b');
		expect(readPersistedModel('c1', s)).toBe('model-a');
		expect(readPersistedModel('c2', s)).toBe('model-b');
	});
});

describe('writePersistedModel', () => {
	it('writes the model id under the chat-scoped key', () => {
		const s = new MockStorage();
		writePersistedModel('c1', 'openai-prod/gpt-5', s);
		expect(s.getItem(modelStorageKeyForChat('c1'))).toBe('openai-prod/gpt-5');
	});

	it('overwrites a prior selection for the same chat', () => {
		const s = new MockStorage();
		writePersistedModel('c1', 'model-a', s);
		writePersistedModel('c1', 'model-b', s);
		expect(readPersistedModel('c1', s)).toBe('model-b');
	});
});

describe('write→read round-trip', () => {
	it('survives a simulated refresh (new read using the same backing store)', () => {
		const s = new MockStorage();
		writePersistedModel('c1', 'anthropic-prod/claude-opus-4-8', s);
		// Simulate remount: a fresh read against the same storage instance
		// (localStorage itself survives a page refresh; only in-memory state
		// like modelByChat does not).
		expect(readPersistedModel('c1', s)).toBe('anthropic-prod/claude-opus-4-8');
	});
});

describe('Storage failure is non-fatal', () => {
	it('readPersistedModel returns null when getItem throws', () => {
		expect(readPersistedModel('c1', new ThrowingStorage())).toBeNull();
	});

	it('writePersistedModel swallows a throwing setItem (no exception)', () => {
		expect(() =>
			writePersistedModel('c1', 'anthropic-prod/claude-opus-4-8', new ThrowingStorage())
		).not.toThrow();
	});
});

describe('readAvailablePersistedModel', () => {
	it('returns the persisted id when it is still in the catalog', () => {
		const s = new MockStorage();
		s.setItem(modelStorageKeyForChat('c1'), 'anthropic-prod/claude-opus-4-8');
		expect(
			readAvailablePersistedModel(
				'c1',
				['smart', 'anthropic-prod/claude-opus-4-8', 'openai-prod/gpt-5'],
				s
			)
		).toBe('anthropic-prod/claude-opus-4-8');
	});

	it('returns null when the persisted id is no longer in the catalog', () => {
		const s = new MockStorage();
		s.setItem(modelStorageKeyForChat('c1'), 'anthropic-prod/claude-opus-4-7');
		expect(
			readAvailablePersistedModel('c1', ['smart', 'anthropic-prod/claude-opus-4-8'], s)
		).toBeNull();
	});
});
