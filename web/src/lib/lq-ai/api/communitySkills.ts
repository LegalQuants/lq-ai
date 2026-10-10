/**
 * Admin community-skill installer API client — 3.8 / DE-263 (ADR 0041).
 *
 * Surface:
 *
 *   - GET  /api/v1/admin/community-skills                — catalog list
 *   - GET  /api/v1/admin/community-skills/{slug}         — full SKILL.md detail
 *   - POST /api/v1/admin/community-skills/{slug}/install — install as a
 *     reviewed copy for a selected team or the installing admin
 *
 * The catalog is served FROM THE LOCAL `skills/community` submodule
 * checkout — never a network fetch (ADR 0041). All endpoints are
 * admin-gated server-side; non-admin users get 403 which the page
 * renders inline. `attested_by` is the verbatim frontmatter declaration
 * or null ("none declared") — attestation is displayed, never
 * synthesized.
 */
import { apiRequest } from './client';
import type { UserSkill } from '../types';

export interface CommunityCatalogSource {
	path: string;
	/** Submodule HEAD commit, or null when unresolvable ("unknown"). */
	sha: string | null;
	repository: string | null;
	metadata_source: string;
	submodule_present: boolean;
	/** Set when the catalog is absent/empty — names the git submodule remedy. */
	operator_hint: string | null;
}

export interface CommunitySkillSummary {
	slug: string;
	title: string;
	description: string;
	version: string;
	author: string | null;
	license: string | null;
	tags: string[];
	jurisdiction: string | null;
	/** Verbatim frontmatter declaration; null == none declared in SKILL.md. */
	attested_by: string | null;
	/** Whether the selected receiving scope already holds this slug. */
	installed: boolean;
	installed_for_me: boolean;
	body_preview: string;
}

export interface CommunityCatalogResponse {
	items: CommunitySkillSummary[];
	source: CommunityCatalogSource;
	/** Per-skill parse failures, verbatim — broken entries stay visible. */
	load_errors: string[];
}

export interface CommunitySkillDetail extends CommunitySkillSummary {
	output_format: string | null;
	minimum_inference_tier: number | null;
	content_yaml: string;
	content_md: string;
	/** The forked_from provenance string an install would write now. */
	install_ref: string;
	provenance: CommunityProvenance;
}

export interface CommunityProvenance {
	content_hash: string;
	review_hash: string;
	hash_contract: string;
	source: {
		repository: string | null;
		revision: string | null;
		skill_path: string;
		metadata_source: string;
		revision_content_verified: boolean;
		declared_author: string | null;
		declared_attestation: string | null;
		declared_license: string | null;
	};
}

function targetQuery(teamId?: string): string {
	return teamId ? `?scope=team&owner_team_id=${encodeURIComponent(teamId)}` : '';
}

export async function listCommunitySkills(teamId?: string): Promise<CommunityCatalogResponse> {
	return apiRequest<CommunityCatalogResponse>(`/admin/community-skills${targetQuery(teamId)}`, {
		method: 'GET'
	});
}

export async function getCommunitySkill(
	slug: string,
	teamId?: string
): Promise<CommunitySkillDetail> {
	return apiRequest<CommunitySkillDetail>(
		`/admin/community-skills/${encodeURIComponent(slug)}${targetQuery(teamId)}`,
		{
			method: 'GET'
		}
	);
}

export async function installCommunitySkill(
	slug: string,
	expectedReviewHash: string,
	teamId?: string
): Promise<UserSkill> {
	return apiRequest<UserSkill>(`/admin/community-skills/${encodeURIComponent(slug)}/install`, {
		method: 'POST',
		body: {
			scope: teamId ? 'team' : 'user',
			owner_team_id: teamId ?? null,
			expected_review_hash: expectedReviewHash
		}
	});
}
