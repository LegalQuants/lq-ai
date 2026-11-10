/**
 * The run as one column of lines: the plan, one line per task, and the answer.
 *
 * Each line is a closed one-line summary of what sits under it. A closed line
 * carries only what the run's records state: the task topic exactly as the plan
 * wrote it (model-written, so the component shows it as text), counts, statuses,
 * spend, and the latest step in the renderer registry's plain words. Never a
 * finding and never any other model-written prose; findings stay under the fold.
 *
 * A request the orchestrator answered by itself has no plan, no tasks and no approval, so its
 * column is one line: `direct`. The answer it gave is the chat message's own content.
 *
 * Built on the helpers that already compute these facts (`runProgress`,
 * `taskLatestStep`, `currentSteps`, `planView`, `evidenceLine`, ...); this
 * file only arranges them. Total: it works on every recorded run, including runs
 * from before chat hosting and runs in a status this client does not know.
 */
import type { OrchestrationChatRun, RunProgress } from '../api/orchestration';
import { evidenceLine } from './evidence';
import { formatUsd, humanise, pluralise } from './format';
import { planState, planView } from './plan';
import { currentSteps, runProgress, taskLatestStep, type ProgressState } from './progress';
import { LEGACY_MODEL_CALL, describeEffect, stepContext, type StepContext } from './renderers';
import { READING_REQUEST, isActiveStatus, isTerminalStatus, plansByTool } from './status';

export type ActivityKind = 'plan' | 'task' | 'answer' | 'direct';
export type ActivityState = ProgressState;

/** What the shared line draws. */
export interface ActivityLine {
	state: ActivityState;
	/** The lead of the line: a heading, or a task's topic. */
	label: string;
	/** What the line says after the label, or null. */
	summary: string | null;
	/** Small trailing text, such as a task's spend, or null. */
	meta: string | null;
}

export interface ActivityRow extends ActivityLine {
	/** `plan`, `task-1`, `task-2`, ..., `answer`; or `direct` alone, for an answer given without a plan. */
	id: string;
	kind: ActivityKind;
	/** 1-based, for a task row (as the plan numbers its tasks); null otherwise. */
	index: number | null;
	/** Whether there is anything under the line to open. */
	openable: boolean;
	/** Whether the line starts open in the chat: only the plan, while it awaits approval. */
	openByDefault: boolean;
}

const WAITING = 'waiting to start';
const NO_OUTCOME = 'a provider call has no confirmed outcome';

// ---- the plan -----------------------------------------------------------------------------

/** The profile of the earlier demonstration: its root has no trace to read, so no line opens to one. */
const DEMONSTRATION_PROFILE = 'demonstration';

/**
 * Whether a run stopped before it had a plan, without answering by itself: failed, halted, expired
 * or closed, or left uncertain. Its plan line has no plan to open, but the call that was meant to
 * make one is on record, so the line opens to that call: how it was set up, what the model wrote
 * and its receipts. A run still reading the request has nothing finished to show, an answer given
 * by the orchestrator has its own line, and a run of the earlier demonstration has no trace.
 */
export function endedBeforeAPlan(
	run: Pick<OrchestrationChatRun, 'status' | 'tree' | 'answered_directly' | 'profile'>
): boolean {
	if (run.tree || run.answered_directly === true) return false;
	if (run.profile === DEMONSTRATION_PROFILE) return false;
	return isTerminalStatus(run.status) || run.status === 'uncertain';
}

function planRow(run: OrchestrationChatRun, stages: ReturnType<typeof runProgress>): ActivityRow {
	const view = planView(run);
	const [proposal, approval] = stages;
	const base = { id: 'plan', kind: 'plan' as const, index: null, meta: null };

	// One row for two stages: the proposal, then the owner's decision on it.
	const state: ActivityState = proposal.state !== 'done' ? proposal.state : approval.state;
	const uncertain = run.status === 'uncertain' ? NO_OUTCOME : null;
	const tasks = view ? pluralise(view.tasks.length, 'task') : null;
	const detail = (proposal.state !== 'done' ? proposal.detail : approval.detail) ?? null;

	let label: string;
	let summary: string | null = null;
	if (!view) {
		// Where the first call may answer instead of planning, a plan is not yet said to be coming.
		label =
			state === 'current'
				? plansByTool(run)
					? READING_REQUEST
					: 'Proposing a plan…'
				: 'No plan was produced';
		summary = state === 'current' ? uncertain : detail;
	} else if (planState(run) === 'approved') {
		label = 'Plan approved';
		summary = [`revision ${view.revision}`, tasks].join(' · ');
	} else if (planState(run) === 'rejected') {
		label = 'You rejected the plan';
	} else if (run.status === 'awaiting_approval') {
		label = 'Plan proposed';
		summary = [tasks, `total cap ${view.totalCap}`, 'waiting for your approval'].join(' · ');
	} else {
		label = state === 'stopped' ? 'Plan not approved' : 'Plan proposed';
		summary = [tasks, uncertain ?? detail].filter(Boolean).join(' · ') || null;
	}
	return {
		...base,
		state,
		label,
		summary,
		openable: view !== null || endedBeforeAPlan(run),
		openByDefault: run.status === 'awaiting_approval' && view !== null && !view.approved
	};
}

// ---- the tasks ----------------------------------------------------------------------------

/**
 * What a task did, from its records: documents read, searches of the knowledge bases made,
 * and model calls. A kind of work the task did not do is left out, never counted as none.
 */
function workDone(child: RunProgress): string[] {
	let models = 0;
	let reads = 0;
	let searches = 0;
	for (const effect of child.effects ?? []) {
		const view = describeEffect(effect);
		if (view.tone !== 'done') continue;
		if (view.kind === 'model_turn' || (view.kind === 'legacy' && view.text === LEGACY_MODEL_CALL)) {
			models += 1;
		} else if (view.kind === 'document_read') {
			reads += 1;
		} else if (view.kind === 'knowledge_search') {
			searches += 1;
		}
	}
	const parts: string[] = [];
	if (reads > 0) parts.push(`read ${pluralise(reads, 'document')}`);
	if (searches > 0) parts.push(searches === 1 ? 'searched once' : `searched ${searches} times`);
	if (models > 0) parts.push(pluralise(models, 'model call'));
	return parts;
}

function hasUncertainStep(child: RunProgress): boolean {
	return (child.effects ?? []).some((effect) => effect.status === 'uncertain');
}

function taskRow(
	child: RunProgress,
	position: number,
	topic: string,
	runActive: boolean,
	context: StepContext
): ActivityRow {
	const steps = child.effects?.length ?? 0;
	let state: ActivityState;
	let summary: string;
	switch (child.status) {
		case 'completed': {
			state = 'done';
			const work = workDone(child);
			if (child.outcome?.status === 'empty') work.push('no findings');
			summary = ['done', ...work].join(' · ');
			break;
		}
		case 'failed': {
			state = 'stopped';
			const code = child.outcome?.failure_code;
			summary = `could not complete: ${humanise(code).toLowerCase() || 'no reason recorded'}`;
			break;
		}
		case 'running':
			// A run that ended cannot have a task still running.
			state = runActive ? 'current' : 'stopped';
			summary = runActive
				? (taskLatestStep(child, context) ?? 'running')
				: `stopped after ${pluralise(steps, 'step')}`;
			break;
		case 'pending':
		case 'queued':
			state = runActive ? 'pending' : 'skipped';
			summary = runActive ? WAITING : 'did not run';
			break;
		case 'halted':
			state = 'stopped';
			summary = `halted after ${pluralise(steps, 'step')}`;
			break;
		case 'stopped':
			state = 'stopped';
			summary = `stopped after ${pluralise(steps, 'step')}`;
			break;
		default:
			state = runActive ? 'pending' : 'stopped';
			summary = humanise(child.status).toLowerCase() || 'status not recorded';
	}
	if (hasUncertainStep(child) && state !== 'done') summary = NO_OUTCOME;
	const showSpend = state === 'done' || state === 'current' || state === 'stopped';
	return {
		id: `task-${position + 1}`,
		kind: 'task',
		index: position + 1,
		state,
		label: topic,
		summary,
		meta: showSpend ? formatUsd(child.spent_usd) : null,
		openable: true,
		openByDefault: false
	};
}

// ---- the answer ---------------------------------------------------------------------------

function answerRow(
	run: OrchestrationChatRun,
	stage: ReturnType<typeof runProgress>[number]
): ActivityRow {
	const tree = run.tree;
	const base = { id: 'answer', kind: 'answer' as const, index: null, meta: null };
	const open = !!tree && stage.state !== 'pending' && stage.state !== 'skipped';
	switch (stage.state) {
		case 'done': {
			const coverage = tree?.result?.coverage;
			const parts: string[] = [];
			if (coverage === 'partial') parts.push('covers part of the request');
			else if (coverage === 'empty') parts.push('no findings');
			parts.push(evidenceLine(run));
			return {
				...base,
				state: 'done',
				label: 'Answer delivered',
				summary: parts.join(' · '),
				openable: open,
				openByDefault: false
			};
		}
		case 'current': {
			const latest = currentSteps(run).find((line) => line.who === null);
			const text =
				run.status === 'uncertain' ? NO_OUTCOME : (latest?.text ?? 'combining the tasks’ answers…');
			return {
				...base,
				state: 'current',
				label: 'Combining',
				summary: text,
				openable: open,
				openByDefault: false
			};
		}
		case 'stopped':
			return {
				...base,
				state: 'stopped',
				label: 'Combine and deliver the answer',
				summary: stage.detail,
				openable: open,
				openByDefault: false
			};
		case 'skipped':
			return {
				...base,
				state: 'skipped',
				label: 'Combine and deliver the answer',
				summary: 'did not run',
				openable: false,
				openByDefault: false
			};
		default:
			return {
				...base,
				state: 'pending',
				label: 'Combine and deliver the answer',
				summary: null,
				openable: false,
				openByDefault: false
			};
	}
}

// ---- an answer the orchestrator gave by itself ---------------------------------------------

/** The first thing under the line of a run answered without a plan: what the line means. */
export const DIRECT_NOTE =
	'The orchestrator answered this request by itself. No task ran, nothing was read or searched, ' +
	'and nothing was put to you for approval.';

/**
 * The answer the orchestrator gave by itself, for a view that has no chat message beside it to show
 * it: the receipt page. (In the thread the answer is the message, drawn beneath the run.) Null for a
 * run that was not answered directly, and for one whose read carries no answer. It is model-written
 * text, and is returned untouched for a component to show as text.
 */
export function directAnswerText(
	run: Pick<OrchestrationChatRun, 'answered_directly' | 'direct_answer'>
): string | null {
	if (run.answered_directly !== true) return null;
	const text = run.direct_answer;
	return typeof text === 'string' && text.trim() !== '' ? text : null;
}

/**
 * The one line of a run answered without a plan. Nothing was read or searched, no task ran and
 * nothing was put to the owner for approval, and that is all the closed line says besides what
 * the call cost. The answer is not on the line: it is the chat message's own content.
 */
function directRow(run: OrchestrationChatRun): ActivityRow {
	// Only a completed run has been answered; any other state of one is said as it is.
	const state: ActivityState =
		run.status === 'completed' ? 'done' : isActiveStatus(run.status) ? 'current' : 'stopped';
	return {
		id: 'direct',
		kind: 'direct',
		index: null,
		state,
		label: 'Answered directly',
		summary: 'no plan · nothing read',
		meta: formatUsd(run.spent_usd),
		openable: true,
		openByDefault: false
	};
}

// ---- the column ---------------------------------------------------------------------------

/**
 * The lines of a run, in order: the plan, a line per task once the plan is approved,
 * then the answer. A run answered by the orchestrator itself is the one line, `direct`.
 * Where the plan is handed over by a tool call, the first call may answer instead, so while
 * the run is reading the request and no plan exists the plan line stands alone: the answer
 * line is drawn once there is a plan.
 *
 * While a run is active at least one line is `current`: the plan while it is proposed
 * or awaits approval, every running task (a plan with two tasks running has two lines
 * to follow), or the answer while it is combined. When the run holds no running task
 * yet, the first task still to run (or the one with an unresolved call) stands for the
 * stage. A run that ended has none, and the lines after where it stopped are `skipped`.
 */
export function runActivity(run: OrchestrationChatRun): ActivityRow[] {
	if (run.answered_directly === true) return [directRow(run)];
	const stages = runProgress(run);
	const active = isActiveStatus(run.status);
	const tree = run.tree;
	const rows: ActivityRow[] = [planRow(run, stages)];

	const children = tree?.approved ? (tree.children ?? []) : [];
	const context = stepContext(run);
	const tasks = children.map((child, position) =>
		taskRow(
			child,
			position,
			tree?.plan.children[position]?.task.topic || `Task ${position + 1}`,
			active,
			context
		)
	);
	const answer = answerRow(run, stages[3]);
	// Under a tool call the first call may end the run with an answer of its own, and combine nothing.
	// Until a plan exists the answer line is not the next step: it is drawn once there is a plan, and
	// where the run stopped without one (then it says it did not run, which is true).
	const mayAnswerWithoutCombining = !tree && plansByTool(run) && answer.state === 'pending';
	rows.push(...tasks);
	if (!mayAnswerWithoutCombining) rows.push(answer);

	if (active && !rows.some((row) => row.state === 'current') && stages[2].state === 'current') {
		const waiting = children.findIndex(hasUncertainStep);
		const target = waiting >= 0 ? tasks[waiting] : tasks.find((row) => row.state !== 'done');
		if (target) target.state = 'current';
	}
	return rows;
}
