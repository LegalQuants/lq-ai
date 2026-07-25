/**
 * Pure helpers for the DE-263 admin community-skills page.
 *
 * Extracted out of `+page.svelte` so vitest can exercise them without a
 * SvelteKit runtime (the intake-bridges page-helpers convention). The
 * helpers cover:
 *
 *   - client-side catalog search across slug / title / description / tags
 *   - honest attestation labeling (display what the file declares; never
 *     claim attestation that isn't there — ADR 0027 §5)
 *   - short-sha rendering with the "unknown" degradation
 *   - the install-confirm dialog copy (includes the provenance ref that
 *     will be written to `forked_from`)
 *   - empty-catalog messaging (absent submodule is a hint, not an error)
 */

import type {
	CommunityCatalogResponse,
	CommunitySkillDetail,
	CommunitySkillSummary
} from '$lib/lq-ai/api/communitySkills';

/** Case-insensitive catalog filter across slug, title, description, tags. */
export function filterCatalog(
	items: CommunitySkillSummary[],
	query: string
): CommunitySkillSummary[] {
	const q = query.trim().toLowerCase();
	if (!q) return items;
	return items.filter(
		(item) =>
			item.slug.toLowerCase().includes(q) ||
			item.title.toLowerCase().includes(q) ||
			item.description.toLowerCase().includes(q) ||
			item.tags.some((tag) => tag.toLowerCase().includes(q))
	);
}

/**
 * Honest attestation label. Community skills are attested (or not) at
 * their source repo; we render exactly what the SKILL.md declares.
 */
export function attestationLabel(attestedBy: string | null): string {
	return attestedBy
		? `Attested at source repo by: ${attestedBy}`
		: 'No attestation declared in SKILL.md';
}

/** Render the submodule sha pin; degrades to "unknown" honestly. */
export function shortSha(sha: string | null): string {
	return sha ? sha.slice(0, 12) : 'unknown';
}

/** Confirm-dialog copy for the install action — names the provenance ref. */
export function installConfirmMessage(detail: CommunitySkillDetail): string {
	return (
		`Install community skill "${detail.title}" (${detail.slug})?\n\n` +
		`This creates an editable copy owned by you (provenance: ${detail.install_ref}). ` +
		`The copy does not auto-update when the community catalog moves. ` +
		attestationLabel(detail.attested_by)
	);
}

/**
 * Empty-state copy for the catalog list. Absent submodule → the
 * server's operator hint (the `git submodule update --init` remedy);
 * present-but-filtered → a search message; present-and-empty → hint too.
 */
export function catalogEmptyMessage(
	catalog: CommunityCatalogResponse | null,
	visibleCount: number,
	query: string
): string | null {
	if (catalog === null) return null;
	if (catalog.items.length === 0) {
		return catalog.source.operator_hint ?? 'The community catalog is empty.';
	}
	if (visibleCount === 0 && query.trim()) {
		return `No community skills match "${query.trim()}".`;
	}
	return null;
}

/** Install-button state for one row. */
export function installButtonState(
	item: CommunitySkillSummary,
	pendingSlug: string | null
): { label: string; disabled: boolean } {
	if (item.installed) return { label: 'Installed', disabled: true };
	if (pendingSlug === item.slug) return { label: 'Installing…', disabled: true };
	return { label: 'Install', disabled: pendingSlug !== null };
}
