/**
 * /api/v1/tabular — preview / execute / list / detail / delete / cancel
 * helpers for the Tabular / Multi-Document Review surface (M3-C2 / M3-C3).
 *
 * Wraps the six endpoints in `api/app/api/tabular.py`. Mirrors
 * `playbooks.ts` exactly: uses `apiRequest` for auth-header attachment,
 * refresh-on-401, and structured error translation. The shapes come
 * from the backend Pydantic surface in `api/app/schemas/tabular.py`.
 */
import { getAccessToken } from '../auth/store';
import { apiRequest, LQ_AI_API_BASE_URL, LQAIApiError } from './client';
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

/**
 * GET /api/v1/tabular/executions/{id}/export?format=xlsx|csv — M3-C4a.
 *
 * Returns the grid as a Blob plus the server-suggested filename (from
 * the Content-Disposition header). Caller is responsible for triggering
 * the browser download — typical pattern:
 *
 * ```ts
 * const { blob, filename } = await exportTabularExecution(id, 'xlsx');
 * const url = URL.createObjectURL(blob);
 * const a = document.createElement('a');
 * a.href = url; a.download = filename;
 * a.click(); URL.revokeObjectURL(url);
 * ```
 *
 * Uses a focused `fetch` rather than `apiRequest` because the response
 * is binary (XLSX) or text-CSV, not JSON. Auth header attachment is
 * inlined; refresh-on-401 is deferred — operators on an expired token
 * see the export fail and re-login (acceptable for a long-running
 * result-view session that has likely already prompted on the polling
 * detail request).
 */
export async function exportTabularExecution(
	executionId: string,
	format: 'xlsx' | 'csv'
): Promise<{ blob: Blob; filename: string }> {
	const path = `/tabular/executions/${encodeURIComponent(executionId)}/export?format=${format}`;
	const token = getAccessToken();
	const res = await fetch(`${LQ_AI_API_BASE_URL}${path}`, {
		method: 'GET',
		headers: token ? { Authorization: `Bearer ${token}` } : undefined
	});
	if (!res.ok) {
		let detail: string | undefined;
		try {
			const body: unknown = await res.json();
			if (body && typeof body === 'object' && 'detail' in body) {
				const d = (body as { detail?: unknown }).detail;
				if (typeof d === 'string') detail = d;
			}
		} catch {
			// Non-JSON error body (likely an HTML error page); fall through
			// to the generic message.
		}
		throw new LQAIApiError(
			res.status,
			'export_failed',
			detail ?? `Tabular export failed (HTTP ${res.status}).`
		);
	}
	const blob = await res.blob();
	const cd = res.headers.get('Content-Disposition') ?? '';
	const m = /filename="([^"]+)"/.exec(cd);
	const filename = m ? m[1] : `tabular-${executionId}.${format}`;
	return { blob, filename };
}
