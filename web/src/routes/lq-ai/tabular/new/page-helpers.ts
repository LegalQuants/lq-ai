/**
 * Pure helpers for the Tabular Review wizard (`/lq-ai/tabular/new`).
 *
 * The Svelte +page.svelte holds rendering + imperative state; these
 * functions hold the deterministic state-machine + validation +
 * request-builder logic so the wizard's gating behaviour is tested
 * without spinning up a browser (matches the M3-A4 playbooks pattern).
 *
 * Constants:
 * - `TABULAR_MAX_DOCS` = 200 — Decision C-7's deployment cap.
 *   The backend enforces this too (LQ_AI_TABULAR_MAX_DOCS); the wizard
 *   surfaces it at the form level to avoid a server round-trip on
 *   obvious over-selection.
 * - `COST_CONFIRMATION_THRESHOLD_USD` = $1.00 — Decision C-5's gate.
 *   At or above this estimated cost, the operator must tick the
 *   confirmation checkbox before the wizard's final "Run" button arms.
 */
import type {
	TabularColumnSpec,
	TabularExecutionCreate,
	TabularPreviewCostRequest
} from '$lib/lq-ai/types';

export type WizardStep = 'documents' | 'columns' | 'preview' | 'confirm';

const STEP_ORDER: WizardStep[] = ['documents', 'columns', 'preview', 'confirm'];

export const TABULAR_MAX_DOCS = 200;
export const COST_CONFIRMATION_THRESHOLD_USD = 1.0;

/** Zero-indexed position of a step in the ordered wizard. */
export function stepIndex(step: WizardStep): number {
	return STEP_ORDER.indexOf(step);
}

/** Advance to the next step; the last step returns itself. */
export function nextStep(step: WizardStep): WizardStep {
	const i = stepIndex(step);
	return i < STEP_ORDER.length - 1 ? STEP_ORDER[i + 1] : step;
}

/** Retreat to the previous step; the first step returns itself. */
export function prevStep(step: WizardStep): WizardStep {
	const i = stepIndex(step);
	return i > 0 ? STEP_ORDER[i - 1] : step;
}

export function isFirstStep(step: WizardStep): boolean {
	return stepIndex(step) === 0;
}

export function isLastStep(step: WizardStep): boolean {
	return stepIndex(step) === STEP_ORDER.length - 1;
}

/**
 * Validate the documents step. Returns an operator-facing error string
 * OR `null` when the selection is valid.
 */
export function validateDocumentsStep(documentIds: string[]): string | null {
	if (documentIds.length === 0) {
		return 'Select at least one document.';
	}
	if (documentIds.length > TABULAR_MAX_DOCS) {
		return `Tabular runs are capped at ${TABULAR_MAX_DOCS} documents — split your selection or contact your admin to lift the cap.`;
	}
	return null;
}

interface ColumnsStepInput {
	skillName: string | null;
	columns: TabularColumnSpec[];
}

/**
 * Validate the columns step. Either a saved skill OR at least one
 * fully-populated ad-hoc column is required. Per Decision C-1 every
 * column has a name + query; duplicate column names break the grid's
 * header keying and are rejected before we round-trip to the server.
 */
export function validateColumnsStep(input: ColumnsStepInput): string | null {
	if (input.skillName && input.skillName.trim().length > 0) {
		return null;
	}
	if (input.columns.length === 0) {
		return 'Choose a skill or define at least one column.';
	}
	for (const col of input.columns) {
		if (!col.name.trim() || !col.query.trim()) {
			return 'Every column needs a name and query.';
		}
	}
	const seen = new Set<string>();
	for (const col of input.columns) {
		const key = col.name.trim().toLowerCase();
		if (seen.has(key)) {
			return `Duplicate column name: ${col.name.trim()}.`;
		}
		seen.add(key);
	}
	return null;
}

/**
 * Decision C-5: gate the final "Run" button behind a confirmation
 * checkbox at or above $1.00 estimated cost. Below that, the operator
 * sees no friction. Defensive on non-numeric strings — pre-fetch /
 * fetch-failure states render as no-gate.
 */
export function requiresCostConfirmation(estimatedCostUsd: string): boolean {
	const n = Number(estimatedCostUsd);
	if (!Number.isFinite(n)) return false;
	return n >= COST_CONFIRMATION_THRESHOLD_USD;
}

interface RequestBuilderInput {
	documentIds: string[];
	skillName: string | null;
	columns: TabularColumnSpec[];
}

/**
 * Build the body for `POST /api/v1/tabular/preview-cost`. Backend
 * accepts either `skill_name` OR `columns`; we omit the unused side
 * so the wire payload stays tight.
 */
export function buildPreviewRequest(input: RequestBuilderInput): TabularPreviewCostRequest {
	if (input.skillName && input.skillName.trim().length > 0) {
		return {
			document_ids: input.documentIds,
			skill_name: input.skillName
		};
	}
	return {
		document_ids: input.documentIds,
		columns: input.columns
	};
}

interface ExecuteBuilderInput extends RequestBuilderInput {
	confirmedCostUsd: string;
}

/**
 * Build the body for `POST /api/v1/tabular/execute`. The
 * `confirmed_cost_usd` is the echo of the preview response so the
 * server can persist an audit trail of the operator confirming a
 * specific cost ceiling before kickoff.
 */
export function buildExecuteRequest(input: ExecuteBuilderInput): TabularExecutionCreate {
	if (input.skillName && input.skillName.trim().length > 0) {
		return {
			document_ids: input.documentIds,
			skill_name: input.skillName,
			confirmed_cost_usd: input.confirmedCostUsd
		};
	}
	return {
		document_ids: input.documentIds,
		columns: input.columns,
		confirmed_cost_usd: input.confirmedCostUsd
	};
}
