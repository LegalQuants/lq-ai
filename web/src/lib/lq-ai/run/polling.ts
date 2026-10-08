/**
 * When to look at a run again.
 *
 * A run can outlive a request, the access token and a browser tab, so it is
 * followed with no fixed limit on how long: start at two seconds, back off
 * gently while nothing changes, never wait more than ten, pause while the tab is
 * hidden and resume when it is shown again.
 */
import type { OrchestrationChatRun } from '../api/orchestration';
import { shouldPollStatus } from './status';

export const POLL_START_MS = 2000;
export const POLL_MAX_MS = 10000;
const GROWTH = 1.25;

/**
 * Delay before the next look, given how many looks in a row found nothing new.
 * 0 gives 2 s; each unchanged look grows it by a quarter, in steps of 100 ms,
 * up to 10 s. A look that finds a change starts again from 0.
 */
export function nextPollDelay(unchanged: number): number {
	const steps = Number.isFinite(unchanged) ? Math.max(0, Math.floor(unchanged)) : 0;
	const raw = POLL_START_MS * GROWTH ** steps;
	if (!Number.isFinite(raw)) return POLL_MAX_MS;
	return Math.min(POLL_MAX_MS, Math.round(raw / 100) * 100);
}

export type PollDecision = 'poll' | 'paused' | 'stop';

/**
 * `poll`: schedule the next look. `paused`: the run is moving but the tab is
 * hidden, so wait for it to be shown. `stop`: nothing will change on its own.
 */
export function pollDecision(input: { status: string; hidden: boolean }): PollDecision {
	if (!shouldPollStatus(input.status)) return 'stop';
	return input.hidden ? 'paused' : 'poll';
}

/**
 * A string that changes whenever the run has visibly moved: its status, how many
 * steps each session has recorded, and each task's status. Used to decide whether
 * a look found something new, so the delay can start again from two seconds.
 */
export function runFingerprint(run: OrchestrationChatRun): string {
	const tree = run.tree;
	const parts = [run.status, String(run.effects?.length ?? 0), run.spent_usd, run.reserved_usd];
	if (tree) {
		parts.push(String(tree.approved), String(tree.root?.effects?.length ?? 0));
		for (const child of tree.children ?? []) {
			parts.push(`${child.status}:${child.effects?.length ?? 0}:${child.files?.length ?? 0}`);
		}
	}
	return parts.join('|');
}
