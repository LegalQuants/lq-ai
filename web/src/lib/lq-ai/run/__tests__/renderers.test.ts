/**
 * The step renderer registry: every kind the backend emits today reads as a plain
 * sentence, an unknown kind goes through the generic fallback, and a step never
 * throws or renders as nothing.
 */
import { describe, expect, it } from 'vitest';

import type { RunEffect, StepNote } from '../../api/orchestration';
import {
	describeEffect,
	describeEffects,
	knownStepKinds,
	refusalText,
	registerStepRenderer
} from '../renderers';
import { allRuns, run } from './fixtures';

function effect(step: StepNote | null | undefined, patch: Partial<RunEffect> = {}): RunEffect {
	return {
		effect_key: 'topic:t1:c0',
		status: 'completed',
		reserved_usd: '0.0000',
		charged_usd: '0.0000',
		intent: 'workspace_write',
		outcome: 'success',
		step,
		...patch
	};
}

/** What each kind the backend emits today should say, for a typical note. */
const KNOWN: [StepNote, string, string[]][] = [
	[{ kind: 'planning' }, 'Asked the model for a plan', []],
	[{ kind: 'synthesis' }, 'Asked the model to combine the tasks’ answers', []],
	[
		{ kind: 'model_turn', summary: { turn: 1, tool_calls: 2, finish_reason: 'tool_calls' } },
		'Asked the model (turn 1)',
		['asked for 2 tool calls']
	],
	[
		{ kind: 'model_turn', summary: { turn: 2, tool_calls: 0, finish_reason: 'stop' } },
		'Asked the model (turn 2)',
		['wrote its answer']
	],
	[
		{
			kind: 'document_read',
			tool: 'read_document',
			label: 'Read a selected document',
			summary: { document: 2, filename: 'dpa.md', start: 0, end: 190, total_chars: 190, truncated: false }
		},
		'Read document 2 (dpa.md)',
		['characters 0–190 of 190']
	],
	[
		{
			kind: 'document_read',
			summary: { document: 1, filename: 'msa.pdf', start: 0, end: 40000, total_chars: 90000, truncated: true }
		},
		'Read document 1 (msa.pdf)',
		['characters 0–40000 of 90000 (cut short)']
	],
	[
		{ kind: 'note_saved', tool: 'save_note', summary: { name: 'note-terms.md', revision: 1, size_bytes: 14 } },
		'Saved a working note (note-terms.md)',
		['revision 1', '14 bytes']
	],
	[
		{ kind: 'note_read', tool: 'read_note', summary: { name: 'note-terms.md', revision: 3, size_bytes: 1 } },
		'Read back a working note (note-terms.md)',
		['revision 3', '1 byte']
	],
	[
		{ kind: 'tool_refused', summary: { code: 'tool_not_granted' } },
		'A tool call was refused',
		['that tool is not granted to this task']
	],
	[
		{ kind: 'tool_refused', label: 'Read a selected document', summary: { code: 'document_not_selected' } },
		'A tool call was refused: Read a selected document',
		['the document is not one you selected']
	],
	[{ kind: 'notes_started' }, 'Started the task’s private notes', []],
	[{ kind: 'notes_read' }, 'Read the task’s notes', []],
	[{ kind: 'findings_saved' }, 'Saved the task’s findings', []],
	[{ kind: 'notes_updated' }, 'Updated the task’s notes', []],
	[{ kind: 'findings_read' }, 'Read the task’s findings back', []],
	[{ kind: 'findings_shared' }, 'Shared the task’s findings with the orchestrator', []],
	[{ kind: 'findings_collected' }, 'Collected a task’s findings', []]
];

describe('known step kinds', () => {
	it.each(KNOWN)('%j', (step, text, facts) => {
		const view = describeEffect(effect(step));
		expect(view.known).toBe(true);
		expect(view.kind).toBe(step.kind);
		expect(view.text).toBe(text);
		expect(view.facts).toEqual(facts);
	});

	it('has a renderer for every kind the backend emits today', () => {
		expect(knownStepKinds().sort()).toEqual(
			[
				'planning',
				'synthesis',
				'model_turn',
				'document_read',
				'note_saved',
				'note_read',
				'tool_refused',
				'notes_started',
				'notes_read',
				'findings_saved',
				'notes_updated',
				'findings_read',
				'findings_shared',
				'findings_collected'
			].sort()
		);
	});

	it('survives a note with no summary or an odd one', () => {
		for (const kind of knownStepKinds()) {
			for (const summary of [undefined, null, {}, { turn: 'one', document: {}, name: 5 }]) {
				const view = describeEffect(effect({ kind, summary: summary as StepNote['summary'] }));
				expect(view.text.length, `${kind} ${JSON.stringify(summary)}`).toBeGreaterThan(0);
			}
		}
	});

	it('carries the model’s stated reason through untouched', () => {
		const view = describeEffect(
			effect({ kind: 'document_read', reason: 'The agreement is needed.', summary: { document: 1 } })
		);
		expect(view.reason).toBe('The agreement is needed.');
		expect(describeEffect(effect({ kind: 'notes_started' })).reason).toBeNull();
	});
});

describe('an unknown step kind', () => {
	const probe: StepNote = {
		kind: 'probe_stamp',
		label: 'Stamp a probe note',
		summary: { name: 'note-stamp.md', revision: 1 }
	};

	it('renders through the generic fallback from its label and summary', () => {
		const view = describeEffect(effect(probe));
		expect(view.known).toBe(false);
		expect(view.kind).toBe('probe_stamp');
		expect(view.text).toBe('Stamp a probe note');
		expect(view.facts).toEqual(['name: note-stamp.md', 'revision: 1']);
	});

	it('includes the model’s reason', () => {
		const view = describeEffect(effect({ ...probe, reason: 'To mark the draft.' }));
		expect(view.reason).toBe('To mark the draft.');
	});

	it('uses a humanised kind when there is no label', () => {
		expect(describeEffect(effect({ kind: 'probe_stamp' })).text).toBe('Probe stamp');
		expect(describeEffect(effect({ kind: 'probe_stamp', label: '   ' })).text).toBe('Probe stamp');
	});

	it('never renders as nothing, however little it is given', () => {
		expect(describeEffect(effect({ kind: '' })).text).toBe('A step was recorded');
		expect(describeEffect(effect({ kind: '_' })).text).toBe('A step was recorded');
		expect(describeEffect(effect({ kind: 'x', label: '' })).text).toBe('X');
	});

	it('stringifies summary values of any shape without throwing', () => {
		const cyclic: Record<string, unknown> = {};
		cyclic.self = cyclic;
		const view = describeEffect(
			effect({
				kind: 'odd_step',
				summary: {
					nothing: null,
					flag: true,
					count: 3,
					nested: { a: [1, 2] },
					cyclic,
					long: 'x'.repeat(500)
				}
			})
		);
		expect(view.facts).toContain('nothing: —');
		expect(view.facts).toContain('flag: yes');
		expect(view.facts).toContain('count: 3');
		expect(view.facts).toContain('nested: {"a":[1,2]}');
		expect(view.facts.find((fact) => fact.startsWith('long: '))).toBe(`long: ${'x'.repeat(500)}`);
		expect(view.facts.find((fact) => fact.startsWith('cyclic: '))).toBeDefined();
	});

	it('does not mistake an object property for a registered kind', () => {
		for (const kind of ['constructor', '__proto__', 'toString', 'hasOwnProperty']) {
			const view = describeEffect(effect({ kind }));
			expect(view.known, kind).toBe(false);
			expect(typeof view.text, kind).toBe('string');
		}
	});

	it('can be taught a nicer sentence without changing anything else', () => {
		registerStepRenderer('probe_stamp_taught', (step) => ({
			text: `Stamped ${(step.summary as { name: string }).name}`
		}));
		const view = describeEffect(
			effect({ kind: 'probe_stamp_taught', summary: { name: 'note-stamp.md' } })
		);
		expect(view.known).toBe(true);
		expect(view.text).toBe('Stamped note-stamp.md');
	});

	it('falls back when a renderer itself fails', () => {
		registerStepRenderer('probe_broken', () => {
			throw new Error('renderer bug');
		});
		const view = describeEffect(effect({ kind: 'probe_broken', label: 'Broken step' }));
		expect(view.known).toBe(false);
		expect(view.text).toBe('Broken step');
	});
});

describe('an effect with no step note (earlier runs, and effects that never completed)', () => {
	it.each([
		['chat:plan:v1', 'plan', 'Asked the model for a plan'],
		['demo:notes:create:v1', 'workspace_write', 'Started the task’s private notes'],
		['demo:notes:read:v1', 'workspace_read', 'Read the task’s notes'],
		['demo:topic:v1', 'run_skill', 'Asked the model'],
		['topic:t1', 'run_skill', 'Asked the model'],
		['demo:findings:write:v1', 'workspace_write', 'Saved the task’s findings'],
		['demo:notes:update:v1', 'workspace_write', 'Updated the task’s notes'],
		['demo:findings:read:v1', 'workspace_read', 'Read the task’s findings back'],
		['demo:findings:share:v1', 'workspace_share', 'Shared the task’s findings with the orchestrator'],
		['demo:collect:abc:v1', 'workspace_read', 'Collected a task’s findings'],
		['demo:synthesis:v1', 'run_skill', 'Asked the model to combine the tasks’ answers']
	])('%s (%s)', (key, intent, text) => {
		const view = describeEffect(effect(null, { effect_key: key, intent }));
		expect(view.kind).toBe('legacy');
		expect(view.known).toBe(false);
		expect(view.text).toBe(text);
	});

	it('falls back to the intent, then to the key', () => {
		expect(describeEffect(effect(undefined, { effect_key: 'x:1', intent: 'retrieve_chunks' })).text).toBe('Read a document');
		expect(describeEffect(effect(undefined, { effect_key: 'x:1', intent: 'something_new' })).text).toBe('Something new');
		expect(describeEffect(effect(undefined, { effect_key: 'x:1', intent: '' })).text).toBe('X:1');
		expect(describeEffect(effect(undefined, { effect_key: '', intent: '' })).text).toBe('A step was recorded');
		expect(describeEffect(effect(undefined, { effect_key: 'k', intent: 'constructor' })).text).toBe('Constructor');
	});

	it('tolerates a malformed step', () => {
		for (const step of [{}, { kind: 5 }, 'text', 12, [], { kind: null }]) {
			const view = describeEffect(effect(step as unknown as StepNote));
			expect(view.text.length).toBeGreaterThan(0);
			expect(view.kind).toBe('legacy');
		}
	});
});

describe('tone and cost', () => {
	it('marks refusals, uncertain and closed effects, and effects still in flight', () => {
		expect(describeEffect(effect({ kind: 'tool_refused' })).tone).toBe('refused');
		expect(describeEffect(effect(null, { outcome: 'tool_refused', intent: 'refused' })).tone).toBe('refused');
		expect(describeEffect(effect(null, { status: 'uncertain', charged_usd: null }))).toMatchObject({
			tone: 'uncertain'
		});
		expect(describeEffect(effect(null, { status: 'closed' })).tone).toBe('closed');
		expect(describeEffect(effect(null, { status: 'admitted', charged_usd: null })).tone).toBe('working');
		expect(describeEffect(effect({ kind: 'notes_read' })).tone).toBe('done');
	});

	it('says an uncertain effect will not be retried, and a closed one was charged', () => {
		const uncertain = describeEffect(effect(null, { status: 'uncertain', charged_usd: null }));
		expect(uncertain.facts).toContain('No confirmed outcome. It will not be retried automatically.');
		const closed = describeEffect(effect(null, { status: 'closed', charged_usd: '0.1842', reserved_usd: '0.1842' }));
		expect(closed.facts).toContain('Closed without an outcome. The reserved amount was charged.');
		expect(closed.cost).toBe('$0.1842');
	});

	it('shows what was charged, or what is still reserved, and nothing for a free step', () => {
		expect(describeEffect(effect({ kind: 'model_turn' }, { charged_usd: '0.1841', reserved_usd: '0.1841' })).cost).toBe('$0.1841');
		expect(describeEffect(effect({ kind: 'notes_read' })).cost).toBeNull();
		expect(
			describeEffect(effect(null, { status: 'uncertain', charged_usd: null, reserved_usd: '0.0648' })).cost
		).toBe('$0.0648 reserved');
	});
});

describe('refusalText', () => {
	it('words the codes the backend uses, and shows an unknown code as words', () => {
		expect(refusalText('invalid_arguments')).toBe('the arguments did not match the tool’s schema');
		expect(refusalText('budget_exhausted')).toBe('the task’s allowance could not fund the call');
		expect(refusalText('note_too_large')).toBe('note too large');
		expect(refusalText(null)).toBe('the call was refused');
		expect(refusalText('constructor')).toBe('constructor');
	});
});

describe('over every recorded run', () => {
	it('describes every effect in every run, old and new, with non-empty text', () => {
		let count = 0;
		for (const { label, run: value } of allRuns()) {
			const lists = [
				value.effects,
				value.tree?.root?.effects ?? [],
				...(value.tree?.children ?? []).map((child) => child.effects)
			];
			for (const effects of lists) {
				for (const view of describeEffects(effects)) {
					count += 1;
					expect(view.text.length, label).toBeGreaterThan(0);
					expect(['done', 'working', 'refused', 'uncertain', 'closed']).toContain(view.tone);
				}
			}
		}
		expect(count).toBeGreaterThan(200);
	});

	it('reads a recorded document read the way a person would', () => {
		const first = run('documents.completed').tree!.children[0].effects.find(
			(e) => e.step?.kind === 'document_read'
		)!;
		const view = describeEffect(first);
		expect(view.text).toBe('Read document 1 (msa.txt)');
		expect(view.reason).toBe('Read the MSA.');
	});
});
