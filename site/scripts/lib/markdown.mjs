/**
 * Markdown surgery for the transform: frontmatter, fence-aware heading work,
 * include slicing, and the MDX → Markdown reduction the machine surface needs.
 *
 * Everything that looks at headings is fence-aware. A shell block in
 * `docs/quickstart.md` contains lines that start with `#`, and a comment in a
 * YAML block contains lines that start with `## `. Treating those as headings
 * would truncate an include at the wrong place — silently, and in the middle
 * of an install procedure. So every walk over the text tracks fence state and
 * only heading lines *outside* a fence count.
 */

import matter from 'gray-matter';

const FENCE = /^\s{0,3}(`{3,}|~{3,})/;
const ATX_HEADING = /^(#{1,6})(\s|$)/;

/**
 * Walk the lines of a Markdown document, reporting whether each is inside a
 * fenced code block.
 *
 * @param {string} text
 * @returns {{ line: string, inFence: boolean }[]}
 */
export function scanLines(text) {
  const out = [];
  let fence = null;
  for (const line of String(text).split('\n')) {
    const match = FENCE.exec(line);
    if (fence) {
      const marker = match?.[1];
      // A fence closes only on the same character, at least as long.
      const closes = marker && marker[0] === fence[0] && marker.length >= fence.length;
      out.push({ line, inFence: true });
      if (closes) fence = null;
      continue;
    }
    if (match) {
      fence = match[1];
      out.push({ line, inFence: true });
      continue;
    }
    out.push({ line, inFence: false });
  }
  return out;
}

/** Is this line an ATX heading that is not inside a code fence? */
export const isHeading = ({ line, inFence }) => !inFence && ATX_HEADING.test(line);

/** Parse a page into `{ data, content }`. Throws on malformed YAML. */
export function parsePage(raw) {
  const parsed = matter(raw);
  return { data: parsed.data ?? {}, content: parsed.content ?? '' };
}

/** Serialise `{ data, content }` back to a page with a YAML frontmatter block. */
export function serializePage(data, content) {
  // `lineWidth: -1` keeps a long description on one line: a wrapped YAML scalar
  // is still valid, but it reads badly in the generated tree a maintainer
  // debugs against, and `llms.txt` shows descriptions verbatim.
  return matter.stringify(`${String(content).replace(/^\n+/, '')}\n`, data, { lineWidth: -1 });
}

/** Strip a leading YAML frontmatter block from a repository file. */
export function stripFrontmatter(raw) {
  return matter(String(raw)).content;
}

/**
 * Drop the document's first H1.
 *
 * The page's own `title` replaces it — a curation page that shows both reads
 * as two titles stacked, and the second one is the one Starlight did not put
 * in the sidebar.
 */
export function dropFirstH1(text) {
  const lines = scanLines(text);
  const index = lines.findIndex((entry) => !entry.inFence && /^#\s/.test(entry.line));
  if (index === -1) return text;
  const kept = lines.map((entry) => entry.line);
  kept.splice(index, 1);
  // Collapse the blank line the removed heading leaves behind.
  if (kept[index]?.trim() === '' && (index === 0 || kept[index - 1]?.trim() === '')) {
    kept.splice(index, 1);
  }
  return kept.join('\n');
}

/**
 * Slice a document between two exact heading lines, `to` exclusive.
 *
 * Both are compared as whole trimmed lines, because that is what the authoring
 * contract promises a writer: copy the heading line out of the source file.
 *
 * @returns {{ ok: true, text: string } | { ok: false, missing: 'from' | 'to' }}
 */
export function sliceBetweenHeadings(text, from, to) {
  const lines = scanLines(text);
  let start = 0;
  if (from) {
    const index = lines.findIndex((entry) => isHeading(entry) && entry.line.trim() === from.trim());
    if (index === -1) return { ok: false, missing: 'from' };
    start = index;
  }
  let end = lines.length;
  if (to) {
    const offset = lines
      .slice(start + 1)
      .findIndex((entry) => isHeading(entry) && entry.line.trim() === to.trim());
    if (offset === -1) return { ok: false, missing: 'to' };
    end = start + 1 + offset;
  }
  return { ok: true, text: lines.slice(start, end).map((entry) => entry.line).join('\n') };
}

/**
 * Demote every heading by `levels`.
 *
 * An included file's H2s sit under the including page's own H2, so the writer
 * says `shift=1` and the outline stays legal. A heading that would pass H6 is
 * clamped: HTML has no `<h7>`, and silently emitting `#######` renders the
 * hashes as text.
 */
export function shiftHeadings(text, levels) {
  const n = Number(levels) || 0;
  if (n <= 0) return text;
  return scanLines(text)
    .map((entry) => {
      if (!isHeading(entry)) return entry.line;
      const [, hashes] = ATX_HEADING.exec(entry.line);
      const depth = Math.min(6, hashes.length + n);
      return '#'.repeat(depth) + entry.line.slice(hashes.length);
    })
    .join('\n');
}

/** The first H1's text, or undefined. Used for ADR and release titles. */
export function firstH1(text) {
  for (const entry of scanLines(text)) {
    if (!entry.inFence && /^#\s/.test(entry.line)) return entry.line.replace(/^#\s+/, '').trim();
  }
  return undefined;
}

/**
 * Reduce an MDX page to plain Markdown for the `.md` twin and `llms-full.txt`.
 *
 * Only the hub components are meaningful to a machine reader, and only their
 * content is: a `<LinkCard>` becomes the list item it stands for. Everything
 * else JSX — imports, `<CardGrid>` wrappers, stray tags — carries no text and
 * is removed rather than shown as markup an agent would have to parse.
 */
export function reduceMdx(text) {
  let out = String(text);

  // `import { CardGrid } from '@astrojs/starlight/components';`
  out = out.replace(/^\s*import\s+[^\n]*?from\s+['"][^'"]+['"];?\s*$/gm, '');
  out = out.replace(/^\s*export\s+const\s+[^\n]*$/gm, '');

  // A LinkCard becomes the link it is. Attributes are order-independent, and
  // the indentation it sat at inside `<CardGrid>` goes with the wrapper — a
  // two-space indent that meant nothing in JSX turns a top-level list into a
  // nested one in Markdown.
  out = out.replace(/^[ \t]*(?=<LinkCard\b)/gm, '');
  out = out.replace(/<LinkCard\b([^>]*?)\/?>(?:\s*<\/LinkCard>)?/g, (_match, attrs) => {
    const attr = (name) => {
      const found = new RegExp(`${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|\\{\`([^\`]*)\`\\})`).exec(
        attrs
      );
      return found ? (found[1] ?? found[2] ?? found[3] ?? '').trim() : '';
    };
    const title = attr('title');
    const href = attr('href');
    const description = attr('description');
    if (!title && !href) return '';
    const link = href ? `[${title || href}](${href})` : title;
    return description ? `- ${link} — ${description}` : `- ${link}`;
  });

  // Remaining component tags carry no text of their own.
  out = out.replace(/<\/?(?:CardGrid|Card|Tabs|TabItem|Aside|Steps|Badge|Icon)\b[^>]*>/g, '');

  return out.replace(/\n{3,}/g, '\n\n').trim();
}

/**
 * Turn a GFM task list into a plain one.
 *
 * `- [ ] item` renders as `<input type="checkbox" disabled>`, and a disabled
 * checkbox with no label is an unlabelled form control: it fails WCAG 1.3.1
 * (axe `label`), and the accessibility gate is a gate. It is also a lie — the
 * reader cannot tick it. Several canonical files carry checklists
 * (`docs/skill-authoring-guide.md`'s authoring checklist, among others), and
 * those are included verbatim into curation pages, so this has to be handled in
 * the transform rather than by asking writers to avoid the syntax upstream.
 *
 * `☐` and `✓` carry the same meaning as text, which is what the design language
 * already uses for a checklist. Fence-aware, so a code sample that *shows* the
 * syntax keeps it.
 */
export function plainCheckboxes(text) {
  return scanLines(text)
    .map((entry) => {
      if (entry.inFence) return entry.line;
      return entry.line.replace(
        /^(\s*(?:[-*+]|\d+[.)])\s+)\[([ xX])\]\s+/,
        (_match, bullet, mark) => `${bullet}${mark === ' ' ? '☐' : '✓'} `
      );
    })
    .join('\n');
}

/**
 * GitHub alert syntax → a Starlight aside.
 *
 * A canonical repository file has to render as a callout on GitHub too
 * (Starlight's `:::type[]` directive means nothing there), so the house rule
 * is the alert form GitHub itself renders:
 *
 *     > [!CAUTION]
 *     > **Silent failure** — a control that fails without telling anyone is
 *     > worse than one that fails loudly.
 *
 * This turns it into `:::caution[Silent failure]\n…\n:::` for the built page.
 * The leading bold phrase in the blockquote's first line becomes the aside's
 * title, exactly as `:::type[Title]` would have named it by hand; a block with
 * no bold lead keeps the aside's default title for its type.
 *
 * Fence-aware — a code sample that *shows* the alert syntax is left alone —
 * and only a blockquote whose very first line is the `[!TYPE]` marker is
 * converted, so an ordinary quote that happens to contain those five words is
 * never mistaken for one.
 */
const ALERT_TYPES = {
  NOTE: 'note',
  TIP: 'tip',
  IMPORTANT: 'note',
  WARNING: 'caution',
  CAUTION: 'danger',
};

const ALERT_MARKER = /^(\s*)>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$/;
const BLOCKQUOTE_LINE = /^\s*>/;
const BOLD_LEAD = /^\*\*(.+?)\*\*\s*(?:[—–-]\s*)?(.*)$/;

export function convertGithubAlerts(text) {
  const lines = scanLines(text);
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const entry = lines[i];
    const marker = !entry.inFence && ALERT_MARKER.exec(entry.line);
    if (!marker) {
      out.push(entry.line);
      i += 1;
      continue;
    }

    const indent = marker[1];
    const aside = ALERT_TYPES[marker[2]];
    const body = [];
    let j = i + 1;
    while (j < lines.length && !lines[j].inFence && BLOCKQUOTE_LINE.test(lines[j].line)) {
      body.push(lines[j].line.replace(BLOCKQUOTE_LINE, '').replace(/^ /, ''));
      j += 1;
    }

    let title;
    if (body.length) {
      const bold = BOLD_LEAD.exec(body[0]);
      if (bold) {
        title = bold[1];
        body[0] = bold[2];
        if (!body[0]) body.shift();
      }
    }

    out.push(`${indent}${title ? `:::${aside}[${title}]` : `:::${aside}`}`);
    out.push(...body.map((line) => `${indent}${line}`));
    out.push(`${indent}:::`);
    i = j;
  }

  return out.join('\n');
}

/** Escape a cell so a pipe or newline in source text cannot break a table. */
export const cell = (value) => {
  const text = value == null || value === '' ? '' : String(value);
  return text.replace(/\|/g, '\\|').replace(/\s*\n\s*/g, ' ').trim();
};

/** Render a Markdown table. Rows shorter than the header are padded. */
export function table(headers, rows) {
  const line = (values) => `| ${headers.map((_, i) => cell(values[i])).join(' | ')} |`;
  return [
    line(headers),
    `|${headers.map(() => '---').join('|')}|`,
    ...rows.map((row) => line(row)),
  ].join('\n');
}
