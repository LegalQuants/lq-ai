import { describe, expect, it } from 'vitest';

import { directAnswerText, endedBeforeAPlan, runActivity, type ActivityRow } from '../activity';
import { formatUsd } from '../format';
import { isActiveStatus } from '../status';
import { HOSTILE_STRINGS, expectPlainText } from './hostile';
import { allRuns, legacyRun, run, thread, whileSearching, withRun, withTasks } from './fixtures';

const kinds = (rows: ActivityRow[]) => rows.map((row) => row.kind);
const byKind = (rows: ActivityRow[], kind: ActivityRow['kind']) =>
	rows.filter((row) => row.kind === kind);

describe('runActivity: every recorded run', () => {
	it.each(allRuns().map((entry) => [entry.label, entry.run] as const))('%s', (_label, value) => {
		const rows = runActivity(value);
		if (value.answered_directly) {
			// The orchestrator answered by itself: one line, and no plan, task or answer line.
			expect(kinds(rows)).toEqual(['direct']);
		} else if (
			!value.tree &&
			value.planning.terms?.planning === 'tool' &&
			isActiveStatus(value.status)
		) {
			// Reading the request, where the first call may answer instead of planning: the plan line
			// alone, as there may be no answer to combine. The answer line comes with a plan.
			expect(kinds(rows)).toEqual(['plan']);
		} else {
			expect(rows.length).toBeGreaterThanOrEqual(2);
			expect(rows[0].kind).toBe('plan');
			expect(rows[rows.length - 1].kind).toBe('answer');
		}
		expect(new Set(rows.map((row) => row.id)).size).toBe(rows.length);
		for (const row of rows) {
			expect(row.label, row.id).not.toBe('');
			for (const text of [row.label, row.summary, row.meta]) {
				expect(text ?? '').not.toMatch(/undefined|NaN|\[object|null/);
			}
		}
		// Task rows only once the plan is approved, one per task, numbered from 1.
		const tasks = byKind(rows, 'task');
		expect(tasks.map((row) => row.index)).toEqual(
			(value.tree?.approved ? (value.tree.children ?? []) : []).map((_, at) => at + 1)
		);
		// Only the plan, and only while it awaits approval, starts open.
		const open = rows.filter((row) => row.openByDefault).map((row) => row.kind);
		expect(open).toEqual(value.status === 'awaiting_approval' ? ['plan'] : []);
	});

	it('has a current line while the run is active, and none once it has ended', () => {
		for (const { label, run: value } of allRuns()) {
			const current = runActivity(value).filter((row) => row.state === 'current');
			if (isActiveStatus(value.status)) {
				expect(current.length, label).toBeGreaterThanOrEqual(1);
				// One current line, except that every running task is its own.
				if (current.length > 1) expect(kinds(current), label).toEqual(current.map(() => 'task'));
			} else {
				expect(current, label).toEqual([]);
			}
		}
	});

	it('gives each running task its own current line', () => {
		const two = withTasks(run('children-admitted'), ['running', 'running'], 'running');
		const current = runActivity(two).filter((row) => row.state === 'current');
		expect(current.map((row) => row.kind)).toEqual(['task', 'task']);
	});
});

describe('the plan line', () => {
	it('says what is awaited, and is open only then', () => {
		const [plan] = runActivity(run('awaiting-approval'));
		expect(plan.state).toBe('current');
		expect(plan.label).toBe('Plan proposed');
		expect(plan.summary).toMatch(/^2 tasks · total cap \$\d+\.\d\d+ · waiting for your approval$/);
		expect(plan.openByDefault).toBe(true);
		expect(plan.openable).toBe(true);
	});

	it('says the plan was approved, and is closed', () => {
		const [plan] = runActivity(run('completed'));
		expect(plan.state).toBe('done');
		expect(plan.label).toBe('Plan approved');
		expect(plan.summary).toMatch(/^revision \d+ · 2 tasks$/);
		expect(plan.openByDefault).toBe(false);
	});

	it('says the owner rejected it', () => {
		const rows = runActivity(run('rejected'));
		expect(rows[0].label).toBe('You rejected the plan');
		expect(rows[0].state).toBe('stopped');
		expect(rows.map((row) => row.kind)).toEqual(['plan', 'answer']);
	});

	it('is proposing while the model plans, with nothing to open', () => {
		const [plan] = runActivity(run('planning'));
		expect(plan.label).toBe('Proposing a plan…');
		expect(plan.state).toBe('current');
		expect(plan.openable).toBe(false);
	});

	it('is reading the request, not proposing a plan, where the first call may answer instead', () => {
		// The intake says the plan is handed over by a tool call: until the call has replied,
		// nothing says a plan is coming.
		for (const name of ['direct.planning', 'knowledge.planning', 'documents.planning'] as const) {
			const planning = run(name);
			expect(planning.planning.terms?.planning, name).toBe('tool');
			const [plan] = runActivity(planning);
			expect(plan.label, name).toBe('Reading your request…');
			expect(plan.state, name).toBe('current');
			expect(plan.openable, name).toBe(false);
			expect(plan.summary, name).toBeNull();
		}
	});

	it('keeps its wording for a run whose intake states no terms, or states that the plan is written in text', () => {
		// A run recorded before terms were frozen carries none.
		expect(run('planning').planning.terms ?? null).toBeNull();
		expect(runActivity(run('planning'))[0].label).toBe('Proposing a plan…');
		const text = structuredClone(run('direct.planning'));
		text.planning.terms = { ...text.planning.terms!, planning: 'text' };
		expect(runActivity(text)[0].label).toBe('Proposing a plan…');
		const unstated = structuredClone(run('direct.planning'));
		delete (unstated.planning as { terms?: unknown }).terms;
		expect(runActivity(unstated)[0].label).toBe('Proposing a plan…');
	});

	it('says only what an unresolved call is while it is reading the request', () => {
		const stuck = structuredClone(run('direct.planning'));
		stuck.status = 'uncertain';
		const [plan] = runActivity(stuck);
		expect(plan.label).toBe('Reading your request…');
		expect(plan.summary).toBe('a provider call has no confirmed outcome');
	});

	it('gives the stop reason when no plan could be made', () => {
		const [plan] = runActivity(run('failed-plan'));
		expect(plan.state).toBe('stopped');
		expect(plan.summary).toMatch(/usable plan|budget/);
	});

	it('says the model wrote its plan out as text, when it did not hand it over', () => {
		const rows = runActivity(run('plan-not-handed-over'));
		expect(kinds(rows)).toEqual(['plan', 'answer']);
		expect(rows[0].state).toBe('stopped');
		expect(rows[0].label).toBe('No plan was produced');
		expect(rows[0].summary).toBe(
			'The model wrote its plan out as text instead of handing it over, so there is no plan to approve.'
		);
		// There is no plan to open, but the call that did not hand one over can be read.
		expect(rows[0].openable).toBe(true);
		expect(rows[0].openByDefault).toBe(false);
		// Nothing after it ran.
		expect(rows[1].state).toBe('skipped');
		expect(rows[1].summary).toBe('did not run');
	});
});

describe('the answer line, where the first call may answer instead of planning', () => {
	const planning = ['direct.planning', 'knowledge.planning', 'documents.planning'] as const;

	it('is not drawn while the run reads the request: the plan line stands alone, as there may be nothing to combine', () => {
		for (const name of [...planning, 'harness.follow-up.planning'] as const) {
			const value = run(name);
			expect(value.tree, name).toBeNull();
			expect(value.planning.terms?.planning, name).toBe('tool');
			const rows = runActivity(value);
			expect(kinds(rows), name).toEqual(['plan']);
			expect(rows[0].state, name).toBe('current');
		}
	});

	it('is not drawn while the first call has no confirmed outcome either', () => {
		const stuck = structuredClone(run('direct.planning'));
		stuck.status = 'uncertain';
		expect(kinds(runActivity(stuck))).toEqual(['plan']);
	});

	it('is drawn, not started, once there is a plan: that is when it becomes the next step', () => {
		for (const name of [
			'knowledge.awaiting-approval',
			'documents.awaiting-approval',
			'harness.no-documents.awaiting-approval'
		] as const) {
			const rows = runActivity(run(name));
			expect(kinds(rows).at(-1), name).toBe('answer');
			expect(rows.at(-1)!.state, name).toBe('pending');
		}
	});

	it('is drawn, saying it did not run, where the run stopped without a plan', () => {
		for (const name of ['plan-not-handed-over', 'plan-has-placeholders'] as const) {
			const rows = runActivity(run(name));
			expect(kinds(rows), name).toEqual(['plan', 'answer']);
			expect(rows[1].state, name).toBe('skipped');
			expect(rows[1].summary, name).toBe('did not run');
		}
	});

	it('is drawn, not started, where the plan is written in text, as it always was', () => {
		const older = runActivity(run('planning'));
		expect(kinds(older)).toEqual(['plan', 'answer']);
		expect(older[1].state).toBe('pending');
		const text = structuredClone(run('direct.planning'));
		text.planning.terms = { ...text.planning.terms!, planning: 'text' };
		expect(kinds(runActivity(text))).toEqual(['plan', 'answer']);
		const unstated = structuredClone(run('direct.planning'));
		delete (unstated.planning as { terms?: unknown }).terms;
		expect(kinds(runActivity(unstated))).toEqual(['plan', 'answer']);
	});
});

describe('the answer a run gave by itself, for a view with no chat message beside it', () => {
	const answered = run('direct.completed');

	it('is the text on the run read, untouched', () => {
		expect(answered.answered_directly).toBe(true);
		expect(typeof answered.direct_answer).toBe('string');
		expect(directAnswerText(answered)).toBe(answered.direct_answer);
		// It is the chat message's own content, which the thread shows beneath the run.
		expect(directAnswerText(answered)).toBe(thread('direct.completed')[1].content);
	});

	it('is nothing for a run that was not answered directly, whatever its read carries', () => {
		for (const name of [
			'direct.planning',
			'completed',
			'knowledge.completed',
			'plan-not-handed-over'
		] as const) {
			expect(directAnswerText(run(name)), name).toBeNull();
		}
		// A planned run's answer stays in its tree; a stray field does not become its answer.
		const planned = structuredClone(run('completed'));
		planned.direct_answer = 'Not an answer.';
		expect(directAnswerText(planned)).toBeNull();
	});

	it('is nothing where the read carries no answer: from an older server, or an empty one', () => {
		for (const stated of [undefined, null, '', '   \n', 7 as unknown as string]) {
			const value = structuredClone(answered);
			value.direct_answer = stated;
			expect(directAnswerText(value), String(stated)).toBeNull();
		}
		const missing = structuredClone(answered);
		delete missing.direct_answer;
		expect(directAnswerText(missing)).toBeNull();
	});

	it('hands back what the model wrote as the text it is', () => {
		for (const hostile of HOSTILE_STRINGS) {
			const value = structuredClone(answered);
			value.direct_answer = hostile;
			expect(directAnswerText(value)).toBe(hostile);
		}
	});
});

describe('a plan refused for carrying a placeholder', () => {
	it('is the plan line stopped, with the one sentence of the reason, and nothing after it run', () => {
		const rows = runActivity(run('plan-has-placeholders'));
		expect(kinds(rows)).toEqual(['plan', 'answer']);
		expect(rows[0].state).toBe('stopped');
		expect(rows[0].label).toBe('No plan was produced');
		expect(rows[0].summary).toBe(
			'The plan carried a placeholder that stands for a name or an identifier.'
		);
		expect(rows[0].openable).toBe(true);
		expect(rows[1].state).toBe('skipped');
		expect(rows[1].summary).toBe('did not run');
	});
});

describe('the plan line of a run that stopped before it had a plan', () => {
	const WITHOUT_A_PLAN = [
		'plan-not-handed-over',
		'plan-has-placeholders',
		'failed-plan',
		'unfunded-plan',
		'uncertain-planning',
		'closed-planning'
	] as const;
	const statusOf = (name: string) => run(name).status;

	it('covers a failed, an uncertain and a closed run, among the recordings', () => {
		// The cases below are not all the same status: each way of ending is recorded.
		expect(new Set(WITHOUT_A_PLAN.map(statusOf))).toEqual(
			new Set(['failed', 'uncertain', 'closed'])
		);
		for (const name of WITHOUT_A_PLAN) {
			expect(run(name).tree, name).toBeNull();
			expect(run(name).answered_directly === true, name).toBe(false);
		}
	});

	it.each(WITHOUT_A_PLAN)('%s: is a plan line that can be opened', (name) => {
		const [plan] = runActivity(run(name));
		expect(plan.kind).toBe('plan');
		expect(plan.openable).toBe(true);
		// Nothing to approve and nothing to decide, so it does not start open in the chat.
		expect(plan.openByDefault).toBe(false);
		expect(endedBeforeAPlan(run(name))).toBe(true);
	});

	it('says on its closed line what it said before it could be opened', () => {
		const wording = (name: (typeof WITHOUT_A_PLAN)[number]) => {
			const [plan] = runActivity(run(name));
			return { state: plan.state, label: plan.label, summary: plan.summary, meta: plan.meta };
		};
		expect(wording('plan-not-handed-over')).toEqual({
			state: 'stopped',
			label: 'No plan was produced',
			summary:
				'The model wrote its plan out as text instead of handing it over, so there is no plan to approve.',
			meta: null
		});
		expect(wording('plan-has-placeholders')).toEqual({
			state: 'stopped',
			label: 'No plan was produced',
			summary: 'The plan carried a placeholder that stands for a name or an identifier.',
			meta: null
		});
		// A run left uncertain still reads as the run it is: the first call has no outcome.
		expect(wording('uncertain-planning')).toMatchObject({
			state: 'current',
			summary: 'a provider call has no confirmed outcome'
		});
		for (const name of ['failed-plan', 'unfunded-plan', 'closed-planning'] as const) {
			expect(wording(name), name).toMatchObject({
				state: 'stopped',
				label: 'No plan was produced'
			});
		}
	});

	it('keeps the rest of the column as it was: the answer line, which did not run', () => {
		for (const name of WITHOUT_A_PLAN.filter((n) => statusOf(n) !== 'uncertain')) {
			const rows = runActivity(run(name));
			expect(kinds(rows), name).toEqual(['plan', 'answer']);
			expect(rows[1].openable, name).toBe(false);
		}
	});

	it('is opened for a run that ended in any way, and for one left uncertain', () => {
		for (const status of ['failed', 'halted', 'expired', 'closed', 'uncertain']) {
			const ended = withRun(run('plan-not-handed-over'), { status });
			expect(endedBeforeAPlan(ended), status).toBe(true);
			expect(runActivity(ended)[0].openable, status).toBe(true);
		}
	});

	it('stays a line with nothing to open while the first call is still being answered', () => {
		for (const name of ['planning', 'direct.planning', 'knowledge.planning'] as const) {
			expect(endedBeforeAPlan(run(name)), name).toBe(false);
			expect(runActivity(run(name))[0].openable, name).toBe(false);
		}
		// A status this client has never seen is not taken for one that ended.
		const strange = withRun(run('plan-not-handed-over'), { status: 'mystery' });
		expect(endedBeforeAPlan(strange)).toBe(false);
		expect(runActivity(strange)[0].openable).toBe(false);
	});

	it('is not drawn for a run that answered by itself, which has its own line, or that has a plan', () => {
		expect(endedBeforeAPlan(run('direct.completed'))).toBe(false);
		for (const name of [
			'awaiting-approval',
			'completed',
			'rejected',
			'halted',
			'failed-plan'
		] as const) {
			const value = run(name);
			// A run with a plan opens as the plan, which is what it was; one without opens as set out above.
			expect(endedBeforeAPlan(value), name).toBe(value.tree === null);
		}
	});

	it('stays a static line for a run of the earlier demonstration, which has no trace to read', () => {
		const demonstration = withRun(run('plan-not-handed-over'), { profile: 'demonstration' });
		expect(endedBeforeAPlan(demonstration)).toBe(false);
		const [plan] = runActivity(demonstration);
		expect(plan.openable).toBe(false);
		// Its words are the same.
		expect(plan.label).toBe('No plan was produced');
	});

	it('treats a run recorded before profiles were named as a run with a trace to read', () => {
		for (const name of ['fenced-plan-run', 'truncated-plan-run'] as const) {
			const value = legacyRun(name);
			expect(value.profile, name).toBeUndefined();
			expect(endedBeforeAPlan(value), name).toBe(true);
			expect(runActivity(value)[0].openable, name).toBe(true);
		}
	});
});

describe('a stop reason the page has never seen', () => {
	const MADE_UP = 'mystery_code';
	const stopped = (name: Parameters<typeof run>[0], status: string) => {
		const copy = structuredClone(run(name));
		copy.status = status;
		copy.stop_reason = MADE_UP;
		if (copy.tree) copy.tree.status = status;
		return copy;
	};

	it('is said in plain words on the plan line, when the plan was never made', () => {
		const [plan, answer] = runActivity(stopped('failed-plan', 'failed'));
		expect(plan.state).toBe('stopped');
		expect(plan.label).toBe('No plan was produced');
		expect(plan.summary).toBe('Mystery code.');
		expect(answer.state).toBe('skipped');
	});

	it('is said in plain words on the answer line, when the tasks had finished', () => {
		const rows = runActivity(stopped('refusals-and-partial', 'failed'));
		const answer = rows.at(-1)!;
		expect(answer.kind).toBe('answer');
		expect(answer.state).toBe('stopped');
		expect(answer.summary).toBe('Mystery code.');
	});

	it('leaves every line of every recorded run readable, with the code nowhere as it came', () => {
		for (const { label, run: value } of allRuns()) {
			const odd = structuredClone(value);
			odd.status = 'failed';
			odd.stop_reason = MADE_UP;
			if (odd.tree) odd.tree.status = 'failed';
			for (const row of runActivity(odd)) {
				const text = `${row.label} ${row.summary ?? ''} ${row.meta ?? ''}`;
				expect(row.label, `${label} ${row.id}`).not.toBe('');
				expect(text, `${label} ${row.id}`).not.toMatch(/undefined|NaN|\[object|\bnull\b/);
				expect(row.summary, `${label} ${row.id}`).not.toBe('.');
				expect(text, `${label} ${row.id}`).not.toContain(MADE_UP);
			}
		}
	});
});

describe('a request the orchestrator answered by itself', () => {
	const answered = run('direct.completed');

	it('is one line: no plan, no task and no answer line, with no approval to give', () => {
		expect(answered.answered_directly).toBe(true);
		expect(answered.tree).toBeNull();
		const rows = runActivity(answered);
		expect(kinds(rows)).toEqual(['direct']);
		expect(rows[0].id).toBe('direct');
		expect(rows[0].index).toBeNull();
	});

	it('says it was answered directly, that there was no plan, that nothing was read, and what the call cost', () => {
		const [line] = runActivity(answered);
		expect(line.state).toBe('done');
		expect(line.label).toBe('Answered directly');
		expect(line.summary).toBe('no plan · nothing read');
		// The cost is written as the other lines write theirs: in money, from the run's own spend
		// (read from the recording, which changes with the size of what the call was sent).
		expect(line.meta).toBe(formatUsd(answered.spent_usd));
		expect(line.meta).toMatch(/^\$0\.\d{2,4}$/);
		expect([line.label, line.summary, line.meta].join(' · ')).toBe(
			`Answered directly · no plan · nothing read · ${formatUsd(answered.spent_usd)}`
		);
	});

	it('can be opened, to read how it was set up, and starts closed', () => {
		const [line] = runActivity(answered);
		expect(line.openable).toBe(true);
		expect(line.openByDefault).toBe(false);
	});

	it('is the same line for a request that is answered after documents were selected', () => {
		const withDocuments = structuredClone(answered);
		withDocuments.planning.documents = structuredClone(
			run('documents.completed').planning.documents
		);
		expect(kinds(runActivity(withDocuments))).toEqual(['direct']);
		expect(runActivity(withDocuments)[0].summary).toBe('no plan · nothing read');
	});

	it('says what state a run is in that is flagged as answered but is not completed, and never "done"', () => {
		for (const status of ['planning', 'uncertain', 'quarantined', 'failed']) {
			const odd = structuredClone(answered);
			odd.status = status;
			const [line] = runActivity(odd);
			expect(line.state, status).not.toBe('done');
			expect(line.state, status).toBe(
				['planning', 'uncertain'].includes(status) ? 'current' : 'stopped'
			);
		}
	});

	it('is not drawn for a run that merely has no plan', () => {
		for (const name of ['plan-not-handed-over', 'failed-plan'] as const) {
			expect(run(name).answered_directly, name).toBe(false);
			expect(kinds(runActivity(run(name))), name).toEqual(['plan', 'answer']);
		}
		// One still reading the request is the plan line alone: there may be nothing to combine.
		expect(run('direct.planning').answered_directly).toBe(false);
		expect(kinds(runActivity(run('direct.planning')))).toEqual(['plan']);
		// Nor for a run read from a server that does not say.
		const unstated = structuredClone(run('failed-plan'));
		delete unstated.answered_directly;
		expect(kinds(runActivity(unstated))).toEqual(['plan', 'answer']);
	});
});

describe('task lines', () => {
	it('a completed task carries counts and spend, and no finding text', () => {
		const value = run('documents.completed');
		const tasks = byKind(runActivity(value), 'task');
		expect(tasks).toHaveLength(2);
		for (const [at, row] of tasks.entries()) {
			expect(row.state).toBe('done');
			expect(row.label).toBe(value.tree!.plan.children[at].task.topic);
			expect(row.summary).toMatch(
				/^done( · read \d+ documents?)?( · searched (?:once|\d+ times))?( · \d+ model calls?)?$/
			);
			expect(row.meta).toMatch(/^\$/);
			const findings = value.tree!.children[at].outcome!.findings;
			expect(findings.length).toBeGreaterThan(0);
			for (const finding of findings) {
				expect(`${row.summary} ${row.meta}`).not.toContain(finding);
			}
			expect(row.summary).not.toContain(value.tree!.children[at].outcome!.summary);
		}
		expect(tasks.some((row) => /read \d+ documents?/.test(row.summary ?? ''))).toBe(true);
		expect(tasks.some((row) => /\d+ model calls?/.test(row.summary ?? ''))).toBe(true);
	});

	describe('a task that searched the knowledge bases', () => {
		const completed = run('knowledge.completed');
		const searches = (value: typeof completed) => byKind(runActivity(value), 'task')[0].summary;

		it('says how many times, after the documents it read and before its model calls', () => {
			const [task] = byKind(runActivity(completed), 'task');
			expect(task.state).toBe('done');
			expect(task.summary).toBe('done · searched 2 times · 2 model calls');
			expect(task.meta).toBe(formatUsd(completed.tree!.children[0].spent_usd));
		});

		it('says "once" for one search, and never "1 times"', () => {
			const one = structuredClone(completed);
			const effects = one.tree!.children[0].effects;
			effects.splice(
				effects.findIndex((effect) => effect.step?.kind === 'knowledge_search'),
				1
			);
			expect(searches(one)).toBe('done · searched once · 2 model calls');
		});

		it('says nothing of searching for a task that made no search, and never "0 times"', () => {
			const none = structuredClone(completed);
			none.tree!.children[0].effects = none.tree!.children[0].effects.filter(
				(effect) => effect.step?.kind !== 'knowledge_search'
			);
			expect(searches(none)).toBe('done · 2 model calls');
			expect(searches(none)).not.toMatch(/searched|0 /);
		});

		it('counts a task that both read documents and searched, in that order', () => {
			const both = structuredClone(completed);
			const read = structuredClone(run('documents.completed').tree!.children[0].effects).find(
				(effect) => effect.step?.kind === 'document_read'
			)!;
			both.tree!.children[0].effects.splice(2, 0, read);
			expect(searches(both)).toBe('done · read 1 document · searched 2 times · 2 model calls');
		});

		it('counts only searches that were made: not one that is still going, was refused or has no outcome', () => {
			const odd = structuredClone(completed);
			const [first, second] = odd.tree!.children[0].effects.filter(
				(effect) => effect.step?.kind === 'knowledge_search'
			);
			first.status = 'admitted';
			second.step = { kind: 'tool_refused', summary: { code: 'tool_not_granted' } };
			expect(searches(odd)).toBe('done · 2 model calls');
		});
	});

	it('a task that has not started waits, with no spend', () => {
		const [, first] = runActivity(run('queued'));
		expect(first.summary).toBe('waiting to start');
		expect(first.meta).toBeNull();
	});

	it('a running task shows its latest step', () => {
		const value = withTasks(run('one-child-done'), ['completed', 'running'], 'running');
		value.tree!.children[1].effects = structuredClone(value.tree!.children[0].effects.slice(0, 2));
		const second = byKind(runActivity(value), 'task')[1];
		expect(second.state).toBe('current');
		expect(second.summary).toMatch(/\S/);
		expect(second.summary).not.toBe('waiting to start');
	});

	it('a task that failed says it could not complete, and why in the record’s own code', () => {
		const rows = byKind(runActivity(run('refusals-and-partial')), 'task');
		expect(rows[1].state).toBe('stopped');
		expect(rows[1].summary).toBe('could not complete: execution failed');
	});

	it('a halted task says after how many steps', () => {
		const rows = byKind(runActivity(run('closed-child')), 'task');
		expect(rows[1].state).toBe('stopped');
		expect(rows[1].summary).toBe('halted after 3 steps');
	});

	it('a task that never started when the run ended did not run', () => {
		const ended = withTasks(run('children-admitted'), ['pending', 'queued'], 'halted');
		ended.stop_reason = 'owner_halt';
		const tasks = byKind(runActivity(ended), 'task');
		expect(tasks.map((row) => [row.state, row.summary])).toEqual([
			['skipped', 'did not run'],
			['skipped', 'did not run']
		]);
	});

	it('a run that has ended cannot have a task still running', () => {
		const ended = withTasks(run('children-admitted'), ['running', 'queued'], 'halted');
		const rows = runActivity(ended);
		expect(rows.filter((row) => row.state === 'current')).toEqual([]);
	});

	it('the line of an unresolved call says so and is the current one', () => {
		const rows = runActivity(run('uncertain-child'));
		const current = rows.filter((row) => row.state === 'current');
		expect(current).toHaveLength(1);
		expect(current[0].kind).toBe('task');
		expect(current[0].summary).toBe('a provider call has no confirmed outcome');
	});
});

describe('a task that is making a search whose call has no step note yet', () => {
	const taskLine = (value: ReturnType<typeof whileSearching>) =>
		runActivity(value).find((row) => row.id === 'task-1')!;

	it('is recorded as the server sends it: the last step of a running task, without a note', () => {
		for (const status of ['admitted', 'uncertain'] as const) {
			const value = whileSearching(status);
			const last = value.tree!.children[0].effects.at(-1)!;
			expect(last.step, status).toBeNull();
			expect(last.status, status).toBe(status);
			expect(last.intent, status).toBe('retrieve_chunks');
			expect(last.effect_key, status).toMatch(/^topic:t1:c\d+$/);
		}
	});

	it('says it is searching the knowledge bases where the plan lists only knowledge bases', () => {
		const line = taskLine(whileSearching('admitted'));
		expect(line.state).toBe('current');
		expect(line.summary).toBe('Searched the knowledge bases…');
		expect(line.summary).not.toMatch(/document/i);
	});

	it('says it is reading a document where the plan lists only documents, as it did', () => {
		expect(taskLine(whileSearching('admitted', 'documents')).summary).toBe('Read a document…');
	});

	it('says it may be either where the plan lists both', () => {
		expect(taskLine(whileSearching('admitted', 'both')).summary).toBe(
			'Read a document or searched the knowledge bases…'
		);
	});

	it('says only that a provider call has no confirmed outcome, whichever it was, when it is left uncertain', () => {
		for (const lists of ['knowledge', 'documents', 'both'] as const) {
			const line = taskLine(whileSearching('uncertain', lists));
			expect(line.summary, lists).toBe('a provider call has no confirmed outcome');
		}
	});

	it('makes no claim about what the search found', () => {
		for (const lists of ['knowledge', 'documents', 'both'] as const) {
			const line = taskLine(whileSearching('admitted', lists));
			expect(line.summary, lists).not.toMatch(/nothing found|passage|\bfound\b/i);
		}
	});
});

describe('the answer line', () => {
	it('is waiting while the tasks run', () => {
		const rows = runActivity(run('children-admitted'));
		const answer = rows[rows.length - 1];
		expect(answer.state).toBe('pending');
		expect(answer.label).toBe('Combine and deliver the answer');
		expect(answer.openable).toBe(false);
	});

	it('says it is combining, then that it was delivered with the evidence counts', () => {
		const combining = withTasks(run('completed'), ['completed', 'completed'], 'running');
		combining.tree!.result = null;
		const during = runActivity(combining).at(-1)!;
		expect(during.state).toBe('current');
		expect(during.label).toBe('Combining');

		const delivered = runActivity(run('documents.completed')).at(-1)!;
		expect(delivered.state).toBe('done');
		expect(delivered.label).toBe('Answer delivered');
		expect(delivered.summary).toMatch(/\d+ of \d+ checked quotations? matched/);
		expect(delivered.openable).toBe(true);
	});

	it('says "unverified" for a profile that checks nothing', () => {
		const delivered = runActivity(run('completed')).at(-1)!;
		expect(delivered.summary).toContain('Model-generated; unverified');
	});

	it('says the run stopped before it, or that it did not run', () => {
		const stopped = runActivity(run('failed-plan')).at(-1)!;
		expect(stopped.state).toBe('skipped');
		expect(stopped.summary).toBe('did not run');

		// Halted with a task unfinished: the answer never began.
		expect(runActivity(run('halted')).at(-1)!.state).toBe('skipped');

		// Every task finished but the combined answer was not usable: it stopped here.
		const unusable = withTasks(run('completed'), ['completed', 'completed'], 'failed');
		unusable.stop_reason = 'invalid_synthesis';
		unusable.tree!.result = null;
		const answer = runActivity(unusable).at(-1)!;
		expect(answer.state).toBe('stopped');
		expect(answer.summary).toBe('The combined answer could not be produced.');
	});
});

describe('statuses this client does not know', () => {
	it('do not throw, and end every line', () => {
		for (const { run: value } of allRuns()) {
			const odd = withRun(value, { status: 'quarantined', stop_reason: 'mystery_code' });
			odd.tree?.children.forEach((child) => (child.status = 'mystery'));
			const rows = runActivity(odd);
			expect(rows.length).toBeGreaterThanOrEqual(value.answered_directly ? 1 : 2);
			expect(rows.filter((row) => row.state === 'current')).toEqual([]);
		}
	});

	it('say the unknown status in words', () => {
		const odd = withRun(run('completed'), { status: 'quarantined' });
		odd.tree!.children[0].status = 'mystery';
		expect(byKind(runActivity(odd), 'task')[0].summary).toBe('mystery');
	});
});

describe('closed lines are made of records, not prose', () => {
	it('a hostile topic comes back exactly as written, and nothing else in the lines carries it', () => {
		for (const hostile of HOSTILE_STRINGS) {
			const value = structuredClone(run('documents.completed'));
			value.tree!.plan.children[0].task.topic = hostile;
			value.tree!.children[0].outcome!.summary = hostile;
			value.tree!.children[0].outcome!.findings = [hostile];
			const rows = runActivity(value);
			const task = byKind(rows, 'task')[0];
			expect(task.label).toBe(hostile);
			for (const row of rows) {
				expectPlainText(row.summary ?? '', hostile, `${row.id} summary`);
				expect(row.summary ?? '').not.toContain(hostile);
				expect(row.meta ?? '').not.toContain(hostile);
			}
		}
	});

	it('a hostile file name, knowledge-base name or stated reason of a search comes back in no closed line', () => {
		for (const hostile of HOSTILE_STRINGS) {
			const value = structuredClone(run('knowledge.completed'));
			for (const effect of value.tree!.children[0].effects) {
				if (effect.step?.kind !== 'knowledge_search') continue;
				effect.step.reason = hostile;
				for (const file of effect.step.summary!.sources as { filename: string }[]) {
					file.filename = hostile;
				}
			}
			value.sources![0].filename = hostile;
			value.planning.knowledge_bases![0].name = hostile;
			value.tree!.plan.knowledge_bases![0].name = hostile;
			for (const row of runActivity(value)) {
				expectPlainText(`${row.label} ${row.summary ?? ''} ${row.meta ?? ''}`, hostile, row.id);
				expect(row.summary ?? '', `${row.id} summary`).not.toContain(hostile);
				expect(row.label, `${row.id} label`).not.toContain(hostile);
			}
		}
	});

	it('a hostile figure in a search step’s summary counts as a search made and reads as none of it', () => {
		const value = structuredClone(run('knowledge.completed'));
		for (const effect of value.tree!.children[0].effects) {
			if (effect.step?.kind === 'knowledge_search') {
				effect.step.summary = { passages: '<img src=x>', sources: '<script>', listed: {} };
			}
		}
		expect(byKind(runActivity(value), 'task')[0].summary).toBe(
			'done · searched 2 times · 2 model calls'
		);
	});

	it('a hostile failure code is shown as words, not as markup', () => {
		const value = structuredClone(run('refusals-and-partial'));
		value.tree!.children[1].outcome!.failure_code = '<img src=x onerror=alert(1)>';
		const summary = byKind(runActivity(value), 'task')[1].summary!;
		expect(summary.startsWith('could not complete: ')).toBe(true);
	});
});

describe('runs recorded before chat hosting', () => {
	it.each(['model-run', 'rejected-run', 'timeout-run', 'fenced-plan-run'] as const)(
		'%s',
		(name) => {
			const rows = runActivity(legacyRun(name));
			expect(rows[0].kind).toBe('plan');
			expect(rows.at(-1)!.kind).toBe('answer');
		}
	);
});
