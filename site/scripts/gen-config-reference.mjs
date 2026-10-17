/**
 * `/reference/configuration/` — every setting the backend and the gateway read.
 *
 * Built by parsing `api/app/config.py` and `gateway/app/config.py` with Python's
 * own `ast` (see `gen-config-reference.py`), then rendering one table per
 * settings class: field, type, default, and whatever description the source
 * actually carries. A field the repository does not document shows an em dash
 * in that column, because "the repository does not say" is the true answer and
 * an invented sentence is not.
 *
 * Below the tables, `gateway.yaml.example` and `mcp.yaml.example` are included
 * verbatim, comments intact. The comments in those files are the operator
 * documentation — stripping them to "tidy up" the page would delete the thing
 * the page is for.
 */

import { cell, table } from './lib/markdown.mjs';
import { fromRst, parsePythonModels } from './lib/python.mjs';

export const id = 'gen-config-reference';

const ROUTE = 'reference/configuration.md';
const INTRO = 'reference/configuration.intro.md';

const PYTHON_SOURCES = ['api/app/config.py', 'gateway/app/config.py'];
const YAML_EXAMPLES = ['gateway.yaml.example', 'mcp.yaml.example'];

const TITLES = {
  'api/app/config.py': 'Backend API — environment settings',
  'gateway/app/config.py': 'Inference Gateway — `gateway.yaml` schema',
};

export async function generate(ctx) {
  const sources = [...PYTHON_SOURCES, ...YAML_EXAMPLES];
  const stamp = ctx.stamp(sources, INTRO);

  const parsed = parsePythonModels(PYTHON_SOURCES);
  for (const problem of parsed.problems ?? []) {
    ctx.report({ level: 'error', page: ROUTE, line: 1, message: problem });
  }

  const sections = [];

  for (const file of parsed.files ?? []) {
    sections.push(`## ${TITLES[file.path] ?? file.path}`, '');
    sections.push(
      `Parsed from [\`${file.path}\`](${ctx.blob(file.path, stamp.sha)}) at the commit this page was checked against.`,
      ''
    );

    if (file.classes.length === 0) {
      sections.push(`No settings class was found in \`${file.path}\`.`, '');
      continue;
    }

    for (const klass of file.classes) {
      if (klass.fields.length === 0) continue;
      sections.push(`### \`${klass.name}\``, '');
      if (klass.doc) sections.push(fromRst(klass.doc), '');
      sections.push(...renderFields(klass.fields), '');
    }
  }

  for (const example of YAML_EXAMPLES) {
    const text = ctx.read(example);
    sections.push(`## \`${example}\``, '');
    if (text == null) {
      ctx.report({
        level: 'warn',
        page: ROUTE,
        line: 1,
        message: `${example} is not in the repository — the page says so instead of showing it`,
      });
      sections.push(
        `\`${example}\` is not in the repository as of the checked commit.`,
        ''
      );
      continue;
    }
    sections.push(
      `Reproduced in full from [\`${example}\`](${ctx.blob(example, stamp.sha)}), comments included — the comments are the operator documentation.`,
      '',
      fence(text, 'yaml'),
      ''
    );
  }

  const body = [
    ...sections,
    '## Next',
    '',
    `- [Skill frontmatter](${ctx.route('reference/skill-frontmatter')}) — the other generated schema.`,
    `- [Install with Docker Compose](${ctx.route('operate/install-docker-compose')}) — where these values are set.`,
    `- [Rotate a leaked key](${ctx.route('operate/rotate-a-leaked-key')}) — the provider-key settings in practice.`,
  ].join('\n');

  return [
    {
      relPath: ROUTE,
      intro: INTRO,
      stamp,
      frontmatter: {
        title: 'Configuration reference',
        description:
          'Every setting the backend and the Inference Gateway read, generated from their Pydantic settings classes, plus the two example configuration files in full.',
        audience: ['operator', 'agent'],
        sources,
        sidebar: { order: 10 },
      },
      body,
    },
  ];
}

/** One table per `# ----- Section -----` banner the source file groups by. */
function renderFields(fields) {
  const headers = ['Setting', 'Type', 'Default', 'Description'];
  const row = (field) => [
    `\`${field.name}\``,
    field.annotation ? `\`${field.annotation}\`` : '—',
    field.required ? '**required**' : field.default ? `\`${cell(field.default)}\`` : '—',
    [fromRst(field.description) || '—', constraintNote(field.constraints)]
      .filter(Boolean)
      .join(' '),
  ];

  const sections = [];
  let current = null;
  for (const field of fields) {
    const name = field.section ?? '';
    if (!current || current.name !== name) {
      current = { name, rows: [] };
      sections.push(current);
    }
    current.rows.push(row(field));
  }

  if (sections.length === 1 && !sections[0].name) {
    return [table(headers, sections[0].rows)];
  }

  return sections.flatMap((section) => [
    ...(section.name ? [`**${section.name}**`, ''] : []),
    table(headers, section.rows),
    '',
  ]);
}

const constraintNote = (constraints) => {
  const entries = Object.entries(constraints ?? {});
  if (entries.length === 0) return '';
  return `(${entries.map(([key, value]) => `${key} ${value}`).join(', ')})`;
};

/**
 * Fence a file whose own content may contain a fence.
 *
 * `gateway.yaml.example` is 29 KB of commented YAML; a backtick run inside it
 * would end the block early and spill the rest of the file into the page as
 * prose. The fence is therefore always longer than the longest run in the text.
 */
export function fence(text, language) {
  const longest = Math.max(
    2,
    ...[...String(text).matchAll(/`+/g)].map((match) => match[0].length)
  );
  const marker = '`'.repeat(Math.max(3, longest + 1));
  return `${marker}${language}\n${String(text).replace(/\n+$/, '')}\n${marker}`;
}
