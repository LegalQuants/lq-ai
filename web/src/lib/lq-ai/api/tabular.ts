/**
 * /api/v1/tabular — preview / execute / list / detail / delete / cancel
 * helpers for the Tabular / Multi-Document Review surface (M3-C2 / M3-C3).
 *
 * Wraps the six endpoints in `api/app/api/tabular.py`. Mirrors
 * `playbooks.ts` exactly: uses `apiRequest` for auth-header attachment,
 * refresh-on-401, and structured error translation. The shapes come
 * from the backend Pydantic surface in `api/app/schemas/tabular.py`.
 */
import { apiRequest } from './client';
import type {
	TabularExecution,
	TabularExecutionCreate,
	TabularExecutionSummary,
	TabularPreviewCostRequest,
	TabularPreviewCostResponse
} from '../types';

/**
 * POST /api/v1/tabular/preview-cost — synchronous cost preview; no
 * execution row is created. Called by the wizard's Step 3 before
 * showing the confirmation modal (Decision C-5).
 */
export async function previewTabularCost(
	body: TabularPreviewCostRequest
): Promise<TabularPreviewCostResponse> {
	return apiRequest<TabularPreviewCostResponse>('/tabular/preview-cost', {
		method: 'POST',
		body: body as unknown as Record<string, unknown>
	});
}

/**
 * POST /api/v1/tabular/execute — kick off a tabular execution.
 * Returns 202 + the row at `status='pending'`. Poll
 * {@link getTabularExecution} until status reaches a terminal state
 * (`completed` / `failed` / `cancelled`).
 */
export async function executeTabular(
	body: TabularExecutionCreate
): Promise<TabularExecution> {
	return apiRequest<TabularExecution>('/tabular/execute', {
		method: 'POST',
		body: body as unknown as Record<string, unknown>
	});
}

/**
 * GET /api/v1/tabular/executions — list the caller's tabular
 * executions (recent-first, soft-deleted excluded). Returns a
 * paginated-on-the-backend slice as plain array.
 */
export async function listTabularExecutions(): Promise<TabularExecutionSummary[]> {
	return apiRequest<TabularExecutionSummary[]>('/tabular/executions');
}

/**
 * GET /api/v1/tabular/executions/{id} — full execution row including
 * the (potentially large) `results` payload once status is terminal.
 */
export async function getTabularExecution(executionId: string): Promise<TabularExecution> {
	return apiRequest<TabularExecution>(
		`/tabular/executions/${encodeURIComponent(executionId)}`
	);
}

/**
 * DELETE /api/v1/tabular/executions/{id} — soft-delete (sets
 * `deleted_at`). Already-deleted rows return 404.
 */
export async function deleteTabularExecution(executionId: string): Promise<void> {
	await apiRequest<void>(`/tabular/executions/${encodeURIComponent(executionId)}`, {
		method: 'DELETE'
	});
}

/**
 * POST /api/v1/tabular/executions/{id}/cancel — set status to
 * `cancelled`; the worker's per-cell loop honors this at the next
 * cell-iteration boundary. Already-terminal rows return 409.
 */
export async function cancelTabularExecution(
	executionId: string
): Promise<TabularExecution> {
	return apiRequest<TabularExecution>(
		`/tabular/executions/${encodeURIComponent(executionId)}/cancel`,
		{ method: 'POST' }
	);
}
