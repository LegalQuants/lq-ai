/**
 * Unit tests for the shared file ingestion-status poll helper (PR #316
 * review follow-ups F-5/F-6/F-8).
 *
 * Convention note: pure-function tests, no component mount (per the
 * ChatPanel-slash-detect.test.ts header). The fetcher is injected via the
 * `getFile` option so no fetch/auth mocking is needed; timers are faked so
 * the 2 s poll interval costs nothing.
 *
 * Coverage:
 *   - resolves with 'ready' / 'failed' outcomes on terminal states
 *   - abort stops the loop promptly, mid-sleep, without another fetch
 *   - a transient fetch rejection does not kill the loop
 *   - exhausting maxAttempts resolves 'timeout' (never pretends success)
 *   - an undefined ingestion_status is never reported over a known one
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { pollFileStatus } from '../api/files';
import type { FileMeta, IngestionStatus } from '../types';

function meta(status?: IngestionStatus): FileMeta {
	return {
		id: 'f1',
		owner_id: 'u1',
		filename: 'nda.pdf',
		mime_type: 'application/pdf',
		size_bytes: 2048,
		ingestion_status: status,
		created_at: '2026-01-01T00:00:00Z'
	};
}

/** Fetcher that yields the given results in order (an Error entry rejects). */
function fetcherOf(...results: Array<FileMeta | Error>) {
	let i = 0;
	return vi.fn(async (): Promise<FileMeta> => {
		const next = results[Math.min(i, results.length - 1)];
		i++;
		if (next instanceof Error) throw next;
		return next;
	});
}

const INTERVAL = 2000;

async function tick(times = 1): Promise<void> {
	for (let i = 0; i < times; i++) {
		await vi.advanceTimersByTimeAsync(INTERVAL);
	}
}

describe('pollFileStatus', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	it("resolves 'ready' once the file reaches ready", async () => {
		const getFile = fetcherOf(meta('pending'), meta('processing'), meta('ready'));
		const promise = pollFileStatus('f1', { getFile, intervalMs: INTERVAL });
		await tick(3);
		const result = await promise;
		expect(result.outcome).toBe('ready');
		expect(result.file?.ingestion_status).toBe('ready');
		expect(getFile).toHaveBeenCalledTimes(3);
	});

	it("resolves 'failed' once the file reaches failed", async () => {
		const getFile = fetcherOf(meta('pending'), meta('failed'));
		const promise = pollFileStatus('f1', { getFile, intervalMs: INTERVAL });
		await tick(2);
		const result = await promise;
		expect(result.outcome).toBe('failed');
		expect(result.file?.ingestion_status).toBe('failed');
	});

	it('reports intermediate statuses via onStatus', async () => {
		const getFile = fetcherOf(meta('processing'), meta('ready'));
		const onStatus = vi.fn();
		const promise = pollFileStatus('f1', { getFile, intervalMs: INTERVAL, onStatus });
		await tick(2);
		await promise;
		expect(onStatus.mock.calls.map(([f]) => f.ingestion_status)).toEqual(['processing', 'ready']);
	});

	it('aborts promptly mid-sleep without another fetch', async () => {
		const getFile = fetcherOf(meta('pending'));
		const controller = new AbortController();
		const promise = pollFileStatus('f1', {
			getFile,
			intervalMs: INTERVAL,
			signal: controller.signal
		});
		// Abort during the first sleep — the loop must resolve with NO timer
		// advance at all (i.e. it does not wait out the 2 s interval).
		controller.abort();
		const result = await promise;
		expect(result).toEqual({ outcome: 'aborted', file: undefined });
		expect(getFile).not.toHaveBeenCalled();
	});

	it('keeps the last known file when aborted after a successful fetch', async () => {
		const getFile = fetcherOf(meta('processing'));
		const controller = new AbortController();
		const promise = pollFileStatus('f1', {
			getFile,
			intervalMs: INTERVAL,
			signal: controller.signal
		});
		await tick(1); // one successful 'processing' fetch, now in second sleep
		controller.abort();
		const result = await promise;
		expect(result.outcome).toBe('aborted');
		expect(result.file?.ingestion_status).toBe('processing');
	});

	it('survives a transient fetch rejection and keeps polling', async () => {
		const getFile = fetcherOf(new Error('network blip'), meta('ready'));
		const promise = pollFileStatus('f1', { getFile, intervalMs: INTERVAL });
		await tick(2);
		const result = await promise;
		expect(result.outcome).toBe('ready');
		expect(getFile).toHaveBeenCalledTimes(2);
	});

	it("resolves 'timeout' after maxAttempts instead of pretending success", async () => {
		const getFile = fetcherOf(meta('pending'));
		const promise = pollFileStatus('f1', { getFile, intervalMs: INTERVAL, maxAttempts: 3 });
		await tick(3);
		const result = await promise;
		expect(result.outcome).toBe('timeout');
		// Last known (non-terminal) status is preserved, not fabricated.
		expect(result.file?.ingestion_status).toBe('pending');
		expect(getFile).toHaveBeenCalledTimes(3);
	});

	it('never reports an undefined status over a previously known one', async () => {
		const getFile = fetcherOf(meta('processing'), meta(undefined), meta('ready'));
		const onStatus = vi.fn();
		const promise = pollFileStatus('f1', { getFile, intervalMs: INTERVAL, onStatus });
		await tick(3);
		const result = await promise;
		expect(result.outcome).toBe('ready');
		// The undefined-status response was skipped entirely.
		expect(onStatus.mock.calls.map(([f]) => f.ingestion_status)).toEqual(['processing', 'ready']);
	});

	it('keeps the last defined status when timing out through undefined responses', async () => {
		const getFile = fetcherOf(meta('processing'), meta(undefined));
		const promise = pollFileStatus('f1', { getFile, intervalMs: INTERVAL, maxAttempts: 2 });
		await tick(2);
		const result = await promise;
		expect(result.outcome).toBe('timeout');
		expect(result.file?.ingestion_status).toBe('processing');
	});
});
