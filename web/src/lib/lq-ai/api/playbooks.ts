/**
 * /api/v1/playbooks + /api/v1/playbook-executions — list / detail / execute /
 * poll helpers (M3-A4).
 *
 * Wraps the M3-A1/A2/A4 backend endpoints. Mirrors ``knowledgeBases.ts`` /
 * ``savedPrompts.ts``: uses ``apiRequest`` for auth-header attachment,
 * refresh-on-401, and structured error translation.
 *
 * Per the M3-A4 §5.1 decision, playbook CRUD (create / update / delete)
 * is deferred to M3-A6; only the four read + execute endpoints are
 * surfaced here.
 */
import { apiRequest } from './client';
import type { Playbook, PlaybookExecution, PlaybookExecutionCreate } from '../types';

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
