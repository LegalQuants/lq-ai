/**
 * The knowledge-base files a run's searches found, as the list under the answer line names them.
 *
 * A search numbers each file it finds, above the documents the owner selected, and the number is
 * what a quotation's `(Source: [N])` marker carries. The answer cites by number, so the list is
 * how a reader gets from `[27]` to a file name, and to the task whose search found it.
 *
 * File names are the owner's own text: returned as written, for a component to show as text.
 */
import type { OrchestrationChatRun } from '../api/orchestration';

/** What the list is called. */
export const SOURCES_TITLE = 'Files found by search';

export interface SourceRow {
	/** The number a quotation's marker carries. */
	number: number;
	filename: string;
	/** The task whose search found the file, by its position in the plan (from 1); null when the run does not say. */
	task: number | null;
	/** `[27] travel-policy.txt · found by task 2`. */
	text: string;
}

/**
 * Where a task stands in the plan, from its session id: its place among the run's tasks, which
 * is the number its line and the plan card give it. Null for a session that is none of them.
 */
function taskPosition(run: Pick<OrchestrationChatRun, 'tree'>, sessionId: string): number | null {
	const tree = run.tree;
	if (!tree || typeof sessionId !== 'string' || sessionId === '') return null;
	const started = (tree.children ?? []).findIndex((child) => child.session_id === sessionId);
	if (started >= 0) return started + 1;
	// A task not yet admitted has no session of its own; the plan names the one it will have.
	const planned = (tree.plan?.children ?? []).findIndex((child) => child.dispatch_id === sessionId);
	return planned >= 0 ? planned + 1 : null;
}

/**
 * One row per file the run's searches found, in the order of their numbers. Empty when none was
 * found, and for a run recorded before searches existed. A source with no usable number or no
 * file name is left out rather than guessed at.
 */
export function runSources(run: Pick<OrchestrationChatRun, 'sources' | 'tree'>): SourceRow[] {
	const rows: SourceRow[] = [];
	for (const source of run.sources ?? []) {
		if (!source || typeof source !== 'object') continue;
		const { number, filename, session_id: sessionId } = source;
		if (typeof number !== 'number' || !Number.isFinite(number)) continue;
		if (typeof filename !== 'string' || filename === '') continue;
		const task = taskPosition(run, sessionId);
		rows.push({
			number,
			filename,
			task,
			text: `[${number}] ${filename}${task === null ? '' : ` · found by task ${task}`}`
		});
	}
	return rows.sort((a, b) => a.number - b.number);
}
