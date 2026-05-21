/**
 * /api/v1/playbooks + /api/v1/playbook-executions — list / detail / execute /
 * poll helpers (M3-A4) + CRUD + Easy Playbook wizard (M3-A6).
 *
 * Wraps the M3-A1/A2/A4/A6 backend endpoints. Mirrors ``knowledgeBases.ts`` /
 * ``savedPrompts.ts``: uses ``apiRequest`` for auth-header attachment,
 * refresh-on-401, and structured error translation.
 */
import { apiRequest } from './client';
import type {
	Playbook,
	PlaybookCreate,
	PlaybookUpdate,
	PlaybookExecution,
	PlaybookExecutionCreate,
	EasyPlaybookGeneration,
	EasyPlaybookGenerationCreate
} from '../types';

/**
 * GET /api/v1/playbooks — list visible playbooks. Positions are NOT
 * inlined; call {@link getPlaybook} for the full position list.
 */
export async function listPlaybooks(): Promise<Playbook[]> {
	return apiRequest<Playbook[]>('/playbooks');
}

/**
 * GET /api/v1/playbooks/{id} — playbook header + full position list.
 */
export async function getPlaybook(playbookId: string): Promise<Playbook> {
	return apiRequest<Playbook>(`/playbooks/${encodeURIComponent(playbookId)}`);
}

/**
 * POST /api/v1/playbooks/{id}/execute — kick off a playbook against a
 * target document. Returns 202 + a {@link PlaybookExecution} at status
 * 'pending'. Poll {@link getPlaybookExecution} until the status is
 * terminal ('completed' or 'error').
 */
export async function executePlaybook(
	playbookId: string,
	body: PlaybookExecutionCreate
): Promise<PlaybookExecution> {
	return apiRequest<PlaybookExecution>(`/playbooks/${encodeURIComponent(playbookId)}/execute`, {
		method: 'POST',
		body
	});
}

/**
 * GET /api/v1/playbook-executions/{id} — poll the current state of a
 * playbook execution.
 */
export async function getPlaybookExecution(executionId: string): Promise<PlaybookExecution> {
	return apiRequest<PlaybookExecution>(`/playbook-executions/${encodeURIComponent(executionId)}`);
}

// ---------------------------------------------------------------------------
// M3-A6 — Playbook CRUD + Easy Playbook wizard
// ---------------------------------------------------------------------------

/**
 * POST /api/v1/playbooks — create a new playbook owned by the caller.
 * Built-ins (`created_by IS NULL`) can never be minted through this
 * endpoint; the server unconditionally sets `created_by` to the caller.
 */
export async function createPlaybook(body: PlaybookCreate): Promise<Playbook> {
	return apiRequest<Playbook>('/playbooks', {
		method: 'POST',
		body: body as unknown as Record<string, unknown>
	});
}

/**
 * PATCH /api/v1/playbooks/{id} — update a playbook. All fields optional.
 * If `positions` is supplied, the server atomically replaces the entire
 * positions list. Built-ins are 403 (operators fork built-ins, never
 * edit them in place).
 */
export async function updatePlaybook(
	playbookId: string,
	body: PlaybookUpdate
): Promise<Playbook> {
	return apiRequest<Playbook>(`/playbooks/${encodeURIComponent(playbookId)}`, {
		method: 'PATCH',
		body: body as unknown as Record<string, unknown>
	});
}

/**
 * DELETE /api/v1/playbooks/{id} — soft-delete a playbook. Built-ins
 * 403; non-built-ins require admin OR ownership.
 */
export async function deletePlaybook(playbookId: string): Promise<void> {
	await apiRequest<void>(`/playbooks/${encodeURIComponent(playbookId)}`, {
		method: 'DELETE'
	});
}

/**
 * POST /api/v1/playbooks/easy — kick off an Easy Playbook generation
 * against the supplied document corpus. Returns 202 + the generation
 * row at status `pending`; the wizard's Step 2 polls
 * `getEasyPlaybookGeneration` until status reaches a terminal value.
 */
export async function startEasyPlaybookGeneration(
	body: EasyPlaybookGenerationCreate
): Promise<EasyPlaybookGeneration> {
	return apiRequest<EasyPlaybookGeneration>('/playbooks/easy', {
		method: 'POST',
		body: body as unknown as Record<string, unknown>
	});
}

/**
 * GET /api/v1/playbooks/easy/{generation_id} — poll the current state
 * of an Easy Playbook generation row. When `status='completed'`,
 * `draft_playbook` carries the assembled `PlaybookCreate` shape.
 */
export async function getEasyPlaybookGeneration(
	generationId: string
): Promise<EasyPlaybookGeneration> {
	return apiRequest<EasyPlaybookGeneration>(
		`/playbooks/easy/${encodeURIComponent(generationId)}`
	);
}
