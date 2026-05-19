/**
 * Pure helpers for the `/lq-ai/playbooks` list page, extracted to a sibling
 * `.ts` file so vitest can exercise them without the svelte transformer
 * (matching the pattern in the M3-A4 plan, Task 5).
 */
import type { Playbook } from '$lib/lq-ai/types';

/** Returns a new array sorted case-insensitively by playbook name. */
export function sortPlaybooksByName(playbooks: Playbook[]): Playbook[] {
	return [...playbooks].sort((a, b) =>
		a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
	);
}

/** Prefix a version string with "v"; empty input passes through. */
export function formatVersion(version: string): string {
	if (!version) return '';
	return `v${version}`;
}
