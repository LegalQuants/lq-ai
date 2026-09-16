/**
 * Unit tests for `scripts/lib/rehype-lq-tables.mjs` — the pure helpers
 * (`readTable`, `classifyTable`, `transformTable`, `parseDirective`) and the
 * plugin's tree walk, exercised directly against hand-built hast, no Astro
 * involved. `node --test`, `node:assert` — same policy as `sync.test.mjs`:
 * no test framework dependency for four Node scripts and a Python one.
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import rehypeLqTables, {
  classifyTable,
  parseDirective,
  readTable,
  transformTable,
} from '../scripts/lib/rehype-lq-tables.mjs';

// ---------------------------------------------------------------------------
// fixture builder
// ---------------------------------------------------------------------------

/** A cell as a hast `children` array: a bare string becomes one text node, an array is used as-is (so a test can exercise `code`/`a`/`em`/`strong` survival). */
const cellChildren = (cell) => (typeof cell === 'string' ? [{ type: 'text', value: cell }] : cell);

const cellEl = (tagName, cell) => ({
  type: 'element',
  tagName,
  properties: {},
  children: cellChildren(cell),
});

const rowEl = (cells, tagName) => ({
  type: 'element',
  tagName: 'tr',
  properties: {},
  children: cells.map((cell) => cellEl(tagName, cell)),
});

/**
 * Build a `<table>` hast node from a header row and body rows.
 *
 * `{ sections: false }` skips the `thead`/`tbody` wrappers and emits the
 * rows as direct `tr` children of `table` instead — the shape "some
 * generators emit only `tr`s" describes.
 */
function table(headers, rows, { sections = true } = {}) {
  const headerRow = rowEl(headers, sections ? 'th' : 'td');
  const bodyRows = rows.map((r) => rowEl(r, 'td'));

  if (!sections) {
    return { type: 'element', tagName: 'table', properties: {}, children: [headerRow, ...bodyRows] };
  }

  const children = [{ type: 'element', tagName: 'thead', properties: {}, children: [headerRow] }];
  if (bodyRows.length) {
    children.push({ type: 'element', tagName: 'tbody', properties: {}, children: bodyRows });
  }
  return { type: 'element', tagName: 'table', properties: {}, children };
}

/** Walk a hast (sub)tree, returning every node matching `predicate`. */
function findAll(node, predicate, out = []) {
  if (!node) return out;
  if (predicate(node)) out.push(node);
  for (const child of node.children ?? []) findAll(child, predicate, out);
  return out;
}

const textOf = (node) => findAll(node, (n) => n.type === 'text').map((n) => n.value).join('');
const classOf = (node) => node.properties?.class ?? '';

// ---------------------------------------------------------------------------
// parseDirective
// ---------------------------------------------------------------------------

describe('parseDirective', () => {
  it('parses a bare shape directive', () => {
    assert.deepEqual(parseDirective(' table: grid '), { shape: 'grid' });
    assert.deepEqual(parseDirective('table: dl'), { shape: 'dl' });
    assert.deepEqual(parseDirective('table: records'), { shape: 'records' });
  });

  it('parses a records directive with a key', () => {
    assert.deepEqual(parseDirective(' table: records key=2 '), { shape: 'records', key: 2 });
  });

  it('returns null for a comment that is not a directive', () => {
    assert.equal(parseDirective(' just a comment '), null);
    assert.equal(parseDirective(' table: bogus '), null);
    assert.equal(parseDirective(''), null);
  });
});

// ---------------------------------------------------------------------------
// readTable
// ---------------------------------------------------------------------------

describe('readTable', () => {
  it('reads headers and rows, keeping inline hast and computing trimmed text', () => {
    const codeSpan = [{ type: 'element', tagName: 'code', properties: {}, children: [{ type: 'text', value: 'lq_ai_docling_enabled' }] }];
    const t = table(['Setting', 'Default'], [[codeSpan, '  true  ']]);
    const result = readTable(t);

    assert.deepEqual(result.headerText, ['Setting', 'Default']);
    assert.deepEqual(result.cellText, [['lq_ai_docling_enabled', 'true']]);
    // The code element survives as hast, not flattened to text.
    assert.equal(result.rows[0][0][0].type, 'element');
    assert.equal(result.rows[0][0][0].tagName, 'code');
  });

  it('treats the first row as the header when there is no thead (only trs)', () => {
    const t = table(['Tag', 'Tagged', 'Notes'], [['v0.7.0', '2026-08-01', 'minor']], { sections: false });
    const result = readTable(t);

    assert.deepEqual(result.headerText, ['Tag', 'Tagged', 'Notes']);
    assert.deepEqual(result.cellText, [['v0.7.0', '2026-08-01', 'minor']]);
  });

  it('returns no rows for a header-only table', () => {
    const t = table(['A', 'B'], []);
    const result = readTable(t);
    assert.deepEqual(result.headerText, ['A', 'B']);
    assert.deepEqual(result.rows, []);
  });
});

// ---------------------------------------------------------------------------
// classifyTable
// ---------------------------------------------------------------------------

describe('classifyTable', () => {
  it('classifies a 2-column table as dl', () => {
    const t = readTable(table(['Setting', 'Description'], [['a', 'b']]));
    assert.deepEqual(classifyTable(t, null), { shape: 'dl', key: 1 });
  });

  it('classifies short wide-enough tables as grid', () => {
    const t = readTable(
      table(
        ['Tag', 'Tagged', 'Notes'],
        [
          ['v0.7.1', '2026-09-01', 'patch'],
          ['v0.7.0', '2026-08-01', 'minor'],
        ]
      )
    );
    assert.deepEqual(classifyTable(t, null), { shape: 'grid', key: 1 });
  });

  it('falls back to records when a column is long', () => {
    const t = readTable(
      table(
        ['Setting', 'Type', 'Default', 'Description'],
        [
          [
            'LQ_AI_DOCLING_ENABLED',
            'boolean',
            'false',
            'Whether the Docling ingestion path is enabled for this deployment.',
          ],
        ]
      )
    );
    assert.deepEqual(classifyTable(t, null), { shape: 'records', key: 1 });
  });

  it('a directive wins over the measured classification', () => {
    const t = readTable(
      table(
        ['Setting', 'Type', 'Default', 'Description'],
        [['A', 'boolean', 'false', 'A description long enough to force records on its own merit.']]
      )
    );
    assert.deepEqual(classifyTable(t, { shape: 'grid' }), { shape: 'grid', key: 1 });
    assert.deepEqual(classifyTable(t, { shape: 'records', key: 2 }), { shape: 'records', key: 2 });
  });
});

// ---------------------------------------------------------------------------
// transformTable — dl
// ---------------------------------------------------------------------------

describe('transformTable — dl', () => {
  const t = table(
    ['Setting', 'Description'],
    [
      ['lq_ai_docling_enabled', 'Enables the Docling path.'],
      ['lq_ai_empty', ''],
    ]
  );

  const result = transformTable(t, null);

  it('wraps a caption and a dl in the documented shape', () => {
    assert.equal(result.tagName, 'div');
    assert.equal(classOf(result), 'lq-dl');
    assert.equal(result.properties.role, 'group');
    assert.equal(result.properties['aria-label'], 'Setting and Description');

    const [caption, dl] = result.children;
    assert.equal(classOf(caption), 'lq-dl__caption');
    assert.equal(textOf(caption), 'Setting → Description');
    assert.equal(dl.tagName, 'dl');

    const items = dl.children;
    assert.equal(items.length, 2);
    for (const item of items) {
      assert.equal(classOf(item), 'lq-dl__item');
      assert.deepEqual(item.children.map((c) => c.tagName), ['dt', 'dd']);
    }
  });

  it('gives an empty value cell a muted em dash', () => {
    const [, dl] = result.children;
    const emptyItem = dl.children[1];
    const dd = emptyItem.children[1];
    assert.equal(dd.children.length, 1);
    assert.equal(classOf(dd.children[0]), 'lq-muted');
    assert.equal(textOf(dd), '—');
  });
});

// ---------------------------------------------------------------------------
// transformTable — grid
// ---------------------------------------------------------------------------

describe('transformTable — grid', () => {
  it('keeps the original table, wrapped, untouched', () => {
    const t = table(
      ['Tag', 'Tagged', 'Notes'],
      [['v0.7.1', '2026-09-01', 'patch']]
    );
    const result = transformTable(t, null);

    assert.equal(result.tagName, 'div');
    assert.equal(classOf(result), 'lq-table');
    assert.equal(result.properties.tabindex, undefined);
    assert.equal(result.properties.role, undefined);
    assert.equal(result.children.length, 1);
    assert.strictEqual(result.children[0], t, 'the original table node is reused, not rebuilt');
  });

  it('a directive overrides a table that would otherwise become records', () => {
    const t = table(
      ['Setting', 'Type', 'Default', 'Description'],
      [['A', 'boolean', 'false', 'A description long enough to force records on its own merit, easily.']]
    );
    const result = transformTable(t, { shape: 'grid' });
    assert.equal(classOf(result), 'lq-table');
    assert.equal(result.children[0].tagName, 'table');
  });
});

// ---------------------------------------------------------------------------
// transformTable — records
// ---------------------------------------------------------------------------

describe('transformTable — records', () => {
  const longDescription =
    'Whether the Docling ingestion path is enabled for this deployment; long enough to force the body.';

  const t = table(
    ['Setting', 'Type', 'Default', 'Description'],
    [['LQ_AI_DOCLING_ENABLED', 'boolean', 'false', longDescription]]
  );

  const result = transformTable(t, null, { usedIds: new Set() });

  it('wraps records in the documented shape, keyed on column 1 by default', () => {
    assert.equal(classOf(result), 'lq-records');
    assert.equal(result.children.length, 1);

    const article = result.children[0];
    assert.equal(article.tagName, 'article');
    assert.equal(classOf(article), 'lq-record');
    assert.equal(article.properties.id, 'lq_ai_docling_enabled');
    assert.equal(article.properties['aria-labelledby'], 'lq_ai_docling_enabled-title');

    const title = article.children[0];
    assert.equal(classOf(title), 'lq-record__title');
    assert.equal(title.properties.id, 'lq_ai_docling_enabled-title');
    assert.equal(textOf(title), 'LQ_AI_DOCLING_ENABLED');
  });

  it('splits short columns into meta and long columns into the body', () => {
    const article = result.children[0];
    const meta = article.children.find((c) => classOf(c) === 'lq-record__meta');
    const body = article.children.find((c) => classOf(c) === 'lq-record__body');

    assert.ok(meta, 'meta line present');
    assert.ok(body, 'body present');

    const metaFields = meta.children.filter((c) => c.type === 'element');
    assert.equal(metaFields.length, 2); // Type, Default
    assert.equal(textOf(metaFields[0]), 'Type boolean');
    assert.equal(textOf(metaFields[1]), 'Default false');

    assert.equal(body.children.length, 1); // Description
    assert.equal(classOf(body.children[0]), 'lq-record__field lq-record__field--long');
    assert.match(textOf(body.children[0]), /^Description/);
    assert.match(textOf(body.children[0]), /force the body\.$/);
  });

  it('omits the meta line when every non-key column is long', () => {
    const allLong = table(['Setting', 'Type', 'Notes'], [['A', 'x'.repeat(40), 'y'.repeat(40)]]);
    const r = transformTable(allLong, { shape: 'records' }, { usedIds: new Set() });
    const article = r.children[0];
    assert.equal(article.children.find((c) => classOf(c) === 'lq-record__meta'), undefined);
    assert.ok(article.children.find((c) => classOf(c) === 'lq-record__body'));
  });

  it('omits the body when every non-key column is short', () => {
    const allShort = table(['Setting', 'Type', 'Status'], [['A', 'x', 'draft']]);
    const r = transformTable(allShort, { shape: 'records' }, { usedIds: new Set() });
    const article = r.children[0];
    assert.ok(article.children.find((c) => classOf(c) === 'lq-record__meta'));
    assert.equal(article.children.find((c) => classOf(c) === 'lq-record__body'), undefined);
  });

  it('honours a `records key=2` directive for the title column', () => {
    const adrIndex = table(
      ['ADR', 'Decision', 'Status'],
      [['0028', 'Deployment target is configuration, not content', 'accepted']]
    );
    const r = transformTable(adrIndex, { shape: 'records', key: 2 }, { usedIds: new Set() });
    const article = r.children[0];
    assert.equal(textOf(article.children[0]), 'Deployment target is configuration, not content');
    // ADR and Status are both short, and become meta fields (not the title).
    const meta = article.children.find((c) => classOf(c) === 'lq-record__meta');
    assert.equal(textOf(meta), 'ADR 0028 Status accepted');
  });
});

// ---------------------------------------------------------------------------
// records — slugs
// ---------------------------------------------------------------------------

describe('transformTable — records slugs', () => {
  it('slugifies the key cell, lower-cased, non-alphanumerics to `-`', () => {
    const t = table(['Setting', 'Description'], [['LQ AI: Docling / Enabled!', 'x'.repeat(40)]]);
    const r = transformTable(t, { shape: 'records' }, { usedIds: new Set() });
    assert.equal(r.children[0].properties.id, 'lq-ai-docling-enabled');
  });

  it('keeps underscores as alphanumeric-adjacent', () => {
    const t = table(['Setting', 'Description'], [['lq_ai_docling_enabled', 'x'.repeat(40)]]);
    const r = transformTable(t, { shape: 'records' }, { usedIds: new Set() });
    assert.equal(r.children[0].properties.id, 'lq_ai_docling_enabled');
  });

  it('appends -2, -3, … on collision, in row order', () => {
    const t = table(
      ['Setting', 'Description'],
      [
        ['dup', 'x'.repeat(40)],
        ['dup', 'x'.repeat(40)],
        ['dup', 'x'.repeat(40)],
      ]
    );
    const r = transformTable(t, { shape: 'records' }, { usedIds: new Set() });
    assert.deepEqual(
      r.children.map((a) => a.properties.id),
      ['dup', 'dup-2', 'dup-3']
    );
  });

  it('collides against ids already used elsewhere (shared ctx)', () => {
    const usedIds = new Set(['dup']);
    const t = table(['Setting', 'Description'], [['dup', 'x'.repeat(40)]]);
    const r = transformTable(t, { shape: 'records' }, { usedIds });
    assert.equal(r.children[0].properties.id, 'dup-2');
  });

  it('falls back to row-<n> for an empty key cell', () => {
    const t = table(
      ['Setting', 'Description'],
      [
        ['', 'x'.repeat(40)],
        ['named', 'x'.repeat(40)],
        ['   ', 'x'.repeat(40)],
      ]
    );
    const r = transformTable(t, { shape: 'records' }, { usedIds: new Set() });
    assert.equal(r.children[0].properties.id, 'row-1');
    assert.equal(r.children[1].properties.id, 'named');
    assert.equal(r.children[2].properties.id, 'row-3');
  });
});

// ---------------------------------------------------------------------------
// records — status class
// ---------------------------------------------------------------------------

describe('transformTable — status class', () => {
  it('marks a status-word value with lq-status--<word>, case-insensitively', () => {
    const t = table(['ADR', 'Decision', 'Status'], [['0028', 'x'.repeat(40), 'Accepted']]);
    const r = transformTable(t, null, { usedIds: new Set() });
    const meta = r.children[0].children.find((c) => classOf(c) === 'lq-record__meta');
    const statusField = meta.children.find((c) => c.type === 'element' && textOf(c).startsWith('Status'));
    const valueSpan = statusField.children.at(-1);
    assert.equal(classOf(valueSpan), 'lq-record__value lq-status lq-status--accepted');
  });

  it('leaves a non-status value with the plain value class', () => {
    const t = table(['ADR', 'Decision', 'Status'], [['0028', 'x'.repeat(40), 'n/a']]);
    const r = transformTable(t, null, { usedIds: new Set() });
    const meta = r.children[0].children.find((c) => classOf(c) === 'lq-record__meta');
    const statusField = meta.children.find((c) => c.type === 'element' && textOf(c).startsWith('Status'));
    const valueSpan = statusField.children.at(-1);
    assert.equal(classOf(valueSpan), 'lq-record__value');
  });
});

// ---------------------------------------------------------------------------
// the plugin — comment handling, end to end
// ---------------------------------------------------------------------------

describe('rehypeLqTables (default export)', () => {
  const run = (tree) => {
    rehypeLqTables()(tree);
    return tree;
  };

  it('consumes a directive comment immediately before a table', () => {
    const tree = {
      type: 'root',
      children: [
        { type: 'comment', value: ' table: grid ' },
        table(['Tag', 'Tagged', 'Notes'], [['v0.7.1', '2026-09-01', 'patch']]),
      ],
    };
    run(tree);
    assert.equal(tree.children.length, 1);
    assert.equal(tree.children[0].type, 'element');
    assert.equal(classOf(tree.children[0]), 'lq-table');
  });

  it('tolerates whitespace-only text nodes between the comment and the table', () => {
    const tree = {
      type: 'root',
      children: [
        { type: 'comment', value: ' table: dl ' },
        { type: 'text', value: '\n\n' },
        table(['Setting', 'Description'], [['a', 'b']]),
      ],
    };
    run(tree);
    assert.equal(tree.children.length, 1);
    assert.equal(classOf(tree.children[0]), 'lq-dl');
  });

  it('leaves a comment alone when it is not a table directive', () => {
    const tree = {
      type: 'root',
      children: [
        { type: 'comment', value: ' unrelated comment ' },
        table(['Setting', 'Description'], [['a', 'b']]),
      ],
    };
    run(tree);
    assert.equal(tree.children.length, 2);
    assert.equal(tree.children[0].type, 'comment');
    assert.equal(classOf(tree.children[1]), 'lq-dl'); // still classified on its own merit
  });

  it('walks into nested containers (e.g. a table inside an aside)', () => {
    const tree = {
      type: 'root',
      children: [
        {
          type: 'element',
          tagName: 'aside',
          properties: {},
          children: [table(['Setting', 'Description'], [['a', 'b']])],
        },
      ],
    };
    run(tree);
    const aside = tree.children[0];
    assert.equal(classOf(aside.children[0]), 'lq-dl');
  });

  it('avoids a slug already used elsewhere in the document', () => {
    const tree = {
      type: 'root',
      children: [
        { type: 'element', tagName: 'h2', properties: { id: 'dup' }, children: [{ type: 'text', value: 'Dup' }] },
        { type: 'comment', value: ' table: records ' },
        table(['Setting', 'Description'], [['dup', 'x'.repeat(40)]]),
      ],
    };
    run(tree);
    const records = tree.children[1];
    assert.equal(classOf(records), 'lq-records');
    assert.equal(records.children[0].properties.id, 'dup-2');
  });

  it('keeps slugs unique across two tables in the same document', () => {
    const tree = {
      type: 'root',
      children: [
        { type: 'comment', value: ' table: records ' },
        table(['Setting', 'Description'], [['dup', 'x'.repeat(40)]]),
        { type: 'comment', value: ' table: records ' },
        table(['Setting', 'Description'], [['dup', 'x'.repeat(40)]]),
      ],
    };
    run(tree);
    assert.equal(tree.children[0].children[0].properties.id, 'dup');
    assert.equal(tree.children[1].children[0].properties.id, 'dup-2');
  });
});
