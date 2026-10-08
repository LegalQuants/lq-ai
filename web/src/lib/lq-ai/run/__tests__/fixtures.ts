/**
 * Loaders for the recorded runs the run helpers and components are tested against.
 *
 * `run/__fixtures__` holds responses recorded from the running backend for this
 * release; `docs/uat/adr35-chat` holds the six runs recorded for the previous
 * release. Both are the same response type, and the older ones lack the fields added
 * since (no `profile`, no `step` on effects, no `tools`, no `documents`), so every
 * helper has to work on both. Read from disk, not imported, so the JSON keeps the
 * exact shape the server sent.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import type {
	OrchestrationChatRun,
	PromptRead,
	RunDocumentsRead,
	RunProfilesRead,
	SessionTraceRead
} from '../../api/orchestration';
import type { ChatLedger, Citation, Message } from '../../types';

function load<T>(relative: string): T {
	return JSON.parse(readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')) as T;
}

export const fixture = <T>(name: string): T => load<T>(`../__fixtures__/${name}.json`);
export const run = (name: string): OrchestrationChatRun =>
	fixture<OrchestrationChatRun>(`run.${name}`);
export const thread = (name: string): Message[] => fixture<Message[]>(`thread.${name}`);
export const profiles = (name: string): RunProfilesRead =>
	fixture<RunProfilesRead>(`profiles.${name}`);
/**
 * A recorded `run-documents` read: `list` (in a matter), `after-run`, `no-project`, or
 * `knowledge-bases` (a matter with two knowledge bases attached and no files).
 */
export const documents = (name = 'list'): RunDocumentsRead =>
	fixture<RunDocumentsRead>(`documents.${name}`);
/**
 * A recorded trace of one session: `root.planned`, `root.completed` (a plan handed over as a
 * call to `propose_plan`), `root.direct` (a request the orchestrator answered itself),
 * `child.completed` or `child.knowledge` (a task that searched the knowledge bases).
 */
export const trace = (name: string): SessionTraceRead => fixture<SessionTraceRead>(`trace.${name}`);
/** A recorded prompt file: `orchestrator` or `subagent`. */
export const prompt = (name: string): PromptRead => fixture<PromptRead>(`prompt.${name}`);
/**
 * The citation rows recorded for a delivered answer: those of `run.documents.completed`
 * (`documents`, the default) or of `run.knowledge.completed` (`knowledge`).
 */
export const citations = (name: 'documents' | 'knowledge' = 'documents'): Citation[] =>
	fixture<Citation[]>(`citations.${name}`);
/** The ledger and gate recorded for the same answer. */
export const ledger = (): ChatLedger => fixture<ChatLedger>('ledger.documents');

/** The six runs recorded for the previous release (docs/uat/adr35-chat). */
export const LEGACY_RUNS = [
	'model-run',
	'rejected-run',
	'stalled-model-run',
	'timeout-run',
	'fenced-plan-run',
	'truncated-plan-run'
] as const;

export const legacyRun = (name: (typeof LEGACY_RUNS)[number]): OrchestrationChatRun =>
	load<OrchestrationChatRun>(`../../../../../../docs/uat/adr35-chat/${name}.json`);

/** Every run fixture recorded for this release, by file name (without `run.` and `.json`). */
export const CURRENT_RUNS = [
	'planning',
	'awaiting-approval',
	'queued',
	'children-admitted',
	'one-child-done',
	'completed',
	'rejected',
	'halted',
	'failed-plan',
	'unfunded-plan',
	'uncertain-planning',
	'uncertain-child',
	'closed-planning',
	'closed-child',
	'refusals-and-partial',
	'documents.planning',
	'documents.awaiting-approval',
	'documents.completed',
	// New harness, recorded after it became a chat model: a follow-up that is shown the
	// thread, and runs with no documents at all.
	'harness.completed',
	'harness.follow-up.planning',
	'harness.no-documents.awaiting-approval',
	'harness.no-documents.completed',
	// The orchestrator's first call may be answered in text: a run with no plan (still planning,
	// then completed), and the two ways a plan handed over as a tool call can fail: by being
	// written out as text instead, and by carrying a placeholder the gateway cannot restore.
	'direct.planning',
	'direct.completed',
	'plan-not-handed-over',
	'plan-has-placeholders',
	// Tasks that may search the matter's knowledge bases, at each stage.
	'knowledge.planning',
	'knowledge.awaiting-approval',
	'knowledge.completed'
] as const;

/** The runs the orchestrator answered by itself: no plan, no tasks, `tree` is null. */
export const DIRECT_RUNS = ['direct.completed'] as const;

/** All runs, old and new, labelled. */
export function allRuns(): { label: string; run: OrchestrationChatRun }[] {
	return [
		...CURRENT_RUNS.map((name) => ({ label: `run.${name}`, run: run(name) })),
		...LEGACY_RUNS.map((name) => ({ label: `legacy ${name}`, run: legacyRun(name) }))
	];
}

/** A copy of a recorded run with fields replaced, for testing one state of it. */
export function withRun(
	base: OrchestrationChatRun,
	patch: Partial<OrchestrationChatRun>
): OrchestrationChatRun {
	return { ...structuredClone(base), ...patch };
}

/**
 * A copy of a recorded run that has an approved plan, with each task's status set
 * and the run's status changed: the in-between states the recordings do not capture.
 */
export function withTasks(
	base: OrchestrationChatRun,
	taskStatuses: string[],
	status: string
): OrchestrationChatRun {
	const copy = structuredClone(base);
	if (!copy.tree) throw new Error('the recorded run has no plan');
	copy.tree.children.forEach((child, index) => {
		if (taskStatuses[index] !== undefined) child.status = taskStatuses[index];
	});
	copy.status = status;
	copy.tree.status = status;
	return copy;
}

/**
 * The recorded knowledge run, stopped while its first task is making the search it made: the run
 * is running (the call is `admitted`) or left `uncertain` (the call has no outcome), and the call
 * is the task's last step, with no step note, because the server writes the note when a call
 * settles. `lists` is what the plan lists for the tasks: knowledge bases (as recorded), documents,
 * or both.
 */
export function whileSearching(
	status: 'admitted' | 'uncertain',
	lists: 'knowledge' | 'documents' | 'both' = 'knowledge'
): OrchestrationChatRun {
	// The recorded run has one task, the one that searched.
	const copy = withTasks(
		run('knowledge.completed'),
		['running'],
		status === 'admitted' ? 'running' : 'uncertain'
	);
	const tree = copy.tree!;
	const [first] = tree.children;
	const at = first.effects.findIndex((effect) => effect.step?.kind === 'knowledge_search');
	first.effects = first.effects.slice(0, at + 1);
	Object.assign(first.effects[at], {
		status,
		step: null,
		outcome: null,
		accounting: null,
		completed_at: null,
		charged_usd: null
	});
	first.outcome = null;
	tree.result = null;
	const listed = run('documents.completed').tree!.plan.documents;
	if (lists !== 'knowledge') tree.plan.documents = structuredClone(listed);
	if (lists === 'documents') tree.plan.knowledge_bases = [];
	return copy;
}
