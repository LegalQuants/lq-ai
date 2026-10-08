/**
 * Plain-language status over every recorded run: the six from the previous release
 * (no profile, no step notes, no tools) and the ones recorded for this release.
 */
import { describe, expect, it } from 'vitest';

import {
	ACTIVE_STATUSES,
	POLLING_STATUSES,
	READING_REQUEST,
	TERMINAL_STATUSES,
	UNCERTAIN_EXPLANATION,
	isActiveStatus,
	isTerminalStatus,
	plansByTool,
	runDetail,
	runHeadline,
	runTitle,
	shouldAnnounceSettled,
	shouldPollStatus,
	stopReasonText,
	taskCounts
} from '../status';
import { allRuns, legacyRun, run, withRun, withTasks } from './fixtures';

const UNCERTAIN = 'Uncertain: a provider call has no confirmed outcome';
const READING = 'Reading your request…';
const NOT_HANDED_OVER =
	'The model wrote its plan out as text instead of handing it over, so there is no plan to approve.';
const HAS_PLACEHOLDERS =
	'The plan carried a placeholder that stands for a name or an identifier. This route is pseudonymized, and a placeholder in a plan cannot be turned back into the real value, so the plan was refused. Nothing ran. Try the request again without the name or identifier.';

describe('runHeadline on recorded runs', () => {
	const expected: [string, string][] = [
		['planning', 'Proposing a plan…'],
		['awaiting-approval', 'Waiting for your approval'],
		['queued', 'Plan approved. Waiting for the tasks to start'],
		['children-admitted', '2 tasks waiting to start'],
		['one-child-done', '1 task waiting to start'],
		['completed', 'Answer delivered'],
		['rejected', 'You rejected the plan'],
		['halted', 'Halted'],
		['failed-plan', 'The model could not produce a usable plan'],
		['unfunded-plan', 'The plan needs more tasks than the budget can fund'],
		['uncertain-planning', UNCERTAIN],
		['uncertain-child', UNCERTAIN],
		['closed-planning', 'Closed'],
		['closed-child', 'Closed'],
		['refusals-and-partial', 'Answer delivered'],
		// New harness hands its plan over by a tool call, so while its first call runs it may be
		// about to answer instead: it is reading the request, and no plan is said to be coming.
		['documents.planning', READING],
		['documents.awaiting-approval', 'Waiting for your approval'],
		['documents.completed', 'Answer delivered'],
		['harness.follow-up.planning', READING],
		['direct.planning', READING],
		['direct.completed', 'Answer delivered'],
		['plan-not-handed-over', 'The run failed'],
		['plan-has-placeholders', 'The run failed'],
		['knowledge.planning', READING],
		['knowledge.awaiting-approval', 'Waiting for your approval'],
		['knowledge.completed', 'Answer delivered']
	];
	it.each(expected)('run.%s', (name, headline) => {
		expect(runHeadline(run(name))).toBe(headline);
	});

	it.each([
		['model-run', 'Answer delivered'],
		['rejected-run', 'You rejected the plan'],
		['stalled-model-run', UNCERTAIN],
		['timeout-run', UNCERTAIN],
		['fenced-plan-run', 'The model could not produce a usable plan'],
		['truncated-plan-run', 'The model could not produce a usable plan']
	] as const)('previous release: %s', (name, headline) => {
		expect(runHeadline(legacyRun(name))).toBe(headline);
	});
});

describe('runHeadline while tasks are in flight', () => {
	const admitted = run('children-admitted');

	it('counts the tasks that are running', () => {
		expect(runHeadline(withTasks(admitted, ['running', 'running'], 'waiting_children'))).toBe(
			'2 tasks running'
		);
		expect(runHeadline(withTasks(admitted, ['running', 'queued'], 'waiting_children'))).toBe(
			'1 task running'
		);
	});

	it('says the answers are being combined once every task has finished', () => {
		expect(runHeadline(withTasks(admitted, ['completed', 'completed'], 'running'))).toBe(
			'Combining the answers'
		);
		// A task that failed has still finished.
		expect(runHeadline(withTasks(admitted, ['completed', 'failed'], 'running'))).toBe(
			'Combining the answers'
		);
	});

	it('says the tasks are starting before any is admitted', () => {
		expect(runHeadline(withTasks(admitted, [], 'running'))).toBe('2 tasks waiting to start');
		const empty = withRun(admitted, { tree: null, status: 'running' });
		expect(runHeadline(empty)).toBe('Starting the tasks');
	});
});

describe('runHeadline on endings the recordings do not cover', () => {
	const base = run('completed');
	it('names a budget overrun, a deadline and an unusable combined answer', () => {
		expect(
			runHeadline(withRun(base, { status: 'halted', stop_reason: 'observed_budget_overrun' }))
		).toBe('Halted: a call cost more than its allowance');
		expect(runHeadline(withRun(base, { status: 'expired', stop_reason: 'root_deadline' }))).toBe(
			'The run reached its time limit'
		);
		expect(runHeadline(withRun(base, { status: 'failed', stop_reason: 'invalid_synthesis' }))).toBe(
			'The combined answer could not be produced'
		);
	});

	it('does not throw on a status it has never seen', () => {
		expect(runHeadline(withRun(base, { status: 'paused_for_review' }))).toBe('Paused for review');
		expect(runHeadline(withRun(base, { status: '' }))).toBe('Unknown status');
	});

	it('says something for a failure with no stop reason', () => {
		expect(runHeadline(withRun(base, { status: 'failed', stop_reason: null }))).toBe(
			'The run failed'
		);
	});
});

describe('runHeadline while the first call runs', () => {
	it('is "Reading your request…" where the plan is handed over by a tool call', () => {
		expect(READING_REQUEST).toBe('Reading your request…');
		const planning = run('direct.planning');
		expect(planning.planning.terms?.planning).toBe('tool');
		expect(plansByTool(planning)).toBe(true);
		expect(runHeadline(planning)).toBe('Reading your request…');
	});

	it('keeps "Proposing a plan…" for a run whose intake states no terms, or a plan written in text', () => {
		const old = run('planning');
		// A run recorded before terms were frozen carries none.
		expect(old.planning.terms ?? null).toBeNull();
		expect(plansByTool(old)).toBe(false);
		expect(runHeadline(old)).toBe('Proposing a plan…');
		const text = structuredClone(run('direct.planning'));
		text.planning.terms = { ...text.planning.terms!, planning: 'text' };
		expect(runHeadline(text)).toBe('Proposing a plan…');
		const unstated = structuredClone(run('direct.planning'));
		delete (unstated.planning as { terms?: unknown }).terms;
		expect(runHeadline(unstated)).toBe('Proposing a plan…');
		for (const odd of [undefined, null, {}, { terms: null }, { terms: { planning: 7 } }]) {
			expect(plansByTool({ planning: odd as never }), JSON.stringify(odd)).toBe(false);
		}
	});

	it('changes the wording only while the run is planning', () => {
		const base = run('direct.planning');
		expect(runHeadline({ ...base, status: 'awaiting_approval' })).toBe('Waiting for your approval');
		expect(runHeadline({ ...base, status: 'uncertain' })).toBe(UNCERTAIN);
		expect(runHeadline(run('direct.completed'))).toBe('Answer delivered');
	});

	it('words a plan that was not handed over as a failure, with the detail beneath it', () => {
		const failed = run('plan-not-handed-over');
		expect(runHeadline(failed)).toBe('The run failed');
		// Neither the headline nor anything else calls it a usable plan, or one that was approved.
		expect(runHeadline(failed)).not.toMatch(/usable plan|approved/i);
	});
});

describe('runDetail', () => {
	it('explains an uncertain run in plain words, including what closing does', () => {
		for (const name of ['uncertain-planning', 'uncertain-child'] as const) {
			const detail = runDetail(run(name));
			expect(detail).toBe(UNCERTAIN_EXPLANATION);
			expect(detail).toMatch(/will not\s+retry/);
			expect(detail).toMatch(/charges that unresolved\s+reservation/);
			expect(detail).toMatch(/frees you to start another run/);
		}
	});

	it('says a closed run was charged and retried nothing', () => {
		expect(runDetail(run('closed-child'))).toMatch(/charged and nothing was retried/);
	});

	it('says how many tasks have finished while the run is moving', () => {
		expect(runDetail(run('one-child-done'))).toBe('1 of 2 tasks finished.');
		expect(runDetail(run('children-admitted'))).toBe('0 of 2 tasks finished.');
	});

	it('says an answer covers only part of the request when coverage is partial', () => {
		expect(runDetail(run('refusals-and-partial'))).toMatch(/only part of the request/);
		expect(runDetail(run('completed'))).toBeNull();
	});

	it('explains the four ways a plan can fail', () => {
		expect(runDetail(run('failed-plan'))).toMatch(/could not be turned into a valid plan/);
		expect(runDetail(run('unfunded-plan'))).toMatch(/more tasks than the total cap can fund/);
		expect(runDetail(run('plan-not-handed-over'))).toBe(
			`${NOT_HANDED_OVER} Nothing ran. Send the request again.`
		);
		expect(runDetail(run('plan-has-placeholders'))).toBe(HAS_PLACEHOLDERS);
	});

	it('says the model wrote its plan out as text, that nothing ran, and to send the request again', () => {
		const failed = run('plan-not-handed-over');
		expect(failed.status).toBe('failed');
		expect(failed.stop_reason).toBe('plan_not_handed_over');
		const detail = runDetail(failed)!;
		expect(detail).toBe(
			'The model wrote its plan out as text instead of handing it over, so there is no plan to approve. Nothing ran. Send the request again.'
		);
		// It begins with the sentence the stop reason is worded with.
		expect(detail.startsWith(`${stopReasonText('plan_not_handed_over')} `)).toBe(true);
		// A model's own wording would be a claim: this says what the application found.
		expect(detail).not.toMatch(/(?<!un)verified|\bconfirmed\b|\bchecked\b/i);
	});

	it('says the plan carried a placeholder, why it was refused, that nothing ran, and what to try, word for word', () => {
		const failed = run('plan-has-placeholders');
		expect(failed.status).toBe('failed');
		expect(failed.stop_reason).toBe('plan_has_placeholders');
		expect(failed.tree).toBeNull();
		const detail = runDetail(failed)!;
		expect(detail).toBe(
			'The plan carried a placeholder that stands for a name or an identifier. This route is pseudonymized, and a placeholder in a plan cannot be turned back into the real value, so the plan was refused. Nothing ran. Try the request again without the name or identifier.'
		);
		// It begins with the sentence the stop reason is worded with, as the other plan failures do.
		expect(stopReasonText('plan_has_placeholders')).toBe(
			'The plan carried a placeholder that stands for a name or an identifier.'
		);
		expect(detail.startsWith(`${stopReasonText('plan_has_placeholders')} `)).toBe(true);
		// The headline is the failure; it makes no claim of its own about why.
		expect(runHeadline(failed)).toBe('The run failed');
		// Nothing in it calls the plan checked, verified or confirmed.
		expect(detail).not.toMatch(/(?<!un)verified|\bconfirmed\b|\bchecked\b/i);
	});

	it('explains a run that is reading the request without saying a plan is coming', () => {
		const planning = run('direct.planning');
		expect(plansByTool(planning)).toBe(true);
		const detail = runDetail(planning)!;
		expect(detail).toBe(
			'One model call is reading your request. It will answer, or propose a plan. No task runs until you approve a plan.'
		);
		expect(detail).not.toMatch(/proposing|bounded tasks/i);
		// It no longer says "nothing has been approved" as if a plan were waiting to be.
		expect(detail).not.toMatch(/nothing has been approved/i);
		// Where the plan is written in text the model is proposing tasks, and that is said as before.
		expect(runDetail(run('planning'))).toBe(
			'The model is proposing bounded tasks. Nothing has been approved, and nothing else runs until you approve a plan.'
		);
	});

	it('says nothing more of a run that answered by itself: the answer is the message', () => {
		expect(runDetail(run('direct.completed'))).toBeNull();
	});

	it('works on every recorded shape and always returns text or null', () => {
		for (const { label, run: value } of allRuns()) {
			const detail = runDetail(value);
			expect(detail === null || (typeof detail === 'string' && detail.length > 0), label).toBe(
				true
			);
			expect(runHeadline(value).length, label).toBeGreaterThan(0);
		}
	});
});

describe('status sets', () => {
	it('"active" is exactly the states that hold the owner’s single allowance', () => {
		expect([...ACTIVE_STATUSES].sort()).toEqual(
			['awaiting_approval', 'planning', 'queued', 'running', 'uncertain', 'waiting_children'].sort()
		);
	});

	it('polls only planning, queued, running and waiting_children', () => {
		expect([...POLLING_STATUSES].sort()).toEqual(
			['planning', 'queued', 'running', 'waiting_children'].sort()
		);
		for (const status of POLLING_STATUSES) expect(shouldPollStatus(status)).toBe(true);
		for (const status of ['awaiting_approval', 'uncertain', ...TERMINAL_STATUSES]) {
			expect(shouldPollStatus(status)).toBe(false);
		}
	});

	it('every known status is active or terminal, never both', () => {
		for (const status of [...ACTIVE_STATUSES, ...TERMINAL_STATUSES]) {
			expect(isActiveStatus(status) !== isTerminalStatus(status), status).toBe(true);
		}
		expect(isActiveStatus('something_new')).toBe(false);
		expect(isTerminalStatus('something_new')).toBe(false);
		expect(shouldPollStatus('something_new')).toBe(false);
	});
});

describe('shouldAnnounceSettled', () => {
	it('fires once when a run moves from active to finished', () => {
		expect(
			shouldAnnounceSettled({ previous: 'running', current: 'completed', messageHasContent: false })
		).toBe(true);
		expect(
			shouldAnnounceSettled({ previous: 'planning', current: 'failed', messageHasContent: false })
		).toBe(true);
		expect(
			shouldAnnounceSettled({ previous: 'uncertain', current: 'closed', messageHasContent: false })
		).toBe(true);
		expect(
			shouldAnnounceSettled({
				previous: 'completed',
				current: 'completed',
				messageHasContent: true
			})
		).toBe(false);
	});

	it('stays quiet while the run is still active', () => {
		expect(
			shouldAnnounceSettled({
				previous: 'running',
				current: 'waiting_children',
				messageHasContent: false
			})
		).toBe(false);
		expect(
			shouldAnnounceSettled({ previous: null, current: 'uncertain', messageHasContent: false })
		).toBe(false);
	});

	it('on a first look, only a completed run whose message is still empty needs the row read again', () => {
		expect(
			shouldAnnounceSettled({ previous: null, current: 'completed', messageHasContent: false })
		).toBe(true);
		expect(
			shouldAnnounceSettled({ previous: null, current: 'completed', messageHasContent: true })
		).toBe(false);
		expect(
			shouldAnnounceSettled({ previous: null, current: 'halted', messageHasContent: false })
		).toBe(false);
	});
});

describe('stopReasonText', () => {
	it('says every reason the backend emits as a sentence', () => {
		for (const reason of [
			'owner_halt',
			'owner_closed',
			'invalid_proposal',
			'plan_not_handed_over',
			'plan_has_placeholders',
			'unfunded_plan',
			'invalid_synthesis',
			'unresolved_effect',
			'unresolved_reservation',
			'root_deadline',
			'observed_budget_overrun'
		]) {
			const text = stopReasonText(reason);
			expect(text, reason).toMatch(/^[A-Z].*\.$/);
			expect(text, reason).not.toContain('_');
		}
	});

	it('humanises a reason it does not know and returns null for none', () => {
		expect(stopReasonText('provider_went_away')).toBe('Provider went away.');
		expect(stopReasonText(null)).toBeNull();
		expect(stopReasonText('')).toBeNull();
	});

	it('does not mistake an object property for a known reason', () => {
		expect(stopReasonText('constructor')).toBe('Constructor.');
		expect(stopReasonText('__proto__')).toBe('Proto.');
		expect(stopReasonText('toString')).toBe('ToString.');
	});

	it('says a code with no words in it as it came, and a blank one not at all, never as a lone full stop', () => {
		expect(stopReasonText('___')).toBe('___.');
		expect(stopReasonText('-')).toBe('-.');
		for (const blank of [' ', '   ', '\t\n']) {
			expect(stopReasonText(blank), JSON.stringify(blank)).toBeNull();
		}
		for (const odd of ['___', '-', '.', ' _ ', 'a', 'mystery_code', '9']) {
			expect(stopReasonText(odd), odd).not.toBe('.');
			expect(stopReasonText(odd), odd).toMatch(/\S\.$/);
		}
	});
});

describe('taskCounts', () => {
	it('counts tasks by what they are doing', () => {
		expect(taskCounts(run('one-child-done').tree)).toEqual({
			total: 2,
			finished: 1,
			running: 0,
			waiting: 1,
			stopped: 0,
			failed: 0
		});
		expect(taskCounts(run('refusals-and-partial').tree)).toMatchObject({
			total: 2,
			finished: 2,
			failed: 1
		});
		expect(taskCounts(run('halted').tree)).toMatchObject({ finished: 1, stopped: 1 });
	});

	it('is safe with no plan', () => {
		expect(taskCounts(null)).toMatchObject({ total: 0, finished: 0 });
		expect(taskCounts(undefined)).toMatchObject({ total: 0 });
		expect(taskCounts(run('failed-plan').tree)).toMatchObject({ total: 0 });
	});
});

describe('runDetail for a halted run', () => {
	const REST =
		'No combined answer was produced. Task answers and files finished before the halt remain below.';

	it('says the owner halted it, when they did', () => {
		const halted = run('halted');
		expect(halted.stop_reason).toBe('owner_halt');
		expect(runDetail(halted)).toBe(`You halted the run. ${REST}`);
	});

	it('does not say the owner did it when something else stopped it', () => {
		for (const stop_reason of [
			'observed_budget_overrun',
			'root_deadline',
			'unresolved_effect',
			'',
			null
		]) {
			expect(runDetail(withRun(run('halted'), { stop_reason })), String(stop_reason)).toBe(REST);
		}
		// A reason the page has never seen is added, in plain words, after what the halt says.
		expect(runDetail(withRun(run('halted'), { stop_reason: 'something_new' }))).toBe(
			`${REST} Something new.`
		);
	});

	it('begins with the same sentence the stop reason is worded with, and leaves the headline alone', () => {
		const halted = run('halted');
		expect(runDetail(halted)!.startsWith(`${stopReasonText('owner_halt')} `)).toBe(true);
		expect(runHeadline(halted)).toBe('Halted');
		expect(runHeadline(withRun(halted, { stop_reason: 'observed_budget_overrun' }))).toBe(
			'Halted: a call cost more than its allowance'
		);
	});

	it('is not what an uncertain run says, even one recorded with the owner’s halt as its stop reason', () => {
		for (const name of ['stalled-model-run', 'timeout-run'] as const) {
			const stalled = legacyRun(name);
			expect(stalled.stop_reason).toBe('owner_halt');
			expect(runDetail(stalled)).toBe(UNCERTAIN_EXPLANATION);
		}
	});
});

describe('a stop reason the page has never seen', () => {
	const MADE_UP = 'mystery_code';
	const IN_WORDS = 'Mystery code.';
	/** A copy of a recorded run in this status, stopped for this reason. */
	const stopped = (name: Parameters<typeof run>[0], status: string, stop_reason: string | null) => {
		const copy = structuredClone(run(name));
		copy.status = status;
		copy.stop_reason = stop_reason;
		if (copy.tree) copy.tree.status = status;
		return copy;
	};

	it('shows a failed plan as failed, and the code in plain words', () => {
		const failed = stopped('failed-plan', 'failed', MADE_UP);
		expect(failed.tree).toBeNull();
		expect(runHeadline(failed)).toBe('The run failed');
		expect(runDetail(failed)).toBe(IN_WORDS);
	});

	it('shows a run that failed after its tasks ran as failed, and the code in plain words', () => {
		const failed = stopped('refusals-and-partial', 'failed', MADE_UP);
		expect(failed.tree).not.toBeNull();
		expect(runHeadline(failed)).toBe('The run failed');
		expect(runDetail(failed)).toBe(IN_WORDS);
	});

	it.each(['halted', 'expired', 'closed', 'rejected', 'uncertain'])(
		'shows what a %s run says of itself, and then the code in plain words',
		(status) => {
			const own = runDetail(stopped('one-child-done', status, null));
			expect(own, 'what the status says on its own').toMatch(/\S/);
			const detail = runDetail(stopped('one-child-done', status, MADE_UP));
			expect(detail).toBe(`${own} ${IN_WORDS}`);
			// The headline is the status's, whatever the code.
			expect(runHeadline(stopped('one-child-done', status, MADE_UP))).toBe(
				runHeadline(stopped('one-child-done', status, null))
			);
		}
	);

	it('shows a status it has never seen as words, with the code', () => {
		const odd = stopped('failed-plan', 'quarantined', MADE_UP);
		expect(runHeadline(odd)).toBe('Quarantined');
		expect(runDetail(odd)).toBe(IN_WORDS);
	});

	it('shows the code once, where the status has nothing to say but the code', () => {
		for (const status of ['failed', 'quarantined']) {
			const detail = runDetail(stopped('failed-plan', status, MADE_UP))!;
			expect(detail.split(IN_WORDS).length - 1, status).toBe(1);
		}
	});

	it('reads a code it has a sentence for as it always did: nothing is added after the status’s own', () => {
		const known = [
			'owner_halt',
			'owner_closed',
			'root_deadline',
			'observed_budget_overrun',
			'unresolved_effect',
			'unresolved_reservation',
			'invalid_proposal',
			'unfunded_plan',
			'invalid_synthesis',
			'plan_not_handed_over',
			'plan_has_placeholders'
		];
		for (const status of ['halted', 'expired', 'closed', 'rejected', 'uncertain']) {
			const base = runDetail(stopped('one-child-done', status, null));
			for (const code of known) {
				const detail = runDetail(stopped('one-child-done', status, code));
				const expected =
					status === 'halted' && code === 'owner_halt' ? `You halted the run. ${base}` : base;
				expect(detail, `${status} / ${code}`).toBe(expected);
			}
		}
	});

	it('is no part of what a run that is moving, or was delivered, says', () => {
		for (const status of [
			'planning',
			'awaiting_approval',
			'queued',
			'running',
			'waiting_children',
			'completed'
		]) {
			const detail = runDetail(stopped('one-child-done', status, MADE_UP));
			expect(detail ?? '', status).not.toContain('Mystery');
		}
	});

	it('leaves a code with no words in it, or nothing in it, from showing as a lone full stop or as nothing', () => {
		for (const code of [MADE_UP, '___', '-', ' ', '9', '<img src=x onerror=alert(1)>']) {
			for (const status of [
				'failed',
				'halted',
				'expired',
				'closed',
				'rejected',
				'uncertain',
				'quarantined'
			]) {
				const value = stopped('one-child-done', status, code);
				const label = `${status} / ${JSON.stringify(code)}`;
				expect(runHeadline(value).length, label).toBeGreaterThan(0);
				const detail = runDetail(value);
				// A status the page has never seen, with no reason to give either, is its headline alone.
				if (status === 'quarantined' && code.trim() === '') {
					expect(detail, label).toBeNull();
					continue;
				}
				expect(detail, label).not.toBeNull();
				expect(detail, label).toMatch(/\S/);
				expect(detail, label).not.toBe('.');
			}
		}
		// A failed run with nothing to say of why still says that it stopped.
		expect(runDetail(stopped('failed-plan', 'failed', ' '))).toBe(
			'The run stopped before it finished.'
		);
	});

	it('hands the code back as the text it is, and builds no markup from it', () => {
		const hostile = '<img src=x onerror=alert(1)>';
		for (const status of ['failed', 'halted', 'expired', 'closed', 'quarantined']) {
			const detail = runDetail(stopped('one-child-done', status, hostile))!;
			expect(detail, status).toContain(hostile);
			expect(detail.replace(hostile, ''), status).not.toMatch(/[<>]/);
		}
	});
});

describe('runTitle, the heading of a run message', () => {
	it('names New harness, its prompt version and the model it is pinned to, and marks it experimental', () => {
		const recorded = run('harness.completed');
		expect(runTitle(recorded)).toEqual({
			text: 'New harness v2 → selected/native',
			experimental: true
		});
		// The pieces are the run's own: its profile title, the version it pinned and its model.
		expect(recorded.profile_title).toBe('New harness');
		expect(recorded.planning.root_skill_version).toBe('2');
		expect(recorded.planning.model).toBe('selected/native');
	});

	it('says the same for a run that is still planning, which has no plan to read the prompt from', () => {
		for (const name of ['documents.planning', 'harness.follow-up.planning'] as const) {
			const planning = run(name);
			expect(planning.tree, name).toBeNull();
			expect(runTitle(planning), name).toEqual({
				text: 'New harness v2 → selected/native',
				experimental: true
			});
		}
	});

	it('says the same in every status of a New harness run', () => {
		for (const name of [
			'documents.planning',
			'documents.awaiting-approval',
			'documents.completed',
			'harness.completed',
			'harness.no-documents.awaiting-approval',
			'harness.no-documents.completed'
		] as const) {
			expect(runTitle(run(name)).text, name).toBe('New harness v2 → selected/native');
		}
	});

	it('keeps the profile’s own title for a run instructed by a skill, with no marker', () => {
		for (const { label, run: value } of allRuns()) {
			if (value.planning.root?.skill?.kind === 'prompt') continue;
			expect(runTitle(value), label).toEqual({
				text: value.profile_title?.trim() || 'Governed run',
				experimental: false
			});
		}
		expect(runTitle(run('completed'))).toEqual({
			text: 'Contract Questions Orchestrator',
			experimental: false
		});
	});

	it('is "Governed run" for a run recorded before profiles had titles', () => {
		for (const name of ['model-run', 'rejected-run'] as const) {
			expect(runTitle(legacyRun(name)), name).toEqual({
				text: 'Governed run',
				experimental: false
			});
		}
	});

	it('reads the prompt from the plan when the planning snapshot does not say', () => {
		const value = withRun(run('harness.completed'), {});
		delete (value.planning as { root?: unknown }).root;
		expect(runTitle(value)).toEqual({
			text: 'New harness v2 → selected/native',
			experimental: true
		});
	});

	it('leaves out a version or a model the run does not state, rather than printing a gap', () => {
		const base = run('harness.completed');
		const without = (change: (copy: typeof base) => void) => {
			const copy = structuredClone(base);
			change(copy);
			return runTitle(copy).text;
		};
		expect(without((copy) => (copy.planning.root_skill_version = ''))).toBe(
			'New harness → selected/native'
		);
		expect(without((copy) => (copy.planning.model = '  '))).toBe('New harness v2');
		expect(
			without((copy) => {
				copy.planning.root_skill_version = '';
				copy.planning.model = '';
			})
		).toBe('New harness');
		expect(without((copy) => (copy.profile_title = null))).toBe(
			'Governed run v2 → selected/native'
		);
		for (const text of [
			without((copy) => (copy.planning.root_skill_version = '')),
			without((copy) => (copy.planning.model = ''))
		]) {
			expect(text).not.toMatch(/undefined|null|NaN|v\s*$|→\s*$/);
		}
	});

	it('hands back the title, version and model untouched, as one plain string', () => {
		const hostile = '<img src=x onerror=alert(1)>';
		const value = structuredClone(run('harness.completed'));
		value.profile_title = hostile;
		value.planning.root_skill_version = hostile;
		value.planning.model = hostile;
		expect(runTitle(value).text).toBe(`${hostile} v${hostile} → ${hostile}`);
	});
});
