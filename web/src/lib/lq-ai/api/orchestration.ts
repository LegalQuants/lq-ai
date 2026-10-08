import { apiRequest } from './client';
import type { Phase } from './autonomous';
import { shouldPollStatus } from '../run/status';

export interface TopicOutcome {
	status: 'completed' | 'empty' | 'failed';
	summary: string;
	findings: string[];
	verification: 'unverified';
	failure_code: string | null;
	/** The shared findings file this outcome was read from (absent on older runs). */
	artifact?: {
		session_id: string;
		name: string;
		revision: number;
		digest: string;
	} | null;
}

export interface WorkspaceFile {
	session_id: string;
	name: string;
	revision: number;
	digest: string;
	size_bytes: number;
	shared: boolean;
	updated_at: string;
}

/**
 * What one step did, in registry terms (ADR 0038 D3). `kind` selects a renderer;
 * an unknown kind falls back to a generic presentation. Absent on runs recorded
 * before the registry existed, and null on effects that never completed.
 * `reason` is the model's own stated reason and `summary` holds counts and the
 * owner's own file names: both are text to display, never markup.
 */
export interface StepNote {
	kind: string;
	tool?: string | null;
	label?: string | null;
	reason?: string | null;
	summary?: Record<string, unknown> | null;
}

/** One durable effect (a model call, a tool call, a file write) with its receipt. */
export interface RunEffect {
	effect_key: string;
	status: string;
	reserved_usd: string;
	charged_usd: string | null;
	intent?: string;
	created_at?: string;
	completed_at?: string | null;
	skill?: { name: string; version: string; digest: string } | null;
	accounting?: {
		provider: string;
		model: string;
		basis: string;
		estimated_prompt_tokens: number;
		reported_usage_cost_usd: string;
		[key: string]: unknown;
	} | null;
	/** `success`, `tool_refused`, or absent on runs recorded before tools existed. */
	outcome?: string | null;
	step?: StepNote | null;
}

/** A tool a task's approved plan grants, as the plan card lists it. */
export interface RunTool {
	name: string;
	label: string;
	phase: string;
	registered?: boolean;
}

export interface RunProgress {
	session_id: string;
	status: string;
	phase: Phase;
	allocation_usd: string;
	spent_usd: string;
	reserved_usd: string;
	outcome: TopicOutcome | null;
	files: WorkspaceFile[];
	effects: RunEffect[];
	/** Tools this task may call (absent on runs recorded before tools existed). */
	tools?: RunTool[];
	turn_limit?: number;
	updated_at?: string | null;
}

/** A document a run may read, numbered in the owner's selection order. */
export interface PlanDocument {
	number: number;
	file_id: string;
	document_id: string;
	filename: string;
	/** True when the file was attached to the matter by accepting this run. */
	attached_for_run: boolean;
}

/** Tool names granted to a task, by phase (`analysis`, `drafting`, ...). */
export type PlanTools = Record<string, string[] | undefined>;

export interface PlanChild {
	dispatch_id: string;
	budget_usd: string;
	task: {
		topic: string;
		question: string;
		boundaries: string;
		output_contract: string;
		stopping_condition: string;
	};
	profile?: string;
	execution?: {
		resources?: { document_ids?: string[]; source_names?: string[] };
		skill?: { name: string; digest: string };
		[key: string]: unknown;
	};
	/** Granted tool names by phase (contract version 3). */
	tools?: PlanTools;
	turn_limit?: number;
}

export interface OrchestrationTree {
	root_id: string;
	status: string;
	stop_reason: string | null;
	plan_hash: string;
	approved: boolean;
	/** The registry profile the run was started under (a literal on older runs). */
	mode: string;
	verification: 'unverified';
	plan: {
		revision: number;
		goal: string;
		budget_usd: string;
		root_allowance_usd: string;
		max_active_children: number;
		deadline: string;
		attempt_timeout_seconds?: number;
		contract_version?: number;
		profile?: string | null;
		documents?: PlanDocument[];
		root: { skill: { name: string; digest: string } };
		children: PlanChild[];
	};
	root: RunProgress;
	children: RunProgress[];
	spent_usd: string;
	reserved_usd: string;
	result: {
		summary: string;
		coverage: 'complete' | 'partial' | 'empty' | 'failed';
		verification: 'unverified';
		kind?: string;
		topics?: { session_id: string; topic: string; outcome: TopicOutcome }[];
	} | null;
	partial_summary: string | null;
}

const base = '/autonomous/orchestration';
export const orchestrationApi = {
	tree: (id: string, signal?: AbortSignal) =>
		apiRequest<OrchestrationTree>(`${base}/${encodeURIComponent(id)}/tree`, { signal }),
	file: (root: string, session: string, name: string, signal?: AbortSignal) =>
		apiRequest<WorkspaceFile & { content: string }>(
			`${base}/${encodeURIComponent(root)}/files/${encodeURIComponent(session)}/${encodeURIComponent(name)}`,
			{ signal }
		),
	approve: (tree: OrchestrationTree) =>
		apiRequest<OrchestrationTree>(`${base}/${encodeURIComponent(tree.root_id)}/approve`, {
			method: 'POST',
			body: { revision: tree.plan.revision, plan_hash: tree.plan_hash }
		}),
	reject: (tree: OrchestrationTree) =>
		apiRequest<OrchestrationTree>(`${base}/${encodeURIComponent(tree.root_id)}/reject`, {
			method: 'POST',
			body: { revision: tree.plan.revision }
		}),
	halt: (id: string) =>
		apiRequest<OrchestrationTree>(`${base}/${encodeURIComponent(id)}/halt`, { method: 'POST' })
};

/** True while the run is making progress on its own (so a client should keep following it). */
export function shouldPollTree(status: string): boolean {
	return shouldPollStatus(status);
}

/** The stand-alone page's operator switch read (the fictional profile only). */
export interface ChatCapabilities {
	enabled: boolean;
	attempt_timeout_seconds?: number;
	profile?: 'model_demo_v1';
	title?: string;
	project_id?: string;
	project_name?: string;
	packet_id?: 'fictional-agreement-v1';
	packet?: string;
	model?: string;
	budget_usd?: string;
	planning_allowance_usd?: string;
	root_allowance_usd?: string;
	child_skill?: string;
	deployment_children?: number;
}

export type RunEvidence = 'unverified' | 'citations';

/**
 * How the quotations in a delivered answer fared against the documents the owner
 * selected. `gate_status` is `fiduciary_grade` (every checked quotation matched),
 * `supported_only`, or `flagged` (at least one quotation could not be matched to
 * the document it cites). The ledger gate behind it is shown by the citation UI.
 */
export interface EvidenceResult {
	gate_status: string;
	checked: number;
	matched: number;
	unmatched: number;
	/**
	 * Quotations whose marker names no selected document, or that fall past the
	 * checking cap: nothing was checked for them. Absent on runs read before this field.
	 */
	unresolved?: number;
	/** Quoted passages with no source marker: the checks never saw them. */
	unmarked?: number;
}

export interface OrchestrationChatRun {
	root_id: string;
	status: string;
	stop_reason: string | null;
	/** The registry profile id; absent on runs recorded before chat hosting. */
	profile?: string;
	profile_title?: string | null;
	/** What the profile may read, in the profile's own words. */
	reads?: string | null;
	/** How the delivered answer is checked (ADR 0038 D5). */
	evidence?: RunEvidence;
	/**
	 * Present only for a delivered answer on a profile with `evidence: "citations"`
	 * whose answer quoted a selected document. Null before delivery, for an
	 * `unverified` profile, and when no quotation could be checked. Absent on older runs.
	 */
	evidence_result?: EvidenceResult | null;
	/** The chat turn this run is bound to; null or absent for a stand-alone run. */
	chat_id?: string | null;
	message_id?: string | null;
	packet: string | null;
	planning: {
		attempt_timeout_seconds: number;
		goal: string;
		model: string;
		budget_usd: string;
		root_allowance_usd: string;
		planning_allowance_usd: string;
		packet_digest?: string | null;
		gateway_revision: string;
		child_skill_version: string;
		root_skill_version: string;
		deadline: string;
		contract_version?: number;
		profile?: string | null;
		documents?: PlanDocument[];
		max_children?: number;
		max_active_children?: number;
	};
	effects: RunEffect[];
	spent_usd: string;
	reserved_usd: string;
	tree: OrchestrationTree | null;
}

/** One profile's availability for a chat, as the composer shows it. */
export interface ProfileAvailability {
	profile: string;
	title: string;
	summary: string;
	reads: string;
	/** `packet`: a fixed document. `selected`: the owner picks documents. */
	documents: 'packet' | 'selected';
	evidence: RunEvidence;
	available: boolean;
	reason?: string | null;
	reason_text?: string | null;
	planning_notice: string;
	model?: string | null;
	budget_usd?: string | null;
	planning_allowance_usd?: string | null;
	root_allowance_usd?: string | null;
	child_allowance_usd?: string | null;
	max_children?: number | null;
	attempt_timeout_seconds?: number | null;
	child_turn_limit: number;
	max_documents?: number | null;
	tools: RunTool[];
}

/** The owner's run that holds the single active-run allowance. */
export interface ActiveRun {
	root_id: string;
	status: string;
	profile: string;
	chat_id?: string | null;
	chat_title?: string | null;
	message_id?: string | null;
}

export interface RunProfilesRead {
	chat_id: string;
	project_id: string | null;
	profiles: ProfileAvailability[];
	active_run: ActiveRun | null;
}

export interface RunDocument {
	file_id: string;
	filename: string;
	mime_type: string;
	size_bytes: number;
	characters: number;
	attached_to_project: boolean;
	selectable: boolean;
	/** `unsupported_type`, `not_ingested`, `ingestion_failed` or `no_text`. */
	reason?: string | null;
}

export interface RunDocumentsRead {
	chat_id: string;
	project_id: string;
	max_documents: number;
	documents: RunDocument[];
}

export interface StartRunBody {
	/** Client-generated. Sending the same id again returns the same run. */
	request_id: string;
	profile: string;
	goal: string;
	/** Documents the run may read, in the owner's order (profiles that read a selection). */
	file_ids?: string[];
}

export const orchestrationChatApi = {
	/** The stand-alone page's operator-switch read; the chat composer uses `runProfiles`. */
	capabilities: () => apiRequest<ChatCapabilities>(`${base}/chat-runs`),
	/**
	 * The retired stand-alone intake. Kept for existing clients; runs now start from
	 * a chat with `startRun`.
	 */
	start: (body: { request_id: string; project_id: string; goal: string }) =>
		apiRequest<OrchestrationChatRun>(`${base}/chat-runs`, {
			method: 'POST',
			body: { ...body, profile: 'model_demo_v1', packet_id: 'fictional-agreement-v1' }
		}),
	read: (id: string, signal?: AbortSignal) =>
		apiRequest<OrchestrationChatRun>(`${base}/chat-runs/${encodeURIComponent(id)}`, { signal }),
	halt: (id: string) =>
		apiRequest<OrchestrationChatRun>(`${base}/chat-runs/${encodeURIComponent(id)}/halt`, {
			method: 'POST'
		}),
	/**
	 * Close an `uncertain` run: charge the unresolved reservation, retry nothing, and
	 * release the owner's single active-run allowance. 409 for any other status.
	 */
	close: (id: string) =>
		apiRequest<OrchestrationChatRun>(`${base}/chat-runs/${encodeURIComponent(id)}/close`, {
			method: 'POST'
		}),
	/** Each profile's availability for this chat, and the owner's active run if any. */
	runProfiles: (chatId: string, signal?: AbortSignal) =>
		apiRequest<RunProfilesRead>(`/chats/${encodeURIComponent(chatId)}/run-profiles`, { signal }),
	/**
	 * The files a run started here could read. `candidateFileIds` are the owner's own
	 * files that are not attached to the matter yet (typically the chat's attachments).
	 */
	runDocuments: (chatId: string, candidateFileIds: string[] = [], signal?: AbortSignal) => {
		const params = new URLSearchParams();
		for (const id of candidateFileIds) params.append('file_id', id);
		const query = params.toString();
		return apiRequest<RunDocumentsRead>(
			`/chats/${encodeURIComponent(chatId)}/run-documents${query ? `?${query}` : ''}`,
			{ signal }
		);
	},
	/** Start a governed run as a turn in this chat (202). Idempotent on `request_id`. */
	startRun: (chatId: string, body: StartRunBody) =>
		apiRequest<OrchestrationChatRun>(`/chats/${encodeURIComponent(chatId)}/runs`, {
			method: 'POST',
			body
		})
};
