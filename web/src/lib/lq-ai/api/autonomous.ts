/**
 * Autonomous Layer API client — M4-C2. Wraps /api/v1/autonomous/*.
 *
 * Auth gating (server-side):
 *   - Read + halt endpoints: bearer token only (ActiveUser dep).
 *   - All mutate endpoints: bearer token + autonomous opt-in required
 *     (AutonomousEnabledUser dep). Callers that haven't opted in get 403.
 *
 * Types mirror app/schemas/autonomous.py and app/autonomous/receipt.py
 * build_receipt(). Field names are exact — a mismatch here propagates into
 * every downstream dashboard page (Tasks 10–17).
 *
 * DELETE endpoints return 200 with the updated entity (NOT 204) — the
 * backend deliberately avoids the FastAPI/JSONResponse 204 pitfall.
 */
import { apiRequest } from './client';

// ---------------------------------------------------------------------------
// Enums (mirror app/schemas/autonomous.py StrEnum values exactly)
// ---------------------------------------------------------------------------

export type SessionStatus = 'running' | 'completed' | 'halted' | 'failed';

/** Orthogonal brake state — separate from SessionStatus. */
export type HaltState = 'running' | 'halt_requested' | 'halted' | 'paused';

export type TriggerKind = 'watch' | 'schedule' | 'suggestion' | 'manual';

export type Phase = 'intake' | 'analysis' | 'drafting' | 'ethics_review' | 'delivery';

export type MemoryState = 'proposed' | 'kept' | 'dismissed';

export type ProposalState = 'proposed' | 'accepted' | 'rejected';

export type NotificationChannel = 'in_app' | 'email' | 'webhook';

// ---------------------------------------------------------------------------
// Entity interfaces (mirror *Read Pydantic models)
// ---------------------------------------------------------------------------

export interface AutonomousSessionRead {
	id: string;
	user_id: string;
	project_id: string | null;
	trigger_kind: TriggerKind;
	trigger_ref: string | null;
	current_phase: Phase;
	halt_state: HaltState;
	max_cost_usd: string | null; // Decimal → string in JSON
	cost_total_usd: string; // Decimal → string in JSON
	cost_cap_reached: boolean;
	idle_halt_minutes: number;
	last_activity_at: string;
	status: SessionStatus;
	params: Record<string, unknown>;
	result: Record<string, unknown> | null;
	error: string | null;
	created_at: string;
	updated_at: string;
	completed_at: string | null;
}

/** One phase-machine transition from build_receipt. */
export interface ReceiptPhaseTransition {
	to_phase: Phase | null;
	/** ISO-8601 string; key is `timestamp`, NOT `at`. */
	timestamp: string | null;
}

/** One tool-call entry from build_receipt. */
export interface ReceiptToolCall {
	tool: string | null;
	outcome: string | null;
	/** ISO-8601 string; key is `timestamp`, NOT `at`. */
	timestamp: string | null;
	cost_usd?: number;
}

/** The live-reconstructed receipt from app/autonomous/receipt.py build_receipt. */
export interface SessionReceipt {
	session_id: string;
	trigger_kind: string | null;
	status: string | null;
	halt_state: string | null;
	current_phase: string | null;
	// number here (build_receipt float()s it) — distinct from AutonomousSessionRead.cost_total_usd (string)
	cost_total_usd: number;
	max_cost_usd: number | null;
	cost_cap_reached: boolean;
	created_at: string | null;
	completed_at: string | null;
	phase_transitions: ReceiptPhaseTransition[];
	tool_calls: ReceiptToolCall[];
	terminal_reason: string | null;
}

/** GET /autonomous/sessions/{id} — session + live receipt envelope. */
export interface AutonomousSessionDetailResponse {
	session: AutonomousSessionRead;
	receipt: SessionReceipt;
}

/** GET /autonomous/sessions — paginated list. Envelope key: `sessions`. */
export interface AutonomousSessionListResponse {
	sessions: AutonomousSessionRead[];
	total_count: number;
	limit: number;
	offset: number;
}

export interface AutonomousMemoryRead {
	id: string;
	user_id: string;
	state: MemoryState;
	category: string;
	content: string;
	source_session_id: string | null;
	kept_at: string | null;
	deleted_at: string | null;
	created_at: string;
	updated_at: string;
}

/** GET /autonomous/memory — paginated list. Envelope key: `entries`. */
export interface AutonomousMemoryListResponse {
	entries: AutonomousMemoryRead[];
	total_count: number;
	limit: number;
	offset: number;
}

export interface PrecedentEntryRead {
	id: string;
	user_id: string;
	pattern_kind: string;
	summary: string;
	observed_count: number;
	source_session_id: string | null;
	dismissed_at: string | null;
	created_at: string;
	updated_at: string;
}

/** GET /autonomous/precedents — paginated list. Envelope key: `entries`. */
export interface PrecedentEntryListResponse {
	entries: PrecedentEntryRead[];
	total_count: number;
	limit: number;
	offset: number;
}

export interface ProjectContextProposalRead {
	id: string;
	user_id: string;
	precedent_id: string;
	project_id: string;
	suggested_md: string;
	state: ProposalState;
	accepted_at: string | null;
	rejected_at: string | null;
	created_at: string;
	updated_at: string;
}

/** GET /autonomous/project-context-proposals — paginated list. Envelope key: `proposals`. */
export interface ProjectContextProposalListResponse {
	proposals: ProjectContextProposalRead[];
	total_count: number;
	limit: number;
	offset: number;
}

export interface AutonomousScheduleRead {
	id: string;
	user_id: string;
	project_id: string | null;
	name: string | null;
	cron_expr: string;
	playbook_id: string | null;
	skill_ref: string | null;
	target_kb_id: string | null;
	enabled: boolean;
	last_run_at: string | null;
	next_run_at: string | null;
	deleted_at: string | null;
	created_at: string;
	updated_at: string;
}

/** GET /autonomous/schedules — paginated list. Envelope key: `schedules`. */
export interface AutonomousScheduleListResponse {
	schedules: AutonomousScheduleRead[];
	total_count: number;
	limit: number;
	offset: number;
}

export interface AutonomousWatchRead {
	id: string;
	user_id: string;
	project_id: string | null;
	knowledge_base_id: string;
	playbook_id: string | null;
	skill_ref: string | null;
	enabled: boolean;
	deleted_at: string | null;
	created_at: string;
	updated_at: string;
}

/** GET /autonomous/watches — paginated list. Envelope key: `watches`. */
export interface AutonomousWatchListResponse {
	watches: AutonomousWatchRead[];
	total_count: number;
	limit: number;
	offset: number;
}

export interface AutonomousNotificationRead {
	id: string;
	user_id: string;
	session_id: string;
	channel: NotificationChannel;
	title: string;
	body: string;
	payload: Record<string, unknown> | null;
	read_at: string | null;
	created_at: string;
	updated_at: string;
}

/** GET /autonomous/notifications — paginated list. Envelope key: `notifications`. */
export interface AutonomousNotificationListResponse {
	notifications: AutonomousNotificationRead[];
	total_count: number;
	limit: number;
	offset: number;
}

// ---------------------------------------------------------------------------
// Request-body types (mirror Create/Update/Request Pydantic models)
// ---------------------------------------------------------------------------

/** POST /autonomous/memory/{id}/keep — optional edit-on-keep. */
export interface MemoryKeepRequest {
	content?: string | null;
}

/** POST /autonomous/schedules — create body. */
export interface AutonomousScheduleCreate {
	cron_expr: string;
	name?: string | null;
	playbook_id?: string | null;
	skill_ref?: string | null;
	target_kb_id?: string | null;
	project_id?: string | null;
	enabled?: boolean;
	/** Per-schedule spend cap. Decimal serialized as a string; null/omitted falls back to the system default. */
	max_cost_usd?: string;
}

/** PATCH /autonomous/schedules/{id} — partial update. */
export interface AutonomousScheduleUpdate {
	name?: string | null;
	cron_expr?: string | null;
	enabled?: boolean | null;
	playbook_id?: string | null;
	skill_ref?: string | null;
	target_kb_id?: string | null;
}

/** POST /autonomous/watches — create body. */
export interface AutonomousWatchCreate {
	knowledge_base_id: string;
	playbook_id?: string | null;
	skill_ref?: string | null;
	project_id?: string | null;
	enabled?: boolean;
	/** Per-watch spend cap. Decimal serialized as a string; null/omitted falls back to the system default. */
	max_cost_usd?: string;
}

/** PATCH /autonomous/watches/{id} — partial update. */
export interface AutonomousWatchUpdate {
	enabled?: boolean | null;
	playbook_id?: string | null;
	skill_ref?: string | null;
}

/** POST /autonomous/precedents/{id}/promote — body. */
export interface PromotePrecedentRequest {
	project_id: string;
}

/**
 * POST /autonomous/run-now — manual-trigger body. All fields optional.
 * Mirrors app/schemas/autonomous.py ManualRunRequest. `max_cost_usd` is a
 * Decimal serialized as a string, matching AutonomousScheduleCreate.
 */
export interface ManualRunRequest {
	playbook_id?: string;
	skill_ref?: string;
	target_kb_id?: string;
	project_id?: string;
	max_cost_usd?: string;
}

// ---------------------------------------------------------------------------
// Sessions (read + halt — gated on ActiveUser; always reachable for audit)
// ---------------------------------------------------------------------------

/** GET /autonomous/sessions — paginated, newest first. */
export const listSessions = (
	limit = 50,
	offset = 0
): Promise<AutonomousSessionListResponse> =>
	apiRequest<AutonomousSessionListResponse>(
		`/autonomous/sessions?limit=${limit}&offset=${offset}`
	);

/** GET /autonomous/sessions/{session_id} — detail + live receipt. */
export const getSession = (id: string): Promise<AutonomousSessionDetailResponse> =>
	apiRequest<AutonomousSessionDetailResponse>(`/autonomous/sessions/${id}`);

/**
 * POST /autonomous/sessions/{session_id}/halt
 * Idempotent. Returns the updated AutonomousSessionRead (not unknown).
 * Gated on ActiveUser (not AutonomousEnabledUser) — reachable even when not opted in.
 */
export const haltSession = (id: string): Promise<AutonomousSessionRead> =>
	apiRequest<AutonomousSessionRead>(`/autonomous/sessions/${id}/halt`, { method: 'POST' });

// ---------------------------------------------------------------------------
// Memory curation (M4-B1)
// ---------------------------------------------------------------------------

/** GET /autonomous/memory — non-deleted entries. Optional state filter. */
export const listMemory = (
	state?: MemoryState,
	limit = 50,
	offset = 0
): Promise<AutonomousMemoryListResponse> => {
	const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
	if (state !== undefined) params.set('state', state);
	return apiRequest<AutonomousMemoryListResponse>(`/autonomous/memory?${params.toString()}`);
};

/**
 * POST /autonomous/memory/{memory_id}/keep
 * Optional edit-on-keep: pass content to overwrite entry text.
 * Returns the updated AutonomousMemoryRead.
 */
export const keepMemory = (id: string, content?: string): Promise<AutonomousMemoryRead> =>
	apiRequest<AutonomousMemoryRead>(`/autonomous/memory/${id}/keep`, {
		method: 'POST',
		body: content !== undefined ? ({ content } satisfies MemoryKeepRequest) : undefined
	});

/**
 * POST /autonomous/memory/{memory_id}/dismiss
 * Returns the updated AutonomousMemoryRead.
 */
export const dismissMemory = (id: string): Promise<AutonomousMemoryRead> =>
	apiRequest<AutonomousMemoryRead>(`/autonomous/memory/${id}/dismiss`, { method: 'POST' });

/**
 * DELETE /autonomous/memory/{memory_id}
 * Soft-delete. Returns 200 with the updated (deleted) AutonomousMemoryRead.
 */
export const deleteMemory = (id: string): Promise<AutonomousMemoryRead> =>
	apiRequest<AutonomousMemoryRead>(`/autonomous/memory/${id}`, { method: 'DELETE' });

// ---------------------------------------------------------------------------
// Precedent board (M4-B2)
// ---------------------------------------------------------------------------

/** GET /autonomous/precedents — non-dismissed entries. Optional pattern_kind filter. */
export const listPrecedents = (
	pattern_kind?: string,
	limit = 50,
	offset = 0
): Promise<PrecedentEntryListResponse> => {
	const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
	if (pattern_kind !== undefined) params.set('pattern_kind', pattern_kind);
	return apiRequest<PrecedentEntryListResponse>(`/autonomous/precedents?${params.toString()}`);
};

/**
 * POST /autonomous/precedents/{precedent_id}/dismiss
 * Idempotent. Returns the updated PrecedentEntryRead.
 */
export const dismissPrecedent = (id: string): Promise<PrecedentEntryRead> =>
	apiRequest<PrecedentEntryRead>(`/autonomous/precedents/${id}/dismiss`, { method: 'POST' });

/**
 * POST /autonomous/precedents/{precedent_id}/promote
 * Creates a ProjectContextProposal (proposal only — never writes Project context).
 * Returns 201 with the new ProjectContextProposalRead.
 * Body: { project_id } — server derives suggested_md from the precedent's summary.
 */
export const promotePrecedent = (
	precedentId: string,
	projectId: string
): Promise<ProjectContextProposalRead> =>
	apiRequest<ProjectContextProposalRead>(`/autonomous/precedents/${precedentId}/promote`, {
		method: 'POST',
		body: { project_id: projectId } satisfies PromotePrecedentRequest
	});

// ---------------------------------------------------------------------------
// Project-context proposals (M4-B2)
// ---------------------------------------------------------------------------

/**
 * GET /autonomous/project-context-proposals
 * Optional state + project_id filters.
 */
export const listProposals = (
	state?: ProposalState,
	project_id?: string,
	limit = 50,
	offset = 0
): Promise<ProjectContextProposalListResponse> => {
	const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
	if (state !== undefined) params.set('state', state);
	if (project_id !== undefined) params.set('project_id', project_id);
	return apiRequest<ProjectContextProposalListResponse>(
		`/autonomous/project-context-proposals?${params.toString()}`
	);
};

/**
 * POST /autonomous/project-context-proposals/{proposal_id}/accept
 * The user-authorized write: appends suggested_md to the project's context_md.
 * One-shot per proposal (idempotent context append — guarded server-side by accepted_at).
 * Returns the updated ProjectContextProposalRead.
 */
export const acceptProposal = (id: string): Promise<ProjectContextProposalRead> =>
	apiRequest<ProjectContextProposalRead>(
		`/autonomous/project-context-proposals/${id}/accept`,
		{ method: 'POST' }
	);

/**
 * POST /autonomous/project-context-proposals/{proposal_id}/reject
 * Does NOT touch Project context. Returns the updated ProjectContextProposalRead.
 */
export const rejectProposal = (id: string): Promise<ProjectContextProposalRead> =>
	apiRequest<ProjectContextProposalRead>(
		`/autonomous/project-context-proposals/${id}/reject`,
		{ method: 'POST' }
	);

// ---------------------------------------------------------------------------
// Schedules (M4-B3)
// ---------------------------------------------------------------------------

/** GET /autonomous/schedules — non-deleted entries. Optional enabled filter. */
export const listSchedules = (
	enabled?: boolean,
	limit = 50,
	offset = 0
): Promise<AutonomousScheduleListResponse> => {
	const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
	if (enabled !== undefined) params.set('enabled', String(enabled));
	return apiRequest<AutonomousScheduleListResponse>(
		`/autonomous/schedules?${params.toString()}`
	);
};

/**
 * POST /autonomous/schedules
 * Returns 201 with the created AutonomousScheduleRead.
 */
export const createSchedule = (body: AutonomousScheduleCreate): Promise<AutonomousScheduleRead> =>
	apiRequest<AutonomousScheduleRead>('/autonomous/schedules', { method: 'POST', body });

/**
 * POST /autonomous/run-now
 * Manual trigger — kicks off a session immediately (trigger_kind 'manual').
 * Returns 201 with the created AutonomousSessionRead.
 */
export const runNow = (body: ManualRunRequest): Promise<AutonomousSessionRead> =>
	apiRequest<AutonomousSessionRead>('/autonomous/run-now', { method: 'POST', body });

/**
 * PATCH /autonomous/schedules/{schedule_id}
 * Partial update. Returns 200 with the updated AutonomousScheduleRead.
 */
export const updateSchedule = (
	id: string,
	body: AutonomousScheduleUpdate
): Promise<AutonomousScheduleRead> =>
	apiRequest<AutonomousScheduleRead>(`/autonomous/schedules/${id}`, { method: 'PATCH', body });

/**
 * DELETE /autonomous/schedules/{schedule_id}
 * Soft-delete. Returns 200 with the updated (deleted) AutonomousScheduleRead.
 */
export const deleteSchedule = (id: string): Promise<AutonomousScheduleRead> =>
	apiRequest<AutonomousScheduleRead>(`/autonomous/schedules/${id}`, { method: 'DELETE' });

// ---------------------------------------------------------------------------
// Watches (M4-B4)
// ---------------------------------------------------------------------------

/** GET /autonomous/watches — non-deleted entries. Optional enabled + knowledge_base_id filters. */
export const listWatches = (
	enabled?: boolean,
	knowledge_base_id?: string,
	limit = 50,
	offset = 0
): Promise<AutonomousWatchListResponse> => {
	const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
	if (enabled !== undefined) params.set('enabled', String(enabled));
	if (knowledge_base_id !== undefined) params.set('knowledge_base_id', knowledge_base_id);
	return apiRequest<AutonomousWatchListResponse>(`/autonomous/watches?${params.toString()}`);
};

/**
 * POST /autonomous/watches
 * Returns 201 with the created AutonomousWatchRead.
 */
export const createWatch = (body: AutonomousWatchCreate): Promise<AutonomousWatchRead> =>
	apiRequest<AutonomousWatchRead>('/autonomous/watches', { method: 'POST', body });

/**
 * PATCH /autonomous/watches/{watch_id}
 * Partial update (enabled / playbook_id / skill_ref). knowledge_base_id is immutable.
 * Returns 200 with the updated AutonomousWatchRead.
 */
export const updateWatch = (
	id: string,
	body: AutonomousWatchUpdate
): Promise<AutonomousWatchRead> =>
	apiRequest<AutonomousWatchRead>(`/autonomous/watches/${id}`, { method: 'PATCH', body });

/**
 * DELETE /autonomous/watches/{watch_id}
 * Soft-delete. Returns 200 with the updated (deleted) AutonomousWatchRead.
 */
export const deleteWatch = (id: string): Promise<AutonomousWatchRead> =>
	apiRequest<AutonomousWatchRead>(`/autonomous/watches/${id}`, { method: 'DELETE' });

// ---------------------------------------------------------------------------
// Notifications (M4-C1)
// ---------------------------------------------------------------------------

/**
 * GET /autonomous/notifications — newest first.
 * Pass unreadOnly=true to narrow to unread rows (read_at IS NULL).
 */
export const listNotifications = (
	unreadOnly?: boolean,
	limit = 50,
	offset = 0
): Promise<AutonomousNotificationListResponse> => {
	const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
	if (unreadOnly) params.set('unread', 'true');
	return apiRequest<AutonomousNotificationListResponse>(
		`/autonomous/notifications?${params.toString()}`
	);
};

/**
 * POST /autonomous/notifications/{notification_id}/read
 * "Read" IS the dismiss action — sets read_at. Idempotent.
 * Returns the updated AutonomousNotificationRead.
 */
export const readNotification = (id: string): Promise<AutonomousNotificationRead> =>
	apiRequest<AutonomousNotificationRead>(`/autonomous/notifications/${id}/read`, {
		method: 'POST'
	});
