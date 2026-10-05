/**
 * Tables → shapes: render a Markdown table by its content's shape, not as a
 * generic wide grid. 118 tables were audited on 2026-09-16 and most are not
 * tabular data — two-column key→value lists and one-row-per-entity records
 * with prose cells, both of which overflow the reading column as a `<table>`.
 * The Markdown source stays a table (GitHub and the `.md` twin both want
 * that); only the rendered HTML changes.
 *
 * A plain rehype plugin: default export `() => (tree) => void`. No
 * dependencies — hast is walked by hand. Node shapes assumed throughout:
 * element `{ type: 'element', tagName, properties, children }`, text
 * `{ type: 'text', value }`, comment `{ type: 'comment', value }`.
 *
 * The pure pieces (`readTable`, `classifyTable`, `transformTable`,
 * `parseDirective`) are exported so they can be unit-tested without Astro —
 * see `test/tables.test.mjs`.
 *
 * ## Directive
 *
 * An HTML comment immediately before the table (only whitespace text nodes
 * between it and the table): `<!-- table: grid -->`, `<!-- table: dl -->`,
 * `<!-- table: records -->`, `<!-- table: records key=2 -->` (1-based column
 * index that becomes the record title). The comment is removed from the
 * output when it parses as a directive; an unrelated comment that merely
 * precedes a table is left alone.
 *
 * Whether that comment survives to this plugin at all is a pipeline question,
 * not a table question — see the note below.
 *
 * ## Classification (in this order)
 *
 * 1. A directive on the table wins outright.
 * 2. Exactly 2 columns → `dl`.
 * 3. Otherwise measure `maxLen[c]`, the longest cell text in column `c`
 *    (header included): `grid` if `sum(maxLen) <= 72`, every `maxLen[c] <=
 *    36`, and there are at most 5 columns.
 * 4. Otherwise `records`, keyed on column 1.
 *
 * ## A note on how the comment gets here
 *
 * This workspace's installed Markdown processor is `@astrojs/markdown-satteri`
 * (Astro 7's default), not `@astrojs/markdown-remark` — confirmed by empirical
 * probing (see the "Sätteri integration adapter" section below, near the
 * bottom of this file). Two things follow from that: a comment immediately
 * before a table survives, but as `{ type: 'raw', value: '<!-- … -->' }`, not
 * `{ type: 'comment', value: '…' }`; and a plain `(tree) => void` walk that
 * mutates `children` arrays directly — the classic rehype-plugin contract
 * this file exports by default, and the shape `test/tables.test.mjs` exercises
 * — does not reach the rendered page under Sätteri's plugin API, which expects
 * structural mutations through a hook's `ctx` instead. `rehypeLqTablesSatteri`
 * below is the adapter actually wired into `astro.config.mjs`; the default
 * export stays exactly as specified, for the tests and for any future
 * processor that does support the classic contract.
 */

// ---------------------------------------------------------------------------
// hast node builders
// ---------------------------------------------------------------------------

/** @returns {{type: 'element', tagName: string, properties: object, children: any[]}} */
function h(tagName, properties, children) {
  return { type: 'element', tagName, properties: properties ?? {}, children: children ?? [] };
}

/** @returns {{type: 'text', value: string}} */
function text(value) {
  return { type: 'text', value: String(value) };
}

// ---------------------------------------------------------------------------
// tree walking helpers
// ---------------------------------------------------------------------------

const isElement = (node, tagName) =>
  !!node && node.type === 'element' && (tagName === undefined || node.tagName === tagName);

const isWhitespaceText = (node) =>
  !!node && node.type === 'text' && typeof node.value === 'string' && node.value.trim() === '';

/** Concatenated text of every descendant text node, trimmed. */
function textOf(nodes) {
  let out = '';
  for (const node of nodes ?? []) {
    if (!node) continue;
    if (node.type === 'text' && typeof node.value === 'string') {
      out += node.value;
    } else if (Array.isArray(node.children)) {
      out += textOf(node.children);
    }
  }
  return out.trim();
}

/** The `th`/`td` element children of a `tr`, in order. */
function cellsOf(rowNode) {
  return (rowNode?.children ?? []).filter((c) => isElement(c, 'th') || isElement(c, 'td'));
}

/**
 * Locate the header row and the body rows of a `<table>`, tolerating the
 * shapes a hand-written or generator-emitted table can arrive in:
 *
 *  - the usual `table > thead > tr` + `table > tbody > tr*`;
 *  - a table with `tbody` rows but no `thead` (the first body row becomes
 *    the header row);
 *  - a table with no section wrappers at all, `tr`s directly under `table`
 *    (some generators emit only `tr`s) — the first `tr` becomes the header
 *    row.
 *
 * In every shape the first row found is treated as the header row; GFM
 * tables always have one syntactically, whether or not a generator's HTML
 * happens to wrap it in `<thead>`.
 */
function readRows(tableNode) {
  const sections = (tableNode?.children ?? []).filter((c) => c.type === 'element');
  const thead = sections.find((s) => s.tagName === 'thead');
  const bodyLike = sections.filter((s) => s.tagName === 'tbody' || s.tagName === 'tfoot');
  const directRows = sections.filter((s) => s.tagName === 'tr');

  const bodySectionRows = bodyLike.flatMap((s) => (s.children ?? []).filter((c) => isElement(c, 'tr')));

  if (thead) {
    const headerRow = (thead.children ?? []).find((c) => isElement(c, 'tr')) ?? null;
    return { headerRow, bodyRows: [...bodySectionRows, ...directRows] };
  }

  const allRows = [...bodySectionRows, ...directRows];
  const [headerRow = null, ...bodyRows] = allRows;
  return { headerRow, bodyRows };
}

// ---------------------------------------------------------------------------
// the exported pure helpers
// ---------------------------------------------------------------------------

/**
 * Read a `<table>` hast node into the shape the rest of this module works
 * with: cell content as `children` arrays (so inline hast — `code`, `a`,
 * `em`, `strong` — survives into whatever the table is turned into) plus the
 * plain concatenated text of each cell, for classification and slugging.
 *
 * @param {object} tableNode
 * @returns {{headers: any[][], rows: any[][][], headerText: string[], cellText: string[][]}}
 */
export function readTable(tableNode) {
  const { headerRow, bodyRows } = readRows(tableNode);
  const headers = headerRow ? cellsOf(headerRow).map((cell) => cell.children ?? []) : [];
  const headerText = headers.map((children) => textOf(children));
  const rows = bodyRows.map((row) => cellsOf(row).map((cell) => cell.children ?? []));
  const cellText = rows.map((cells) => cells.map((children) => textOf(children)));
  return { headers, rows, headerText, cellText };
}

const DIRECTIVE_RE = /^table:\s*(dl|records|grid)(?:\s+key=(\d+))?\s*$/;

/**
 * Parse an `<!-- table: … -->` comment's raw value (a hast comment node's
 * `.value`, i.e. the text between `<!--` and `-->`, unstripped). Returns
 * `null` for a comment that isn't one of ours — such a comment is left in
 * place, not consumed.
 *
 * @param {string} commentValue
 * @returns {{shape: 'dl'|'records'|'grid', key?: number} | null}
 */
export function parseDirective(commentValue) {
  if (typeof commentValue !== 'string') return null;
  const match = DIRECTIVE_RE.exec(commentValue.trim());
  if (!match) return null;
  const [, shape, key] = match;
  return key === undefined ? { shape } : { shape, key: Number.parseInt(key, 10) };
}

/** `maxLen[c]`: the longest cell text in column `c`, header text included. */
function columnMaxLens(headerText, cellText) {
  const maxLen = headerText.map((t) => t.length);
  for (const row of cellText) {
    for (let c = 0; c < maxLen.length; c++) {
      const len = row[c]?.length ?? 0;
      if (len > maxLen[c]) maxLen[c] = len;
    }
  }
  return maxLen;
}

/**
 * @param {{headerText: string[], cellText: string[][]}} table
 * @param {{shape?: string, key?: number} | null} directive
 * @returns {{shape: 'dl'|'records'|'grid', key: number}}
 */
export function classifyTable({ headerText, cellText }, directive) {
  if (directive?.shape) {
    return { shape: directive.shape, key: directive.key ?? 1 };
  }
  const numCols = headerText.length;
  if (numCols === 2) return { shape: 'dl', key: 1 };
  const maxLen = columnMaxLens(headerText, cellText);
  const sum = maxLen.reduce((a, b) => a + b, 0);
  const fitsGrid = numCols <= 5 && sum <= 72 && maxLen.every((len) => len <= 36);
  return fitsGrid ? { shape: 'grid', key: 1 } : { shape: 'records', key: 1 };
}

// ---------------------------------------------------------------------------
// output builders
// ---------------------------------------------------------------------------

/** `div.lq-dl > p.lq-dl__caption + dl > (div.lq-dl__item > dt + dd)*` */
function buildDl(table) {
  const h1 = table.headerText[0] ?? '';
  const h2 = table.headerText[1] ?? '';

  const caption = h('p', { class: 'lq-dl__caption' }, [
    h('span', {}, [text(h1)]),
    text(' '),
    h('span', { 'aria-hidden': 'true' }, [text('→')]),
    text(' '),
    h('span', {}, [text(h2)]),
  ]);

  const items = table.rows.map((cells, i) => {
    const keyChildren = cells[0] ?? [];
    const valueChildren = cells[1] ?? [];
    const valueIsEmpty = (table.cellText[i]?.[1] ?? '').trim() === '';
    const dd = valueIsEmpty
      ? h('dd', {}, [h('span', { class: 'lq-muted' }, [text('—')])])
      : h('dd', {}, valueChildren);
    return h('div', { class: 'lq-dl__item' }, [h('dt', {}, keyChildren), dd]);
  });

  return h('div', { class: 'lq-dl', role: 'group', 'aria-label': `${h1} and ${h2}` }, [
    caption,
    h('dl', {}, items),
  ]);
}

/** `div.lq-table > table` — the original table, untouched, just wrapped. */
function buildGrid(tableNode) {
  return h('div', { class: 'lq-table' }, [tableNode]);
}

const STATUS_WORDS = new Set([
  'shipped',
  'partial',
  'scaffold',
  'deferred',
  'draft',
  'reviewed',
  'accepted',
  'proposed',
  'superseded',
  'deprecated',
  'rejected',
]);

/** `lq-status--<word>` when a cell's whole text is one of the status words. */
function statusModifier(cellText) {
  const word = cellText.trim().toLowerCase();
  return STATUS_WORDS.has(word) ? `lq-status--${word}` : null;
}

function valueClass(cellText) {
  const modifier = statusModifier(cellText);
  return modifier ? `lq-record__value lq-status ${modifier}` : 'lq-record__value';
}

function buildMetaField(label, valueChildren, cellText) {
  return h('span', { class: 'lq-record__field' }, [
    h('span', { class: 'lq-record__label' }, [text(label)]),
    text(' '),
    h('span', { class: valueClass(cellText) }, valueChildren),
  ]);
}

function buildBodyField(label, valueChildren, cellText) {
  return h('div', { class: 'lq-record__field lq-record__field--long' }, [
    h('span', { class: 'lq-record__label' }, [text(label)]),
    h('div', { class: valueClass(cellText) }, valueChildren),
  ]);
}

/** Interleave sibling nodes with a literal space text node, as the shapes in the spec do. */
function withSpaces(nodes) {
  const out = [];
  nodes.forEach((node, i) => {
    if (i > 0) out.push(text(' '));
    out.push(node);
  });
  return out;
}

/** lower-cased, non-`[a-z0-9_]` runs → one `-`, trimmed. */
function slugify(str) {
  return str
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** Make `base` unique against `usedIds`, appending `-2`, `-3`, … as needed, and reserve it. */
function uniqueId(base, usedIds) {
  let candidate = base;
  let n = 2;
  while (usedIds.has(candidate)) {
    candidate = `${base}-${n}`;
    n++;
  }
  usedIds.add(candidate);
  return candidate;
}

function buildRecords(table, key, usedIds) {
  const { rows, headerText, cellText } = table;
  const numCols = headerText.length;
  const keyIndex = numCols > 0 ? Math.min(Math.max((key ?? 1) - 1, 0), numCols - 1) : 0;
  const maxLen = columnMaxLens(headerText, cellText);

  const metaCols = [];
  const bodyCols = [];
  for (let c = 0; c < numCols; c++) {
    if (c === keyIndex) continue;
    (maxLen[c] <= 28 ? metaCols : bodyCols).push(c);
  }

  const articles = rows.map((cells, i) => {
    const keyChildren = cells[keyIndex] ?? [];
    const keyText = (cellText[i]?.[keyIndex] ?? '').trim();
    const base = keyText ? slugify(keyText) : '';
    const slug = uniqueId(base || `row-${i + 1}`, usedIds);

    const children = [h('p', { class: 'lq-record__title', id: `${slug}-title` }, keyChildren)];

    // An empty cell is omitted, label and all — a bare "NOTE" with nothing
    // after it tells the reader less than its absence does. (The dl shape
    // keeps its em dash because a definition with no value is itself the
    // information there.)
    const filled = (c) => (cellText[i]?.[c] ?? '').trim() !== '';

    const metaFields = metaCols
      .filter(filled)
      .map((c) => buildMetaField(headerText[c], cells[c] ?? [], cellText[i]?.[c] ?? ''));
    if (metaFields.length) {
      children.push(h('p', { class: 'lq-record__meta' }, withSpaces(metaFields)));
    }

    const bodyFields = bodyCols
      .filter(filled)
      .map((c) => buildBodyField(headerText[c], cells[c] ?? [], cellText[i]?.[c] ?? ''));
    if (bodyFields.length) {
      children.push(h('div', { class: 'lq-record__body' }, bodyFields));
    }

    return h(
      'article',
      { class: 'lq-record', id: slug, 'aria-labelledby': `${slug}-title` },
      children
    );
  });

  return h('div', { class: 'lq-records' }, articles);
}

/**
 * Turn one `<table>` into its replacement hast node: read it, classify it
 * (the directive, if any, wins outright), build the matching shape.
 *
 * `ctx.usedIds` is a `Set<string>` of ids already present in the document —
 * shared and mutated across every table `transformTable` is called for
 * during one file's walk, so slugs stay unique both against pre-existing
 * anchors and against records already emitted by an earlier table.
 *
 * @param {object} tableNode
 * @param {{shape?: string, key?: number} | null} directive
 * @param {{usedIds?: Set<string>}} [ctx]
 * @returns {object} the replacement hast node
 */
export function transformTable(tableNode, directive, ctx = {}) {
  const usedIds = ctx.usedIds ?? (ctx.usedIds = new Set());
  const table = readTable(tableNode);
  const { shape, key } = classifyTable(table, directive);
  if (shape === 'dl') return buildDl(table);
  if (shape === 'grid') return buildGrid(tableNode);
  return buildRecords(table, key, usedIds);
}

// ---------------------------------------------------------------------------
// the plugin
// ---------------------------------------------------------------------------

/** Collect every `properties.id` already in the tree, so new slugs avoid them. */
function collectIds(node, into) {
  if (!node) return;
  if (node.type === 'element' && typeof node.properties?.id === 'string') {
    into.add(node.properties.id);
  }
  if (Array.isArray(node.children)) {
    for (const child of node.children) collectIds(child, into);
  }
}

/**
 * Replace every `<table>` in `node`'s subtree with its shaped equivalent,
 * consuming a directive comment immediately before it (only whitespace text
 * nodes in between) when one parses.
 */
function walk(node, ctx) {
  const children = node?.children;
  if (!Array.isArray(children)) return;

  for (let i = 0; i < children.length; i++) {
    const child = children[i];

    if (isElement(child, 'table')) {
      let j = i - 1;
      while (j >= 0 && isWhitespaceText(children[j])) j--;

      let directive = null;
      let directiveStart = i;
      if (j >= 0 && children[j].type === 'comment') {
        const parsed = parseDirective(children[j].value);
        if (parsed) {
          directive = parsed;
          directiveStart = j;
        }
      }

      const replacement = transformTable(child, directive, ctx);
      children.splice(directiveStart, i - directiveStart + 1, replacement);
      i = directiveStart;
      continue;
    }

    walk(child, ctx);
  }
}

/** The plugin: `() => (tree) => void`. A classic rehype-style plugin, exactly
 * per spec — used directly by the unit tests in `test/tables.test.mjs` against
 * hand-built hast trees, and importable as `markdown.rehypePlugins` on a
 * processor that supports that classic contract. */
export default function rehypeLqTables() {
  return (tree) => {
    const usedIds = new Set();
    collectIds(tree, usedIds);
    walk(tree, { usedIds });
  };
}

// ---------------------------------------------------------------------------
// Sätteri integration adapter
// ---------------------------------------------------------------------------
//
// This workspace's installed Markdown processor is `@astrojs/markdown-satteri`
// (Astro 7's default), not `@astrojs/markdown-remark` — `markdown.rehypePlugins`
// does not exist as a config option here (Astro's own config validator throws
// asking for `@astrojs/markdown-remark` to be installed, which the "no new npm
// dependencies" constraint rules out). Sätteri instead takes `hastPlugins`, an
// array of `{ name, before?, after?, element?, comment?, ... }` visitor objects
// (see `node_modules/satteri/dist/hast/hast-visitor.d.ts`). Two things were
// verified empirically against this exact pipeline before writing this adapter
// (see `_probe_satteri*.mjs`, not part of the repo):
//
// 1. An `after(root, ctx)` hook is handed a *materialized* hast root that can
//    be walked like an ordinary tree, but mutating its `children` arrays
//    directly (the classic-plugin approach `rehypeLqTables()` above uses) is
//    silently discarded — it never reaches the rendered HTML. Mutations must
//    go through the hook's `ctx`: `ctx.replaceNode(node, newNode)` and
//    `ctx.removeNode(node)` do apply and were confirmed to render correctly.
// 2. An HTML comment immediately before a Markdown table *does* survive this
//    pipeline (the spec asked this to be checked, not assumed) — but not as a
//    `{ type: 'comment', value: '<inner text>' }` node the way the classic
//    remark-rehype + rehype-raw pipeline the spec describes would produce it.
//    Sätteri materializes it as `{ type: 'raw', value: '<!-- inner text -->' }`
//    — the whole literal `<!-- … -->`, delimiters included. `directiveValueOf`
//    below unwraps that shape (as well as a plain `comment` node, for
//    resilience if the processor ever changes) before handing the inner text
//    to the same `parseDirective` the classic path and the unit tests use. No
//    fallback (a `{table: …}` paragraph marker) was needed — the directive
//    comment syntax in the spec works as written once this shape difference is
//    accounted for.

const RAW_HTML_COMMENT_RE = /^<!--([\s\S]*)-->$/;

/** The directive comment's inner text (between `<!--` and `-->`), from either
 * hast shape a Markdown comment can arrive in — `null` if `node` isn't one. */
function directiveValueOf(node) {
  if (!node || typeof node.value !== 'string') return null;
  if (node.type === 'comment') return node.value;
  if (node.type === 'raw') {
    const match = RAW_HTML_COMMENT_RE.exec(node.value.trim());
    if (match) return match[1];
  }
  return null;
}

const isCommentLike = (node) => directiveValueOf(node) !== null;

/**
 * Walk `node`'s subtree using the Sätteri hook `ctx`'s structural-mutation
 * methods (`replaceNode`, `removeNode`) instead of direct array splicing, so
 * the transform actually reaches the rendered page. Shares every pure helper
 * above (`readTable`, `classifyTable`, `transformTable`, `parseDirective`)
 * with the classic-plugin path; only how a replacement is *applied* differs.
 */
function walkSatteri(node, hookCtx, tableCtx) {
  const children = node?.children;
  if (!Array.isArray(children)) return;

  for (let i = 0; i < children.length; i++) {
    const child = children[i];

    if (isElement(child, 'table')) {
      let j = i - 1;
      while (j >= 0 && isWhitespaceText(children[j])) j--;

      let directive = null;
      let directiveNode = null;
      if (j >= 0 && isCommentLike(children[j])) {
        const parsed = parseDirective(directiveValueOf(children[j]));
        if (parsed) {
          directive = parsed;
          directiveNode = children[j];
        }
      }

      const replacement = transformTable(child, directive, tableCtx);
      hookCtx.replaceNode(child, replacement);
      if (directiveNode) hookCtx.removeNode(directiveNode);
      continue;
    }

    walkSatteri(child, hookCtx, tableCtx);
  }
}

/**
 * The Sätteri `hastPlugins` entry: `{ name, after(root, ctx) }`. Wire into
 * `astro.config.mjs` via `satteri({ hastPlugins: [rehypeLqTablesSatteri()] })`
 * (from `@astrojs/markdown-satteri`), not `markdown.rehypePlugins` — see the
 * note above.
 */
export function rehypeLqTablesSatteri() {
  return {
    name: 'lq-tables',
    after(root, hookCtx) {
      const usedIds = new Set();
      collectIds(root, usedIds);
      walkSatteri(root, hookCtx, { usedIds });
    },
  };
}
