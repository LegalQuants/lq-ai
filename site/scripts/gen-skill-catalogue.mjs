/**
 * `/skills/catalogue/` — one row per first-party skill, built from each
 * `SKILL.md`'s own frontmatter.
 *
 * The catalogue is generated for the same reason the ADR index is: a
 * hand-maintained table of what ships drifts from what ships, and this one is
 * the page a lawyer uses to decide whether the work product they need exists.
 *
 * Two columns carry the site's honesty rules rather than data:
 *
 *  - **Attested by.** No first-party skill records an attestation in
 *    frontmatter — there is no field for it. The column says "not recorded in
 *    frontmatter" in every row rather than showing a blank, because a blank in
 *    an attestation column reads as "not attested", which is a different and
 *    more damaging claim. When the corpus starts carrying the field, the column
 *    fills in on its own and the note under the table disappears.
 *  - **Tier floor.** `lq_ai.minimum_inference_tier` where a skill declares one,
 *    blank where it does not. Blank means the skill sets no floor, not tier 1.
 *
 * A column that no frontmatter carries at all is omitted from the table, and
 * the note under it says which columns were dropped and why.
 */

import { table } from './lib/markdown.mjs';
import {
  NOT_RECORDED,
  SKILLS_DIR,
  attestationOf,
  jurisdictionOf,
  readSkills,
  tagsOf,
  titleOf,
} from './lib/skills.mjs';

export const id = 'gen-skill-catalogue';

const ROUTE = 'skills/catalogue.md';
const INTRO = 'skills/catalogue.intro.md';

export async function generate(ctx) {
  const skills = readSkills(ctx);
  const stamp = ctx.stamp([SKILLS_DIR], INTRO);

  if (skills.length === 0) {
    ctx.report({
      level: 'warn',
      page: ROUTE,
      line: 1,
      message: `no ${SKILLS_DIR}/*/SKILL.md found — the catalogue ships empty`,
    });
  }

  const anyAttestation = skills.some((skill) => attestationOf(skill));
  const anyTierFloor = skills.some(
    (skill) => typeof skill.lq.minimum_inference_tier === 'number'
  );

  const headers = ['Skill', 'Practice area', 'Jurisdiction', 'Version', 'Author', 'Attested by'];
  if (anyTierFloor) headers.push('Tier floor');

  const rows = skills.map((skill) => {
    const tags = tagsOf(skill);
    const row = [
      `[${titleOf(skill)}](${ctx.blob(skill.path, stamp.sha)})`,
      tags.length ? tags.map((tag) => `\`${tag}\``).join(' ') : '—',
      jurisdictionOf(skill) ?? '—',
      skill.lq.version ?? '—',
      skill.lq.author ?? '—',
      attestationOf(skill) ?? NOT_RECORDED,
    ];
    if (anyTierFloor) {
      row.push(
        typeof skill.lq.minimum_inference_tier === 'number'
          ? String(skill.lq.minimum_inference_tier)
          : ''
      );
    }
    return row;
  });

  const notes = [];
  if (!anyAttestation) {
    notes.push(
      `**No skill in \`${SKILLS_DIR}/\` records an attestation in its frontmatter as of the checked commit.** There is no frontmatter field for it in the loader's schema, so every row reads "${NOT_RECORDED}" rather than a blank that could be read as "unattested". What an attestation covers, and when it decays, is on [The attestation bar](${ctx.route('skills/attestation')}).`
    );
  }
  if (!anyTierFloor) {
    notes.push(
      'No skill declares `lq_ai.minimum_inference_tier`, so the tier-floor column is not rendered.'
    );
  }
  notes.push(
    `A dash means the skill's frontmatter does not carry that field. \`skill-creator\` carries no \`lq_ai:\` block at all, which is why most of its row is dashes.`
  );

  const body = [
    table(headers, rows),
    '',
    ...notes.map((note) => `${note}\n`),
    '## Next',
    '',
    `- [The attestation bar](${ctx.route('skills/attestation')})`,
    `- [Coverage by jurisdiction and practice area](${ctx.route('skills/coverage')})`,
    `- [Where skills live](${ctx.route('skills/where-skills-live')})`,
  ].join('\n');

  return [
    {
      relPath: ROUTE,
      intro: INTRO,
      stamp,
      frontmatter: {
        title: 'Skill catalogue',
        description: `Every first-party skill in ${SKILLS_DIR}/, with its practice area, jurisdiction, version and author, generated from each SKILL.md.`,
        audience: ['author', 'evaluator', 'agent'],
        sources: [SKILLS_DIR],
        sidebar: { order: 20 },
      },
      body,
    },
  ];
}
