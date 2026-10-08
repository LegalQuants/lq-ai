/**
 * Composer helpers: what the owner sees and may do before a run exists.
 *
 * Choosing a profile, reading why one is unavailable, naming the run that is
 * blocking a new one, picking documents, and building the request that starts a
 * run. Pure functions; the chat panel and its run components only render them.
 */
import type {
	ActiveRun,
	ProfileAvailability,
	RunDocument,
	RunTool,
	StartRunBody
} from '../api/orchestration';
import { formatDuration, formatUsd, humanise, own, pluralise } from './format';
import { isActiveStatus } from './status';

/** The goal is limited to 4,096 characters by the API. */
export const MAX_GOAL_CHARS = 4096;

/** At most this many candidate files can be named in one `run-documents` read. */
export const MAX_CANDIDATE_FILES = 16;

// ---- why a profile is unavailable ------------------------------------------------

const FALLBACK_REASONS: Record<string, string> = {
	operator_disabled: 'The operator has not enabled this profile.',
	not_configured: 'The operator has enabled this profile but its configuration is incomplete.',
	autonomous_opt_in_required: 'Turn on Autonomous in your settings to start a run.',
	project_required: 'Runs start from a chat inside a matter. This chat has no matter.',
	project_not_permitted: 'The operator has limited this profile to a dedicated demo matter.',
	route_unavailable: 'The profile’s model route, protection or pricing is unavailable.',
	active_run: 'Another run of yours is still active. One run can be active at a time.'
};

/**
 * Why a profile cannot be used here, or null when it can. Uses the server's own
 * words (`reason_text`) and falls back to wording for the reason code, so a
 * profile is never disabled without a reason.
 */
export function unavailableReason(profile: ProfileAvailability): string | null {
	if (profile.available) return null;
	const text = typeof profile.reason_text === 'string' ? profile.reason_text.trim() : '';
	if (text) return text;
	return own(FALLBACK_REASONS, profile.reason) ?? 'This profile is unavailable right now.';
}

// ---- the run that is blocking a new one ------------------------------------------

/**
 * Names the owner's active run: "A run is active in <chat title>". The title is the
 * chat's own, shown as text. A run in the chat being viewed says so.
 */
export function activeRunLabel(active: ActiveRun, currentChatId: string | null): string {
	if (!active.chat_id) return 'A run you started outside a chat is active';
	const title = typeof active.chat_title === 'string' ? active.chat_title.trim() : '';
	const here = currentChatId !== null && active.chat_id === currentChatId;
	if (title) return `A run is active in ${title}${here ? ' (this chat)' : ''}`;
	return here ? 'A run is active in this chat' : 'A run is active in another chat';
}

/** Where the active run is, in a few words. */
export function activeRunStatusText(status: string): string {
	switch (status) {
		case 'planning':
			return 'Proposing a plan';
		case 'awaiting_approval':
			return 'Waiting for your approval';
		case 'queued':
			return 'Approved, waiting to start';
		case 'running':
		case 'waiting_children':
			return 'Tasks are running';
		case 'uncertain':
			return 'Uncertain: a provider call has no confirmed outcome';
		default:
			return humanise(status);
	}
}

/** Only an uncertain run can be closed. */
export function canCloseActiveRun(active: ActiveRun): boolean {
	return active.status === 'uncertain';
}

/**
 * How often the composer reads again which run holds the owner's allowance, while
 * one does. A run in another chat has no message in this thread to follow it, so
 * without this the notice would never learn that it moved on or ended.
 */
export const ACTIVE_RUN_POLL_MS = 10000;

/**
 * The availability read, with its active run's status taken from a run read shown
 * in the thread. The run message follows its run closely and the composer reads
 * availability rarely, so the notice would otherwise name an older state than the
 * message beside it. A run that has ended no longer holds the allowance, so its
 * notice goes at once; the composer then reads availability again for the rest.
 * Returns the same object when there is nothing to change; a read of some other
 * run changes nothing.
 */
export function syncActiveRun<T extends { active_run: ActiveRun | null }>(
	profiles: T,
	run: { root_id: string; status: string }
): T {
	const active = profiles.active_run;
	if (!active || active.root_id !== run.root_id || active.status === run.status) return profiles;
	if (!isActiveStatus(run.status)) return { ...profiles, active_run: null };
	return { ...profiles, active_run: { ...active, status: run.status } };
}

/** Said beside every Close run button (ADR 0038 D6). */
export const CLOSE_RUN_NOTE =
	'Closing charges the unresolved reservation, retries nothing, and frees you to start another run.';

// ---- run mode ------------------------------------------------------------------------

export interface RunFact {
	label: string;
	value: string;
}

/** Unique tool labels, in the order the profile lists them. */
export function toolLabelList(tools: RunTool[] | null | undefined): string[] {
	const seen = new Set<string>();
	const labels: string[] = [];
	for (const tool of tools ?? []) {
		if (seen.has(tool.name)) continue;
		seen.add(tool.name);
		labels.push((tool.label ?? '').trim() || humanise(tool.name));
	}
	return labels;
}

/**
 * The limits a run in this profile works within, for the composer's run mode: the
 * model, the total cap, the planning allowance, the per-task allowance, the
 * maximum number of tasks, the attempt limit. A value the server has not priced
 * (an unavailable profile) is left out rather than shown as zero.
 */
export function runModeFacts(profile: ProfileAvailability): RunFact[] {
	const facts: RunFact[] = [];
	if (profile.model) facts.push({ label: 'Model', value: profile.model });
	if (profile.budget_usd) facts.push({ label: 'Total cap', value: formatUsd(profile.budget_usd) });
	if (profile.planning_allowance_usd) {
		facts.push({ label: 'Planning allowance', value: formatUsd(profile.planning_allowance_usd) });
	}
	if (profile.child_allowance_usd) {
		facts.push({ label: 'Per-task allowance', value: formatUsd(profile.child_allowance_usd) });
	}
	if (profile.max_children) {
		facts.push({ label: 'Maximum tasks', value: String(profile.max_children) });
	}
	if (profile.attempt_timeout_seconds) {
		facts.push({
			label: 'Attempt limit',
			value: `${formatDuration(profile.attempt_timeout_seconds)} per attempt`
		});
	}
	if (profile.child_turn_limit > 0) {
		// The limit counts turns in which the task may call tools; one more model call,
		// without tools, gives the answer. Both are in the per-task allowance.
		facts.push({
			label: 'Tool turns per task',
			value: `up to ${profile.child_turn_limit}, then one answer`
		});
	}
	return facts;
}

// ---- documents ------------------------------------------------------------------------

/** Shown on a file the run will add to the matter when the plan is proposed. */
export const ADDED_TO_MATTER_NOTE = 'Will be added to this matter when you propose the plan';

const UNREADABLE_REASONS: Record<string, string> = {
	unsupported_type:
		'This type of file cannot be read in a run. Runs read PDF with text, plain text and Markdown.',
	not_ingested: 'Not processed yet. Wait for it to finish, then refresh the list.',
	ingestion_failed: 'Processing failed, so this file cannot be read.',
	no_text: 'No text could be extracted from this file, for example a scan or an image-only PDF.'
};

/** Why a file cannot be selected, or null when it can. Never silently empty for a file that cannot. */
export function unreadableReason(doc: RunDocument): string | null {
	if (doc.selectable) return null;
	const known = own(UNREADABLE_REASONS, doc.reason);
	if (known) return known;
	return doc.reason
		? `This file cannot be read in a run (${doc.reason.replace(/[_-]+/g, ' ')}).`
		: 'This file cannot be read in a run.';
}

/** The note for a selectable file that is not yet attached to the matter, else null. */
export function documentNote(doc: RunDocument): string | null {
	return doc.selectable && !doc.attached_to_project ? ADDED_TO_MATTER_NOTE : null;
}

/** Select or deselect a file. Selection order is the numbering; the limit is enforced. */
export function toggleDocument(selected: string[], fileId: string, max: number): string[] {
	if (selected.includes(fileId)) return selected.filter((id) => id !== fileId);
	if (selected.length >= max) return selected;
	return [...selected, fileId];
}

/** 1-based position in the selection, or null when not selected. */
export function documentNumber(selected: string[], fileId: string): number | null {
	const index = selected.indexOf(fileId);
	return index === -1 ? null : index + 1;
}

export interface DocumentRow {
	fileId: string;
	filename: string;
	characters: number;
	number: number | null;
	checked: boolean;
	disabled: boolean;
	/** Why the row cannot be selected, or null. */
	reason: string | null;
	/** An informational note, or null. */
	note: string | null;
}

/** The picker's rows. Unselectable files are listed, disabled, with the reason. */
export function documentRows(docs: RunDocument[], selected: string[], max: number): DocumentRow[] {
	const atCap = selected.length >= max;
	return docs.map((doc) => {
		const checked = selected.includes(doc.file_id);
		const unreadable = unreadableReason(doc);
		const capped = !checked && !unreadable && atCap;
		return {
			fileId: doc.file_id,
			filename: doc.filename,
			characters: doc.characters,
			number: documentNumber(selected, doc.file_id),
			checked,
			disabled: unreadable !== null || capped,
			reason: unreadable ?? (capped ? `Up to ${pluralise(max, 'document')} can be selected.` : null),
			note: documentNote(doc)
		};
	});
}

/** Keep only selections that are still listed and selectable, in their order. */
export function pruneSelection(selected: string[], docs: RunDocument[]): string[] {
	const usable = new Set(docs.filter((doc) => doc.selectable).map((doc) => doc.file_id));
	return selected.filter((id) => usable.has(id));
}

/** The chat's own attached files, as candidates for `run-documents`. */
export function candidateFileIds(files: { id: string }[]): string[] {
	return files.slice(0, MAX_CANDIDATE_FILES).map((file) => file.id);
}

/** Changes when a candidate is added, removed or changes ingestion status. */
export function candidatesSignature(files: { id: string; ingestion_status?: string }[]): string {
	return files.map((file) => `${file.id}:${file.ingestion_status ?? ''}`).join(',');
}

// ---- proposing the plan ---------------------------------------------------------------

/**
 * Why the plan cannot be proposed yet, or null when it can. The send button reads
 * "Propose plan" in run mode; this is the sentence under it when it is disabled.
 */
export function proposeBlocker(input: {
	profile: ProfileAvailability | null;
	goal: string;
	selectedCount: number;
}): string | null {
	const { profile } = input;
	if (!profile) return 'Choose what to run first.';
	const unavailable = unavailableReason(profile);
	if (unavailable) return unavailable;
	const goal = input.goal.trim();
	if (!goal) return 'Describe what the run should examine.';
	if (goal.length > MAX_GOAL_CHARS) {
		return `The request is limited to ${MAX_GOAL_CHARS.toLocaleString('en-US')} characters.`;
	}
	if (profile.documents === 'selected' && input.selectedCount < 1) {
		return 'Select at least one document for this run.';
	}
	return null;
}

export interface PendingRequest {
	id: string;
	signature: string;
}

/** What a request id stands for. The server refuses an id reused with a different request. */
export function requestSignature(parts: {
	chatId: string;
	profile: string;
	goal: string;
	fileIds: string[];
}): string {
	return JSON.stringify([parts.chatId, parts.profile, parts.goal.trim(), parts.fileIds]);
}

/**
 * The request id to send. Kept while the same request is retried, so a retry after
 * a lost response returns the same run instead of starting a second one; replaced
 * as soon as the request itself changes (the server answers 409 to an id reused
 * with different input).
 */
export function requestFor(
	previous: PendingRequest | null,
	signature: string,
	makeId: () => string
): PendingRequest {
	return previous && previous.signature === signature ? previous : { id: makeId(), signature };
}

/** `crypto.randomUUID()`, with a fallback for pages served without a secure context. */
export function newRequestId(): string {
	const api = typeof crypto !== 'undefined' ? crypto : undefined;
	if (api && typeof api.randomUUID === 'function') return api.randomUUID();
	const bytes = new Uint8Array(16);
	if (api && typeof api.getRandomValues === 'function') api.getRandomValues(bytes);
	else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
	bytes[6] = (bytes[6] & 0x0f) | 0x40;
	bytes[8] = (bytes[8] & 0x3f) | 0x80;
	const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * The body of `POST /chats/{chat_id}/runs`. A profile that reads a fixed document
 * is sent no `file_ids` (the server refuses them); one that reads a selection is
 * sent the owner's selection in order.
 */
export function buildStartBody(args: {
	requestId: string;
	profile: ProfileAvailability;
	goal: string;
	fileIds: string[];
}): StartRunBody {
	const body: StartRunBody = {
		request_id: args.requestId,
		profile: args.profile.profile,
		goal: args.goal.trim()
	};
	if (args.profile.documents === 'selected') body.file_ids = [...args.fileIds];
	return body;
}
