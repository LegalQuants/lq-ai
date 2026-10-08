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

/**
 * What instructs one role of a run: an installed skill, or one of the engine's own
 * versioned prompt files (ADR 0038 D3). The prompt's text is at `orchestrationApi.prompt`.
 */
export type InstructionKind = 'skill' | 'prompt';

/** The skill or prompt a session is pinned to. `kind` is absent for a skill. */
export interface PinnedInstruction {
	name: string;
	digest: string;
	kind?: InstructionKind;
	version?: string;
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
	skill?: { name: string; version: string; digest: string; kind?: InstructionKind } | null;
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

/**
 * A knowledge base a run's tasks may search: one attached to the run's matter when the request
 * was accepted. The name is the owner's own text, shown as text. Contract version 3.
 */
export interface KnowledgeBaseRef {
	knowledge_base_id: string;
	name: string;
}

/**
 * The limits a run states to its models and is held to, frozen when the request was sent.
 * Absent on a run recorded before they were frozen, which reads its profile's limits instead.
 */
export interface RunTerms {
	task_turns: number;
	task_answer_chars: number;
	answer_chars: number;
	read_chars: number;
	/**
	 * How the orchestrator hands over its plan. `text`: a JSON object in its reply. `tool`: one
	 * call to `propose_plan`; under it, a reply with no call is the orchestrator's own answer.
	 */
	planning: 'text' | 'tool';
}

/**
 * A knowledge-base file one of the run's searches found. `number` is what a quotation's
 * `(Source: [N])` marker carries; numbers above the selected documents belong to these.
 * `session_id` is the task whose search found it.
 */
export interface RunSource {
	number: number;
	file_id: string;
	filename: string;
	session_id: string;
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
		resources?: {
			document_ids?: string[];
			source_names?: string[];
			knowledge_base_ids?: string[];
		};
		skill?: PinnedInstruction;
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
		/** The knowledge bases the tasks may search; approving the plan is consent to it. */
		knowledge_bases?: KnowledgeBaseRef[];
		root: { skill: PinnedInstruction };
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

/** One of the engine's own versioned prompt files (ADR 0038 D3). `text` is the system message. */
export interface PromptRead {
	/** `<family>/<role>.v<N>`, for example `new_harness/orchestrator.v1`. */
	name: string;
	family: string;
	role: string;
	version: number;
	digest: string;
	text: string;
}

/** Which model call of a session: the plan, one task's work, or the combine step. */
export type TraceStepName = 'plan' | 'task' | 'combine';

/**
 * How a call's rebuilt opening compares with the digest recorded when it was sent:
 * `matches`, `differs`, `not_recorded` (no digest was kept, or the call has not been
 * made) or `not_rebuilt` (a skill-pinned session, or pinned text no longer installed).
 */
export type TraceCheck = 'matches' | 'differs' | 'not_recorded' | 'not_rebuilt';

/** A session's pinned system message. `text` is null when the pinned text is no longer installed. */
export interface TraceSystem {
	kind: InstructionKind;
	name: string;
	version?: string | null;
	digest: string;
	text?: string | null;
}

/** What one model call was opened with. The opening is rebuilt from the run's records, not stored. */
export interface TraceCall {
	step: TraceStepName;
	effect_key: string;
	sent: boolean;
	system: TraceSystem;
	/** The opening user message; null where the read does not rebuild it. */
	opening?: string | null;
	/** The tool schemas offered, as the provider was sent them (`{type, function: {name, description, parameters}}`). */
	tools?: Record<string, unknown>[];
	check: TraceCheck;
}

export interface TraceToolCall {
	id: string;
	name: string;
	/** The arguments as the model wrote them: text, never parsed here. */
	arguments: string;
}

/** One model reply. `text` is model-written. A turn's `effect_key` is its step's in the run read. */
export interface TraceTurn {
	effect_key: string;
	status: string;
	text?: string | null;
	finish_reason?: string | null;
	tool_calls?: TraceToolCall[];
}

/**
 * How one session of a run was set up, and what its model wrote back. `session_id` is the
 * run's root for the orchestrator, or one task's session.
 */
export interface SessionTraceRead {
	root_id: string;
	session_id: string;
	role: 'orchestrator' | 'sub-agent';
	calls: TraceCall[];
	turns: TraceTurn[];
	note?: string;
}

/**
 * The URL path of a prompt file, from its name `<family>/<role>.v<N>`: two segments,
 * each URL-encoded. Null for a name that is not exactly two plain segments, so a name
 * from a server never reaches the request as anything else (no empty, `.` or `..` part).
 */
export function promptPath(name: string): string | null {
	if (typeof name !== 'string') return null;
	const cut = name.indexOf('/');
	if (cut === -1) return null;
	const parts = [name.slice(0, cut), name.slice(cut + 1)];
	for (const part of parts) {
		if (part === '' || part === '.' || part === '..' || /[/\\]/.test(part)) return null;
	}
	return parts.map(encodeURIComponent).join('/');
}

const base = '/autonomous/orchestration';
export const orchestrationApi = {
	tree: (id: string, signal?: AbortSignal) =>
		apiRequest<OrchestrationTree>(`${base}/${encodeURIComponent(id)}/tree`, { signal }),
	/** How one session of a run was set up and what its model wrote. Owner-only. */
	trace: (rootId: string, sessionId: string, signal?: AbortSignal) =>
		apiRequest<SessionTraceRead>(
			`${base}/${encodeURIComponent(rootId)}/sessions/${encodeURIComponent(sessionId)}/trace`,
			{ signal }
		),
	/** The text of one engine prompt file, by name (`new_harness/orchestrator.v1`). */
	prompt: async (name: string, signal?: AbortSignal) => {
		const path = promptPath(name);
		if (path === null) throw new Error('That is not the name of a prompt file.');
		return apiRequest<PromptRead>(`${base}/prompts/${path}`, { signal });
	},
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

/** One earlier message of the chat, as the planning call was shown it (contract version 3). */
export interface ThreadMessage {
	role: 'user' | 'assistant';
	content: string;
	/** True when the text was shortened to fit. */
	cut: boolean;
}

export interface OrchestrationChatRun {
	root_id: string;
	status: string;
	stop_reason: string | null;
	/**
	 * True when the orchestrator answered the request by itself: the run is completed with no
	 * plan, no tasks and no approval, `tree` is null, and nothing was read or searched. The
	 * answer is the chat message's content. Absent on runs read from an older server.
	 */
	answered_directly?: boolean;
	/**
	 * The orchestrator's own answer, set only when `answered_directly`: the text that is also the chat
	 * message's content, for a view (the receipt page) that has no message beside it. A planned run's
	 * answer stays `tree.result.summary`. Null for any other run, and absent on an older server.
	 */
	direct_answer?: string | null;
	/** The knowledge-base files the run's searches found, by source number. Absent on older runs. */
	sources?: RunSource[];
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
		/** The knowledge bases attached to the run's matter when the request was accepted. */
		knowledge_bases?: KnowledgeBaseRef[];
		max_children?: number;
		max_active_children?: number;
		/**
		 * The limits this run states and is held to, frozen when the request was sent. Null or
		 * absent on a run recorded before they were frozen.
		 */
		terms?: RunTerms | null;
		/** The chat's recent messages the planning call was shown; absent before contract version 3. */
		thread?: ThreadMessage[];
		/** The date the planning call was told (UTC, `YYYY-MM-DD`). */
		today?: string;
		/** The matter the run started in; null for a chat outside any matter. */
		project_id?: string | null;
		/** What the orchestrator session is pinned to: its skill, or its prompt file (`kind: "prompt"`). */
		root?: { skill: PinnedInstruction; [key: string]: unknown };
	};
	effects: RunEffect[];
	spent_usd: string;
	reserved_usd: string;
	tree: OrchestrationTree | null;
}

/** What instructs one role of a profile, before anything is sent. */
export interface InstructionsRef {
	role: 'orchestrator' | 'sub-agent';
	kind: InstructionKind;
	/** For a prompt, `<family>/<role>.v<N>`: its text is at `orchestrationApi.prompt(name)`. */
	name: string;
	/** Null until the route is priced. */
	version?: string | null;
	digest?: string | null;
}

/** One profile's availability for a chat, as the composer shows it. */
export interface ProfileAvailability {
	profile: string;
	title: string;
	summary: string;
	reads: string;
	/**
	 * `packet`: a fixed document. `selected`: the owner picks one to eight.
	 * `optional`: the owner picks none to eight, and a run with none reads no document.
	 */
	documents: 'packet' | 'selected' | 'optional';
	evidence: RunEvidence;
	available: boolean;
	/**
	 * Why the profile cannot be used here: `operator_disabled`, `not_configured`,
	 * `autonomous_opt_in_required`, `chat_archived`, `project_required`,
	 * `project_unavailable`, `project_not_permitted`, `route_unavailable` or `active_run`.
	 */
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
	/** The fewest documents a request may name: 0 or 1. Absent on an older server. */
	min_documents?: number;
	max_documents?: number | null;
	/** What instructs each role: an installed skill or an engine prompt file. */
	instructions?: InstructionsRef[];
	/** The inference tier the pinned route resolves to; null until the route is priced. */
	routed_tier?: number | null;
	/** Whether the gateway pseudonymizes calls on that route; null until it is priced. */
	pseudonymized?: boolean | null;
	/** Set only when the operator chose one. */
	reasoning_effort?: string | null;
	/**
	 * True where the orchestrator may answer a request by itself: the reply is then delivered
	 * with no plan and no approval, having read nothing. Absent on an older server.
	 */
	answers_directly?: boolean;
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
	/** The one profile the composer offers as New harness; the server decides. */
	composer_profile?: string | null;
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
	/**
	 * `unsupported_type`, `not_ingested`, `ingestion_failed`, `no_text`, `in_a_matter`
	 * (a file that belongs to a matter, listed from a chat that is in none), or
	 * `in_another_matter` (a candidate that only another matter holds).
	 */
	reason?: string | null;
}

/** A knowledge base attached to the chat's matter, which a task of a run started here may search. */
export interface RunKnowledgeBase {
	knowledge_base_id: string;
	name: string;
}

export interface RunDocumentsRead {
	chat_id: string;
	/** Null for a chat outside any matter: only the chat's own files are listed and nothing is added to a matter. */
	project_id: string | null;
	max_documents: number;
	documents: RunDocument[];
	/**
	 * The knowledge bases a task of a run started here may search: all of those attached to the
	 * chat's matter, at most 16. They are not picked. Empty outside a matter. Absent on an older server.
	 */
	knowledge_bases?: RunKnowledgeBase[];
	/** How many more are attached than one run lists. Those are not searched. */
	knowledge_bases_omitted?: number;
	/** The documents the last run in this chat read that can still be read, in that run's order. */
	suggested_file_ids?: string[];
}

export interface StartRunBody {
	/** Client-generated. Sending the same id again returns the same run. */
	request_id: string;
	profile: string;
	goal: string;
	/**
	 * Documents the run may read, in the owner's order. Profiles that read a selection or
	 * take an optional one are sent the list (possibly empty); a profile that reads a fixed
	 * document is sent none, and the server refuses any.
	 */
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
