/**
 * /api/v1/skills — list + detail.
 *
 * A skill's declared inputs come from `getInputs` (the api resolves them
 * from the frontmatter, top-level or under `lq_ai:`); the detail payload
 * carries only the raw frontmatter in `content_yaml`.
 */
import { apiRequest } from './client';
import type { Skill, SkillAutocompleteResponse, SkillInputs, SkillSummary } from '../types';

/** GET /api/v1/skills — summary list. */
export async function listSkills(scope?: 'builtin' | 'user' | 'team'): Promise<SkillSummary[]> {
	const qs = scope ? `?scope=${encodeURIComponent(scope)}` : '';
	return apiRequest<SkillSummary[]>(`/skills${qs}`);
}

/** GET /api/v1/skills/{name}/inputs — canonical input definitions resolved user > team > built-in. */
export async function getInputs(name: string): Promise<SkillInputs> {
	return apiRequest<SkillInputs>(`/skills/${encodeURIComponent(name)}/inputs`);
}

/**
 * GET /api/v1/skills/autocomplete?q=&limit= — Wave D.2 Task 2.5.
 *
 * Lightweight typeahead suggestions for the slash-invocation dropdown
 * and the Skill Creator's "fork from existing" picker. The backend ranks
 * results by slash-alias prefix > slug prefix > title-substring; this
 * client just forwards the query unchanged. ``limit`` defaults to 10
 * (the backend caps at 50).
 */
export async function autocompleteSkills(
	q: string,
	limit: number = 10
): Promise<SkillAutocompleteResponse> {
	const path = `/skills/autocomplete?q=${encodeURIComponent(q)}&limit=${limit}`;
	return apiRequest<SkillAutocompleteResponse>(path);
}

/** GET /api/v1/skills/{name} — full skill payload. */
export async function getSkill(name: string): Promise<Skill> {
	return apiRequest<Skill>(`/skills/${encodeURIComponent(name)}`);
}
