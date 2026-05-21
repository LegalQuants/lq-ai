/**
 * Pure helpers for the Easy Playbook wizard (`/lq-ai/playbooks/easy`).
 *
 * Kept in a sibling `.ts` file so vitest can exercise them without the
 * svelte transformer (matching the M3-A4 `playbooks/page-helpers.ts`
 * pattern). The +page.svelte holds the rendering + the imperative state
 * machine; these functions hold the deterministic decisions.
 */
import type {
	EasyPlaybookGeneration,
	EasyPlaybookGenerationStatus,
	FileMeta
} from '$lib/lq-ai/types';

export type WizardStep = 'upload' | 'progress' | 'review' | 'approve';

/** Generation lifecycle has reached a state the worker won't change. */
export function isTerminalGenerationStatus(status: EasyPlaybookGenerationStatus): boolean {
	return status === 'completed' || status === 'error';
}

/**
 * True when every uploaded file has a `document_id` (the C5 parse
 * pipeline has produced a documents row for it).
 */
export function allDocumentsReady(files: FileMeta[]): boolean {
	if (files.length === 0) return false;
	return files.every((f) => typeof f.document_id === 'string' && f.document_id.length > 0);
}

/** Collect non-null `document_id` values across the uploaded files. */
export function collectReadyDocumentIds(files: FileMeta[]): string[] {
	const out: string[] = [];
	for (const f of files) {
		if (typeof f.document_id === 'string' && f.document_id.length > 0) {
			out.push(f.document_id);
		}
	}
	return out;
}

/**
 * Which wizard step to render given the current generation row.
 *
 * - `pending` / `running` → stay on `progress`.
 * - `completed` → advance to `review` (the inline editor binds to
 *   `draft_playbook`).
 * - `error` → stay on `progress`; the caller surfaces `error_message`
 *   from the row and shows a retry affordance. (We don't return a
 *   distinct "error" step because the progress UI is the natural place
 *   to render either the spinner or the error + retry button.)
 */
export function nextStepFromGeneration(generation: EasyPlaybookGeneration): WizardStep {
	if (generation.status === 'completed') return 'review';
	return 'progress';
}

/**
 * Validate the upload-step inputs. Returns an operator-facing error
 * string OR `null` when the form is ready to submit.
 */
export function validateUploadStep(args: {
	files: FileMeta[];
	contract_type: string;
}): string | null {
	if (args.files.length === 0) {
		return 'Upload at least one contract before generating a playbook.';
	}
	if (!args.contract_type.trim()) {
		return 'Pick a contract type before generating a playbook.';
	}
	return null;
}

/**
 * Default name to suggest when the operator hasn't picked one. Mirrors
 * the backend's `EasyPlaybookGenerationCreate.name` fallback so the
 * pre-filled value matches what the worker would otherwise assign.
 */
export function defaultPlaybookName(contract_type: string): string {
	const t = contract_type.trim();
	if (!t) return 'Generated Playbook';
	return `Generated ${t} Playbook`;
}
