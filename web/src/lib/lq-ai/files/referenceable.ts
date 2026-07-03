/**
 * referenced-files Phase 2 — the referenceable-files set for the chat composer.
 *
 * "Referenceable" = exactly what the backend accepts in
 * `referenced_file_ids` (ADR 0022, KB-only MVP + matter scope): files in
 * Knowledge Bases attached to the chat's project. Loading walks
 * GET /projects/{id} → attached_knowledge_base_ids →
 * GET /knowledge-bases/{kb_id}/files and merges/dedupes (a file may sit
 * in several matter KBs). There is deliberately NO GET /files list call
 * here — that route does not exist (DE-296 unbuilt).
 *
 * `ready` mirrors the backend's ingestion_status === 'ready' send gate:
 * non-ready files render disabled ("Preparing…") and are never
 * selectable — fail-restrictive made visible (P4), so the UI can never
 * assemble a set the backend would 404.
 */
import { listKnowledgeBaseFiles } from '../api/knowledgeBases';
import { getProject } from '../api/projects';
import type { KnowledgeBaseFile } from '../types';

/** Mirrors MESSAGE_REFERENCED_FILES_MAX_LEN (api/app/schemas/chats.py). */
export const MESSAGE_REFERENCED_FILES_MAX = 16;

export interface ReferencedFile {
	id: string;
	filename: string;
	ready: boolean;
}

export interface ReferenceableLoad {
	files: ReferencedFile[];
	/** KBs whose file listing failed; the union of the rest still loads. */
	failedKbCount: number;
}

export function toReferencedFile(row: KnowledgeBaseFile): ReferencedFile {
	return { id: row.id, filename: row.filename, ready: row.ingestion_status === 'ready' };
}

export function mergeKbFileLists(lists: KnowledgeBaseFile[][]): ReferencedFile[] {
	const byId = new Map<string, ReferencedFile>();

	for (const list of lists) {
		for (const row of list) {
			// The same File row can be attached to several KBs; its
			// ingestion_status is file-level, so first occurrence wins.
			if (!byId.has(row.id)) byId.set(row.id, toReferencedFile(row));
		}
	}

	return [...byId.values()].sort((a, b) => a.filename.localeCompare(b.filename));
}

export function filterReferenceable(files: ReferencedFile[], query: string): ReferencedFile[] {
	const q = query.trim().toLowerCase();
	if (!q) return files;
	return files.filter((f) => f.filename.toLowerCase().includes(q));
}

export type AddResult =
	| { added: true; list: ReferencedFile[] }
	| { added: false; reason: 'duplicate' | 'cap' | 'not-ready' };

export function addReferencedFile(
	list: ReferencedFile[],
	file: ReferencedFile,
	cap: number = MESSAGE_REFERENCED_FILES_MAX
): AddResult {
	if (!file.ready) return { added: false, reason: 'not-ready' };
	if (list.some((f) => f.id === file.id)) return { added: false, reason: 'duplicate' };
	if (list.length >= cap) return { added: false, reason: 'cap' };
	return { added: true, list: [...list, file] };
}

export function removeReferencedFile(list: ReferencedFile[], id: string): ReferencedFile[] {
	return list.filter((f) => f.id !== id);
}

/**
 * Load the referenceable set for a project. A single KB listing failure
 * degrades to the union of the KBs that did load (surfaced via
 * `failedKbCount` as a non-blocking note); a getProject failure
 * propagates — with no project there is no referenceable set at all.
 */
export async function loadReferenceableFiles(projectId: string): Promise<ReferenceableLoad> {
	const project = await getProject(projectId);
	const kbIds = project.attached_knowledge_base_ids ?? [];
	const settled = await Promise.allSettled(kbIds.map((id) => listKnowledgeBaseFiles(id)));
	const lists = settled
		.filter((s): s is PromiseFulfilledResult<KnowledgeBaseFile[]> => s.status === 'fulfilled')
		.map((s) => s.value);

	return { files: mergeKbFileLists(lists), failedKbCount: settled.length - lists.length };
}
