/**
 * The plan card: what the owner is asked to approve, built from the run read alone.
 *
 * Over the recordings of this release (a run on a fixed document, a run on documents
 * the owner selected) and the six runs recorded for the previous release, which have no
 * tools, turn limits, documents or profile and still have to read sensibly.
 */
import { describe, expect, it } from 'vitest';

import type { OrchestrationChatRun, RunTool } from '../../api/orchestration';
import {
	approvalSentence,
	orchestratorPin,
	pinnedText,
	planState,
	planView,
	receiptPin,
	searchLine,
	searchLineParts,
	type PlanView
} from '../plan';
import { formatUsd, namedLineText } from '../format';
import { LEGACY_RUNS, allRuns, legacyRun, run } from './fixtures';

/** A copy of a recorded run with `change` applied to it. */
function edited(
	base: OrchestrationChatRun,
	change: (copy: OrchestrationChatRun) => void
): OrchestrationChatRun {
	const copy = structuredClone(base);
	change(copy);
	return copy;
}

function view(value: OrchestrationChatRun): PlanView {
	const result = planView(value);
	if (!result) throw new Error('the run has no plan');
	return result;
}

const READ_DOCUMENT = 'Read a selected document';
const READ_NOTE = 'Read back a working note';
const SAVE_NOTE = 'Save a working note';

describe('the plan of a new run on a fixed document', () => {
	const recorded = run('awaiting-approval');
	const card = view(recorded);

	it('says which plan it is, so approval is for exactly this one', () => {
		expect(card.revision).toBe(1);
		expect(card.planHash).toBe(recorded.tree!.plan_hash);
		expect(card.planHash).toMatch(/^[0-9a-f]{64}$/);
		expect(card.approved).toBe(false);
	});

	it('lists every task with its question, skill, tools, document, budget and turn limit', () => {
		expect(card.tasks).toHaveLength(2);
		const [first, second] = card.tasks;
		expect(first.index).toBe(1);
		expect(first.topic).toBe('Payments');
		expect(second.index).toBe(2);
		expect(second.topic).toBe('Renewal and termination');
		for (const task of card.tasks) {
			expect(task.skill).toBe('contract-qa v1.0.0');
			expect(task.tools).toEqual([READ_DOCUMENT, READ_NOTE, SAVE_NOTE]);
			expect(task.documents).toEqual([
				{ number: 1, filename: 'fictional-vendor-agreement.md', addedForRun: false }
			]);
			expect(task.budget).toBe('$0.7434');
			expect(task.turnLimit).toBe(2);
		}
	});

	it('carries the task’s own words through untouched', () => {
		recorded.tree!.plan.children.forEach((child, position) => {
			const task = card.tasks[position];
			expect(task.question).toBe(child.task.question);
			expect(task.boundaries).toBe(child.task.boundaries);
			expect(task.outputContract).toBe(child.task.output_contract);
			expect(task.stoppingCondition).toBe(child.task.stopping_condition);
		});
	});

	it('states the limits of the whole plan', () => {
		expect(card.totalCap).toBe('$2.00');
		expect(card.rootAllowance).toBe('$0.4956');
		expect(card.planningAllowance).toBe('$0.2478');
		expect(card.deadline).toBe(recorded.tree!.plan.deadline);
		expect(card.maxActive).toBe(2);
		expect(card.attemptLimitSeconds).toBe(120);
		expect(card.model).toBe('selected/native');
		expect(card.reads).toBe(
			'The installed fictional vendor agreement only. No matter documents or live sources.'
		);
		// The charge for the planning call as recorded: it follows the size of the request.
		expect(card.planningCharge).toBe('$0.0647');
	});

	it('lists the document the whole plan may read', () => {
		expect(card.documents).toEqual([
			{ number: 1, filename: 'fictional-vendor-agreement.md', addedForRun: false }
		]);
	});
});

describe('the plan of a new run on documents the owner selected', () => {
	const recorded = run('documents.awaiting-approval');
	const card = view(recorded);

	it('numbers the documents as the owner selected them, and says which the run attached to the matter', () => {
		expect(card.documents).toEqual([
			{ number: 1, filename: 'msa.txt', addedForRun: false },
			{ number: 2, filename: 'dpa.md', addedForRun: true }
		]);
	});

	it('lets each task read the documents the plan names for it, with its own turn limit and budget', () => {
		expect(card.tasks).toHaveLength(2);
		for (const task of card.tasks) {
			expect(task.documents).toEqual(card.documents);
			expect(task.tools).toEqual([READ_DOCUMENT, READ_NOTE, SAVE_NOTE]);
			expect(task.turnLimit).toBe(5);
			expect(task.budget).toBe('$3.4686');
			// Changed on purpose: New harness is instructed by an engine prompt file, not by the
			// contract-qa skill, so the task names that file and the version the run pinned.
			expect(task.skill).toBe('new_harness/subagent.v2 (version 2)');
			expect(task.skillKind).toBe('prompt');
		}
	});

	it('states the profile’s limits and what it may read in its own words', () => {
		expect(card.totalCap).toBe('$10.00');
		expect(card.rootAllowance).toBe('$1.1562');
		expect(card.planningAllowance).toBe('$0.5781');
		expect(card.attemptLimitSeconds).toBe(300);
		expect(card.maxActive).toBe(2);
		// Changed on purpose: the profile also reads the chat's recent messages, the documents
		// are optional ("if any"), and in a matter it reads the knowledge bases attached to it.
		expect(card.reads).toBe(
			"Your request, this chat's recent messages, the documents you select, if any, and in a matter the knowledge bases attached to it. No other files and no live sources."
		);
		// What the planning effect was charged, read from the recording: it changes with
		// the size of what the planning call is sent.
		expect(card.planningCharge).toBe(formatUsd(recorded.effects[0].charged_usd));
		expect(card.planningCharge).toMatch(/^\$0\.0\d+$/);
	});

	it('is the same plan once approved and delivered, now marked approved', () => {
		const delivered = view(run('documents.completed'));
		expect(delivered.approved).toBe(true);
		expect(delivered.tasks.map((task) => task.documents)).toEqual(
			card.tasks.map((task) => task.documents)
		);
		expect(delivered.totalCap).toBe(card.totalCap);
		expect(delivered.planHash).toBe(card.planHash);
	});
});

describe('which documents a task may read', () => {
	const base = run('documents.awaiting-approval');
	const [msaId, dpaId] = base.tree!.plan.documents!.map((doc) => doc.document_id);

	it('lists only the documents that task is given, not every document in the plan', () => {
		const value = edited(base, (copy) => {
			copy.tree!.plan.children[0].execution!.resources!.document_ids = [dpaId];
		});
		const card = view(value);
		expect(card.tasks[0].documents).toEqual([{ number: 2, filename: 'dpa.md', addedForRun: true }]);
		expect(card.tasks[1].documents.map((doc) => doc.number)).toEqual([1, 2]);
		expect(card.documents).toHaveLength(2);
	});

	it('numbers them by the owner’s selection, whatever order the task lists them in', () => {
		const value = edited(base, (copy) => {
			copy.tree!.plan.children[0].execution!.resources!.document_ids = [dpaId, msaId];
		});
		expect(view(value).tasks[0].documents.map((doc) => doc.filename)).toEqual([
			'msa.txt',
			'dpa.md'
		]);
	});

	it('lists the plan’s documents in number order even if the server sent them in another', () => {
		const value = edited(base, (copy) => {
			copy.tree!.plan.documents!.reverse();
		});
		expect(view(value).documents.map((doc) => doc.number)).toEqual([1, 2]);
	});

	it('does not show a document the plan does not describe', () => {
		const value = edited(base, (copy) => {
			copy.tree!.plan.children[0].execution!.resources!.document_ids = [msaId, 'not-in-the-plan'];
		});
		expect(view(value).tasks[0].documents.map((doc) => doc.filename)).toEqual(['msa.txt']);
	});

	it('reads the documents from the planning snapshot when the plan itself does not list them', () => {
		const value = edited(base, (copy) => {
			delete copy.tree!.plan.documents;
		});
		const card = view(value);
		expect(card.documents.map((doc) => doc.filename)).toEqual(['msa.txt', 'dpa.md']);
		expect(card.tasks[0].documents.map((doc) => doc.filename)).toEqual(['msa.txt', 'dpa.md']);
	});

	it('has no documents to list when neither does', () => {
		const value = edited(base, (copy) => {
			delete copy.tree!.plan.documents;
			delete copy.planning.documents;
		});
		const card = view(value);
		expect(card.documents).toEqual([]);
		for (const task of card.tasks) expect(task.documents).toEqual([]);
	});
});

describe('which tools a task may call, and for how many turns', () => {
	const base = run('documents.awaiting-approval');

	it('uses the labels the run read gives the task’s session', () => {
		expect(view(base).tasks[0].tools).toEqual([READ_DOCUMENT, READ_NOTE, SAVE_NOTE]);
	});

	it('falls back to the plan’s own tool names, in words, when the session has none recorded', () => {
		const value = edited(base, (copy) => {
			for (const child of copy.tree!.children) delete child.tools;
		});
		expect(view(value).tasks[0].tools).toEqual(['Read document', 'Read note', 'Save note']);
	});

	it('does not take the tools of a different session', () => {
		const value = edited(base, (copy) => {
			copy.tree!.children[0].session_id = 'some-other-session';
			copy.tree!.children[0].tools = [
				{ name: 'delete_everything', label: 'Delete everything', phase: 'analysis' }
			];
		});
		expect(view(value).tasks[0].tools).toEqual(['Read document', 'Read note', 'Save note']);
	});

	it('lists a tool once even when the plan grants it in several phases', () => {
		const value = edited(base, (copy) => {
			for (const child of copy.tree!.children) delete child.tools;
			copy.tree!.plan.children[0].tools = {
				analysis: ['read_document', 'save_note'],
				drafting: ['save_note', 'read_document', 'read_note'],
				delivery: []
			};
		});
		expect(view(value).tasks[0].tools).toEqual(['Read document', 'Save note', 'Read note']);
	});

	// Approval is consent to the tools a task may call, so a tool is never listed as nothing.
	it('names a tool whose label is blank or only spaces from its name', () => {
		for (const label of ['', ' ', '   ', '\t\n', ' ']) {
			const value = edited(base, (copy) => {
				copy.tree!.children[0].tools = [{ name: 'read_document', label, phase: 'analysis' }];
			});
			expect(view(value).tasks[0].tools, JSON.stringify(label)).toEqual(['Read document']);
		}
	});

	it('names a tool with no label at all from its name', () => {
		for (const label of [undefined, null]) {
			const value = edited(base, (copy) => {
				copy.tree!.children[0].tools = [
					{ name: 'save_note', label, phase: 'analysis' } as unknown as RunTool
				];
			});
			expect(view(value).tasks[0].tools, String(label)).toEqual(['Save note']);
		}
	});

	it('lists a label without the spaces around it', () => {
		const value = edited(base, (copy) => {
			copy.tree!.children[0].tools = [
				{ name: 'read_document', label: '  Read a selected document  ', phase: 'analysis' }
			];
		});
		expect(view(value).tasks[0].tools).toEqual(['Read a selected document']);
	});

	it('never lists a tool as nothing, whatever the recorded plans carry', () => {
		for (const { label, run: value } of allRuns()) {
			for (const task of planView(value)?.tasks ?? []) {
				for (const tool of task.tools) expect(tool.trim().length, label).toBeGreaterThan(0);
			}
		}
	});

	it('gives no turn limit to a task that has no tools to take turns with', () => {
		const value = edited(base, (copy) => {
			for (const child of copy.tree!.children) child.tools = [];
			for (const child of copy.tree!.plan.children) child.tools = {};
		});
		for (const task of view(value).tasks) {
			expect(task.tools).toEqual([]);
			expect(task.turnLimit).toBeNull();
		}
	});

	it('takes the turn limit from the task’s session when the plan does not carry one, and none when it is zero', () => {
		const fromSession = edited(base, (copy) => {
			delete copy.tree!.plan.children[0].turn_limit;
		});
		expect(view(fromSession).tasks[0].turnLimit).toBe(5);
		const zero = edited(base, (copy) => {
			copy.tree!.plan.children[0].turn_limit = 0;
			copy.tree!.children[0].turn_limit = 0;
		});
		expect(view(zero).tasks[0].turnLimit).toBeNull();
	});
});

describe('the skill a task runs', () => {
	const base = run('awaiting-approval');

	it('is the skill’s name and the version the run pinned', () => {
		expect(view(base).tasks[0].skill).toBe('contract-qa v1.0.0');
	});

	it('is the name alone when no version was recorded', () => {
		const value = edited(base, (copy) => {
			copy.planning.child_skill_version = '';
		});
		expect(view(value).tasks[0].skill).toBe('contract-qa');
	});

	it('is a skill for the fixed-document profile, and is named so', () => {
		for (const task of view(base).tasks) expect(task.skillKind).toBe('skill');
	});

	it('says so when no skill was recorded, rather than leaving it blank', () => {
		const value = edited(base, (copy) => {
			delete copy.tree!.plan.children[0].execution;
		});
		expect(view(value).tasks[0].skill).toBe('Skill not recorded');
		expect(view(value).tasks[1].skill).toBe('contract-qa v1.0.0');
	});
});

describe('how a receipt names what instructed a call', () => {
	it('says "Prompt file" for one of the engine’s prompt files, with its name', () => {
		// The name already ends with the version, so the version is not said again.
		expect(receiptPin({ name: 'new_harness/orchestrator.v2', version: '2', kind: 'prompt' })).toBe(
			'Prompt file new_harness/orchestrator.v2'
		);
		expect(receiptPin({ name: 'new_harness/subagent.v2', version: '2', kind: 'prompt' })).toBe(
			'Prompt file new_harness/subagent.v2'
		);
	});

	it('leaves the version out only when the name ends with exactly that version', () => {
		// Another version, a version that merely ends the same, and a name that holds it elsewhere.
		expect(receiptPin({ name: 'new_harness/orchestrator.v2', version: '3', kind: 'prompt' })).toBe(
			'Prompt file new_harness/orchestrator.v2 v3'
		);
		expect(receiptPin({ name: 'new_harness/orchestrator.v12', version: '2', kind: 'prompt' })).toBe(
			'Prompt file new_harness/orchestrator.v12 v2'
		);
		expect(
			receiptPin({ name: 'new_harness/orchestrator.v2.draft', version: '2', kind: 'prompt' })
		).toBe('Prompt file new_harness/orchestrator.v2.draft v2');
		// The same is true of a pin that is named as a skill.
		expect(receiptPin({ name: 'contract-qa.v1', version: '1', kind: 'skill' })).toBe(
			'Skill contract-qa.v1'
		);
		expect(receiptPin({ name: 'contract-qa', version: '1', kind: 'skill' })).toBe(
			'Skill contract-qa v1'
		);
	});

	it('says "Skill" for an installed skill, as it always did, with or without its kind', () => {
		expect(receiptPin({ name: 'contract-qa', version: '1.0.0', kind: 'skill' })).toBe(
			'Skill contract-qa v1.0.0'
		);
		expect(receiptPin({ name: 'contract-qa', version: '1.0.0' })).toBe('Skill contract-qa v1.0.0');
		// A kind it has never seen is not a prompt file: it is named as a skill was before there were any.
		expect(receiptPin({ name: 'x', version: '1', kind: 'something_new' })).toBe('Skill x v1');
	});

	it('leaves out a version the pin does not state, and names nothing for a pin with no name', () => {
		for (const version of ['', '  ', null, undefined]) {
			expect(receiptPin({ name: 'contract-qa', version }), String(version)).toBe(
				'Skill contract-qa'
			);
			expect(receiptPin({ name: 'p/r.v1', version, kind: 'prompt' }), String(version)).toBe(
				'Prompt file p/r.v1'
			);
		}
		expect(receiptPin({ name: '' })).toBeNull();
		expect(receiptPin(null)).toBeNull();
		expect(receiptPin(undefined)).toBeNull();
	});

	it('names what each recorded effect was pinned to, by its kind', () => {
		const prompted = run('direct.completed').effects[0].skill!;
		expect(prompted.kind).toBe('prompt');
		// The recorded pin's name ends with its version: the receipt says the file, once.
		expect(prompted.name.endsWith(`.v${prompted.version}`)).toBe(true);
		expect(receiptPin(prompted)).toBe(`Prompt file ${prompted.name}`);
		const skilled = run('completed').effects.find((e) => e.skill)?.skill;
		if (skilled) expect(receiptPin(skilled)).toBe(`Skill ${skilled.name} v${skilled.version}`);
	});

	it('hands the name and version back as the text they are', () => {
		const hostile = '<img src=x onerror=alert(1)>';
		expect(receiptPin({ name: hostile, version: hostile, kind: 'prompt' })).toBe(
			`Prompt file ${hostile} v${hostile}`
		);
		// A name that ends with the version, hostile or not, is named as it is.
		expect(receiptPin({ name: `${hostile}.v2`, version: '2', kind: 'prompt' })).toBe(
			`Prompt file ${hostile}.v2`
		);
	});
});

describe('what a session is pinned to', () => {
	it('names a skill with its version, and a prompt file with the version it pinned', () => {
		expect(pinnedText({ name: 'contract-qa' }, '1.0.0')).toBe('contract-qa v1.0.0');
		expect(pinnedText({ name: 'contract-qa', kind: 'skill' }, '1.0.0')).toBe('contract-qa v1.0.0');
		expect(pinnedText({ name: 'new_harness/subagent.v1', kind: 'prompt' }, '1')).toBe(
			'new_harness/subagent.v1 (version 1)'
		);
	});

	it('is the name alone when no version was recorded, and nothing when there is no name', () => {
		for (const version of ['', '  ', null, undefined]) {
			expect(pinnedText({ name: 'contract-qa' }, version)).toBe('contract-qa');
			expect(pinnedText({ name: 'p/r.v1', kind: 'prompt' }, version)).toBe('p/r.v1');
		}
		expect(pinnedText({ name: '' }, '1')).toBeNull();
		expect(pinnedText(null, '1')).toBeNull();
		expect(pinnedText(undefined, '1')).toBeNull();
	});

	it('calls the orchestrator’s pin a skill for the fixed-document profile', () => {
		const pin = orchestratorPin(run('completed'))!;
		expect(pin.label).toBe('Orchestrator skill');
		expect(pin.text).toBe('orchestration-chat-demo v1.0.0');
		expect(pin.digest).toBe(run('completed').tree!.plan.root.skill.digest);
	});

	it('calls it a prompt for New harness, with the digest the run pinned', () => {
		const recorded = run('harness.completed');
		const pin = orchestratorPin(recorded)!;
		expect(pin.label).toBe('Orchestrator prompt');
		expect(pin.text).toBe('new_harness/orchestrator.v2 (version 2)');
		expect(pin.digest).toBe(recorded.tree!.plan.root.skill.digest);
		expect(pin.digest).toBe(recorded.planning.root!.skill.digest);
	});

	it('has no pin to show for a run that has no plan yet', () => {
		expect(orchestratorPin(run('harness.follow-up.planning'))).toBeNull();
		expect(orchestratorPin(run('planning'))).toBeNull();
	});
});

describe('money, limits and the planning charge', () => {
	const base = run('documents.awaiting-approval');

	it('leaves out a planning allowance the run does not state', () => {
		for (const empty of ['', undefined]) {
			const value = edited(base, (copy) => {
				(copy.planning as { planning_allowance_usd?: string }).planning_allowance_usd = empty;
			});
			expect(view(value).planningAllowance).toBeNull();
		}
	});

	it('finds the planning charge by the effect that paid for the plan', () => {
		const charge = formatUsd(base.effects[0].charged_usd);
		expect(view(base).planningCharge).toBe(charge);
		const byKey = edited(base, (copy) => {
			copy.effects[0].intent = 'something_else';
		});
		expect(view(byKey).planningCharge).toBe(charge);
		const neither = edited(base, (copy) => {
			copy.effects[0].intent = 'something_else';
			copy.effects[0].effect_key = 'topic:t1';
		});
		expect(view(neither).planningCharge).toBeNull();
		expect(view(edited(base, (copy) => (copy.effects = []))).planningCharge).toBeNull();
	});

	it('does not state a planning charge that has not been settled', () => {
		for (const charged of [null, undefined]) {
			const value = edited(base, (copy) => {
				(copy.effects[0] as { charged_usd?: string | null }).charged_usd = charged;
			});
			expect(view(value).planningCharge).toBeNull();
		}
	});

	it('states a planning charge of zero as zero, since that is a charge', () => {
		const value = edited(base, (copy) => {
			copy.effects[0].charged_usd = '0.0000';
		});
		expect(view(value).planningCharge).toBe('$0.00');
	});

	it('takes the attempt limit from the plan, then the planning snapshot, then nothing', () => {
		expect(view(base).attemptLimitSeconds).toBe(300);
		const fromPlanning = edited(base, (copy) => {
			delete copy.tree!.plan.attempt_timeout_seconds;
		});
		expect(view(fromPlanning).attemptLimitSeconds).toBe(300);
		const nowhere = edited(base, (copy) => {
			delete copy.tree!.plan.attempt_timeout_seconds;
			(copy.planning as { attempt_timeout_seconds?: number }).attempt_timeout_seconds = undefined;
		});
		expect(view(nowhere).attemptLimitSeconds).toBeNull();
	});
});

describe('the knowledge bases the tasks of a plan may search', () => {
	const awaiting = run('knowledge.awaiting-approval');
	const NAMES = ['People policies', 'Travel'];

	it('is one line that names them, for the owner to read before approving', () => {
		expect(awaiting.status).toBe('awaiting_approval');
		expect(awaiting.tree!.plan.knowledge_bases!.map((kb) => kb.name)).toEqual(NAMES);
		expect(view(awaiting).knowledgeBasesLine).toBe('Tasks may search: People policies, Travel.');
		expect(searchLine(NAMES)).toBe('Tasks may search: People policies, Travel.');
		expect(searchLine(['Travel'])).toBe('Tasks may search: Travel.');
	});

	it('is the same line once the plan is approved and the run is delivered', () => {
		const delivered = view(run('knowledge.completed'));
		expect(delivered.approved).toBe(true);
		expect(delivered.knowledgeBasesLine).toBe('Tasks may search: People policies, Travel.');
	});

	it('is the plan’s own list, and the intake’s only where the plan records none', () => {
		const changed = edited(awaiting, (copy) => {
			copy.tree!.plan.knowledge_bases = [{ knowledge_base_id: 'plan-kb', name: 'Plan’s list' }];
			copy.planning.knowledge_bases = [{ knowledge_base_id: 'intake-kb', name: 'Intake’s list' }];
		});
		expect(view(changed).knowledgeBasesLine).toBe('Tasks may search: Plan’s list.');
		const unrecorded = edited(awaiting, (copy) => {
			delete copy.tree!.plan.knowledge_bases;
		});
		expect(view(unrecorded).knowledgeBasesLine).toBe('Tasks may search: People policies, Travel.');
		// An empty list in the plan is the plan's word: it is not replaced by the intake's.
		const none = edited(awaiting, (copy) => {
			copy.tree!.plan.knowledge_bases = [];
		});
		expect(view(none).knowledgeBasesLine).toBeNull();
	});

	it('is nothing at all for a plan whose tasks may search none', () => {
		for (const name of [
			'awaiting-approval',
			'completed',
			'documents.awaiting-approval',
			'harness.completed',
			'harness.no-documents.awaiting-approval'
		] as const) {
			expect(view(run(name)).knowledgeBasesLine, name).toBeNull();
		}
		for (const name of LEGACY_RUNS) {
			const recorded = legacyRun(name);
			if (recorded.tree) expect(view(recorded).knowledgeBasesLine, name).toBeNull();
		}
		expect(searchLine([])).toBeNull();
	});

	it('is said only of the recorded plans that name knowledge bases', () => {
		const said = allRuns()
			.filter(({ run: value }) => value.tree && view(value).knowledgeBasesLine !== null)
			.map(({ label }) => label);
		expect(said).toEqual(['run.knowledge.awaiting-approval', 'run.knowledge.completed']);
	});

	it('leaves out a name with nothing in it, and hands the others back as written', () => {
		const odd = edited(awaiting, (copy) => {
			copy.tree!.plan.knowledge_bases = [
				{ knowledge_base_id: 'a', name: '  Travel  ' },
				{ knowledge_base_id: 'b', name: '' },
				{ knowledge_base_id: 'c', name: '<img src=x onerror=alert(1)>' }
			];
		});
		expect(view(odd).knowledgeBasesLine).toBe(
			'Tasks may search: Travel, <img src=x onerror=alert(1)>.'
		);
	});

	it('carries the same line in pieces, one item to a name, so that each name can be drawn by itself', () => {
		expect(view(awaiting).knowledgeBases).toEqual({
			lead: 'Tasks may search: ',
			names: NAMES,
			tail: '.'
		});
		expect(searchLineParts(['Travel'])).toEqual({
			lead: 'Tasks may search: ',
			names: ['Travel'],
			tail: '.'
		});
		expect(searchLineParts([])).toBeNull();
		// The pieces, put together, are the line; the two cannot say different things.
		for (const { run: value, label } of allRuns()) {
			if (!value.tree) continue;
			const card = view(value);
			expect(card.knowledgeBases === null, label).toBe(card.knowledgeBasesLine === null);
			if (card.knowledgeBases)
				expect(namedLineText(card.knowledgeBases), label).toBe(card.knowledgeBasesLine);
		}
	});

	it('keeps a name with a comma in it as one item, and the names as written', () => {
		const odd = edited(awaiting, (copy) => {
			copy.tree!.plan.knowledge_bases = [
				{ knowledge_base_id: 'a', name: '  Travel, Expenses  ' },
				{ knowledge_base_id: 'b', name: '' },
				{ knowledge_base_id: 'c', name: '\u202Eevil' }
			];
		});
		expect(view(odd).knowledgeBases!.names).toEqual(['Travel, Expenses', '\u202Eevil']);
	});

	it('does not share the list it was given', () => {
		const given = ['A', 'B'];
		const parts = searchLineParts(given)!;
		parts.names.push('C');
		expect(given).toEqual(['A', 'B']);
	});
});

describe('a run with no plan', () => {
	const noPlan = [
		'planning',
		'failed-plan',
		'unfunded-plan',
		'uncertain-planning',
		'closed-planning',
		'documents.planning',
		// An answer the orchestrator gave itself has no plan, and neither does a plan that was
		// written out as text or carried a placeholder, or one still being asked for.
		'direct.planning',
		'direct.completed',
		'plan-not-handed-over',
		'plan-has-placeholders',
		'knowledge.planning'
	] as const;

	it.each(noPlan)('run.%s has no plan card', (name) => {
		expect(planView(run(name))).toBeNull();
	});

	it.each(['fenced-plan-run', 'truncated-plan-run'] as const)(
		'previous release: %s has no plan card',
		(name) => {
			expect(planView(legacyRun(name))).toBeNull();
		}
	);
});

describe('the six runs recorded for the previous release', () => {
	const withPlan = ['model-run', 'rejected-run', 'stalled-model-run', 'timeout-run'] as const;

	it('covers all six: four proposed a plan, two never got one', () => {
		expect(withPlan.length + 2).toBe(LEGACY_RUNS.length);
		expect(LEGACY_RUNS.filter((name) => !(withPlan as readonly string[]).includes(name))).toEqual([
			'fenced-plan-run',
			'truncated-plan-run'
		]);
	});

	it.each(withPlan)('%s still has a plan card with every task, and no invented fields', (name) => {
		const recorded = legacyRun(name);
		const card = view(recorded);
		expect(card.tasks).toHaveLength(recorded.tree!.plan.children.length);
		for (const task of card.tasks) {
			// None of the fields added since exist, and none is made up.
			expect(task.tools).toEqual([]);
			expect(task.documents).toEqual([]);
			expect(task.turnLimit).toBeNull();
			expect(task.skill).toBe('contract-qa v1.0.0');
			expect(task.topic.length).toBeGreaterThan(0);
			expect(task.question.length).toBeGreaterThan(0);
			expect(task.budget).toBe('$0.00');
		}
		expect(card.documents).toEqual([]);
		expect(card.reads).toBeNull();
		expect(card.totalCap).toBe('$2.00');
		expect(card.model.length).toBeGreaterThan(0);
		expect(card.attemptLimitSeconds).toBe(recorded.planning.attempt_timeout_seconds);
	});

	it.each(withPlan)('%s has nothing in the card that reads as a missing value', (name) => {
		const text = JSON.stringify(view(legacyRun(name)));
		expect(text).not.toMatch(/undefined|NaN|\[object|"null"/);
	});

	it('states a plan approved or not as the recording says', () => {
		expect(view(legacyRun('model-run')).approved).toBe(true);
		expect(view(legacyRun('rejected-run')).approved).toBe(false);
	});
});

describe('planState', () => {
	it('is proposed while the plan awaits a decision, and approved once it has one', () => {
		expect(planState(run('awaiting-approval'))).toBe('proposed');
		expect(planState(run('documents.awaiting-approval'))).toBe('proposed');
		for (const name of [
			'queued',
			'children-admitted',
			'one-child-done',
			'completed',
			'halted',
			'uncertain-child',
			'closed-child'
		] as const) {
			expect(planState(run(name)), name).toBe('approved');
		}
	});

	it('is rejected for a rejected run, whatever the plan says', () => {
		expect(planState(run('rejected'))).toBe('rejected');
		expect(planState(legacyRun('rejected-run'))).toBe('rejected');
		expect(planState({ status: 'rejected', tree: null })).toBe('rejected');
		expect(planState(edited(run('completed'), (copy) => (copy.status = 'rejected')))).toBe(
			'rejected'
		);
	});

	it('is proposed when there is no plan at all', () => {
		expect(planState({ status: 'planning', tree: null })).toBe('proposed');
	});
});

describe('approvalSentence', () => {
	it('says Approve is for this revision, exactly as shown', () => {
		expect(approvalSentence(1)).toBe('Approves revision 1 exactly as shown.');
		expect(approvalSentence(12)).toBe('Approves revision 12 exactly as shown.');
	});
});

describe('every recorded run', () => {
	it('either has no plan card or has one that matches its plan task for task', () => {
		let cards = 0;
		for (const { label, run: value } of allRuns()) {
			const card = planView(value);
			if (!value.tree) {
				expect(card, label).toBeNull();
				continue;
			}
			cards += 1;
			expect(card, label).not.toBeNull();
			expect(card!.revision, label).toBe(value.tree.plan.revision);
			expect(card!.planHash, label).toBe(value.tree.plan_hash);
			expect(card!.approved, label).toBe(value.tree.approved);
			expect(
				card!.tasks.map((task) => task.index),
				label
			).toEqual(value.tree.plan.children.map((_, position) => position + 1));
			expect(
				card!.tasks.map((task) => task.topic),
				label
			).toEqual(value.tree.plan.children.map((child) => child.task.topic));
			// Documents are numbered from 1, once each.
			const numbers = card!.documents.map((doc) => doc.number);
			expect(numbers, label).toEqual(numbers.map((_, position) => position + 1));
		}
		expect(cards).toBeGreaterThanOrEqual(15);
	});
});
