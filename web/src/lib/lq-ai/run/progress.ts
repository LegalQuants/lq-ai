/**
 * The run's progress as an ordered list of stages with one current item, and the
 * step each running task is on, in plain words.
 *
 * Four stages cover every run: the plan is proposed, the owner approves it, the
 * tasks run, and the answers are combined and delivered. While a run is active
 * (it holds the owner's allowance) exactly one stage is `current`. Once it has
 * ended without an answer, exactly one stage is `stopped` and the later ones are
 * `skipped`. A completed run has every stage `done`.
 */
import type { OrchestrationChatRun, RunProgress } from '../api/orchestration';
import { humanise, pluralise } from './format';
import { describeEffect, stepContext, type StepContext, type StepTone } from './renderers';
import { isActiveStatus, stopReasonText, taskCounts, type RunLike } from './status';

export type ProgressStageId = 'plan' | 'approval' | 'tasks' | 'answer';
export type ProgressState = 'done' | 'current' | 'pending' | 'stopped' | 'skipped';

export interface ProgressItem {
	id: ProgressStageId;
	label: string;
	state: ProgressState;
	/** One short line that says more about this stage, or null. */
	detail: string | null;
}

const STAGES: { id: ProgressStageId; label: string }[] = [
	{ id: 'plan', label: 'Propose a plan' },
	{ id: 'approval', label: 'You approve the plan' },
	{ id: 'tasks', label: 'Run the tasks' },
	{ id: 'answer', label: 'Combine and deliver the answer' }
];

/** Index of the stage the run is at, or at which it stopped. `STAGES.length` means all done. */
function stageIndex(run: RunLike): number {
	if (run.status === 'completed') return STAGES.length;
	const tree = run.tree;
	if (!tree) return 0;
	if (!tree.approved) return 1;
	if (run.status === 'failed' && run.stop_reason === 'invalid_synthesis') return 3;
	const counts = taskCounts(tree);
	return counts.total > 0 && counts.finished === counts.total ? 3 : 2;
}

function endedText(run: RunLike): string {
	switch (run.status) {
		case 'rejected':
			return 'You rejected the plan';
		case 'halted':
			return 'You halted the run';
		case 'closed':
			return 'You closed the run';
		case 'expired':
			return 'The run reached its time limit';
		case 'failed':
			return 'The run failed';
		default:
			return humanise(run.status);
	}
}

function stageDetail(run: RunLike, id: ProgressStageId, state: ProgressState): string | null {
	const tree = run.tree;
	const counts = taskCounts(tree);
	switch (id) {
		case 'plan': {
			if (state === 'done') {
				const tasks = tree?.plan.children.length ?? 0;
				return tasks > 0 ? `${pluralise(tasks, 'task')} proposed` : null;
			}
			if (state === 'current') {
				return run.status === 'uncertain'
					? 'A provider call has no confirmed outcome'
					: 'The model is proposing tasks';
			}
			if (state === 'stopped') return stopReasonText(run.stop_reason) ?? endedText(run);
			return null;
		}
		case 'approval': {
			if (state === 'done') return tree ? `You approved revision ${tree.plan.revision}` : null;
			if (state === 'current') {
				return run.status === 'uncertain'
					? 'A provider call has no confirmed outcome'
					: 'Nothing runs until you approve';
			}
			if (state === 'stopped') {
				return run.status === 'rejected'
					? 'You rejected the plan'
					: (stopReasonText(run.stop_reason) ?? endedText(run));
			}
			return null;
		}
		case 'tasks': {
			if (counts.total === 0) return null;
			if (state === 'done') {
				return counts.failed > 0
					? `${counts.finished} of ${counts.total} finished, ${counts.failed} could not complete`
					: `All ${pluralise(counts.total, 'task')} finished`;
			}
			if (state === 'current') {
				if (run.status === 'uncertain') return 'A provider call has no confirmed outcome';
				const parts: string[] = [];
				if (counts.running > 0) parts.push(`${counts.running} running`);
				if (counts.waiting > 0) parts.push(`${counts.waiting} waiting to start`);
				parts.push(`${counts.finished} of ${counts.total} finished`);
				return parts.join(' · ');
			}
			if (state === 'stopped')
				return `${counts.finished} of ${counts.total} finished before the run stopped`;
			return null;
		}
		case 'answer': {
			if (state === 'done') {
				switch (tree?.result?.coverage) {
					case 'partial':
						return 'Delivered, covering part of the request';
					case 'empty':
						return 'Delivered with no findings';
					default:
						return 'Delivered';
				}
			}
			if (state === 'current') {
				return run.status === 'uncertain'
					? 'A provider call has no confirmed outcome'
					: 'Combining the tasks’ answers';
			}
			if (state === 'stopped') return stopReasonText(run.stop_reason) ?? endedText(run);
			return null;
		}
	}
}

/** The stages of a run, in order, with where it is. Works on every recorded shape. */
export function runProgress(run: RunLike): ProgressItem[] {
	const at = stageIndex(run);
	const active = isActiveStatus(run.status);
	return STAGES.map((stage, index) => {
		let state: ProgressState;
		if (index < at) state = 'done';
		else if (index === at) state = active ? 'current' : 'stopped';
		else state = active ? 'pending' : 'skipped';
		return { id: stage.id, label: stage.label, state, detail: stageDetail(run, stage.id, state) };
	});
}

/** A task's status as the card's tag reads it. Unknown statuses are humanised. */
export function taskStatusLabel(status: string): string {
	switch (status) {
		case 'pending':
			return 'Waiting';
		case 'queued':
			return 'Waiting to start';
		case 'running':
			return 'Running';
		case 'completed':
			return 'Done';
		case 'failed':
			return 'Could not complete';
		case 'halted':
			return 'Halted';
		case 'stopped':
			return 'Stopped';
		default:
			return humanise(status);
	}
}

/**
 * The summary line to print above a task's findings, or null when a finding
 * already carries it. A Markdown answer's summary is its own first plain line,
 * so printing both would show that line twice.
 */
export function outcomeSummary(
	outcome: { summary: string; findings: string[] } | null | undefined
): string | null {
	const summary = outcome?.summary?.trim() ?? '';
	if (!summary) return null;
	return (outcome?.findings ?? []).some((finding) => finding.includes(summary)) ? null : summary;
}

/**
 * The latest step of a task that has not finished, or null when it has nothing to report. The
 * `context` is the run the task is in: a step still in flight has no note to say what it was.
 */
export function taskLatestStep(child: RunProgress, context: StepContext = {}): string | null {
	switch (child.status) {
		case 'running': {
			const last = child.effects?.[child.effects.length - 1];
			if (!last) return 'Starting';
			const view = describeEffect(last, context);
			return view.tone === 'working' ? `${view.text}…` : view.text;
		}
		case 'queued':
		case 'pending':
			return 'Waiting to start';
		default:
			return null;
	}
}

export interface NowLine {
	/** The task this line is about, or null for the run as a whole. */
	who: string | null;
	text: string;
	tone: StepTone;
}

/**
 * The step each running task is on, in plain words, for the progress list's
 * "Now" lines. Empty when the run is waiting on the owner or has ended.
 */
export function currentSteps(run: OrchestrationChatRun): NowLine[] {
	if (!isActiveStatus(run.status)) return [];
	const tree = run.tree;
	// Every step is read as the run it is in reads it.
	const context = stepContext(run);
	if (!tree) {
		if (run.status === 'planning') {
			return [{ who: null, text: 'Asking the model to propose tasks', tone: 'working' }];
		}
		const last = run.effects?.[run.effects.length - 1];
		if (run.status === 'uncertain' && last) {
			// The call with no outcome is the first one.
			const view = describeEffect(last, context);
			return [{ who: null, text: view.text, tone: view.tone }];
		}
		return [];
	}
	if (run.status === 'awaiting_approval') return [];
	const lines: NowLine[] = [];
	tree.children.forEach((child, index) => {
		const stoppedHere = child.effects?.find((effect) => effect.status === 'uncertain');
		const last = stoppedHere ?? child.effects?.[child.effects.length - 1];
		const who = tree.plan.children[index]?.task.topic ?? null;
		if (run.status === 'uncertain') {
			if (stoppedHere) {
				const view = describeEffect(stoppedHere, context);
				lines.push({ who, text: view.text, tone: view.tone });
			}
			return;
		}
		if (child.status !== 'running') return;
		if (!last) {
			lines.push({ who, text: 'Starting', tone: 'working' });
			return;
		}
		const view = describeEffect(last, context);
		lines.push({
			who,
			text: view.tone === 'working' ? `${view.text}…` : view.text,
			tone: view.tone
		});
	});
	if (lines.length > 0) return lines;
	const counts = taskCounts(tree);
	if (run.status !== 'uncertain' && counts.total > 0 && counts.finished === counts.total) {
		// The orchestrator's own steps since the plan. The planning call is its
		// first step and long done by now, so it is never the current one.
		const since = (tree.root.effects ?? []).filter((effect) => !isPlanningStep(effect));
		const last = since[since.length - 1];
		if (!last) return [{ who: null, text: COLLECTING, tone: 'working' }];
		const view = describeEffect(last, context);
		return [
			{ who: null, text: view.tone === 'working' ? `${view.text}…` : view.text, tone: view.tone }
		];
	}
	return [];
}

/** Shown between the last task finishing and the orchestrator's first step after it. */
export const COLLECTING = 'Collecting the tasks’ findings…';

function isPlanningStep(effect: {
	effect_key?: string | null;
	intent?: string | null;
	step?: { kind?: string | null } | null;
}): boolean {
	return (
		effect.step?.kind === 'planning' ||
		effect.intent === 'plan' ||
		(effect.effect_key ?? '').startsWith('chat:plan')
	);
}
