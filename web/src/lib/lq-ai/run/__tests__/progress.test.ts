/**
 * The progress list: four stages in order, exactly one current while the run is
 * active, exactly one stopped when it ended without an answer.
 */
import { describe, expect, it } from 'vitest';

import {
	COLLECTING,
	currentSteps,
	outcomeSummary,
	runProgress,
	taskLatestStep,
	taskStatusLabel
} from '../progress';
import type { ProgressItem } from '../progress';
import { isActiveStatus } from '../status';
import { allRuns, legacyRun, run, withRun, withTasks } from './fixtures';

const states = (items: ProgressItem[]) => items.map((item) => `${item.id}:${item.state}`);

describe('runProgress on every recorded run', () => {
	it.each(allRuns().map((entry) => [entry.label, entry.run] as const))(
		'%s has four stages in order and one place where the run is',
		(_label, value) => {
			const items = runProgress(value);
			expect(items.map((item) => item.id)).toEqual(['plan', 'approval', 'tasks', 'answer']);
			const current = items.filter((item) => item.state === 'current');
			const stopped = items.filter((item) => item.state === 'stopped');
			if (isActiveStatus(value.status)) {
				// "Exactly one current item while the run is active."
				expect(current).toHaveLength(1);
				expect(stopped).toHaveLength(0);
			} else if (value.status === 'completed') {
				expect(items.every((item) => item.state === 'done')).toBe(true);
			} else {
				expect(current).toHaveLength(0);
				expect(stopped).toHaveLength(1);
			}
			// Nothing before the place the run is can be unfinished, nothing after can be done.
			const at = items.findIndex((item) => item.state === 'current' || item.state === 'stopped');
			if (at >= 0) {
				expect(items.slice(0, at).every((item) => item.state === 'done')).toBe(true);
				expect(items.slice(at + 1).every((item) => ['pending', 'skipped'].includes(item.state))).toBe(true);
			}
		}
	);
});

describe('runProgress states', () => {
	it('proposing a plan', () => {
		expect(states(runProgress(run('planning')))).toEqual([
			'plan:current',
			'approval:pending',
			'tasks:pending',
			'answer:pending'
		]);
	});

	it('waiting for approval', () => {
		const items = runProgress(run('awaiting-approval'));
		expect(states(items)).toEqual(['plan:done', 'approval:current', 'tasks:pending', 'answer:pending']);
		expect(items[0].detail).toBe('2 tasks proposed');
		expect(items[1].detail).toBe('Nothing runs until you approve');
	});

	it('tasks running', () => {
		const items = runProgress(run('one-child-done'));
		expect(states(items)).toEqual(['plan:done', 'approval:done', 'tasks:current', 'answer:pending']);
		expect(items[1].detail).toBe('You approved revision 1');
		expect(items[2].detail).toBe('1 waiting to start · 1 of 2 finished');
		const running = runProgress(withTasks(run('children-admitted'), ['running', 'running'], 'waiting_children'));
		expect(running[2].detail).toBe('2 running · 0 of 2 finished');
	});

	it('combining the answers', () => {
		const combining = withTasks(run('children-admitted'), ['completed', 'completed'], 'running');
		expect(states(runProgress(combining))).toEqual([
			'plan:done',
			'approval:done',
			'tasks:done',
			'answer:current'
		]);
		expect(runProgress(combining)[2].detail).toBe('All 2 tasks finished');
	});

	it('an answer delivered, and one that covers only part of the request', () => {
		expect(runProgress(run('completed'))[3].detail).toBe('Delivered');
		const partial = runProgress(run('refusals-and-partial'));
		expect(partial[2].detail).toBe('2 of 2 finished, 1 could not complete');
		expect(partial[3].detail).toBe('Delivered, covering part of the request');
	});

	it('a plan that could not be used stops at the plan and skips the rest', () => {
		const items = runProgress(run('failed-plan'));
		expect(states(items)).toEqual(['plan:stopped', 'approval:skipped', 'tasks:skipped', 'answer:skipped']);
		expect(items[0].detail).toBe('The model could not produce a usable plan.');
		expect(runProgress(run('unfunded-plan'))[0].detail).toBe(
			'The plan needs more tasks than the budget can fund.'
		);
	});

	it('a rejected plan stops at approval', () => {
		const items = runProgress(run('rejected'));
		expect(states(items)).toEqual(['plan:done', 'approval:stopped', 'tasks:skipped', 'answer:skipped']);
		expect(items[1].detail).toBe('You rejected the plan');
	});

	it('a halted run stops at the tasks, saying how many finished', () => {
		const items = runProgress(run('halted'));
		expect(states(items)).toEqual(['plan:done', 'approval:done', 'tasks:stopped', 'answer:skipped']);
		expect(items[2].detail).toBe('1 of 2 finished before the run stopped');
	});

	it('an uncertain run is still active, so its stage is current, and says why it is stuck', () => {
		const planning = runProgress(run('uncertain-planning'));
		expect(states(planning)).toEqual(['plan:current', 'approval:pending', 'tasks:pending', 'answer:pending']);
		expect(planning[0].detail).toBe('A provider call has no confirmed outcome');
		const child = runProgress(run('uncertain-child'));
		expect(states(child)).toEqual(['plan:done', 'approval:done', 'tasks:current', 'answer:pending']);
		expect(child[2].detail).toBe('A provider call has no confirmed outcome');
	});

	it('a closed run has ended, wherever it was', () => {
		expect(states(runProgress(run('closed-planning')))[0]).toBe('plan:stopped');
		expect(states(runProgress(run('closed-child')))).toEqual([
			'plan:done',
			'approval:done',
			'tasks:stopped',
			'answer:skipped'
		]);
		expect(runProgress(run('closed-child'))[2].detail).toBe('1 of 2 finished before the run stopped');
	});

	it('a combined answer that could not be produced stops at the answer', () => {
		const failed = withRun(withTasks(run('children-admitted'), ['completed', 'completed'], 'failed'), {
			stop_reason: 'invalid_synthesis'
		});
		const items = runProgress(failed);
		expect(states(items)).toEqual(['plan:done', 'approval:done', 'tasks:done', 'answer:stopped']);
		expect(items[3].detail).toBe('The combined answer could not be produced.');
	});

	it('labels are stable, plain words', () => {
		expect(runProgress(run('planning')).map((item) => item.label)).toEqual([
			'Propose a plan',
			'You approve the plan',
			'Run the tasks',
			'Combine and deliver the answer'
		]);
	});
});

describe('currentSteps', () => {
	it('says the model is proposing tasks while planning', () => {
		expect(currentSteps(run('planning'))).toEqual([
			{ who: null, text: 'Asking the model to propose tasks', tone: 'working' }
		]);
	});

	it('says nothing while the run waits for the owner, or after it ended', () => {
		expect(currentSteps(run('awaiting-approval'))).toEqual([]);
		expect(currentSteps(run('completed'))).toEqual([]);
		expect(currentSteps(run('failed-plan'))).toEqual([]);
	});

	it('names the latest step of each running task, under the task’s topic', () => {
		const running = withTasks(run('one-child-done'), ['running', 'running'], 'waiting_children');
		const lines = currentSteps(running);
		expect(lines).toHaveLength(2);
		expect(lines[0].who).toBe('Payments');
		expect(lines[0].text).toBe('Shared the task’s findings with the orchestrator');
		// The second task has recorded no steps yet.
		expect(lines[1]).toEqual({ who: 'Renewal and termination', text: 'Starting', tone: 'working' });
	});

	it('names where an uncertain run stopped', () => {
		const lines = currentSteps(run('uncertain-child'));
		expect(lines).toHaveLength(1);
		expect(lines[0].who).toBe('Renewal and termination');
		expect(lines[0].text).toBe('Asked the model');
		expect(lines[0].tone).toBe('uncertain');
		expect(currentSteps(run('uncertain-planning'))[0]).toMatchObject({
			text: 'Asked the model for a plan',
			tone: 'uncertain'
		});
	});

	it('says what the root is doing once every task has finished', () => {
		const combining = withTasks(run('completed'), ['completed', 'completed'], 'running');
		const lines = currentSteps(combining);
		expect(lines).toHaveLength(1);
		expect(lines[0].text).toBe('Asked the model to combine the tasks’ answers');
	});

	it('never shows the planning call as the current step once the tasks have finished', () => {
		// Seen on a local model: every task done, the orchestrator not yet at its next
		// step, and the line under "Combine and deliver the answer" read "Asked the model
		// for a plan".
		const combining = withTasks(run('completed'), ['completed', 'completed'], 'running');
		const planOnly = structuredClone(combining);
		planOnly.tree!.root.effects = planOnly.tree!.root.effects.filter(
			(effect) => effect.effect_key.startsWith('chat:plan') || effect.intent === 'plan'
		);
		expect(planOnly.tree!.root.effects.length).toBeGreaterThan(0);
		expect(currentSteps(planOnly)).toEqual([{ who: null, text: COLLECTING, tone: 'working' }]);
		// With no orchestrator step recorded at all, the same line is shown.
		const none = structuredClone(combining);
		none.tree!.root.effects = [];
		expect(currentSteps(none)).toEqual([{ who: null, text: COLLECTING, tone: 'working' }]);
		for (const lines of [currentSteps(planOnly), currentSteps(combining)]) {
			expect(lines.map((line) => line.text).join(' ')).not.toMatch(/for a plan/);
		}
	});
});

describe('task labels', () => {
	it('words every task status and humanises one it does not know', () => {
		expect(
			['pending', 'queued', 'running', 'completed', 'failed', 'halted', 'stopped'].map(taskStatusLabel)
		).toEqual(['Waiting', 'Waiting to start', 'Running', 'Done', 'Could not complete', 'Halted', 'Stopped']);
		expect(taskStatusLabel('on_hold')).toBe('On hold');
	});

	it('gives a running task’s latest step, and a waiting one’s', () => {
		const tree = withTasks(run('one-child-done'), ['running', 'queued'], 'running').tree;
		expect(tree).not.toBeNull();
		expect(taskLatestStep(tree!.children[0])).toBe('Shared the task’s findings with the orchestrator');
		expect(taskLatestStep(tree!.children[1])).toBe('Waiting to start');
		expect(taskLatestStep(run('completed').tree!.children[0])).toBeNull();
	});
});

describe('outcomeSummary', () => {
	const outcome = (summary: string, findings: string[]) => ({ summary, findings });

	it('is nothing when a finding already carries it, as a Markdown answer’s summary is its own first line', () => {
		expect(
			outcomeSummary(outcome('Notice is 30 days.', ['Notice is 30 days.\n\n> "at least 30 days" [§5]']))
		).toBeNull();
		expect(outcomeSummary(outcome('Notice is 30 days.', ['## Notice\n\nNotice is 30 days. [§5]']))).toBeNull();
	});

	it('is nothing when any one of several findings carries it', () => {
		expect(outcomeSummary(outcome('B', ['A is here', 'and B is here', 'C']))).toBeNull();
	});

	it('is the summary, trimmed, when no finding carries it', () => {
		expect(outcomeSummary(outcome('  Notice is 30 days.  ', ['Something else entirely.']))).toBe(
			'Notice is 30 days.'
		);
		expect(outcomeSummary(outcome('Notice is 30 days.', ['Notice is 60 days.', 'Fees are due monthly.']))).toBe(
			'Notice is 30 days.'
		);
	});

	it('looks for the trimmed summary, so padding does not hide a match', () => {
		expect(outcomeSummary(outcome('  Notice is 30 days.\n', ['See: Notice is 30 days. [§5]']))).toBeNull();
	});

	it('is the summary for an outcome with no findings, such as an empty or a failed one', () => {
		expect(outcomeSummary(outcome('The topic could not be completed within its approved limits.', []))).toBe(
			'The topic could not be completed within its approved limits.'
		);
		const noFindings = { summary: 'No findings.' } as unknown as { summary: string; findings: string[] };
		expect(outcomeSummary(noFindings)).toBe('No findings.');
	});

	it('is nothing for no outcome, or for a summary that says nothing', () => {
		expect(outcomeSummary(null)).toBeNull();
		expect(outcomeSummary(undefined)).toBeNull();
		for (const summary of ['', ' ', '\n\t  \n']) {
			expect(outcomeSummary(outcome(summary, ['A finding.'])), JSON.stringify(summary)).toBeNull();
			expect(outcomeSummary(outcome(summary, [])), JSON.stringify(summary)).toBeNull();
		}
		const noSummary = { findings: ['A finding.'] } as unknown as { summary: string; findings: string[] };
		expect(outcomeSummary(noSummary)).toBeNull();
	});

	it('returns text it is given as it is, markup and all, for the card to show as text', () => {
		const hostile = '<img src=x onerror=alert(1)>';
		expect(outcomeSummary(outcome(hostile, ['plain']))).toBe(hostile);
		expect(outcomeSummary(outcome(hostile, [`${hostile} and more`]))).toBeNull();
	});

	it('hides the summary on every outcome recorded for this release, where the finding is the summary’s own answer', () => {
		let seen = 0;
		for (const name of ['one-child-done', 'completed', 'halted', 'uncertain-child', 'closed-child', 'documents.completed'] as const) {
			for (const child of run(name).tree!.children) {
				if (!child.outcome) continue;
				seen += 1;
				expect(outcomeSummary(child.outcome), name).toBeNull();
			}
		}
		expect(seen).toBeGreaterThanOrEqual(8);
		// Markup in the summary is no different: the finding begins with it.
		expect(outcomeSummary(run('refusals-and-partial').tree!.children[0].outcome)).toBeNull();
	});

	it('keeps the summary of the recorded outcome that has no findings, and of every one recorded before findings carried it', () => {
		const failed = run('refusals-and-partial').tree!.children[1].outcome!;
		expect(failed.findings).toEqual([]);
		expect(outcomeSummary(failed)).toBe('The topic could not be completed within its approved limits.');
		for (const name of ['model-run', 'stalled-model-run'] as const) {
			for (const child of legacyRun(name).tree!.children) {
				if (!child.outcome) continue;
				expect(outcomeSummary(child.outcome), name).toBe(child.outcome.summary.trim());
			}
		}
	});
});

