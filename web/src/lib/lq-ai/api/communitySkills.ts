/**
 * Admin community-skill installer API client — 3.8 / DE-263 (ADR 0027).
 *
 * Surface:
 *
 *   - GET  /api/v1/admin/community-skills                — catalog list
 *   - GET  /api/v1/admin/community-skills/{slug}         — full SKILL.md detail
 *   - POST /api/v1/admin/community-skills/{slug}/install — install as a
 *     user-scope copy owned by the installing admin
 *
 * The catalog is served FROM THE LOCAL `skills/community` submodule
 * checkout — never a network fetch (ADR 0027). All endpoints are
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
	tags: string[];
	jurisdiction: string | null;
	/** Verbatim frontmatter declaration; null == none declared in SKILL.md. */
	attested_by: string | null;
	/** Whether the calling admin already has a live user-scope row at this slug. */
	installed: boolean;
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
}

export async function listCommunitySkills(): Promise<CommunityCatalogResponse> {
	return apiRequest<CommunityCatalogResponse>('/admin/community-skills', { method: 'GET' });
}

export async function getCommunitySkill(slug: string): Promise<CommunitySkillDetail> {
	return apiRequest<CommunitySkillDetail>(`/admin/community-skills/${encodeURIComponent(slug)}`, {
		method: 'GET'
	});
}

export async function installCommunitySkill(slug: string): Promise<UserSkill> {
	return apiRequest<UserSkill>(`/admin/community-skills/${encodeURIComponent(slug)}/install`, {
		method: 'POST'
	});
}
