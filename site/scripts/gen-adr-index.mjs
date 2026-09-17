/**
 * `/reference/adr-index/` — every architecture decision record, with the status
 * the file actually carries.
 *
 * Generated on purpose. A hand-written ADR index goes stale the week after it
 * is written, and a stale index on a trust centre is a claim that the project
 * decided something it did not. This one reads `docs/adr/*.md` at build time
 * and renders the **Status** line verbatim — including "Proposed" on a decision
 * everyone treats as settled, and including the drift in an ADR whose status
 * was never updated after the committee accepted it. Surfacing that is the
 * point, not a defect: the index is only useful if it can embarrass the
 * repository.
 *
 * Nothing here interprets. The number comes from the filename, the title from
 * the H1, the status from the first `Status` line. An ADR that does not carry
 * one is listed with "no status line in the file".
 */

import { firstH1, table } from './lib/markdown.mjs';

export const id = 'gen-adr-index';

const ADR_DIR = 'docs/adr';
const ROUTE = 'reference/adr-index.md';
const INTRO = 'reference/adr-index.intro.md';

/**
 * A status line is rendered verbatim, and several of them carry their own
 * Markdown links — `extended by [ADR 0012](0012-db-backed-user-skills.md)`,
 * `per the [mini-PRD](../contribute/mini-prds/docx-ingest-support.md)`. Those
 * are relative to `docs/adr/`, not to the page, so they are resolved here
 * against the repository before the text leaves the generator. A target that is
 * not in the repository keeps its text and loses its link rather than shipping
 * a URL that goes nowhere.
 */
function resolveAdrLinks(ctx, text, sha) {
  return String(text).replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, target) => {
    if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(target)) return match;
    const [file, anchor = ''] = target.split(/(#.*)$/);
    const rel = posixNormalise(`${ADR_DIR}/${file}`);
    if (ctx.read(rel) == null) return label;
    return `[${label}](${ctx.blob(rel, sha)}${anchor})`;
  });
}

/** `docs/adr/../contribute/x.md` → `docs/contribute/x.md`. */
function posixNormalise(input) {
  const out = [];
  for (const part of input.split('/')) {
    if (part === '.' || part === '') continue;
    if (part === '..') out.pop();
    else out.push(part);
  }
  return out.join('/');
}

/** `**Status:** Accepted (2026-05-07)` → `Accepted (2026-05-07)`. */
function statusOf(text) {
  const bold = /^\s*\*\*Status:?\*\*\s*(.+)$/m.exec(text);
  if (bold) return bold[1].trim();
  // A table row: `| Status | Accepted |`
  const row = /^\s*\|\s*Status\s*\|\s*(.+?)\s*\|\s*$/im.exec(text);
  if (row) return row[1].trim();
  const plain = /^\s*Status:\s*(.+)$/m.exec(text);
  if (plain) return plain[1].trim();
  return undefined;
}

export async function generate(ctx) {
  const files = ctx.list(ADR_DIR).filter((name) => /^\d{4}.*\.md$/.test(name));

  if (files.length === 0) {
    ctx.report({
      level: 'warn',
      page: ROUTE,
      line: 1,
      message: `${ADR_DIR}/ holds no ADR files — the index ships empty`,
    });
  }

  // The directory, not twenty-five filenames: `git log -1 -- docs/adr` gives
  // the same commit, the footer stays readable, and GitHub serves a blob URL
  // for a directory as its tree view.
  const sources = [ADR_DIR];
  const stamp = ctx.stamp(sources, INTRO);

  const rows = files.map((name) => {
    const relPath = `${ADR_DIR}/${name}`;
    const text = ctx.read(relPath) ?? '';
    const number = name.slice(0, 4);
    const heading = firstH1(text) ?? name.replace(/\.md$/, '');
    // `ADR 0001 — OpenWebUI fork pin` → `OpenWebUI fork pin`; the number is its
    // own column, and repeating it in the title makes the table hard to scan.
    const title = heading.replace(/^ADR\s*\d+\s*[—\-–:]\s*/i, '').trim();
    const status = statusOf(text);
    if (!status) {
      ctx.report({
        level: 'warn',
        page: ROUTE,
        line: 1,
        message: `${relPath} carries no Status line — listed as "no status line in the file"`,
      });
    }
    // The status line is one word (Accepted, Proposed, Superseded, …) followed,
    // in most files, by a date and a note. The word is its own column so the
    // page can badge it; the rest stays verbatim in a Note column.
    const split = status ? /^(\w+)\b\s*(.*)$/s.exec(status.trim()) : null;
    const statusWord = split ? split[1] : 'no status line in the file';
    const statusNote = split && split[2] ? resolveAdrLinks(ctx, split[2], stamp.sha) : '';
    return [number, `[${title}](${ctx.blob(relPath, stamp.sha)})`, statusWord, statusNote];
  });

  const body = [
    // Default classification would key the record on column 1 (the ADR
    // number); the number is not what a reader scans for, the decision title
    // is — so the directive overrides the record title to column 2. See
    // "Known cases to check" in the tables spec.
    '<!-- table: records key=2 -->',
    table(['ADR', 'Decision', 'Status', 'Note'], rows),
    '',
    `Each row links the ADR file at the commit this page was checked against, so the status you read here is the status that file carried at that commit. Statuses are rendered exactly as the file states them — an ADR that says "Proposed" is listed as Proposed even where the decision is being followed, because the file is the record.`,
    '',
    '## Next',
    '',
    `- [Reference](${ctx.route('reference')}) — the rest of the generated material.`,
    `- [Release versioning](${ctx.route('reference/versioning')}) — ADR 0025 in full.`,
    `- [Governance](${ctx.route('trust/governance')}) — who decides, and how a decision is recorded.`,
  ].join('\n');

  return [
    {
      relPath: ROUTE,
      intro: INTRO,
      stamp,
      frontmatter: {
        title: 'ADR index',
        description:
          'Every architecture decision record in the repository, with the status each file carries, generated at build time.',
        audience: ['contributor', 'evaluator', 'agent'],
        sources,
        sidebar: { order: 40 },
      },
      body,
    },
  ];
}
