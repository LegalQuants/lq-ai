/**
 * The supported-shapes table — "which of these hosting combinations is mine?"
 * (journey J22).
 *
 * Not a page of its own: a page writes `<!-- supported-shapes -->` where the
 * table belongs and the sync replaces the directive. The data is
 * `docs/site/_data/supported-shapes.yaml`, so the one list of what the project
 * has and has not tried lives in one file that a reviewer can diff, rather than
 * in prose on whichever page happened to need it.
 *
 * The honest part of this table is the `not tried` rows. A hosting shape with
 * no recipe says so, and says it with the same weight as a shape that has one —
 * an operator deciding where to run this needs the negative answer more than
 * the positive one.
 */

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

import YAML from 'yaml';

import { withBase } from './lib/paths.mjs';
import { blobUrl } from './lib/links.mjs';
import { cell, table } from './lib/markdown.mjs';

const DATA_FILE = '_data/supported-shapes.yaml';

/** `recipe published` and `recipe-published` are the same status. */
const normalise = (status) =>
  String(status ?? '')
    .trim()
    .toLowerCase()
    .replace(/[-_]+/g, ' ');

const KNOWN = new Set(['recipe published', 'known to work', 'not tried']);

/**
 * Render the table.
 *
 * @param {object} options
 * @param {string} options.docsSiteDir
 * @param {string} options.sha       commit the `source` links pin to
 * @param {(problem: object) => void} options.report
 * @returns {Promise<string>}
 */
export async function renderSupportedShapes({ docsSiteDir, sha, report }) {
  const file = path.join(docsSiteDir, DATA_FILE);
  if (!existsSync(file)) {
    report({
      level: 'warn',
      line: 1,
      message: `<!-- supported-shapes --> but no docs/site/${DATA_FILE} — rendered as "not recorded"`,
    });
    return '_The supported-shapes table is not recorded in the repository as of the checked commit._';
  }

  let data;
  try {
    data = YAML.parse(readFileSync(file, 'utf8'));
  } catch (error) {
    report({ level: 'error', line: 1, message: `${DATA_FILE} does not parse: ${error.message}` });
    return '';
  }

  const shapes = Array.isArray(data?.shapes) ? data.shapes : [];
  if (shapes.length === 0) {
    report({ level: 'warn', line: 1, message: `${DATA_FILE} lists no shapes` });
    return '_No hosting shapes are recorded in the repository as of the checked commit._';
  }

  const rows = shapes.map((shape) => {
    const name = shape.name ?? shape.topology ?? '(unnamed)';
    const status = normalise(shape.status);
    if (!KNOWN.has(status)) {
      report({
        level: 'warn',
        line: 1,
        message: `${DATA_FILE}: "${name}" has status "${shape.status}" — expected one of ${[...KNOWN].join(', ')}`,
      });
    }

    const recipe = shape.recipe
      ? `[Read the recipe](${withBase(`operate/${String(shape.recipe).replace(/^\/+/, '')}`)})`
      : 'none';

    const notes = [];
    if (shape.notes) notes.push(cell(shape.notes));
    if (shape.source) notes.push(`Checked against [\`${shape.source}\`](${blobUrl(sha, shape.source)}).`);
    if (!shape.source && status === 'not tried' && !shape.notes) {
      notes.push('Not documented in the repository as of the checked commit.');
    }

    return [name, status || 'not recorded', recipe, notes.join(' ')];
  });

  return table(['Topology', 'Status', 'Recipe', 'Notes'], rows);
}
