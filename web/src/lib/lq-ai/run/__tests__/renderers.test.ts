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
	registerStepRenderer,
	stepContext
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

/**
 * The first search of the recorded knowledge run, as the server sends it before the call settles:
 * the same key and intent, and no step note (that is written when the call settles), with the
 * fields of an effect that has no outcome yet, as the recorded unresolved effects have them.
 */
function unsettledSearch(status: 'admitted' | 'uncertain' | 'closed'): RunEffect {
	const settled = run('knowledge.completed').tree!.children[0].effects!.find(
		(candidate) => candidate.step?.kind === 'knowledge_search'
	)!;
	return {
		...structuredClone(settled),
		status,
		step: null,
		outcome: null,
		accounting: null,
		completed_at: null,
		charged_usd: status === 'closed' ? settled.reserved_usd : null
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
			summary: {
				document: 2,
				filename: 'dpa.md',
				start: 0,
				end: 190,
				total_chars: 190,
				truncated: false
			}
		},
		'Read document 2 (dpa.md)',
		['characters 0–190 of 190']
	],
	[
		{
			kind: 'document_read',
			summary: {
				document: 1,
				filename: 'msa.pdf',
				start: 0,
				end: 40000,
				total_chars: 90000,
				truncated: true
			}
		},
		'Read document 1 (msa.pdf)',
		['characters 0–40000 of 90000 (cut short)']
	],
	[
		{
			kind: 'knowledge_search',
			tool: 'search_knowledge_base',
			label: "Search the matter's knowledge bases",
			summary: {
				passages: 2,
				sources: [
					{ number: 1, file_id: 'f-1', document_id: 'd-1', filename: 'leave-policy.txt' },
					{ number: 2, file_id: 'f-2', document_id: 'd-2', filename: 'travel-policy.txt' }
				],
				listed: 2,
				searched: 2,
				failed: 0,
				withheld: 0
			}
		},
		'Searched the knowledge bases · 2 passages from [1] leave-policy.txt, [2] travel-policy.txt',
		[]
	],
	[
		{
			kind: 'note_saved',
			tool: 'save_note',
			summary: { name: 'note-terms.md', revision: 1, size_bytes: 14 }
		},
		'Saved a working note (note-terms.md)',
		['revision 1', '14 bytes']
	],
	[
		{
			kind: 'note_read',
			tool: 'read_note',
			summary: { name: 'note-terms.md', revision: 3, size_bytes: 1 }
		},
		'Read back a working note (note-terms.md)',
		['revision 3', '1 byte']
	],
	[
		{ kind: 'tool_refused', summary: { code: 'tool_not_granted' } },
		'A tool call was refused',
		['that tool is not granted to this task']
	],
	[
		{
			kind: 'tool_refused',
			label: 'Read a selected document',
			summary: { code: 'document_not_selected' }
		},
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
				'knowledge_search',
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
			effect({
				kind: 'document_read',
				reason: 'The agreement is needed.',
				summary: { document: 1 }
			})
		);
		expect(view.reason).toBe('The agreement is needed.');
		expect(describeEffect(effect({ kind: 'notes_started' })).reason).toBeNull();
	});
});

describe('the first call of a run', () => {
	const FOR_A_PLAN = 'Asked the model for a plan';
	const HOW_TO_RESPOND = 'Asked the model how to respond';
	const BY_TOOL = { plansByTool: true };

	it('reads as a call for a plan when the plan is written in text, or when nothing is said of the run', () => {
		for (const context of [undefined, {}, { plansByTool: false }]) {
			const view = describeEffect(effect({ kind: 'planning' }), context);
			expect(view.text, JSON.stringify(context)).toBe(FOR_A_PLAN);
			expect(view.known).toBe(true);
		}
	});

	it('reads as the model being asked how to respond where the run hands its plan over by a tool call', () => {
		const view = describeEffect(effect({ kind: 'planning' }), BY_TOOL);
		expect(view.text).toBe(HOW_TO_RESPOND);
		expect(view.kind).toBe('planning');
		expect(view.known).toBe(true);
		expect(view.facts).toEqual([]);
	});

	it('reads the same for an effect recorded with no step note under the planning key or intent', () => {
		for (const [label, patch] of [
			['key', { effect_key: 'chat:plan:v1', intent: 'something_else' }],
			['intent', { effect_key: 'x:1', intent: 'plan' }],
			['both', { effect_key: 'chat:plan:v1', intent: 'plan' }]
		] as const) {
			expect(describeEffect(effect(null, patch)).text, label).toBe(FOR_A_PLAN);
			expect(describeEffect(effect(null, patch), {}).text, label).toBe(FOR_A_PLAN);
			expect(describeEffect(effect(null, patch), BY_TOOL).text, label).toBe(HOW_TO_RESPOND);
		}
	});

	it('changes no other step: every other sentence reads the same whatever the run', () => {
		for (const [step, text] of KNOWN) {
			if (step.kind === 'planning') continue;
			expect(describeEffect(effect(step), BY_TOOL).text, step.kind).toBe(text);
		}
		for (const [key, intent, text] of [
			['demo:synthesis:v1', 'run_skill', 'Asked the model to combine the tasks’ answers'],
			['topic:t1', 'run_skill', 'Asked the model'],
			['x:1', 'retrieve_chunks', 'Read a document'],
			['x:1', 'something_new', 'Something new']
		] as const) {
			expect(
				describeEffect(effect(null, { effect_key: key, intent }), BY_TOOL).text,
				`${key} / ${intent}`
			).toBe(text);
		}
	});

	it('is given to every effect of a list, and the position in the list is not taken for it', () => {
		const effects = [
			effect({ kind: 'planning' }),
			effect({ kind: 'findings_collected' }),
			effect({ kind: 'synthesis' })
		];
		expect(describeEffects(effects, BY_TOOL).map((view) => view.text)).toEqual([
			HOW_TO_RESPOND,
			'Collected a task’s findings',
			'Asked the model to combine the tasks’ answers'
		]);
		expect(describeEffects(effects).map((view) => view.text)[0]).toBe(FOR_A_PLAN);
		expect(describeEffects(null, BY_TOOL)).toEqual([]);
	});

	it('is passed to a renderer that is taught, which may ignore it', () => {
		registerStepRenderer('probe_context', (_step, _effect, context) => ({
			text: `By tool: ${String(context.plansByTool)}`
		}));
		expect(describeEffect(effect({ kind: 'probe_context' })).text).toBe('By tool: undefined');
		expect(describeEffect(effect({ kind: 'probe_context' }), BY_TOOL).text).toBe('By tool: true');
		// A renderer written before there was a context takes two arguments and still works.
		registerStepRenderer('probe_two_arguments', (step, effect) => ({
			text: `${step.kind} ${effect.effect_key}`
		}));
		expect(describeEffect(effect({ kind: 'probe_two_arguments' }), BY_TOOL).text).toBe(
			'probe_two_arguments topic:t1:c0'
		);
	});

	it('reads, in the recorded run answered directly and in a planned one, as the run it is in', () => {
		for (const name of ['direct.completed', 'knowledge.completed', 'harness.completed'] as const) {
			const value = run(name);
			const planning = value.effects.find((e) => e.step?.kind === 'planning')!;
			expect(value.planning.terms?.planning, name).toBe('tool');
			expect(describeEffect(planning, { plansByTool: true }).text, name).toBe(HOW_TO_RESPOND);
		}
		// A run whose intake states no terms asked its model for a plan, and says so.
		const older = run('completed');
		const asked = older.effects.find((e) => e.step?.kind === 'planning')!;
		expect(older.planning.terms ?? null).toBeNull();
		expect(describeEffect(asked).text).toBe(FOR_A_PLAN);
	});
});

describe('a search of the knowledge bases', () => {
	const file = (number: number, filename: string) => ({
		number,
		file_id: `file-${number}`,
		document_id: `document-${number}`,
		filename
	});
	/** A search step with these counts, the way the backend records them. */
	const search = (summary: Record<string, unknown>, more: Partial<StepNote> = {}) =>
		describeEffect(
			effect(
				{
					kind: 'knowledge_search',
					tool: 'search_knowledge_base',
					label: "Search the matter's knowledge bases",
					summary: {
						passages: 0,
						sources: [],
						listed: 2,
						searched: 2,
						failed: 0,
						withheld: 0,
						...summary
					},
					...more
				},
				{ intent: 'retrieve_chunks' }
			)
		);

	it('says how many passages it found and the files they came from, each with its source number', () => {
		const view = search({
			passages: 2,
			sources: [file(1, 'leave-policy.txt'), file(2, 'travel-policy.txt')]
		});
		expect(view.known).toBe(true);
		expect(view.kind).toBe('knowledge_search');
		expect(view.text).toBe(
			'Searched the knowledge bases · 2 passages from [1] leave-policy.txt, [2] travel-policy.txt'
		);
		expect(view.facts).toEqual([]);
		expect(view.tone).toBe('done');
	});

	it('says "1 passage" for one, and several passages from one file as one file', () => {
		expect(search({ passages: 1, sources: [file(1, 'leave-policy.txt')] }).text).toBe(
			'Searched the knowledge bases · 1 passage from [1] leave-policy.txt'
		);
		expect(search({ passages: 3, sources: [file(27, 'travel-policy.txt')] }).text).toBe(
			'Searched the knowledge bases · 3 passages from [27] travel-policy.txt'
		);
	});

	it('says nothing was found when no passage was', () => {
		expect(search({ passages: 0 }).text).toBe('Searched the knowledge bases · nothing found');
	});

	it('says how many knowledge bases could be searched, only when not all of them could', () => {
		// Each case is a search that found nothing, so only the clause under test follows.
		expect(search({ listed: 2, searched: 2, failed: 0 }).text).not.toContain('could be searched');
		expect(search({ listed: 2, searched: 1, failed: 0 }).text).toBe(
			'Searched the knowledge bases · nothing found · 1 of 2 knowledge bases could be searched'
		);
		// One that failed was searched for and not searched: the count is what got through.
		expect(search({ listed: 3, searched: 3, failed: 1 }).text).toBe(
			'Searched the knowledge bases · nothing found · 2 of 3 knowledge bases could be searched'
		);
		expect(search({ listed: 2, searched: 2, failed: 2 }).text).toBe(
			'Searched the knowledge bases · nothing found · 0 of 2 knowledge bases could be searched'
		);
		// A failure count the search could not have had is not shown as a negative figure.
		expect(search({ listed: 2, searched: 1, failed: 4 }).text).toContain(
			'0 of 2 knowledge bases could be searched'
		);
	});

	it('says how many matching passages were left out, in the singular for one', () => {
		expect(search({ withheld: 3 }).text).toBe(
			'Searched the knowledge bases · no passage could be shown · 3 matching passages left out'
		);
		expect(search({ withheld: 1 }).text).toBe(
			'Searched the knowledge bases · no passage could be shown · 1 matching passage left out'
		);
		expect(search({ withheld: 0 }).text).not.toContain('left out');
	});

	it('does not say nothing was found when passages matched and none could be shown', () => {
		// Some passages did match: "nothing found" would say the opposite of "left out".
		for (const withheld of [1, 3, 40]) {
			const text = search({ withheld }).text;
			expect(text, String(withheld)).not.toContain('nothing found');
			expect(text, String(withheld)).toContain('no passage could be shown');
		}
		// With nothing withheld, or no figure for it, nothing found is what happened.
		for (const withheld of [0, undefined, null, 'x', -2]) {
			const text = search({ withheld }).text;
			expect(text, String(withheld)).toContain('nothing found');
			expect(text, String(withheld)).not.toContain('no passage could be shown');
		}
	});

	it('leaves the wording of a search that did show passages as it was, whatever was left out', () => {
		const view = search({ passages: 2, sources: [file(1, 'a.txt')], withheld: 4 });
		expect(view.text).toBe(
			'Searched the knowledge bases · 2 passages from [1] a.txt · 4 matching passages left out'
		);
		expect(view.text).not.toContain('could be shown');
	});

	it('puts what could not be searched between the two, for a search that showed nothing', () => {
		expect(search({ withheld: 2, listed: 3, searched: 2, failed: 0 }).text).toBe(
			'Searched the knowledge bases · no passage could be shown · 2 of 3 knowledge bases could be searched · 2 matching passages left out'
		);
	});

	it('puts what was found first, then what could not be searched, then what was left out', () => {
		const view = search({
			passages: 1,
			sources: [file(27, 'travel-policy.txt')],
			listed: 2,
			searched: 1,
			withheld: 1
		});
		expect(view.text).toBe(
			'Searched the knowledge bases · 1 passage from [27] travel-policy.txt · 1 of 2 knowledge bases could be searched · 1 matching passage left out'
		);
	});

	it('shows the model’s stated reason as it does for any tool step, and not the query', () => {
		const view = search({ passages: 0 }, { reason: 'Find the leave entitlement.' });
		expect(view.reason).toBe('Find the leave entitlement.');
		// The query the model wrote is in the tool call's arguments, under "What the model wrote".
		expect(view.text).not.toMatch(/annual leave|query/i);
		expect(search({ passages: 0 }).reason).toBeNull();
	});

	it('says only that it searched while the search is still going, and not that it found nothing', () => {
		// The server writes a search's step note when the call settles, so one that is going has none:
		// it is the call as recorded, with no note, read in a run whose plan lists knowledge bases.
		const going = describeEffect(unsettledSearch('admitted'), { listsKnowledgeBases: true });
		expect(going.kind).toBe('legacy');
		expect(going.text).toBe('Searched the knowledge bases');
		expect(going.tone).toBe('working');
		expect(going.facts).toEqual(['In progress']);
		expect(going.text).not.toMatch(/nothing found|passage/);
	});

	it('says only that it searched for a note that carries none of the figures, as it did', () => {
		const going = describeEffect(
			effect(
				{ kind: 'knowledge_search', tool: 'search_knowledge_base' },
				{ status: 'admitted', charged_usd: null }
			)
		);
		expect(going.text).toBe('Searched the knowledge bases');
		expect(going.text).not.toMatch(/nothing found|passage/);
	});

	it('reads a summary with figures missing or not numbers as saying nothing about them', () => {
		for (const summary of [
			undefined,
			null,
			{},
			{ passages: 'two', sources: 'none', listed: '2', searched: {}, failed: [], withheld: 'x' },
			{
				passages: 1,
				sources: [null, 5, 'x', {}, { number: 'one', filename: 'a.txt' }, { number: 3 }]
			}
		]) {
			const view = describeEffect(
				effect({ kind: 'knowledge_search', summary: summary as StepNote['summary'] })
			);
			expect(view.text, JSON.stringify(summary)).toMatch(/^Searched the knowledge bases/);
			expect(view.text, JSON.stringify(summary)).not.toMatch(/undefined|NaN|null|\[object/);
		}
		// A passage found, from a file the step does not name, is a passage and no more.
		expect(search({ passages: 1, sources: [] }).text).toBe(
			'Searched the knowledge bases · 1 passage'
		);
		// A source with no number or no file name is left out, not guessed at.
		expect(
			search({
				passages: 2,
				sources: [file(1, 'a.txt'), { number: 2 }, { filename: 'b.txt' }, file(4, '')]
			}).text
		).toBe('Searched the knowledge bases · 2 passages from [1] a.txt');
	});

	it('hands the owner’s file names back as the text they are', () => {
		const hostile = '<img src=x onerror=alert(1)>.pdf';
		const view = search({ passages: 1, sources: [file(1, hostile)] });
		expect(view.text).toBe(`Searched the knowledge bases · 1 passage from [1] ${hostile}`);
	});

	it('reads the two searches of the recorded task as a person would', () => {
		const task = run('knowledge.completed').tree!.children[0];
		const searches = task.effects.filter((effect) => effect.step?.kind === 'knowledge_search');
		const lines = describeEffects(searches).map((view) => [view.text, view.reason]);
		// What was found is the application's to say; the reasons are the model's, read from the recording.
		expect(lines).toEqual([
			[
				'Searched the knowledge bases · 1 passage from [1] leave-policy.txt',
				searches[0].step!.reason
			],
			['Searched the knowledge bases · nothing found', searches[1].step!.reason]
		]);
		expect(searches[0].step!.reason).toBeTruthy();
		expect(searches[1].step!.reason).toBeTruthy();
	});
});

describe('a call that fetches text, before it has settled', () => {
	const STATUSES = ['admitted', 'uncertain', 'closed'] as const;

	it('is recorded without a step note, and with the key and the intent a document read has', () => {
		for (const status of STATUSES) {
			const call = unsettledSearch(status);
			expect(call.step, status).toBeNull();
			expect(call.effect_key, status).toMatch(/^topic:t\d+:c\d+$/);
			// A search and a read of a document are told apart only by the note.
			expect(call.intent, status).toBe('retrieve_chunks');
		}
		const read = run('documents.completed').tree!.children[0].effects!.find(
			(candidate) => candidate.step?.kind === 'document_read'
		)!;
		expect(read.intent).toBe('retrieve_chunks');
	});

	it.each(STATUSES)(
		'%s: names a search where the plan lists only knowledge bases, and not a document',
		(status) => {
			const view = describeEffect(unsettledSearch(status), { listsKnowledgeBases: true });
			expect(view.text).toBe('Searched the knowledge bases');
			expect(view.text).not.toMatch(/document/i);
			const stated = describeEffect(unsettledSearch(status), {
				listsKnowledgeBases: true,
				listsDocuments: false
			});
			expect(stated.text).toBe('Searched the knowledge bases');
		}
	);

	it.each(STATUSES)(
		'%s: names a document where the plan lists only documents, as it always did',
		(status) => {
			const only = { listsDocuments: true };
			expect(describeEffect(unsettledSearch(status), only).text).toBe('Read a document');
			expect(
				describeEffect(unsettledSearch(status), { ...only, listsKnowledgeBases: false }).text
			).toBe('Read a document');
			// A plan that lists neither, and a step read with no context, read as before.
			expect(describeEffect(unsettledSearch(status), {}).text).toBe('Read a document');
			expect(describeEffect(unsettledSearch(status)).text).toBe('Read a document');
			expect(
				describeEffect(unsettledSearch(status), {
					listsDocuments: false,
					listsKnowledgeBases: false
				}).text
			).toBe('Read a document');
		}
	);

	it.each(STATUSES)(
		'%s: says it may be either where the plan lists documents and knowledge bases',
		(status) => {
			const both = { listsDocuments: true, listsKnowledgeBases: true };
			expect(describeEffect(unsettledSearch(status), both).text).toBe(
				'Read a document or searched the knowledge bases'
			);
		}
	);

	it('keeps what else it says of the call: whether it is going, has no outcome, or was closed', () => {
		const both = { listsDocuments: true, listsKnowledgeBases: true };
		const going = describeEffect(unsettledSearch('admitted'), both);
		expect([going.tone, going.facts]).toEqual(['working', ['In progress']]);
		const stuck = describeEffect(unsettledSearch('uncertain'), both);
		expect([stuck.tone, stuck.facts]).toEqual([
			'uncertain',
			['No confirmed outcome. It will not be retried automatically.']
		]);
		const closed = describeEffect(unsettledSearch('closed'), both);
		expect([closed.tone, closed.facts]).toEqual([
			'closed',
			['Closed without an outcome. The reserved amount was charged.']
		]);
	});

	it('does not claim what the call found, on any of them', () => {
		for (const status of STATUSES) {
			for (const context of [
				{},
				{ listsDocuments: true },
				{ listsKnowledgeBases: true },
				{ listsDocuments: true, listsKnowledgeBases: true }
			]) {
				const text = describeEffect(unsettledSearch(status), context).text;
				expect(text, `${status} ${JSON.stringify(context)}`).not.toMatch(
					/nothing found|passage|found|matched/i
				);
			}
		}
	});

	it('reads a call that has a step note by the note, whatever the plan lists', () => {
		// A settled search says what it found; the context is only for a call that has no note.
		const settled = run('knowledge.completed').tree!.children[0].effects!.find(
			(candidate) => candidate.step?.kind === 'knowledge_search'
		)!;
		const bare = describeEffect(settled).text;
		for (const context of [{}, { listsDocuments: true }, { listsKnowledgeBases: true }]) {
			expect(describeEffect(settled, context).text).toBe(bare);
		}
		expect(bare).toMatch(/^Searched the knowledge bases · /);
		const read = run('documents.completed').tree!.children[0].effects!.find(
			(candidate) => candidate.step?.kind === 'document_read'
		)!;
		expect(describeEffect(read, { listsKnowledgeBases: true }).text).toBe(
			describeEffect(read).text
		);
	});

	it('words no other call that has no note any differently', () => {
		for (const [key, intent] of [
			['topic:t1', 'run_skill'],
			['demo:notes:read:v1', 'workspace_read'],
			['chat:plan:v1', 'plan'],
			['x:1', 'refused']
		] as const) {
			const call = effect(null, { effect_key: key, intent });
			expect(describeEffect(call, { listsDocuments: true, listsKnowledgeBases: true }).text).toBe(
				describeEffect(call).text
			);
		}
	});

	it('reads it in every place a task’s steps are listed, through the same context', () => {
		const both = { listsDocuments: true, listsKnowledgeBases: true };
		const texts = describeEffects(STATUSES.map(unsettledSearch), both).map((view) => view.text);
		expect(texts).toEqual(Array(3).fill('Read a document or searched the knowledge bases'));
	});
});

describe('what a run’s plan lists, for reading its steps', () => {
	it('lists the knowledge bases of the recorded knowledge run, and no document', () => {
		for (const name of ['knowledge.completed', 'knowledge.awaiting-approval'] as const) {
			expect(stepContext(run(name)), name).toEqual({
				plansByTool: true,
				listsDocuments: false,
				listsKnowledgeBases: true
			});
		}
	});

	it('lists the documents of the recorded documents run, and no knowledge base', () => {
		const context = stepContext(run('documents.completed'));
		expect(context.listsDocuments).toBe(true);
		expect(context.listsKnowledgeBases).toBe(false);
	});

	it('lists both where the plan names documents and knowledge bases', () => {
		const value = structuredClone(run('knowledge.completed'));
		value.tree!.plan.documents = run('documents.completed').tree!.plan.documents;
		expect(value.tree!.plan.documents!.length).toBeGreaterThan(0);
		expect(stepContext(value)).toMatchObject({ listsDocuments: true, listsKnowledgeBases: true });
	});

	it('takes the intake’s lists where the plan has none, as the plan card does', () => {
		const value = structuredClone(run('knowledge.completed'));
		const names = value.tree!.plan.knowledge_bases;
		expect(names!.length).toBeGreaterThan(0);
		delete value.tree!.plan.knowledge_bases;
		value.planning.knowledge_bases = names;
		expect(stepContext(value).listsKnowledgeBases).toBe(true);
		value.planning.knowledge_bases = [];
		expect(stepContext(value).listsKnowledgeBases).toBe(false);
		// A run that is still planning has no plan: its intake's list is what there is.
		expect(stepContext(run('knowledge.planning')).listsKnowledgeBases).toBe(true);
	});

	it('does not count a knowledge base without a name, or a list that is not there', () => {
		const value = structuredClone(run('knowledge.completed'));
		value.tree!.plan.knowledge_bases = [
			{ knowledge_base_id: 'a', name: '   ' },
			{ knowledge_base_id: 'b', name: '' }
		];
		expect(stepContext(value).listsKnowledgeBases).toBe(false);
		for (const empty of [undefined, null, []]) {
			value.tree!.plan.knowledge_bases = empty as never;
			value.planning.knowledge_bases = empty as never;
			expect(stepContext(value).listsKnowledgeBases, String(empty)).toBe(false);
		}
	});

	it('says only that the plan is handed over by a tool call where the intake says so, for an older run', () => {
		const older = stepContext(run('completed'));
		expect(older.plansByTool).toBe(false);
		expect(older.listsKnowledgeBases).toBe(false);
	});

	it('is total: every recorded run gives booleans for all three', () => {
		for (const { label, run: value } of allRuns()) {
			const context = stepContext(value);
			for (const key of ['plansByTool', 'listsDocuments', 'listsKnowledgeBases'] as const) {
				expect(typeof context[key], `${label} ${key}`).toBe('boolean');
			}
		}
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
		[
			'demo:findings:share:v1',
			'workspace_share',
			'Shared the task’s findings with the orchestrator'
		],
		['demo:collect:abc:v1', 'workspace_read', 'Collected a task’s findings'],
		['demo:synthesis:v1', 'run_skill', 'Asked the model to combine the tasks’ answers']
	])('%s (%s)', (key, intent, text) => {
		const view = describeEffect(effect(null, { effect_key: key, intent }));
		expect(view.kind).toBe('legacy');
		expect(view.known).toBe(false);
		expect(view.text).toBe(text);
	});

	it('falls back to the intent, then to the key', () => {
		expect(
			describeEffect(effect(undefined, { effect_key: 'x:1', intent: 'retrieve_chunks' })).text
		).toBe('Read a document');
		expect(
			describeEffect(effect(undefined, { effect_key: 'x:1', intent: 'something_new' })).text
		).toBe('Something new');
		expect(describeEffect(effect(undefined, { effect_key: 'x:1', intent: '' })).text).toBe('X:1');
		expect(describeEffect(effect(undefined, { effect_key: '', intent: '' })).text).toBe(
			'A step was recorded'
		);
		expect(describeEffect(effect(undefined, { effect_key: 'k', intent: 'constructor' })).text).toBe(
			'Constructor'
		);
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
		expect(describeEffect(effect(null, { outcome: 'tool_refused', intent: 'refused' })).tone).toBe(
			'refused'
		);
		expect(describeEffect(effect(null, { status: 'uncertain', charged_usd: null }))).toMatchObject({
			tone: 'uncertain'
		});
		expect(describeEffect(effect(null, { status: 'closed' })).tone).toBe('closed');
		expect(describeEffect(effect(null, { status: 'admitted', charged_usd: null })).tone).toBe(
			'working'
		);
		expect(describeEffect(effect({ kind: 'notes_read' })).tone).toBe('done');
	});

	it('says an uncertain effect will not be retried, and a closed one was charged', () => {
		const uncertain = describeEffect(effect(null, { status: 'uncertain', charged_usd: null }));
		expect(uncertain.facts).toContain(
			'No confirmed outcome. It will not be retried automatically.'
		);
		const closed = describeEffect(
			effect(null, { status: 'closed', charged_usd: '0.1842', reserved_usd: '0.1842' })
		);
		expect(closed.facts).toContain('Closed without an outcome. The reserved amount was charged.');
		expect(closed.cost).toBe('$0.1842');
	});

	it('shows what was charged, or what is still reserved, and nothing for a free step', () => {
		expect(
			describeEffect(
				effect({ kind: 'model_turn' }, { charged_usd: '0.1841', reserved_usd: '0.1841' })
			).cost
		).toBe('$0.1841');
		expect(describeEffect(effect({ kind: 'notes_read' })).cost).toBeNull();
		expect(
			describeEffect(
				effect(null, { status: 'uncertain', charged_usd: null, reserved_usd: '0.0648' })
			).cost
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
