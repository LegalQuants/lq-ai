/**
 * Run status in plain language.
 *
 * Pure functions over the run read (`GET /autonomous/orchestration/chat-runs/{id}`).
 * They must work on runs recorded before chat hosting (no `profile`, no step notes,
 * no tools) as well as on current ones, and must never throw on a shape they do
 * not know: an unknown status or stop reason falls back to a humanised label.
 */
import type { OrchestrationChatRun, OrchestrationTree } from '../api/orchestration';
import { humanise, own, pluralise } from './format';

/** The fields the status helpers read. A full run read satisfies it. */
export type RunLike = Pick<OrchestrationChatRun, 'status' | 'stop_reason'> & {
	tree?: OrchestrationTree | null;
};

/** Holds the owner's single run allowance (ADR 0035 D1). */
export const ACTIVE_STATUSES: readonly string[] = [
	'planning',
	'awaiting_approval',
	'queued',
	'running',
	'waiting_children',
	'uncertain'
];

/** Making progress on its own, so a client keeps following it. */
export const POLLING_STATUSES: readonly string[] = [
	'planning',
	'queued',
	'running',
	'waiting_children'
];

/** Nothing more will happen without the owner starting something new. */
export const TERMINAL_STATUSES: readonly string[] = [
	'completed',
	'failed',
	'rejected',
	'halted',
	'expired',
	'closed'
];

export function isActiveStatus(status: string): boolean {
	return ACTIVE_STATUSES.includes(status);
}

export function isTerminalStatus(status: string): boolean {
	return TERMINAL_STATUSES.includes(status);
}

/** Planning, queued, running and waiting_children. Approval waits and uncertainty do not poll. */
export function shouldPollStatus(status: string): boolean {
	return POLLING_STATUSES.includes(status);
}

/**
 * Whether a run's message should be refreshed from the server now.
 *
 * True when a run was seen moving from an active state to a finished one, or when
 * a run is first seen already completed but its message still has no content (the
 * thread was fetched a moment before delivery). Once per observed transition.
 */
export function shouldAnnounceSettled(input: {
	previous: string | null;
	current: string;
	messageHasContent: boolean;
}): boolean {
	if (!isTerminalStatus(input.current)) return false;
	if (input.previous === null) {
		return input.current === 'completed' && !input.messageHasContent;
	}
	return !isTerminalStatus(input.previous);
}

export interface TaskCounts {
	total: number;
	/** Delivered an outcome, including a failed one. */
	finished: number;
	running: number;
	/** Admitted and queued, or not yet admitted. */
	waiting: number;
	/** Halted or stopped before finishing. */
	stopped: number;
	failed: number;
}

/** Count a run's tasks by what they are doing. Safe on a missing tree. */
export function taskCounts(tree: OrchestrationTree | null | undefined): TaskCounts {
	const counts: TaskCounts = { total: 0, finished: 0, running: 0, waiting: 0, stopped: 0, failed: 0 };
	for (const child of tree?.children ?? []) {
		counts.total += 1;
		switch (child.status) {
			case 'completed':
				counts.finished += 1;
				break;
			case 'failed':
				counts.finished += 1;
				counts.failed += 1;
				break;
			case 'running':
				counts.running += 1;
				break;
			case 'queued':
			case 'pending':
				counts.waiting += 1;
				break;
			default:
				counts.stopped += 1;
		}
	}
	return counts;
}

const STOP_REASONS: Record<string, string> = {
	owner_halt: 'You halted the run.',
	owner_closed: 'You closed the run.',
	invalid_proposal: 'The model could not produce a usable plan.',
	unfunded_plan: 'The plan needs more tasks than the budget can fund.',
	invalid_synthesis: 'The combined answer could not be produced.',
	unresolved_effect: 'A provider call has no confirmed outcome.',
	unresolved_reservation: 'An amount reserved for a call was left unresolved.',
	root_deadline: 'The run reached its time limit.',
	observed_budget_overrun: 'A call cost more than its allowance.'
};

/** A stop reason as one sentence. Unknown codes are humanised, never dropped. */
export function stopReasonText(reason: string | null | undefined): string | null {
	if (!reason) return null;
	return own(STOP_REASONS, reason) ?? `${humanise(reason)}.`;
}

function taskHeadline(run: RunLike): string {
	const counts = taskCounts(run.tree);
	if (!run.tree?.approved || counts.total === 0) return 'Starting the tasks';
	if (counts.finished === counts.total) return 'Combining the answers';
	if (counts.running > 0) return `${pluralise(counts.running, 'task')} running`;
	if (counts.waiting > 0) return `${pluralise(counts.waiting, 'task')} waiting to start`;
	return 'Starting the tasks';
}

function failedHeadline(run: RunLike): string {
	switch (run.stop_reason) {
		case 'invalid_proposal':
			return 'The model could not produce a usable plan';
		case 'unfunded_plan':
			return 'The plan needs more tasks than the budget can fund';
		case 'invalid_synthesis':
			return 'The combined answer could not be produced';
		default:
			return run.tree?.result?.coverage === 'failed'
				? 'No task produced a usable answer'
				: 'The run failed';
	}
}

/**
 * One line that says what the run is doing or how it ended.
 *
 * "Proposing a plan…", "Waiting for your approval", "2 tasks running",
 * "Combining the answers", "Answer delivered", "You rejected the plan", "Halted",
 * "Uncertain: a provider call has no confirmed outcome", "Closed", and so on.
 */
export function runHeadline(run: RunLike): string {
	switch (run.status) {
		case 'planning':
			return 'Proposing a plan…';
		case 'awaiting_approval':
			return 'Waiting for your approval';
		case 'queued':
			return 'Plan approved. Waiting for the tasks to start';
		case 'waiting_children':
		case 'running':
			return taskHeadline(run);
		case 'completed':
			return 'Answer delivered';
		case 'rejected':
			return 'You rejected the plan';
		case 'halted':
			return run.stop_reason === 'observed_budget_overrun'
				? 'Halted: a call cost more than its allowance'
				: 'Halted';
		case 'uncertain':
			return 'Uncertain: a provider call has no confirmed outcome';
		case 'closed':
			return 'Closed';
		case 'expired':
			return 'The run reached its time limit';
		case 'failed':
			return failedHeadline(run);
		default:
			return humanise(run.status) || 'Unknown status';
	}
}

/** Explains `uncertain` in plain words, and what closing does (ADR 0038 D6). */
export const UNCERTAIN_EXPLANATION =
	'A provider call was sent but its outcome was never confirmed. The run stopped there and will not ' +
	'retry it, because repeating it could be charged twice. The amount reserved for that call stays ' +
	'held, and while it does you cannot start another run. Closing the run charges that unresolved ' +
	'reservation, retries nothing, and frees you to start another run. Work that finished earlier stays ' +
	'readable.';

/**
 * A sentence or two that explains the state beyond the headline, or null when the
 * headline says enough. Plain text.
 */
export function runDetail(run: RunLike): string | null {
	const counts = taskCounts(run.tree);
	switch (run.status) {
		case 'planning':
			return 'The model is proposing bounded tasks. Nothing has been approved, and nothing else runs until you approve a plan.';
		case 'awaiting_approval':
			return 'Review the plan below. Nothing runs until you approve it.';
		case 'queued':
		case 'waiting_children':
		case 'running': {
			if (!run.tree?.approved || counts.total === 0) return null;
			const parts = [`${counts.finished} of ${pluralise(counts.total, 'task')} finished.`];
			if (counts.failed > 0) parts.push(`${pluralise(counts.failed, 'task')} could not complete.`);
			return parts.join(' ');
		}
		case 'completed': {
			const coverage = run.tree?.result?.coverage;
			if (coverage === 'partial') {
				return 'Some tasks could not finish, so the answer covers only part of the request.';
			}
			if (coverage === 'empty') return 'No task produced findings.';
			return null;
		}
		case 'rejected':
			return 'No task work or combined answer will run. The planning charge stays in the receipts. You can start a new run from the composer.';
		case 'halted': {
			// Say who stopped it: the owner's own halt reads differently from a system one.
			const who = run.stop_reason === 'owner_halt' ? 'You halted the run. ' : '';
			return `${who}No combined answer was produced. Task answers and files finished before the halt remain below.`;
		}
		case 'uncertain':
			return UNCERTAIN_EXPLANATION;
		case 'closed':
			return 'You closed the run. The unresolved reservation was charged and nothing was retried. You can start another run. Work that finished earlier remains below.';
		case 'expired':
			return 'The deadline passed before the run finished. Work that finished earlier remains below.';
		case 'failed':
			switch (run.stop_reason) {
				case 'invalid_proposal':
					return 'The planning call was paid for, but its reply could not be turned into a valid plan. No task ran. You can start a new run.';
				case 'unfunded_plan':
					return 'The model proposed more tasks than the total cap can fund at the per-task allowance. No task ran. A narrower request needs fewer tasks.';
				case 'invalid_synthesis':
					return 'The tasks finished, but the model’s combined answer was not usable. Task answers remain below.';
				default:
					return stopReasonText(run.stop_reason) ?? 'The run stopped before it finished.';
			}
		default:
			return stopReasonText(run.stop_reason);
	}
}
