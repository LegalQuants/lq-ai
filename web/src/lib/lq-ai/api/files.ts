/**
 * /api/v1/files — multipart upload + metadata + soft-delete, plus the shared
 * ingestion-status poll helper.
 *
 * Project-scoped attach uses /api/v1/projects/{id}/files (per backend
 * OpenAPI sketch C7); chat-scoped attach is client-side panel state whose
 * file ids are sent as `file_ids` on POST /chats/{id}/messages (ChatPanel /
 * selectFileIdsForSend).
 */
import { apiRequest } from './client';
import type { FileMeta } from '../types';

/** POST /api/v1/files — streaming multipart upload. */
export async function uploadFile(
	file: File,
	opts: { project_id?: string } = {}
): Promise<FileMeta> {
	const fd = new FormData();
	fd.append('file', file, file.name);
	if (opts.project_id) fd.append('project_id', opts.project_id);
	return apiRequest<FileMeta>('/files', { method: 'POST', formData: fd });
}

/** GET /api/v1/files/{id} — metadata. */
export async function getFile(id: string): Promise<FileMeta> {
	return apiRequest<FileMeta>(`/files/${encodeURIComponent(id)}`);
}

/** DELETE /api/v1/files/{id} — soft-delete. */
export async function deleteFile(id: string): Promise<void> {
	await apiRequest<void>(`/files/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/**
 * POST /api/v1/projects/{project_id}/files — attach an existing file to a
 * project. Multipart upload to `/api/v1/files` is the canonical create path;
 * this endpoint links an already-created file row to a project.
 */
export async function attachFileToProject(
	projectId: string,
	fileId: string
): Promise<FileMeta> {
	return apiRequest<FileMeta>(`/projects/${encodeURIComponent(projectId)}/files`, {
		method: 'POST',
		body: { file_id: fileId }
	});
}

// ---- ingestion-status polling ----

export type FileStatusPollOutcome = 'ready' | 'failed' | 'timeout' | 'aborted';

export interface FileStatusPollResult {
	outcome: FileStatusPollOutcome;
	/** Last metadata fetched with a defined ingestion_status, if any. */
	file?: FileMeta;
}

export interface PollFileStatusOptions {
	/** Stop condition; defaults to the terminal ingestion states (ready/failed). */
	until?: (file: FileMeta) => boolean;
	intervalMs?: number;
	maxAttempts?: number;
	/** Stops the loop promptly, including mid-sleep. */
	signal?: AbortSignal;
	/** Fetcher override (tests inject a fake here). */
	getFile?: (id: string) => Promise<FileMeta>;
	/** Called on each fetch that carried a defined status, so callers can patch UI state. */
	onStatus?: (file: FileMeta) => void;
}

// Resolves (never rejects) either after `ms` or as soon as `signal` aborts.
function abortableSleep(ms: number, signal?: AbortSignal): Promise<void> {
	return new Promise((resolve) => {
		if (signal?.aborted) {
			resolve();
			return;
		}
		const timer = setTimeout(done, ms);
		function done(): void {
			clearTimeout(timer);
			signal?.removeEventListener('abort', done);
			resolve();
		}
		signal?.addEventListener('abort', done, { once: true });
	});
}

const isTerminal = (f: FileMeta): boolean =>
	f.ingestion_status === 'ready' || f.ingestion_status === 'failed';

/**
 * Poll a file's ingestion status until `until` is satisfied (default: a
 * terminal 'ready'/'failed' state), the signal aborts, or `maxAttempts` is
 * exhausted — the last resolves with a distinct 'timeout' outcome rather
 * than pretending success. A transient fetch error does not kill the loop,
 * and a response with an undefined ingestion_status is skipped so it never
 * overwrites a previously known status.
 */
export async function pollFileStatus(
	id: string,
	opts: PollFileStatusOptions = {}
): Promise<FileStatusPollResult> {
	const {
		until = isTerminal,
		intervalMs = 2000,
		maxAttempts = 40,
		signal,
		getFile: fetchFile = getFile,
		onStatus
	} = opts;
	let lastKnown: FileMeta | undefined;
	for (let attempt = 0; attempt < maxAttempts; attempt++) {
		await abortableSleep(intervalMs, signal);
		if (signal?.aborted) return { outcome: 'aborted', file: lastKnown };
		let latest: FileMeta;
		try {
			latest = await fetchFile(id);
		} catch (e) {
			if (signal?.aborted) return { outcome: 'aborted', file: lastKnown };
			console.error('lq-ai: file status poll failed', e);
			continue; // transient — keep polling
		}
		if (signal?.aborted) return { outcome: 'aborted', file: lastKnown };
		if (latest.ingestion_status === undefined) continue; // never patch over a known status
		lastKnown = latest;
		onStatus?.(latest);
		if (until(latest)) {
			return {
				outcome: latest.ingestion_status === 'failed' ? 'failed' : 'ready',
				file: latest
			};
		}
	}
	return { outcome: 'timeout', file: lastKnown };
}

/**
 * DELETE /api/v1/projects/{project_id}/files/{file_id} — detach a file from a
 * project (file row remains; only the link is removed).
 */
export async function detachFileFromProject(
	projectId: string,
	fileId: string
): Promise<void> {
	await apiRequest<void>(
		`/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`,
		{ method: 'DELETE' }
	);
}
