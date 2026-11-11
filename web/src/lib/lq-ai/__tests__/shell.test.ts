import { describe, expect, it } from 'vitest';
import { SHELL_SWITCH_KEY, readShellSwitch } from '../shell';

function storageWith(value: string | null) {
	const reads: string[] = [];
	return {
		reads,
		get: () => ({
			getItem: (key: string) => {
				reads.push(key);
				return value;
			}
		})
	};
}

describe('readShellSwitch (developer-only sidebar switch)', () => {
	it('selects the sidebar only for the exact value under lq-ai.shell', () => {
		const store = storageWith('sidebar');
		expect(readShellSwitch(store.get)).toBe('sidebar');
		expect(store.reads).toEqual([SHELL_SWITCH_KEY]);
		expect(SHELL_SWITCH_KEY).toBe('lq-ai.shell');
	});

	it('keeps today’s chrome when the switch is unset or holds anything else', () => {
		for (const value of [null, '', 'tabs', 'Sidebar', ' sidebar', 'true', '1'])
			expect(readShellSwitch(storageWith(value).get)).toBe('tabs');
	});

	it('keeps today’s chrome when there is no storage (server-side rendering)', () => {
		expect(readShellSwitch(() => undefined)).toBe('tabs');
		// The default accessor runs under vitest's node environment: no window.
		expect(readShellSwitch()).toBe('tabs');
	});

	it('keeps today’s chrome when reaching or reading storage throws', () => {
		expect(
			readShellSwitch(() => {
				throw new DOMException('blocked', 'SecurityError');
			})
		).toBe('tabs');
		expect(
			readShellSwitch(() => ({
				getItem: () => {
					throw new Error('storage unavailable');
				}
			}))
		).toBe('tabs');
	});
});
