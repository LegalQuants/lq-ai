/**
 * referenced-files Phase 2 — pure logic of the referenceable-files set.
 * loadReferenceableFiles is NOT tested here (it is a thin fetch
 * composition; Cypress covers it end-to-end with stubbed routes).
 */
import { describe, expect, it } from 'vitest';

import {
	MESSAGE_REFERENCED_FILES_MAX,
	addReferencedFile,
	filterReferenceable,
	mergeKbFileLists,
	removeReferencedFile,
	toReferencedFile,
	type ReferencedFile
} from '../files/referenceable';
import type { KnowledgeBaseFile } from '../types';

function kbFile(overrides: Partial<KnowledgeBaseFile> & { id: string }): KnowledgeBaseFile {
	return {
		owner_id: 'u1',
		filename: `${overrides.id}.pdf`,
		mime_type: 'application/pdf',
		size_bytes: 100,
		hash_sha256: 'x',
		ingestion_status: 'ready',
		created_at: '2026-07-01T00:00:00Z',
		attached_at: '2026-07-01T00:00:00Z',
		...overrides
	} as KnowledgeBaseFile;
}

function ref(id: string, filename = `${id}.pdf`, ready = true): ReferencedFile {
	return { id, filename, ready };
}

describe('toReferencedFile', () => {
	it('marks ready exactly when ingestion_status === "ready"', () => {
		expect(toReferencedFile(kbFile({ id: 'a' })).ready).toBe(true);
		expect(toReferencedFile(kbFile({ id: 'b', ingestion_status: 'processing' })).ready).toBe(false);
		expect(toReferencedFile(kbFile({ id: 'c', ingestion_status: 'failed' })).ready).toBe(false);
	});
});

describe('mergeKbFileLists', () => {
	it('dedupes a file present in several KBs (first occurrence wins)', () => {
		const merged = mergeKbFileLists([
			[kbFile({ id: 'a', filename: 'alpha.pdf' })],
			[kbFile({ id: 'a', filename: 'alpha.pdf' }), kbFile({ id: 'b', filename: 'beta.pdf' })]
		]);

		expect(merged.map((f) => f.id)).toEqual(['a', 'b']);
	});

	it('sorts by filename', () => {
		const merged = mergeKbFileLists([
			[kbFile({ id: '1', filename: 'zeta.pdf' }), kbFile({ id: '2', filename: 'alpha.pdf' })]
		]);

		expect(merged.map((f) => f.filename)).toEqual(['alpha.pdf', 'zeta.pdf']);
	});

	it('returns [] for no KBs', () => {
		expect(mergeKbFileLists([])).toEqual([]);
	});
});

describe('filterReferenceable', () => {
	const files = [ref('1', 'Master Agreement.pdf'), ref('2', 'exhibit-a.pdf')];

	it('returns everything for an empty/whitespace query', () => {
		expect(filterReferenceable(files, '')).toEqual(files);
		expect(filterReferenceable(files, ' ')).toEqual(files);
	});

	it('matches case-insensitive substrings', () => {
		expect(filterReferenceable(files, 'master')).toEqual([files[0]]);
		expect(filterReferenceable(files, 'EXHIBIT')).toEqual([files[1]]);
	});

	it('returns [] when nothing matches', () => {
		expect(filterReferenceable(files, 'zzz')).toEqual([]);
	});
});

describe('addReferencedFile', () => {
	it('adds a ready file', () => {
		const r = addReferencedFile([], ref('1'));
		expect(r).toEqual({ added: true, list: [ref('1')] });
	});

	it('rejects a duplicate id', () => {
		const r = addReferencedFile([ref('1')], ref('1'));
		expect(r).toEqual({ added: false, reason: 'duplicate' });
	});

	it('rejects a non-ready file', () => {
		const r = addReferencedFile([], ref('1', '1.pdf', false));
		expect(r).toEqual({ added: false, reason: 'not-ready' });
	});

	it('rejects past the cap', () => {
		const full = Array.from({ length: MESSAGE_REFERENCED_FILES_MAX }, (_, i) => ref(`f${i}`));
		const r = addReferencedFile(full, ref('overflow'));
		expect(r).toEqual({ added: false, reason: 'cap' });
	});

	it('does not mutate the input list', () => {
		const list = [ref('1')];
		addReferencedFile(list, ref('2'));
		expect(list).toEqual([ref('1')]);
	});
});

describe('removeReferencedFile', () => {
	it('removes by id and leaves others', () => {
		expect(removeReferencedFile([ref('1'), ref('2')], '1')).toEqual([ref('2')]);
	});

	it('is a no-op for an unknown id', () => {
		expect(removeReferencedFile([ref('1')], 'nope')).toEqual([ref('1')]);
	});
});
