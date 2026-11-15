import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';

import LedgerEntryRow from '../components/LedgerEntryRow.svelte';
import type { LedgerEntry, LedgerSource } from '../types';

// Mirrors the authority branch of api/app/citation/ledger.py::_resolve_source.
function authorityEntry(
	externalRef: string | null | undefined,
	verificationStatus = 'exact_match'
): LedgerEntry {
	const source = {
		kind: 'statute',
		external_ref: externalRef,
		provider: 'govinfo',
		passages: [
			{
				text: 'Synthetic authority passage.',
				offset_start: 0,
				offset_end: 28,
				verified: !['failed', 'unverified'].includes(verificationStatus),
				method: verificationStatus
			}
		]
	};
	return {
		id: 'synthetic-entry',
		message_id: 'synthetic-message',
		source_kind: source.kind,
		verification_status: verificationStatus,
		confidence: null,
		provider: source.provider,
		retrieved_at: null,
		treatment_id: null,
		created_at: '2026-01-01T00:00:00Z',
		source
	};
}

function markup(entry: LedgerEntry): string {
	return render(LedgerEntryRow, { props: { entry } }).body;
}

function identity(html: string): string | undefined {
	return html.match(/<span class="lq-ledger-identity[^"]*">([\s\S]*?)<\/span>/)?.[1];
}

describe('citation ledger source identity', () => {
	it.each([
		['exact_match', 'verified-exact'],
		['tolerant_match', 'verified-tolerant'],
		['paraphrase_judge', 'verified-paraphrase'],
		['ensemble_strict', 'verified-paraphrase'],
		['ensemble_majority', 'verified-paraphrase'],
		['failed', 'unverified'],
		['unverified', 'unverified']
	])('distinguishes same-kind authorities without changing %s verdicts', (status, state) => {
		const refs = ['USCODE-2024-title17-section107', 'USCODE-2024-title17-section108'];
		const rows = refs.map((ref) => markup(authorityEntry(ref, status)));
		rows.forEach((html, index) => {
			expect(identity(html)).toBe(`statute · ${refs[index]}`);
			expect(html).toContain(`data-state="${state}"`);
			expect(html).toContain(`>${status}</span>`);
			expect(html).toContain('Synthetic authority passage.');
			expect(html).toContain('chars 0–28');
			expect(html).not.toContain('<a ');
		});
		expect(identity(rows[0])).not.toBe(identity(rows[1]));
	});

	it.each([undefined, null, '', '  \t\n '])(
		'keeps a useful kind fallback for an absent or blank reference: %j',
		(ref) => {
			const html = markup(authorityEntry(ref));
			expect(identity(html)).toBe('statute');
			expect(html).not.toContain('<a ');
		}
	);

	it.each(['regulation', 'sec_filing', 'eu_regulation', 'future_authority_kind'])(
		'retains kind context for %s and trims reference padding',
		(kind) => {
			const entry = authorityEntry('  synthetic-reference  ');
			entry.source.kind = kind;
			expect(identity(markup(entry))).toBe(`${kind} · synthetic-reference`);
		}
	);

	it('renders an untrusted reference as text without creating elements or links', () => {
		const html = markup(authorityEntry('<img src=x onerror=alert(1)> & <script>alert(2)</script>'));
		expect(identity(html)).toContain('statute · &lt;img src=x onerror=alert(1)');
		expect(identity(html)).toContain('&amp; &lt;script');
		expect(html).not.toMatch(/<(?:img|script|a)\b/);
	});

	it.each([
		[{ kind: 'kb_document', source_file_id: 'synthetic-file' }, 'Document'],
		[{ kind: 'caselaw', opinion_id: 123, cluster_id: 456 }, 'Opinion 123 · cluster 456'],
		[{ kind: 'mcp', label: 'Source label', tool: 'lookup' }, 'Source label'],
		[{ kind: 'mcp', tool: 'lookup' }, 'lookup'],
		[{ kind: 'mcp', label: '', tool: 'lookup' }, ''],
		[{ kind: 'mcp', tool: '' }, '']
	] satisfies [LedgerSource, string][])(
		'preserves the existing identity preference for %j',
		(source, expected) => {
			const entry = authorityEntry('must-not-override-existing-identity');
			entry.source = { ...entry.source, ...source };
			expect(identity(markup(entry))).toBe(expected);
		}
	);

	it('retains only the URL supplied by the source', () => {
		const entry = authorityEntry('https://untrusted.example/reference');
		expect(markup(entry)).not.toContain('<a ');
		entry.source.url = 'https://example.org/source';
		const html = markup(entry);
		expect(identity(html)).toBe('statute · https://untrusted.example/reference');
		expect(html).toContain('href="https://example.org/source"');
		expect(html.match(/<a /g)).toHaveLength(1);
	});
});
