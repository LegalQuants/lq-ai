/**
 * Unit tests for the composer's skill-input helpers.
 *
 * Regression cover for the v0.8.0 break: the gateway enforces a skill's
 * required inputs (#570), so the form has to offer every one of them and
 * the send has to carry them, or the turn is refused with
 * `skill_input_missing`.
 *
 * Convention note: pure-function tests, no component mount (per the
 * ChatPanel-slash-detect.test.ts header). ChatPanel wires these into the
 * attach flow and the send payload.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';
import { parse } from 'yaml';

import {
	attachedDocumentsValue,
	enumOptions,
	flattenSkillInputs,
	isDocumentInput,
	isFormInput,
	missingInputsMessage,
	resolveSkillInputsForSend,
	skillInputFieldId,
	skillInputsUnavailableMessage
} from '../chat/skillInputs';
import type { SkillInputDef, SkillInputs } from '../types';

// The shape GET /skills/nda-review/inputs returns on v0.8.0 (nulls included).
const NDA_REVIEW: SkillInputs = {
	name: 'nda-review',
	required: [
		{ name: 'document', type: 'document', required: true, description: 'The NDA', enum: null },
		{ name: 'perspective', type: 'text', required: true, description: 'Which side', enum: null }
	],
	optional: [
		{ name: 'jurisdiction', type: 'text', required: false, description: null, default: null }
	]
};
const NDA_DEFS = flattenSkillInputs(NDA_REVIEW);

describe('flattenSkillInputs', () => {
	it('lists required inputs first, then optional, each flagged', () => {
		expect(NDA_DEFS.map((d) => [d.name, d.required])).toEqual([
			['document', true],
			['perspective', true],
			['jurisdiction', false]
		]);
	});

	it('returns [] for a skill that declares no inputs', () => {
		expect(flattenSkillInputs({ name: 'nda-snapshot', required: [], optional: [] })).toEqual([]);
	});

	it('keeps the first entry when a name is declared twice', () => {
		const out = flattenSkillInputs({
			name: 'dupes',
			required: [
				{ name: 'party', type: 'text', description: 'first' },
				{ name: 'party', type: 'text', description: 'second' }
			],
			optional: [{ name: 'party', type: 'text' }, { name: 'term' }]
		});
		expect(out.map((d) => [d.name, d.required, d.description])).toEqual([
			['party', true, 'first'],
			['term', false, undefined]
		]);
	});
});

describe('input classification', () => {
	it('treats document and file types as document inputs', () => {
		expect(isDocumentInput({ name: 'a', type: 'document' })).toBe(true);
		expect(isDocumentInput({ name: 'a', type: 'file' })).toBe(true);
		expect(isDocumentInput({ name: 'a', type: 'text' })).toBe(false);
		expect(isDocumentInput({ name: 'a', type: null })).toBe(false);
	});

	it('hides optional structured inputs but keeps a required one', () => {
		expect(isFormInput({ name: 'chat_history', type: 'structured', required: false })).toBe(false);
		expect(isFormInput({ name: 'payload', type: 'structured', required: true })).toBe(true);
		expect(isFormInput({ name: 'jurisdiction', type: 'text', required: false })).toBe(true);
	});

	it('reads enum options from `enum` or the authoring guide’s `values`', () => {
		expect(enumOptions({ name: 'p', type: 'enum', enum: ['a', 'b'] })).toEqual(['a', 'b']);
		expect(enumOptions({ name: 'p', type: 'enum', enum: null, values: ['x'] })).toEqual(['x']);
		expect(enumOptions({ name: 'p', type: 'enum' })).toEqual([]);
		expect(enumOptions({ name: 'p', type: 'text', enum: ['a'] })).toEqual([]);
	});
});

describe('skillInputFieldId', () => {
	it('scopes the id by skill so two skills sharing an input name do not collide', () => {
		const nda = skillInputFieldId('nda-review', 'perspective');
		const msa = skillInputFieldId('msa-review-saas', 'perspective');
		expect(nda).toBe('lq-ai-skill-input-nda-review-perspective');
		expect(msa).not.toBe(nda);
	});
});

describe('resolveSkillInputsForSend', () => {
	const defs = { 'nda-review': NDA_DEFS };

	it('reports every required input when nothing is entered or attached', () => {
		const out = resolveSkillInputsForSend(['nda-review'], defs, {}, []);
		expect(out.skillInputs).toBeUndefined();
		expect(out.missing).toHaveLength(1);
		expect(out.missing[0].skill).toBe('nda-review');
		expect(out.missing[0].inputs.map((d) => d.name)).toEqual(['document', 'perspective']);
	});

	it('binds a required document input to the ready attached files', () => {
		const out = resolveSkillInputsForSend(
			['nda-review'],
			defs,
			{ 'nda-review': { perspective: 'mutual' } },
			['nda.pdf', 'side-letter.docx']
		);
		expect(out.missing).toEqual([]);
		expect(out.skillInputs).toEqual({
			'nda-review': {
				perspective: 'mutual',
				document: attachedDocumentsValue(['nda.pdf', 'side-letter.docx'])
			}
		});
	});

	it('prefers pasted document text over the attached files', () => {
		const out = resolveSkillInputsForSend(
			['nda-review'],
			defs,
			{ 'nda-review': { document: 'THIS AGREEMENT…', perspective: 'recipient' } },
			['nda.pdf']
		);
		expect(out.skillInputs?.['nda-review'].document).toBe('THIS AGREEMENT…');
	});

	it('treats whitespace-only and cleared-number values as missing and does not send them', () => {
		const out = resolveSkillInputsForSend(
			['nda-review'],
			defs,
			{ 'nda-review': { perspective: '   ', jurisdiction: '', count: NaN } },
			['nda.pdf']
		);
		expect(out.missing[0].inputs.map((d) => d.name)).toEqual(['perspective']);
		expect(out.skillInputs).toEqual({
			'nda-review': { document: attachedDocumentsValue(['nda.pdf']) }
		});
	});

	it('does not bind attached files to an optional document input', () => {
		const withOrderForm: SkillInputDef[] = [
			{ name: 'order_form', type: 'document', required: false }
		];
		const out = resolveSkillInputsForSend(['msa'], { msa: withOrderForm }, {}, ['msa.pdf']);
		expect(out.skillInputs).toBeUndefined();
		expect(out.missing).toEqual([]);
	});

	it('falls back to a declared default the user never touched', () => {
		const withDefault: SkillInputDef[] = [
			{ name: 'depth', type: 'text', required: true, default: 'standard' }
		];
		const out = resolveSkillInputsForSend(['s'], { s: withDefault }, {}, []);
		expect(out.missing).toEqual([]);
		expect(out.skillInputs).toEqual({ s: { depth: 'standard' } });
	});

	it('does not bring a default back once the user has cleared the field', () => {
		const optional: SkillInputDef[] = [{ name: 'depth', type: 'text', default: 'standard' }];
		const cleared = resolveSkillInputsForSend(['s'], { s: optional }, { s: { depth: '' } }, []);
		expect(cleared.skillInputs).toBeUndefined();
		expect(cleared.missing).toEqual([]);

		// Required and cleared: reported, not silently re-defaulted.
		const required: SkillInputDef[] = [{ ...optional[0], required: true }];
		const blocked = resolveSkillInputsForSend(['s'], { s: required }, { s: { depth: '' } }, []);
		expect(blocked.missing[0].inputs.map((d) => d.name)).toEqual(['depth']);
	});

	it('sends false for a required checkbox left unticked', () => {
		const flag: SkillInputDef[] = [{ name: 'redline', type: 'boolean', required: true }];
		const untouched = resolveSkillInputsForSend(['s'], { s: flag }, {}, []);
		expect(untouched.missing).toEqual([]);
		expect(untouched.skillInputs).toEqual({ s: { redline: false } });

		const ticked = resolveSkillInputsForSend(['s'], { s: flag }, { s: { redline: true } }, []);
		expect(ticked.skillInputs).toEqual({ s: { redline: true } });
	});

	it('keeps values for a skill whose input schema has not loaded', () => {
		const out = resolveSkillInputsForSend(
			['pending'],
			{ pending: undefined },
			{ pending: { foo: 'bar' } },
			[]
		);
		expect(out.missing).toEqual([]);
		expect(out.skillInputs).toEqual({ pending: { foo: 'bar' } });
	});

	it('resolves each attached skill independently, in attach order', () => {
		const qa: SkillInputDef[] = [
			{ name: 'document', type: 'document', required: true },
			{ name: 'question', type: 'text', required: true }
		];
		const out = resolveSkillInputsForSend(
			['nda-review', 'contract-qa'],
			{ 'nda-review': NDA_DEFS, 'contract-qa': qa },
			{ 'nda-review': { perspective: 'mutual' } },
			['nda.pdf']
		);
		expect(out.missing.map((m) => m.skill)).toEqual(['contract-qa']);
		expect(out.missing[0].inputs.map((d) => d.name)).toEqual(['question']);
		expect(Object.keys(out.skillInputs ?? {})).toEqual(['nda-review', 'contract-qa']);
	});
});

describe('missingInputsMessage', () => {
	it('names the skill by title and lists the inputs', () => {
		const message = missingInputsMessage(
			{ skill: 'nda-review', inputs: [NDA_DEFS[1]] },
			'NDA Review'
		);
		expect(message).toBe('Skill "NDA Review" is missing required inputs: perspective.');
	});

	it('adds an attach-or-paste hint when a document is missing', () => {
		const message = missingInputsMessage({ skill: 'nda-review', inputs: NDA_DEFS.slice(0, 2) });
		expect(message).toBe(
			'Skill "nda-review" is missing required inputs: document, perspective. Attach a file or paste the document text.'
		);
	});

	it('says a file is still processing instead of asking for one', () => {
		const message = missingInputsMessage(
			{ skill: 'nda-review', inputs: [NDA_DEFS[0]] },
			'NDA Review',
			['nda.pdf']
		);
		expect(message).toBe(
			'Skill "NDA Review" is missing required inputs: document. nda.pdf is still processing — wait for it to finish, or paste the document text.'
		);
	});

	it('leaves the processing note out when no document is missing', () => {
		const message = missingInputsMessage(
			{ skill: 'nda-review', inputs: [NDA_DEFS[1]] },
			'NDA Review',
			['nda.pdf']
		);
		expect(message).toBe('Skill "NDA Review" is missing required inputs: perspective.');
	});
});

describe('skillInputsUnavailableMessage', () => {
	it('distinguishes a failed load from one still in flight', () => {
		expect(skillInputsUnavailableMessage('NDA Review', true)).toContain('Could not load');
		expect(skillInputsUnavailableMessage('NDA Review', true)).toContain('Retry');
		expect(skillInputsUnavailableMessage('NDA Review', false)).toContain('still loading');
	});
});

// ---------------------------------------------------------------------------
// Corpus pin. The gateway refuses a turn unless every required input a
// built-in skill declares is bound, so each one must be reachable from the
// composer: offered by the form, and (for documents) satisfied by a file.
// Located from this file, not the working directory, and skipped when the
// skills corpus is not checked out next to web/ (e.g. a web-only context).
// ---------------------------------------------------------------------------

const SKILLS_DIR = fileURLToPath(new URL('../../../../../skills', import.meta.url));
const HAS_CORPUS = existsSync(SKILLS_DIR);

function declaredInputs(slug: string): SkillInputs {
	const raw = readFileSync(join(SKILLS_DIR, slug, 'SKILL.md'), 'utf-8');
	const frontmatter = parse(raw.split(/^---\s*$/m)[1]) ?? {};
	// Same lookup order as api/app/skills/schema.py::extract_inputs.
	const block = frontmatter.inputs ?? frontmatter.lq_ai?.inputs ?? {};
	return { name: slug, required: block.required ?? [], optional: block.optional ?? [] };
}

function skillsWithRequiredInputs(): string[] {
	if (!HAS_CORPUS) return [];
	return readdirSync(SKILLS_DIR, { withFileTypes: true })
		.filter((entry) => entry.isDirectory())
		.map((entry) => entry.name)
		.filter((slug) => {
			try {
				return declaredInputs(slug).required.length > 0;
			} catch {
				return false; // no SKILL.md (e.g. the community submodule directory)
			}
		});
}

describe.skipIf(!HAS_CORPUS)('built-in skill corpus', () => {
	const slugs = skillsWithRequiredInputs();

	it('finds the skills that declare required inputs', () => {
		expect(slugs).toContain('nda-review');
		expect(slugs.length).toBeGreaterThanOrEqual(10);
	});

	it.each(slugs)('%s: every required input can be supplied from the composer', (slug) => {
		const defs = flattenSkillInputs(declaredInputs(slug));
		const required = defs.filter((d) => d.required);
		expect(required.every(isFormInput)).toBe(true);

		// Nothing entered, nothing attached: every required input is reported.
		const empty = resolveSkillInputsForSend([slug], { [slug]: defs }, {}, []);
		expect(empty.missing[0].inputs.map((d) => d.name)).toEqual(required.map((d) => d.name));

		// A ready file attached and the non-document fields filled in: nothing
		// is missing and every required input is bound to a non-empty value.
		const typed = Object.fromEntries(
			required.filter((d) => !isDocumentInput(d)).map((d) => [d.name, 'value'])
		);
		const full = resolveSkillInputsForSend([slug], { [slug]: defs }, { [slug]: typed }, ['a.pdf']);
		expect(full.missing).toEqual([]);
		for (const def of required) {
			expect(full.skillInputs?.[slug][def.name]).toBeTruthy();
		}
	});
});
