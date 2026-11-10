/**
 * Reading each skill folder's `SKILL.md` frontmatter — shared by the catalogue and the
 * coverage index so the two pages cannot disagree about what is shipped.
 *
 * The corpus is not uniform, and the generators must not pretend it is:
 *
 *  - `skills/skill-creator/SKILL.md` carries **no `lq_ai:` block at all**. Its
 *    row is mostly empty, and empty is the correct rendering — the alternative
 *    is inventing a version and a jurisdiction for a skill that declares
 *    neither.
 *  - `jurisdiction` is free text by design (`us`, `US-default`, `agnostic`,
 *    `regime-aware`, `regime-dependent`), which the loader's own schema notes.
 *    Nothing here normalises it; `docs/site/_data/coverage-notes.yaml` groups
 *    the raw values explicitly, under `match:`, so the grouping is a reviewable
 *    editorial decision rather than a regex in a build script.
 *  - **No skill records an attestation in frontmatter.** There is no field for
 *    it. The catalogue therefore says "not recorded in frontmatter" rather than
 *    leaving a blank that reads as "unattested", and the intro says so too.
 *
 * `skills/playbooks/` is not a skill (it holds playbook YAML) and
 * `skills/community/` is the lq-skills submodule mount point, empty in a plain
 * checkout. Neither has a `SKILL.md`, so both fall out naturally — but they are
 * named here so the next reader does not go looking for them.
 */

import matter from 'gray-matter';

export const SKILLS_DIR = 'skills';

/** The string every "the frontmatter has no field for this" cell carries. */
export const NOT_RECORDED = 'not recorded in frontmatter';

/**
 * Every first-party skill, sorted by folder name.
 *
 * @param {{ list: (dir: string) => string[], read: (path: string) => string | null }} ctx
 * @returns {{ slug: string, path: string, name: string, description: string, lq: object, raw: object }[]}
 */
export function readSkills(ctx) {
  const skills = [];
  for (const slug of ctx.list(SKILLS_DIR)) {
    const relPath = `${SKILLS_DIR}/${slug}/SKILL.md`;
    const raw = ctx.read(relPath);
    if (raw == null) continue;
    let data;
    try {
      data = matter(raw).data ?? {};
    } catch (error) {
      ctx.report?.({
        level: 'warn',
        page: 'skills/catalogue.md',
        line: 1,
        message: `${relPath} frontmatter does not parse (${error.message}) — skill omitted`,
      });
      continue;
    }
    skills.push({
      slug,
      path: relPath,
      name: typeof data.name === 'string' ? data.name : slug,
      description: typeof data.description === 'string' ? data.description : '',
      lq: data.lq_ai && typeof data.lq_ai === 'object' ? data.lq_ai : {},
      raw: data,
    });
  }
  return skills.sort((a, b) => a.slug.localeCompare(b.slug));
}

/** `lq_ai.tags`, always an array of trimmed strings. */
export const tagsOf = (skill) =>
  (Array.isArray(skill.lq.tags) ? skill.lq.tags : [])
    .map((tag) => String(tag).trim())
    .filter(Boolean);

/** `lq_ai.jurisdiction` exactly as the file states it, or `undefined`. */
export const jurisdictionOf = (skill) =>
  typeof skill.lq.jurisdiction === 'string' && skill.lq.jurisdiction.trim()
    ? skill.lq.jurisdiction.trim()
    : undefined;

/** The display title, falling back to the folder slug rather than inventing one. */
export const titleOf = (skill) =>
  typeof skill.lq.title === 'string' && skill.lq.title.trim() ? skill.lq.title.trim() : skill.slug;

/**
 * Whether any skill in the corpus records an attestation.
 *
 * Checked rather than assumed: the day someone adds the field, the column stops
 * saying "not recorded" on its own, with no edit to this script.
 */
export const ATTESTATION_FIELDS = ['attested_by', 'attestedBy', 'attestation', 'attested'];

export function attestationOf(skill) {
  for (const field of ATTESTATION_FIELDS) {
    const value = skill.lq[field] ?? skill.raw[field];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (value && typeof value === 'object') {
      const by = value.by ?? value.name ?? value.attorney;
      if (typeof by === 'string' && by.trim()) return by.trim();
    }
  }
  return undefined;
}

/** A URL-safe slug for a free-text facet value. */
export const slugify = (value) =>
  String(value)
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'unspecified';
