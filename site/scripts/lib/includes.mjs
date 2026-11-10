/**
 * `<!-- include: … -->` — curation without copies.
 *
 * A page that presents a canonical repository file does not paste it. It names
 * it, and the build pulls the text in at sync time. That is the whole reason
 * the site can promise that a page does not drift from the file it presents:
 * there is no second copy to drift.
 *
 *     <!-- include: docs/quickstart.md -->
 *     <!-- include: docs/INSTALL-MAC.md from="## Install" to="## Troubleshooting" -->
 *     <!-- include: docs/security/threat-model.md shift=1 -->
 *
 * Rules, in the order they are applied:
 *
 *  1. the source's own YAML frontmatter is dropped (a SKILL.md has one);
 *  2. the source's H1 is dropped — the page's `title` is the page's title;
 *  3. `from` / `to` slice between two **exact heading lines**, `to` exclusive;
 *  4. `shift=N` demotes every heading by N levels, so the included outline
 *     nests under the including page's own headings;
 *  5. links inside the included text resolve from the **source file's** own
 *     directory, not the page's, and are then mapped like any other link.
 *
 * A missing file, or a `from`/`to` heading that is not in the file, fails the
 * sync and names the page and line. The failure mode this prevents is the one
 * that matters: a heading renamed upstream, an include that silently yields
 * nothing, and a trust-centre page that quietly ships empty.
 */

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

import { REPO_ROOT } from './paths.mjs';
import { dropFirstH1, scanLines, shiftHeadings, sliceBetweenHeadings, stripFrontmatter } from './markdown.mjs';

const DIRECTIVE = /^[ \t]*<!--\s*include:\s*([\s\S]*?)\s*-->[ \t]*$/;

/** Parse the directive body into `{ file, from, to, shift }`. */
export function parseDirective(spec) {
  const text = String(spec).trim();
  const file = text.split(/\s+/)[0];
  const attr = (name) => {
    const found = new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|(\\S+))`).exec(text);
    return found ? (found[1] ?? found[2] ?? found[3]) : undefined;
  };
  return {
    file,
    from: attr('from'),
    to: attr('to'),
    shift: Number(attr('shift') || 0) || 0,
  };
}

/**
 * Expand every include directive in `text`.
 *
 * @param {string} text
 * @param {object} options
 * @param {string} options.baseDir     directory relative links in `text` resolve from
 * @param {(chunk: string, dir: string) => string} options.mapLinks
 * @param {(problem: object) => void} options.report
 * @param {string} options.page        the page path, for error messages
 * @param {string} [options.origin]    the file the text came from, for error messages
 * @param {(relPath: string, directive: object) => void} [options.onInclude]
 * @param {number} [options.depth]
 * @returns {string}
 */
export function expandIncludes(text, options) {
  const { baseDir, mapLinks, report, page, origin = page, onInclude, depth = 0 } = options;

  if (depth > 4) {
    report({
      level: 'error',
      page,
      file: origin,
      line: 1,
      message: 'include nesting deeper than four levels — refusing to recurse further',
    });
    return text;
  }

  const lines = scanLines(text);
  const out = lines.map((entry, index) => {
    if (entry.inFence) return entry.line;
    const match = DIRECTIVE.exec(entry.line);
    if (!match) return entry.line;

    const directive = parseDirective(match[1]);
    const where = { page, file: origin, line: index + 1 };

    if (!directive.file) {
      report({ level: 'error', ...where, message: 'include directive names no file' });
      return entry.line;
    }

    const absolute = path.resolve(REPO_ROOT, directive.file);
    if (!existsSync(absolute)) {
      report({
        level: 'error',
        ...where,
        message: `include target "${directive.file}" does not exist in the repository`,
      });
      return entry.line;
    }

    onInclude?.(directive.file, directive);

    let body = dropFirstH1(stripFrontmatter(readFileSync(absolute, 'utf8')));

    if (directive.from || directive.to) {
      const sliced = sliceBetweenHeadings(body, directive.from, directive.to);
      if (!sliced.ok) {
        const wanted = sliced.missing === 'from' ? directive.from : directive.to;
        report({
          level: 'error',
          ...where,
          message: `include of "${directive.file}": heading ${sliced.missing}="${wanted}" is not in the file`,
        });
        return entry.line;
      }
      body = sliced.text;
    }

    body = shiftHeadings(body, directive.shift);

    const sourceDir = path.dirname(absolute);
    body = expandIncludes(body, {
      ...options,
      baseDir: sourceDir,
      origin: directive.file,
      depth: depth + 1,
    });

    return mapLinks(body, sourceDir).trim();
  });

  return out.join('\n');
}

/** Every file a page includes, in source order. Used to cross-check `sources:`. */
export function includedFiles(text) {
  return scanLines(text)
    .filter((entry) => !entry.inFence)
    .map((entry) => DIRECTIVE.exec(entry.line))
    .filter(Boolean)
    .map((match) => parseDirective(match[1]).file)
    .filter(Boolean);
}
