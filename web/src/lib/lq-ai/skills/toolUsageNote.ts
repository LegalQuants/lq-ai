/** C5 (PR6d) — derive the non-gating skill-detail tool-usage note. */
export interface ToolUsageNote {
	uses: string[];
	warning: string | null;
}

export function toolUsageNote(
	toolUsage: string[] | null | undefined,
	unavailable: string[] | null | undefined
): ToolUsageNote {
	const uses = toolUsage ?? [];
	// `unavailable` null/undefined = undeterminable → no verdict; [] = all available.
	const missing = Array.isArray(unavailable) ? unavailable : [];
	const warning =
		missing.length > 0
			? `${missing.join(', ')} ${missing.length === 1 ? 'is' : 'are'} not configured in this deployment — ask your operator to enable ${missing.length === 1 ? 'it' : 'them'}.`
			: null;
	return { uses, warning };
}
