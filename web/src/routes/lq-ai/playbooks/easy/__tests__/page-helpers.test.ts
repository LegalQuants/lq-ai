import { describe, it, expect } from 'vitest';

import type { EasyPlaybookGeneration, FileMeta } from '$lib/lq-ai/types';
import {
	isTerminalGenerationStatus,
	allDocumentsReady,
	collectReadyDocumentIds,
	nextStepFromGeneration,
	validateUploadStep,
	defaultPlaybookName
} from '../page-helpers';

const mkFile = (overrides: Partial<FileMeta>): FileMeta => ({
	id: overrides.id ?? 'f',
	owner_id: 'u1',
	filename: overrides.filename ?? 'a.pdf',
	mime_type: 'application/pdf',
	size_bytes: 1,
	hash_sha256: '0',
	ingestion_status: overrides.ingestion_status ?? 'ready',
	page_count: null,
	character_count: null,
	document_id: overrides.document_id ?? null,
	created_at: '2026-05-20T00:00:00Z'
});

const mkGen = (overrides: Partial<EasyPlaybookGeneration>): EasyPlaybookGeneration => ({
	id: 'g1',
	user_id: 'u1',
	contract_type: 'NDA',
	status: overrides.status ?? 'pending',
	document_ids: overrides.document_ids ?? ['d1'],
	draft_playbook: overrides.draft_playbook ?? null,
	error_message: overrides.error_message ?? null,
	created_at: '2026-05-20T00:00:00Z'
});

describe('isTerminalGenerationStatus', () => {
	it('returns true for completed', () => {
		expect(isTerminalGenerationStatus('completed')).toBe(true);
	});
	it('returns true for error', () => {
		expect(isTerminalGenerationStatus('error')).toBe(true);
	});
	it('returns false for pending', () => {
		expect(isTerminalGenerationStatus('pending')).toBe(false);
	});
	it('returns false for running', () => {
		expect(isTerminalGenerationStatus('running')).toBe(false);
	});
});

describe('allDocumentsReady', () => {
	it('returns true when every file has a document_id', () => {
		expect(
			allDocumentsReady([
				mkFile({ id: 'f1', document_id: 'd1' }),
				mkFile({ id: 'f2', document_id: 'd2' })
			])
		).toBe(true);
	});
	it('returns false when any file has no document_id', () => {
		expect(
			allDocumentsReady([
				mkFile({ id: 'f1', document_id: 'd1' }),
				mkFile({ id: 'f2', document_id: null })
			])
		).toBe(false);
	});
	it('returns false for an empty list (nothing to start from)', () => {
		expect(allDocumentsReady([])).toBe(false);
	});
});

describe('collectReadyDocumentIds', () => {
	it('returns the document_ids of files where document_id is set', () => {
		expect(
			collectReadyDocumentIds([
				mkFile({ id: 'f1', document_id: 'd1' }),
				mkFile({ id: 'f2', document_id: null }),
				mkFile({ id: 'f3', document_id: 'd3' })
			])
		).toEqual(['d1', 'd3']);
	});
	it('returns an empty array if no files are ready', () => {
		expect(collectReadyDocumentIds([])).toEqual([]);
	});
});

describe('nextStepFromGeneration', () => {
	it('stays on progress when status is pending', () => {
		expect(nextStepFromGeneration(mkGen({ status: 'pending' }))).toBe('progress');
	});
	it('stays on progress when status is running', () => {
		expect(nextStepFromGeneration(mkGen({ status: 'running' }))).toBe('progress');
	});
	it('advances to review when status is completed', () => {
		expect(
			nextStepFromGeneration(
				mkGen({
					status: 'completed',
					draft_playbook: { name: 'X', contract_type: 'NDA', positions: [] }
				})
			)
		).toBe('review');
	});
	it('stays on progress when status is error (caller surfaces error_message)', () => {
		expect(
			nextStepFromGeneration(mkGen({ status: 'error', error_message: 'boom' }))
		).toBe('progress');
	});
});

describe('validateUploadStep', () => {
	it('returns null when at least one file is uploaded and contract_type is non-empty', () => {
		expect(validateUploadStep({ files: [mkFile({})], contract_type: 'NDA' })).toBeNull();
	});
	it('returns an error when no files are uploaded', () => {
		expect(validateUploadStep({ files: [], contract_type: 'NDA' })).toMatch(/upload/i);
	});
	it('returns an error when contract_type is empty', () => {
		expect(validateUploadStep({ files: [mkFile({})], contract_type: '' })).toMatch(
			/contract type/i
		);
	});
	it('returns an error when contract_type is whitespace-only', () => {
		expect(validateUploadStep({ files: [mkFile({})], contract_type: '   ' })).toMatch(
			/contract type/i
		);
	});
});

describe('defaultPlaybookName', () => {
	it('returns "Generated {contract_type} Playbook" for a named contract type', () => {
		expect(defaultPlaybookName('NDA')).toBe('Generated NDA Playbook');
	});
	it('falls back to a generic name when contract_type is empty', () => {
		expect(defaultPlaybookName('')).toBe('Generated Playbook');
	});
});
