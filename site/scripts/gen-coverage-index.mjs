/**
 * `/skills/coverage/` and one page per jurisdiction and per practice area.
 *
 * The question this answers is "is my jurisdiction / my practice area covered?"
 * — and the answer is worth almost nothing without the scope note beside it. A
 * tag is not a coverage claim: `case-law-research` carries the `litigation`
 * tag, and litigation is explicitly out of scope in the PRD. A page that showed
 * the tag and not the note would answer the reader's question wrongly by
 * omission.
 *
 * So the facets come from frontmatter (`lq_ai.jurisdiction`, `lq_ai.tags`) and
 * the meaning comes from `docs/site/_data/coverage-notes.yaml`, which a writer
 * maintains with a canonical source per note. Where a facet has no note, the
 * page says the entry reflects frontmatter only — it never fills the gap.
 *
 * Two shapes of the notes file are accepted, because the schema in the build
 * brief and the file a writer actually produced differ: a **list** of
 * `{id, label, match, note, source}` (what the repository carries, and the
 * better shape — `match:` makes the grouping of free-text frontmatter values an
 * explicit editorial decision) and a **map** of
 * `id: {name, scope_notes, sources, contribution_route}`. Both are read; the
 * list form is preferred. The file's absence is tolerated and visible.
 */

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

import YAML from 'yaml';

import { table } from './lib/markdown.mjs';
import {
  NOT_RECORDED,
  SKILLS_DIR,
  attestationOf,
  jurisdictionOf,
  readSkills,
  slugify,
  tagsOf,
  titleOf,
} from './lib/skills.mjs';

export const id = 'gen-coverage-index';

const NOTES_FILE = '_data/coverage-notes.yaml';
const NOTES_SOURCE = `docs/site/${NOTES_FILE}`;
const INTRO = 'skills/coverage.intro.md';

const FACETS = [
  { kind: 'jurisdiction', dir: 'jurisdiction', label: 'Jurisdiction', plural: 'Jurisdictions' },
  { kind: 'practice-area', dir: 'practice-area', label: 'Practice area', plural: 'Practice areas' },
];

/** Normalise either notes shape into `{ id, label, match: Set, notes: [], sources: [] }`. */
function readNotes(docsSiteDir, report) {
  const file = path.join(docsSiteDir, NOTES_FILE);
  const empty = { jurisdictions: [], practiceAreas: [], overrides: new Map(), route: undefined };
  if (!existsSync(file)) {
    report({
      level: 'warn',
      page: 'skills/coverage/index.md',
      line: 1,
      message: `${NOTES_SOURCE} is not in the repository — every facet renders "no scope notes yet"`,
    });
    return empty;
  }

  let data;
  try {
    data = YAML.parse(readFileSync(file, 'utf8')) ?? {};
  } catch (error) {
    report({
      level: 'error',
      page: 'skills/coverage/index.md',
      line: 1,
      message: `${NOTES_SOURCE} does not parse: ${error.message}`,
    });
    return empty;
  }

  const asList = (block) => {
    if (Array.isArray(block)) {
      return block.map((entry) => ({
        id: String(entry.id ?? entry.label ?? ''),
        label: entry.label ?? entry.name ?? entry.id,
        match: new Set(
          (Array.isArray(entry.match) ? entry.match : [entry.id]).filter(Boolean).map(String)
        ),
        notes: [entry.note, ...(Array.isArray(entry.scope_notes) ? entry.scope_notes : [])].filter(
          Boolean
        ),
        sources: toArray(entry.source ?? entry.sources),
        contributionRoute: entry.contribution_route,
      }));
    }
    if (block && typeof block === 'object') {
      return Object.entries(block).map(([key, entry]) => ({
        id: key,
        label: entry?.name ?? entry?.label ?? key,
        match: new Set([key, ...(Array.isArray(entry?.match) ? entry.match : [])].map(String)),
        notes: [
          ...(Array.isArray(entry?.scope_notes) ? entry.scope_notes : []),
          entry?.note,
        ].filter(Boolean),
        sources: toArray(entry?.sources ?? entry?.source),
        contributionRoute: entry?.contribution_route,
      }));
    }
    return [];
  };

  const overrides = new Map();
  for (const entry of Array.isArray(data.skill_overrides) ? data.skill_overrides : []) {
    if (entry?.slug) {
      overrides.set(String(entry.slug), {
        notes: [entry.note].filter(Boolean),
        sources: toArray(entry.source ?? entry.sources),
      });
    }
  }

  return {
    jurisdictions: asList(data.jurisdictions),
    practiceAreas: asList(data.practice_areas ?? data.practiceAreas),
    overrides,
    route: data.contribution_route
      ? {
          notes: toArray(data.contribution_route.note ?? data.contribution_route.notes),
          sources: toArray(data.contribution_route.source ?? data.contribution_route.sources),
        }
      : undefined,
  };
}

const toArray = (value) =>
  value == null ? [] : (Array.isArray(value) ? value : [value]).map(String).filter(Boolean);

/**
 * Bucket every skill onto the declared facets.
 *
 * `createUndeclared` is the difference between the two facets, and it is a
 * judgement worth stating. **Jurisdiction** is one value per skill, from a small
 * closed-ish vocabulary, so a value nobody has written a note for still deserves
 * its own page — that page is exactly where the missing note shows up.
 * **Tags** are not practice areas: the corpus carries forty of them
 * (`tabular`, `courtlistener`, `productivity`), and giving each a page would put
 * forty entries in the sidebar and imply forty practice areas the project does
 * not claim to cover. Which tags constitute a practice area is the editorial
 * decision recorded under `match:` in the notes file. Ungrouped tags are listed
 * on the index by name, so nothing is hidden — they just are not pages.
 */
function buildFacets(declared, skills, valuesOf, { createUndeclared }) {
  const facets = declared.map((entry) => ({ ...entry, skills: [], declared: true }));
  const byValue = new Map();
  for (const facet of facets) {
    for (const value of facet.match) byValue.set(value, facet);
  }

  const ungrouped = new Map();

  for (const skill of skills) {
    for (const value of valuesOf(skill)) {
      let facet = byValue.get(value);
      if (!facet) {
        if (!createUndeclared) {
          if (!ungrouped.has(value)) ungrouped.set(value, []);
          ungrouped.get(value).push(skill);
          continue;
        }
        facet = {
          id: slugify(value),
          label: value,
          match: new Set([value]),
          notes: [],
          sources: [],
          skills: [],
          declared: false,
        };
        facets.push(facet);
        byValue.set(value, facet);
      }
      if (!facet.skills.includes(skill)) facet.skills.push(skill);
    }
  }

  return {
    facets: facets.map((facet) => ({ ...facet, slug: slugify(facet.id || facet.label) })),
    ungrouped,
  };
}

function facetPage(ctx, { facet, config, stamp, overrides }) {
  const rows = facet.skills.map((skill) => [
    `[${titleOf(skill)}](${ctx.blob(skill.path, stamp.sha)})`,
    jurisdictionOf(skill) ?? '—',
    tagsOf(skill).length ? tagsOf(skill).map((tag) => `\`${tag}\``).join(' ') : '—',
    attestationOf(skill) ?? `attestation ${NOT_RECORDED}`,
  ]);

  const body = [
    facet.skills.length
      ? `${facet.skills.length} first-party skill${facet.skills.length === 1 ? '' : 's'} carr${
          facet.skills.length === 1 ? 'ies' : 'y'
        } this ${config.label.toLowerCase()} in its frontmatter.`
      : `**No first-party skill carries this ${config.label.toLowerCase()} as of the checked commit.** That is a gap in coverage, not a statement that the area is out of scope — read the scope note below, then the contribution route.`,
    '',
    ...(rows.length
      ? [table(['Skill', 'Jurisdiction', 'Tags', 'Attested by'], rows), '']
      : []),
    '## Scope note',
    '',
    ...(facet.notes.length
      ? facet.notes.map((note) => `${String(note).trim()}\n`)
      : [
          `No scope note is recorded for this ${config.label.toLowerCase()} in \`${NOTES_SOURCE}\` as of the checked commit. This entry reflects skill frontmatter only, and should be read as unverified against the wider canon.\n`,
        ]),
    ...(facet.sources.length
      ? [
          'Checked against:',
          '',
          ...facet.sources.map((source) => `- ${sourceLink(ctx, source, stamp.sha)}`),
          '',
        ]
      : []),
    ...facet.skills
      .filter((skill) => overrides.has(skill.slug))
      .flatMap((skill) => {
        const override = overrides.get(skill.slug);
        return [
          `**${titleOf(skill)}.** ${override.notes.join(' ')}`,
          ...(override.sources.length
            ? [
                '',
                override.sources
                  .map((source) => sourceLink(ctx, source, stamp.sha))
                  .join(' · '),
              ]
            : []),
          '',
        ];
      }),
    // The contribution route is one paragraph of canon, and repeating it on
    // every facet page would put eleven copies of it on the site and in
    // `llms-full.txt`. It is stated once, on the index, and pointed at here.
    '## Contributing coverage here',
    '',
    `Coverage for a jurisdiction or practice area is contributed, not requested. The route — and what to do when the area is one the PRD excludes outright — is on the [coverage index](${ctx.route('skills/coverage')}#contributing-coverage), with the canonical files it traces to.`,
    '',
    '## Next',
    '',
    `- [Coverage index](${ctx.route('skills/coverage')})`,
    `- [Skill catalogue](${ctx.route('skills/catalogue')})`,
    `- [Where skills live](${ctx.route('skills/where-skills-live')})`,
  ].join('\n');

  return {
    relPath: `skills/coverage/${config.dir}/${facet.slug}.md`,
    stamp,
    frontmatter: {
      title: `${facet.label}`,
      description: `Which first-party skills declare ${facet.label} in their frontmatter, and what "covered" actually means for it.`,
      audience: ['author', 'evaluator'],
      sources: [SKILLS_DIR, NOTES_SOURCE],
      sidebar: { order: facet.skills.length ? 10 : 20 },
    },
    body,
  };
}

/** A `docs/PRD.md#anchor` source rendered as a pinned link. */
function sourceLink(ctx, source, sha) {
  const [file, anchor] = String(source).split('#');
  const url = ctx.blob(file, sha) + (anchor ? `#${anchor}` : '');
  return `[\`${source}\`](${url})`;
}

export async function generate(ctx) {
  const skills = readSkills(ctx);
  const notes = readNotes(ctx.docsSiteDir, ctx.report);
  const stamp = ctx.stamp([SKILLS_DIR, NOTES_SOURCE], INTRO);

  const { facets: jurisdictions } = buildFacets(
    notes.jurisdictions,
    skills,
    (skill) => {
      const value = jurisdictionOf(skill);
      return value ? [value] : [];
    },
    { createUndeclared: true }
  );
  const { facets: practiceAreas, ungrouped } = buildFacets(notes.practiceAreas, skills, tagsOf, {
    createUndeclared: false,
  });

  const pages = [];
  for (const config of FACETS) {
    const facets = config.kind === 'jurisdiction' ? jurisdictions : practiceAreas;
    for (const facet of facets) {
      pages.push(
        facetPage(ctx, { facet, config, stamp, overrides: notes.overrides })
      );
    }
  }

  // --- the index -------------------------------------------------------------
  const facetTable = (facets, config) =>
    table(
      [config.label, 'Skills', 'Scope note'],
      facets
        .slice()
        .sort((a, b) => b.skills.length - a.skills.length || a.label.localeCompare(b.label))
        .map((facet) => [
          `[${facet.label}](${ctx.route(`skills/coverage/${config.dir}/${facet.slug}`)})`,
          facet.skills.length ? String(facet.skills.length) : 'none',
          facet.notes.length ? 'yes' : 'no scope notes yet',
        ])
    );

  const gaps = practiceAreas.filter((facet) => facet.skills.length === 0);
  const jurisdictionGaps = jurisdictions.filter((facet) => facet.skills.length === 0);
  const unannotated = [...jurisdictions, ...practiceAreas].filter((facet) => !facet.notes.length);

  const body = [
    `Built from ${skills.length} first-party skill${skills.length === 1 ? '' : 's'} in \`${SKILLS_DIR}/\`, faceted two ways. A count in the **Skills** column is a count of frontmatter declarations, not a coverage claim — the scope note is what tells you what "covered" means for that row.`,
    '',
    '## By jurisdiction',
    '',
    facetTable(jurisdictions, FACETS[0]),
    '',
    '## By practice area',
    '',
    facetTable(practiceAreas, FACETS[1]),
    '',
    '## Gaps',
    '',
    gaps.length
      ? `${gaps.length} practice area${gaps.length === 1 ? '' : 's'} named in \`${NOTES_SOURCE}\` ${
          gaps.length === 1 ? 'has' : 'have'
        } no first-party skill against ${gaps.length === 1 ? 'it' : 'them'}: ${gaps
          .map((facet) => `[${facet.label}](${ctx.route(`skills/coverage/practice-area/${facet.slug}`)})`)
          .join(', ')}. Each page says whether the area is an open gap or a deliberate scope exclusion.`
      : 'Every practice area named in the notes file has at least one first-party skill against it.',
    '',
    ...(jurisdictionGaps.length
      ? [
          `${jurisdictionGaps.length} jurisdiction${jurisdictionGaps.length === 1 ? '' : 's'} ${
            jurisdictionGaps.length === 1 ? 'is' : 'are'
          } named with no skill declaring ${jurisdictionGaps.length === 1 ? 'it' : 'them'}: ${jurisdictionGaps
            .map(
              (facet) =>
                `[${facet.label}](${ctx.route(`skills/coverage/jurisdiction/${facet.slug}`)})`
            )
            .join(', ')}.`,
          '',
        ]
      : []),
    ...(ungrouped.size
      ? [
          `${ungrouped.size} tag${ungrouped.size === 1 ? '' : 's'} in skill frontmatter ${
            ungrouped.size === 1 ? 'is' : 'are'
          } not grouped into a practice area by \`${NOTES_SOURCE}\`, so ${
            ungrouped.size === 1 ? 'it has' : 'they have'
          } no page of its own: ${[...ungrouped.keys()]
            .sort()
            .map((tag) => `\`${tag}\``)
            .join(', ')}. A tag is a discovery aid; a practice area is an editorial claim about coverage, and only the second one gets a page.`,
          '',
        ]
      : []),
    ...(unannotated.length
      ? [
          `${unannotated.length} facet${unannotated.length === 1 ? '' : 's'} ${
            unannotated.length === 1 ? 'has' : 'have'
          } no scope note in \`${NOTES_SOURCE}\` and reflect${
            unannotated.length === 1 ? 's' : ''
          } frontmatter only: ${unannotated.map((facet) => `\`${facet.label}\``).join(', ')}.`,
          '',
        ]
      : []),
    '## Contributing coverage',
    '',
    ...(notes.route?.notes.length
      ? notes.route.notes.map((note) => `${String(note).trim()}\n`)
      : [
          `The contribution route is not recorded in \`${NOTES_SOURCE}\` as of the checked commit; [Where skills live](${ctx.route('skills/where-skills-live')}) carries what the repository does say.\n`,
        ]),
    ...(notes.route?.sources.length
      ? [notes.route.sources.map((source) => sourceLink(ctx, source, stamp.sha)).join(' · '), '']
      : []),
    '## Next',
    '',
    `- [Skill catalogue](${ctx.route('skills/catalogue')})`,
    `- [Where skills live](${ctx.route('skills/where-skills-live')})`,
    `- [Author your first skill](${ctx.route('skills/author-your-first-skill')})`,
  ].join('\n');

  pages.push({
    relPath: 'skills/coverage/index.md',
    intro: INTRO,
    stamp,
    frontmatter: {
      title: 'Coverage',
      description:
        'Which jurisdictions and practice areas the first-party skills declare, what each declaration actually covers, and where the gaps are.',
      audience: ['author', 'evaluator'],
      sources: [SKILLS_DIR, NOTES_SOURCE],
      sidebar: { order: 21 },
    },
    body,
  });

  return pages;
}
