/**
 * `/reference/skill-frontmatter/` — what a `SKILL.md`'s YAML block may contain.
 *
 * Generated from the loader's own schema (`api/app/skills/schema.py`) rather
 * than from the authoring guide, because the schema is what actually accepts or
 * rejects a skill at load time. The guide says what a well-formed skill looks
 * like; the schema says what the product will take. Where those two disagree, a
 * skill author needs to know the second one — and the page links the first.
 *
 * The schema is deliberately permissive (`extra="allow"`, almost everything
 * optional) because the starter-skill corpus predates the guide. That is stated
 * on the page, from the schema's own docstrings, rather than left for an author
 * to discover by having a field silently ignored.
 */

import { cell, table } from './lib/markdown.mjs';
import { fromRst, parsePythonModels } from './lib/python.mjs';

export const id = 'gen-skill-frontmatter';

const ROUTE = 'reference/skill-frontmatter.md';
const INTRO = 'reference/skill-frontmatter.intro.md';

const SCHEMA = 'api/app/skills/schema.py';
const GUIDE = 'docs/skill-authoring-guide.md';

/** The classes that describe frontmatter. The wire shapes are a different page. */
const FRONTMATTER_CLASSES = [
  {
    name: 'SkillFrontmatter',
    heading: 'Top level',
    lead: 'The two required keys, plus the `lq_ai:` block everything else nests under.',
  },
  {
    name: 'LQAIFrontmatter',
    heading: 'The `lq_ai:` block',
    lead: 'Every field is optional. A skill that declares none still loads.',
  },
  {
    name: 'ColumnSpec',
    heading: 'A column, for an `output_format: table` skill',
    lead: 'Required only when `output_format: table`; the loader skips a table-mode skill whose `columns` list is missing or empty.',
  },
  {
    name: 'SkillInputDef',
    heading: 'A declared input',
    lead: 'What the skill-input form renders against. Read from `inputs:` at the top level or under `lq_ai:` — the corpus uses both.',
  },
];

export async function generate(ctx) {
  const sources = [SCHEMA, GUIDE];
  const stamp = ctx.stamp(sources, INTRO);

  const parsed = parsePythonModels([SCHEMA]);
  for (const problem of parsed.problems ?? []) {
    ctx.report({ level: 'error', page: ROUTE, line: 1, message: problem });
  }

  const classes = new Map(
    (parsed.files?.[0]?.classes ?? []).map((klass) => [klass.name, klass])
  );

  const sections = [];
  for (const wanted of FRONTMATTER_CLASSES) {
    const klass = classes.get(wanted.name);
    if (!klass) {
      ctx.report({
        level: 'warn',
        page: ROUTE,
        line: 1,
        message: `${SCHEMA} no longer defines ${wanted.name} — that section is omitted`,
      });
      continue;
    }
    sections.push(`## ${wanted.heading}`, '', wanted.lead, '');
    if (klass.doc) sections.push(fromRst(klass.doc), '');
    sections.push(
      table(
        ['Field', 'Type', 'Required', 'Default', 'What it is'],
        klass.fields.map((field) => [
          `\`${field.name}\``,
          field.annotation ? `\`${field.annotation}\`` : '—',
          field.required ? 'required' : 'optional',
          field.required ? '—' : field.default ? `\`${cell(field.default)}\`` : '—',
          fromRst(field.description) || '—',
        ])
      ),
      ''
    );
  }

  const body = [
    `Generated from [\`${SCHEMA}\`](${ctx.blob(SCHEMA, stamp.sha)}) — the loader's own schema, which is what accepts or rejects a skill at load time. The conventions an author should follow are in the [skill-authoring guide](${ctx.blob(GUIDE, stamp.sha)}); this page is the floor the product enforces underneath them.`,
    '',
    ...sections,
    '## Next',
    '',
    `- [Author your first skill](${ctx.route('skills/author-your-first-skill')})`,
    `- [Skill catalogue](${ctx.route('skills/catalogue')}) — the frontmatter of every shipped skill, rendered.`,
    `- [Configuration reference](${ctx.route('reference/configuration')})`,
  ].join('\n');

  return [
    {
      relPath: ROUTE,
      intro: INTRO,
      stamp,
      frontmatter: {
        title: 'Skill frontmatter',
        description:
          "Every field a SKILL.md's YAML frontmatter may carry, generated from the skill loader's own schema.",
        audience: ['author', 'agent'],
        sources,
        sidebar: { order: 30 },
      },
      body,
    },
  ];
}
