/**
 * Hand-typed wire shapes for the LQ.AI backend.
 *
 * Source of truth: docs/api/backend-openapi.yaml. These are the schemas the
 * LQ.AI chat shell consumes; not every backend schema is mirrored here.
 *
 * Contract test in __tests__/types.contract.test.ts pins the field set against
 * the OpenAPI sketch's required-list. If you add a property here, add it to
 * the contract test too.
 */

// ----- Auth / users -----

export type UserRole = 'admin' | 'member' | 'viewer';

export type ReasoningVisibility = 'always_show' | 'disclosure' | 'on_request';
export type FeaturedTools = 'prominent' | 'inline';
export type WorkspaceLayout = 'three_pane' | 'two_pane' | 'one_pane';
export type TrustPills = 'labels' | 'dots';
export type ProvenancePills = 'always' | 'collapsed';

export interface Preferences {
	reasoning_visibility: ReasoningVisibility;
	featured_tools: FeaturedTools;
	workspace_layout: WorkspaceLayout;
	trust_pills: TrustPills;
	provenance_pills: ProvenancePills;
}

export type PreferencesUpdate = Partial<Preferences>;

export interface User {
	id: string;
	email: string;
	display_name?: string | null;
	is_admin: boolean;
	role?: UserRole;
	mfa_enabled: boolean;
	must_change_password: boolean;
	created_at: string;
	last_login_at?: string | null;
	reasoning_visibility?: ReasoningVisibility;
	featured_tools?: FeaturedTools;
	workspace_layout?: WorkspaceLayout;
	trust_pills?: TrustPills;
	provenance_pills?: ProvenancePills;
}

export interface LoginRequest {
	email: string;
	password: string;
}

export interface LoginResponse {
	access_token: string;
	token_type: 'Bearer';
	expires_in: number;
	refresh_token?: string;
	user: User;
}

export interface TokenResponse {
	access_token: string;
	refresh_token: string;
	token_type: 'Bearer';
	expires_in: number;
}

export interface ChangePasswordRequest {
	current_password: string;
	new_password: string;
}

// ----- MFA -----

export interface MfaSetupResponse {
	secret: string;
	provisioning_uri: string;
	recovery_codes: string[];
}

export interface MfaEnableRequest {
	code: string;
}

export interface MfaDisableRequest {
	password: string;
	code: string;
}

// ----- Account ops -----

export type ExportJobStatus = 'queued' | 'processing' | 'completed' | 'failed';

export interface ExportJob {
	job_id: string;
	status: ExportJobStatus;
	download_url?: string | null;
}

export interface DeleteScheduledResponse {
	scheduled_deletion_at: string;
	grace_period_days: number;
}

// ----- Errors -----

export interface ErrorBody {
	/**
	 * FastAPI surfaces three distinct detail shapes:
	 *   1. string         — plain-text error message (most common, e.g. HTTPException with str detail)
	 *   2. object         — LQ.AI structured error { code, message, details? }
	 *   3. array          — Pydantic ValidationError [ { msg, type, loc } ]
	 *
	 * The `errorFor` function in api/client.ts handles all three shapes.
	 */
	detail?:
		| string
		| { code: string; message: string; details?: Record<string, unknown> }
		| Array<{ msg: string; type?: string; loc?: unknown[] }>;
}

// ----- Projects -----

export interface Project {
	id: string;
	name: string;
	slug: string;
	description?: string | null;
	context_md?: string | null;
	owner_id: string;
	privileged: boolean;
	minimum_inference_tier?: 1 | 2 | 3 | 4 | 5 | null;
	attached_skill_names?: string[];
	attached_file_ids?: string[];
	attached_knowledge_base_ids?: string[];
	archived_at?: string | null;
	/**
	 * Wave D.2 Task 2.2 — true for the per-user system-managed try-it
	 * sandbox matter (slug ``__sandbox__``). Sandboxes are excluded from
	 * the default ``GET /projects`` listing; the caller opts in via
	 * ``include_sandbox=true`` / ``only_sandbox=true``.
	 */
	is_sandbox?: boolean;
	created_at: string;
	updated_at: string;
}

export interface ProjectCreate {
	name: string;
	slug?: string;
	description?: string;
	context_md?: string;
	privileged?: boolean;
	minimum_inference_tier?: 1 | 2 | 3 | 4 | 5;
}

// ----- Chats / messages -----

export interface Chat {
	id: string;
	title: string;
	owner_id: string;
	project_id?: string | null;
	archived_at?: string | null;
	message_count?: number;
	created_at: string;
	updated_at: string;
}

export interface ChatCreate {
	title?: string;
	project_id?: string | null;
}

export interface ChatUpdate {
	title?: string;
	archived?: boolean;
}

export interface PaginatedChats {
	items: Chat[];
	next_cursor: string | null;
}

// ----- Chat search (Wave B — /chats/search) -----

export interface ChatSearchHit {
	chat_id: string;
	title: string;
	snippet: string;
	match_source: 'title' | 'message';
	rank: number;
	created_at: string;
	updated_at: string;
}

export interface ChatSearchResponse {
	items: ChatSearchHit[];
	query: string;
}

/**
 * Which verification stage validated this citation. Mirrors
 * `MessageCitation.verification_method` in the backend (M2-A2 / M2-B1 / M2-C1 / M2-D1).
 *
 * - `exact_match` — Stage 1, byte-for-byte (M2-A2).
 * - `tolerant_match` — Stage 2, normalized-whitespace + OCR artefacts (M2-B1).
 * - `paraphrase_judge` — Stage 3, paraphrase judge (M2-C1).
 * - `llm_judge` — reserved for future LLM-based semantic-match stages.
 * - `ensemble_strict` — Stage 4 with strict aggregation: every judge
 *   verified (M2-D1).
 * - `ensemble_majority` — Stage 4 with majority aggregation: simple
 *   majority of judges verified (M2-D1). `partial=true` flags
 *   disagreement (some judges dissented) per the M2-D1 UI spec.
 * - `failed` — every stage rejected; rendered as unverified in the M2-C2 UI.
 */
export type CitationVerificationMethod =
	| 'exact_match'
	| 'tolerant_match'
	| 'paraphrase_judge'
	| 'llm_judge'
	| 'ensemble_strict'
	| 'ensemble_majority'
	| 'failed';

export interface Citation {
	id: string;
	source_file_id: string;
	source_offset_start: number;
	source_offset_end: number;
	source_page?: number | null;
	source_text: string;
	verified: boolean;
	/** Which verification stage validated this citation. Null on legacy rows. */
	verification_method?: CitationVerificationMethod | null;
	/** Stage-reported confidence in [0, 1]. Null on legacy rows. */
	verification_confidence?: number | null;
	/**
	 * M2-C1: true when the paraphrase judge returned `partial` — the source
	 * supports the claim only partially. Drives the M2-C2 UI's "verified
	 * with caveats" rendering. Defaults to `false` server-side.
	 *
	 * M2-D1 reuses the same flag for ensemble disagreement: an
	 * `ensemble_majority` row with `partial=true` indicates at least one
	 * judge dissented (the tooltip surfaces "Models disagreed").
	 */
	partial?: boolean;
	/**
	 * M2-D1: the maximum (weakest) inference tier across the judge
	 * models that ran for ensemble-verified rows. Null for non-ensemble
	 * methods. 1-5 per PRD §1.5.2. Audit-only; the UI does not gate
	 * rendering on this value, but a future Receipts surface may
	 * highlight ensembles that exposed citations to weaker tiers.
	 */
	tier_envelope?: number | null;
	/** ISO-8601 timestamp the citation row was written. */
	created_at?: string;
}

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool';

/**
 * Discriminator over the kind of row carried in a `messages` table entry.
 * Mirrors the T4 backend `MessageResponse.kind` field. The default rendering
 * path keys off `role` (legacy); the refusal-bubble dispatch in
 * `MessageBubble.svelte` keys off `kind === 'refusal'`. Optional on the
 * canonical Message type because pre-T4 rows + the streaming draft path
 * don't populate it; consumers default to the role-driven path when missing.
 */
export type MessageKind = 'user' | 'ai' | 'refusal' | 'system';

export interface Message {
	id: string;
	chat_id: string;
	role: MessageRole;
	content: string;
	/**
	 * Discriminator over the message row variant (per T4). Optional for
	 * back-compat with rows persisted before this column landed and with
	 * client-side optimistic/draft messages; the chat surface treats a
	 * missing `kind` as equivalent to the role-driven path.
	 */
	kind?: MessageKind;
	applied_skills?: string[];
	routed_inference_tier?: 1 | 2 | 3 | 4 | 5 | null;
	routed_provider?: string | null;
	routed_model?: string | null;
	/**
	 * Originally-requested model alias or `provider/model` (ADR 0011
	 * follow-on). Differs from `routed_model` when an alias resolved
	 * server-side; null on rows persisted before this column existed.
	 */
	requested_model?: string | null;
	prompt_tokens?: number | null;
	completion_tokens?: number | null;
	cost_estimate?: number | null;
	error_code?: string | null;
	citations?: Citation[];
	created_at: string;
	/**
	 * Refusal-specific surfacings (only populated when `kind === 'refusal'`).
	 * Whether the backend Message schema itself carries these fields or they
	 * come via `inference_routing_log` is a v1.1+ refinement; for M1 they
	 * remain optional on the type. RefusalMessageBubble has safe defaults
	 * when they are absent.
	 */
	refusal_reason?: string;
	requested_tier?: string;
	enforced_tier?: string;
	/**
	 * Wave D.1 T20 follow-on — true when the message's `applied_skills`
	 * contains `'enhance-prompt'` (ADR 0007 denormalization). Derived
	 * server-side by `message_to_response`. The chat surface keys the
	 * ✨ enhanced provenance pill off this field.
	 */
	is_enhanced?: boolean;
}

export interface PaginatedMessages {
	items: Message[];
	next_cursor: string | null;
}

export interface MessageCreate {
	content: string;
	model?: string;
	stream?: boolean;
	skills?: string[];
	skill_inputs?: Record<string, Record<string, unknown>>;
	/**
	 * Wave D.2 Task 3.0 — per-turn skill attachment for slash invocation
	 * and try-it sandboxing. Each entry carries EITHER ``slug`` (saved
	 * skill — built-in or user / team) OR ``inline_body`` (wizard draft).
	 * Runtime XOR validation lives in the backend; we deliberately keep
	 * the TS shape loose so the SkillTryItPane (Task 3.4) can pass either
	 * mode without a discriminated-union dance.
	 */
	attached_skills?: Array<{
		slug?: string;
		inline_body?: string;
		source?: string;
		inputs?: Record<string, unknown>;
	}>;
}

export interface MessagePostResponse {
	message: Message;
	citations: Citation[];
	routed_inference_tier?: 1 | 2 | 3 | 4 | 5 | null;
	routed_provider?: string | null;
	cost_estimate?: number | null;
	applied_skills?: string[];
}

// ----- SSE message-stream events -----

export interface MessageStartFrame {
	type: 'start';
	lq_ai_message_id: string;
	chat_id: string;
}

export interface MessageDeltaFrame {
	type: 'delta';
	delta: string;
	lq_ai_message_id: string;
	routed_inference_tier?: 1 | 2 | 3 | 4 | 5 | null;
	applied_skills?: string[];
}

export interface MessageCompleteFrame {
	type: 'complete';
	lq_ai_message_id: string;
	message: Message;
	citations?: Citation[];
	applied_skills?: string[];
	routed_inference_tier?: 1 | 2 | 3 | 4 | 5 | null;
	routed_provider?: string | null;
}

export interface MessageErrorFrame {
	type: 'error';
	error: {
		code: string;
		message: string;
		details?: Record<string, unknown>;
	};
}

export type MessageStreamEvent =
	| MessageStartFrame
	| MessageDeltaFrame
	| MessageCompleteFrame
	| MessageErrorFrame;

// ----- Skills -----

export interface SkillInputDef {
	name: string;
	type?: 'string' | 'enum' | 'boolean' | 'integer';
	required?: boolean;
	description?: string;
	enum?: string[];
	default?: unknown;
}

export interface SkillSummary {
	name: string;
	version: string;
	scope: 'builtin' | 'user' | 'team';
	title: string;
	description?: string;
	tags?: string[];
	jurisdiction?: string;
	minimum_inference_tier?: 1 | 2 | 3 | 4 | 5;
	output_format?: string;
	/**
	 * Wave D.2 — leading-slash chat invocation alias for user / team skills
	 * (``^/[a-z0-9-]{1,32}$``). Null on built-ins (the surface lives only
	 * on the DB-backed mutable rows).
	 */
	slash_alias?: string | null;
	/**
	 * Wave D.2 — slug of the skill this row was forked from (built-in or
	 * user / team), set when the Skill Creator's "fork from existing" path
	 * spawned the row. Null for from-scratch creates.
	 */
	forked_from?: string | null;
}

export interface SkillReferenceFile {
	path: string;
	content: string;
}

export interface Skill extends SkillSummary {
	/**
	 * Wave D.2 — underlying ``user_skills.id`` row UUID for user/team scope;
	 * ``null`` for built-in (filesystem-canonical) skills which have no DB
	 * row. The skill detail page's Versions tab consumes this to call the
	 * audit-history endpoint without a second round-trip to resolve
	 * slug → id. Mirrors the ``id`` field on the backend ``Skill`` schema.
	 */
	id?: string | null;
	content_yaml: string;
	content_md: string;
	reference_files?: SkillReferenceFile[];
	example_files?: SkillReferenceFile[];
	/**
	 * Parsed inputs from the frontmatter. The OpenAPI sketch surfaces only
	 * `content_yaml` (the raw frontmatter); we parse it client-side to drive
	 * the input form. The shape mirrors `docs/skill-authoring-guide.md`.
	 *
	 * The backend MAY surface `inputs` as a top-level field in a future
	 * iteration; for now the LQ.AI shell parses YAML.
	 */
	inputs?: SkillInputDef[];
}

/** Response shape for GET /api/v1/skills/{name}/inputs. Resolves user > team > built-in. */
export interface SkillInputs {
	name: string;
	required: SkillInputDef[];
	optional: SkillInputDef[];
}

// ----- Files -----

export type IngestionStatus = 'pending' | 'processing' | 'ready' | 'failed';

/**
 * Knowledge base record. Mirrors ``KnowledgeBase`` in
 * ``docs/api/backend-openapi.yaml`` §components.schemas. ``ingestion_status``
 * is a frontend-side derived/optional convenience — the backend KB row itself
 * does not carry a single status (the constituent files do, per IngestionStatus)
 * but C5/C7 surfaces a roll-up via the GET response in some builds; treat as
 * optional and fall back to ``file_count > 0 ? 'ready' : 'pending'`` when
 * absent.
 */
export interface KnowledgeBase {
	id: string;
	name: string;
	description?: string | null;
	owner_id: string;
	project_id?: string | null;
	hybrid_alpha: number;
	file_count: number;
	chunk_count: number;
	ingestion_status?: IngestionStatus;
	archived_at?: string | null;
	created_at: string;
	updated_at: string;
}

export interface KnowledgeBaseCreate {
	name: string;
	description?: string | null;
	project_id?: string | null;
	hybrid_alpha?: number;
}

export interface FileMeta {
	id: string;
	owner_id: string;
	project_id?: string | null;
	filename: string;
	mime_type: string;
	size_bytes: number;
	hash_sha256?: string;
	ingestion_status?: IngestionStatus;
	ingestion_error?: string | null;
	page_count?: number | null;
	character_count?: number | null;
	created_at: string;
}

/**
 * One row of `GET /knowledge-bases/{kb_id}/files`. Mirrors `FileMeta`
 * (the canonical `File` shape) plus `attached_at` from the join row.
 * Drives the Knowledge surface's detail-page document list (Wave C of
 * the M1 frontend redesign).
 */
export interface KnowledgeBaseFile {
	id: string;
	owner_id: string;
	project_id?: string | null;
	filename: string;
	mime_type: string;
	size_bytes: number;
	hash_sha256: string;
	ingestion_status: IngestionStatus;
	ingestion_error?: string | null;
	page_count?: number | null;
	character_count?: number | null;
	created_at: string;
	attached_at: string;
}

// ----- Saved prompts (D7 / DE-013) -----

/**
 * Per-user saved prompt fragment. Lighter than a skill (no folder, no
 * frontmatter, no semver) — the in-chat reuse case for "the way I always
 * ask for an executive summary." Mirrors the ``SavedPrompt`` schema in
 * ``docs/api/backend-openapi.yaml``.
 */
export interface SavedPrompt {
	id: string;
	user_id: string;
	name: string;
	prompt_text: string;
	tags: string[];
	created_at: string;
	updated_at: string;
}

export interface SavedPromptCreate {
	name: string;
	prompt_text: string;
	tags?: string[];
}

export interface SavedPromptUpdate {
	name?: string;
	prompt_text?: string;
	tags?: string[];
}

// ----- User skills (D8 / ADR 0012) -----

/**
 * A DB-backed user- or team-scope skill. Shadows filesystem-canonical
 * built-ins (per ADR 0004) at slug collision when resolved for the
 * owning user's chats (user shadow) or for any team member's chats
 * (team shadow). The D8.1b resolver picks user > team > built-in.
 * Mirrors the ``UserSkill`` schema in ``docs/api/backend-openapi.yaml``.
 *
 * Exactly one of ``owner_user_id`` / ``owner_team_id`` is set (DB
 * CHECK ``ck_user_skills_scope_owner_consistency``); the other is
 * null.
 */
export interface UserSkill {
	id: string;
	scope: 'user' | 'team';
	owner_user_id: string | null;
	owner_team_id: string | null;
	slug: string;
	display_name: string;
	description: string;
	version: string;
	tags: string[];
	frontmatter_extra: Record<string, unknown>;
	body: string;
	/**
	 * Wave D.2 — leading-slash chat invocation alias
	 * (``^/[a-z0-9-]{1,32}$``). Null when unset.
	 */
	slash_alias: string | null;
	/**
	 * Wave D.2 — slug of the skill this row was forked from (built-in or
	 * user / team), set when the Skill Creator's "fork from existing" path
	 * spawned the row. Null for from-scratch creates.
	 */
	forked_from: string | null;
	archived_at: string | null;
	created_at: string;
	updated_at: string;
}

export interface UserSkillCreate {
	slug: string;
	display_name: string;
	description: string;
	body: string;
	version?: string;
	tags?: string[];
	frontmatter_extra?: Record<string, unknown>;
	/** D8.1b — defaults to 'user' on the server when omitted. */
	scope?: 'user' | 'team';
	/** Required when scope='team'; must be null/omitted when scope='user'. */
	owner_team_id?: string | null;
	/**
	 * Wave D.2 — leading-slash invocation alias; backend validates
	 * ``^/[a-z0-9-]{1,32}$``. Null/undefined means "no alias".
	 */
	slash_alias?: string | null;
	/**
	 * Wave D.2 — documentary slug of the source skill when this row was
	 * forked (built-in or user / team). Write-once at create time.
	 */
	forked_from?: string | null;
	/**
	 * Wave D.2 — capture-flow metadata: source AI message id when the
	 * skill was distilled from a chat message. Documentary; not persisted
	 * as a column — rides the create-time audit-log row.
	 */
	source_message_id?: string | null;
}

export interface UserSkillUpdate {
	display_name?: string;
	description?: string;
	body?: string;
	version?: string;
	tags?: string[];
	frontmatter_extra?: Record<string, unknown>;
}

// ----- Enhance Prompt (T6) -----

export interface EnhancePromptAttachedSkill {
	name: string;
	description?: string | null;
}

export interface EnhancePromptAttachedFile {
	file_id?: string | null;
	filename: string;
	mime_type?: string | null;
	description?: string | null;
}

export interface EnhancePromptRequest {
	raw_input: string;
	chat_id?: string | null;
	attached_skills?: EnhancePromptAttachedSkill[];
	attached_files?: EnhancePromptAttachedFile[];
	jurisdiction?: string | null;
	model?: string | null;
}

export interface EnhancePromptResponse {
	interaction_id: string;
	expansion_applied: boolean;
	expanded_prompt: string;
	reasoning: string[];
	skip_reason?: string | null;
	preview_to_user?: string;
	routed_inference_tier?: 1 | 2 | 3 | 4 | 5 | null;
	routed_provider?: string | null;
	routed_model?: string | null;
}

export interface EnhancePromptOutcomeUpdate {
	used?: boolean;
	edited_before_use?: boolean;
}

// ----- Admin usage -----

export type UsageGroupBy = 'user' | 'provider' | 'model' | 'tier' | 'day';

export interface UsageRow {
	group_key: string;
	request_count: number;
	tokens_in_sum: number;
	tokens_out_sum: number;
	cost_estimate_sum: number;
}

export interface UsageResponse {
	rows: UsageRow[];
	group_by: UsageGroupBy;
	total_request_count: number;
	total_tokens_in: number;
	total_tokens_out: number;
	total_cost_estimate: number;
}

export interface UsageQuery {
	group_by?: UsageGroupBy;
	date_from?: string;
	date_to?: string;
	user_id?: string;
	provider?: string;
	tier?: number;
}

// ----- Admin users -----

export interface AdminUserRow {
  id: string;
  email: string;
  display_name?: string | null;
  role: UserRole;
  is_admin: boolean;
  mfa_enabled: boolean;
  must_change_password: boolean;
  created_at: string;
  last_login_at?: string | null;
  deletion_scheduled_at?: string | null;
}

export interface AdminUserListResponse {
  users: AdminUserRow[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface AdminUserListQuery {
  role?: UserRole;
  email_q?: string;
  limit?: number;
  offset?: number;
}

// ----- Teams (D8.1a + D8.1c caller_role) -----

/**
 * Compact team shape returned by the listing endpoints. ``caller_role``
 * (D8.1c) is populated for user-facing ``GET /api/v1/teams`` responses
 * and null for operator-admin views where the admin isn't a member.
 */
export interface TeamSummary {
	id: string;
	slug: string;
	name: string;
	description: string | null;
	created_by_user_id: string;
	member_count: number;
	caller_role: 'admin' | 'member' | null;
	created_at: string;
	updated_at: string;
}

export interface TeamMember {
	user_id: string;
	email: string;
	display_name: string | null;
	role: 'admin' | 'member';
	added_by_user_id: string;
	created_at: string;
}

export interface Team extends TeamSummary {
	members: TeamMember[];
}

// ----- Skill autocomplete (Wave D.2 Task 2.5) -----

/**
 * One row in the ``GET /skills/autocomplete`` response. Lightweight by
 * design — the autocomplete dropdown needs slug + slash badge + a short
 * label, not the full skill body. ``slash_alias`` is null on built-ins
 * (slash invocation lives only on DB-backed user / team rows).
 */
export interface SkillAutocompleteItem {
	slug: string;
	slash_alias: string | null;
	title: string;
	description: string | null;
	scope: 'user' | 'team' | 'builtin';
	icon: string | null;
}

export interface SkillAutocompleteResponse {
	results: SkillAutocompleteItem[];
}

// ----- User-skill version history (Wave D.2 Task 2.6) -----

/**
 * One audit-log row projected onto the version-history view. The
 * ``details`` blob is the raw ``audit_log.details`` JSON column;
 * ``version`` is surfaced as a top-level convenience because every
 * create / update row carries it (extracted from
 * ``details.version`` / ``details.version_after``).
 */
export interface UserSkillVersion {
	timestamp: string;
	actor_user_id: string | null;
	actor_email: string | null;
	action: string;
	version: string | null;
	details: Record<string, unknown> | null;
}

export interface UserSkillVersionsResponse {
	items: UserSkillVersion[];
}
