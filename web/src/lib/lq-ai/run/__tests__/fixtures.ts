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
	RunDocumentsRead,
	RunProfilesRead
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
export const documents = (): RunDocumentsRead => fixture<RunDocumentsRead>('documents.list');
/** The citation rows recorded for the delivered answer of `run.documents.completed`. */
export const citations = (): Citation[] => fixture<Citation[]>('citations.documents');
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
	'documents.completed'
] as const;

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
