/**
 * The plan card: what the owner is asked to approve, built from the run read alone.
 *
 * Over the recordings of this release (a run on a fixed document, a run on documents
 * the owner selected) and the six runs recorded for the previous release, which have no
 * tools, turn limits, documents or profile and still have to read sensibly.
 */
import { describe, expect, it } from 'vitest';

import type { OrchestrationChatRun, RunTool } from '../../api/orchestration';
import { approvalSentence, planState, planView, type PlanView } from '../plan';
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
			expect(task.skill).toBe('contract-qa v1.0.0');
		}
	});

	it('states the profile’s limits and what it may read in its own words', () => {
		expect(card.totalCap).toBe('$10.00');
		expect(card.rootAllowance).toBe('$1.1562');
		expect(card.planningAllowance).toBe('$0.5781');
		expect(card.attemptLimitSeconds).toBe(300);
		expect(card.maxActive).toBe(2);
		expect(card.reads).toBe(
			'Only the documents you select for this run. No other matter files or live sources.'
		);
		expect(card.planningCharge).toBe('$0.0552');
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

	it('says so when no skill was recorded, rather than leaving it blank', () => {
		const value = edited(base, (copy) => {
			delete copy.tree!.plan.children[0].execution;
		});
		expect(view(value).tasks[0].skill).toBe('Skill not recorded');
		expect(view(value).tasks[1].skill).toBe('contract-qa v1.0.0');
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
		expect(view(base).planningCharge).toBe('$0.0552');
		const byKey = edited(base, (copy) => {
			copy.effects[0].intent = 'something_else';
		});
		expect(view(byKey).planningCharge).toBe('$0.0552');
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

describe('a run with no plan', () => {
	const noPlan = [
		'planning',
		'failed-plan',
		'unfunded-plan',
		'uncertain-planning',
		'closed-planning',
		'documents.planning'
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
