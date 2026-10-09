/**
 * Link resolution — the rule that lets a writer use ordinary relative Markdown
 * links and still get correct URLs on a site whose base path is configuration.
 *
 * A writer writes `[threat model](../trust/threat-model.md)`. GitHub renders
 * it, `docs/audits/check_doc_links.py` checks it, and this module turns it into
 * whatever it should actually be:
 *
 * | The target is…                                   | It becomes                              |
 * |--------------------------------------------------|-----------------------------------------|
 * | another page under `docs/site/`                   | that page's route, with the base        |
 * | a `*.intro.md` beside a generated page            | the generated page's route              |
 * | the primary `sources[0]` of some page, no anchor  | that page's route                       |
 * | an image anywhere in the repository               | a copy under `<base>_repo/…`            |
 * | any other file in the repository                  | a GitHub blob URL pinned to the stamp   |
 * | a directory in the repository                     | a GitHub tree URL pinned to the stamp   |
 * | an absolute URL, a bare `#anchor`, a mailto:      | itself, untouched                       |
 *
 * Anchors survive every branch. A `.md` link that resolves to nothing fails the
 * sync with the file and line — a dead link on a trust centre is worse than a
 * red build.
 *
 * Two deliberate narrowings of the `sources[0]` rule, because the rule can do
 * harm where it was meant to help:
 *
 *  - **A link carrying an anchor is never rewritten to a page route.** The
 *    anchor names a heading inside the canonical file; the curating page may
 *    not carry that heading, and silently landing the reader at the top of a
 *    different document loses the thing they were sent to read. It pins to the
 *    blob instead, where the anchor works.
 *  - **The entry hub is not a presentation of its first source.** `/` curates
 *    eight namespaces, so `README.md` links resolve to the repository, not to
 *    the home page.
 *
 * Both are reported by `npm run sync` when they fire, so the narrowing is
 * visible rather than folklore.
 */

import { existsSync, statSync } from 'node:fs';
import path from 'node:path';

import { DOCS_SITE_DIR, REPO_ROOT, SITE_BASE, repoPath, withBase } from './paths.mjs';
import { blobSha } from './git.mjs';
import { scanLines } from './markdown.mjs';

const REPO_URL = 'https://github.com/LegalQuants/lq-ai';

const IMAGE = /\.(png|jpe?g|svg|gif|webp|avif)$/i;
const MARKDOWN = /\.mdx?$/i;
const ABSOLUTE = /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i;

/** A repository file, served from the site rather than from GitHub. */
export const assetUrl = (relPath) => `${SITE_BASE}_repo/${relPath}`;

/** A repository file at an exact commit. */
export const blobUrl = (sha, relPath) => `${REPO_URL}/blob/${blobSha(sha)}/${relPath}`;

/** A repository directory at an exact commit. */
export const treeUrl = (sha, relPath) => `${REPO_URL}/tree/${blobSha(sha)}/${relPath}`;

/**
 * Split `path#anchor?query` into its parts without decoding the path, so a
 * filename containing a space survives the round trip.
 */
function splitTarget(raw) {
  const target = raw.replace(/^<|>$/g, '');
  const hashAt = target.indexOf('#');
  const queryAt = target.indexOf('?');
  const cut = [hashAt, queryAt].filter((i) => i !== -1).sort((a, b) => a - b)[0];
  if (cut === undefined) return { file: target, suffix: '' };
  return { file: target.slice(0, cut), suffix: target.slice(cut) };
}

/**
 * Build the resolver.
 *
 * @param {object} options
 * @param {Map<string,string>} options.routeByRepoPath  docs/site file → route
 * @param {Map<string,string>} options.routeBySourceFile canonical file → route
 * @param {(relPath: string) => void} options.copyAsset  called for each image
 * @param {(problem: object) => void} options.report     every failure and warning
 */
export function createResolver({ routeByRepoPath, routeBySourceFile, copyAsset, report }) {
  /**
   * @param {string} raw      the link target exactly as written
   * @param {string} baseDir  absolute directory the link is relative to
   * @param {object} where    `{ page, file, line }` for the error message
   * @param {string} sha      the commit repository links pin to
   */
  return function resolve(raw, baseDir, where, sha) {
    const { file, suffix } = splitTarget(raw);

    // A bare anchor, an absolute URL, a mailto: — all already correct.
    if (!file) return raw;
    if (ABSOLUTE.test(file)) return raw;

    if (file.startsWith('/')) {
      report({
        level: 'warn',
        ...where,
        message: `root-absolute link "${raw}" — the authoring contract asks for a relative .md link (the base path is configuration)`,
      });
      return raw;
    }

    let decoded;
    try {
      decoded = decodeURIComponent(file);
    } catch {
      decoded = file;
    }

    const absolute = path.resolve(baseDir, decoded);
    const rel = repoPath(absolute);

    if (rel.startsWith('../')) {
      report({
        level: 'error',
        ...where,
        message: `link "${raw}" resolves outside the repository (${rel})`,
      });
      return raw;
    }

    const isMarkdown = MARKDOWN.test(rel);

    // 1. Another page — including a generated page reached through its intro.
    const route = routeByRepoPath.get(rel);
    if (route !== undefined) return withBase(route) + suffix;

    // 2. A canonical file that some page presents. Never when an anchor is
    //    carried: the anchor belongs to the canonical file's own headings.
    if (!suffix.startsWith('#')) {
      const presented = routeBySourceFile.get(rel);
      if (presented !== undefined) return withBase(presented) + suffix;
    }

    const exists = existsSync(absolute);

    // 3. An image, copied into the site so the page does not hotlink GitHub.
    if (IMAGE.test(rel)) {
      if (!exists) {
        report({ level: 'error', ...where, message: `image "${raw}" does not exist (${rel})` });
        return raw;
      }
      copyAsset(rel);
      return assetUrl(rel) + suffix;
    }

    // 4. Anything else in the repository, pinned to the commit this page was
    //    checked against, so the link shows what the page was written from.
    if (exists) {
      const url = statSync(absolute).isDirectory() ? treeUrl(sha, rel) : blobUrl(sha, rel);
      return url + suffix;
    }

    if (isMarkdown) {
      const looksLikeAPage = rel.startsWith(`${repoPath(DOCS_SITE_DIR)}/`);
      report({
        level: 'error',
        ...where,
        message: looksLikeAPage
          ? `link "${raw}" points at a page that does not exist yet (${rel}) — either the page is still to be written, or the link is wrong`
          : `link "${raw}" resolves to nothing — ${rel} is neither a page nor a file in the repository`,
      });
      return raw;
    }

    report({
      level: 'warn',
      ...where,
      message: `link "${raw}" resolves to ${rel}, which does not exist — left as written`,
    });
    return raw;
  };
}

// --- Rewriting a document ----------------------------------------------------

// `[text](target "title")`, `![alt](target)`, and the angle-bracketed form.
const INLINE_LINK =
  /(!?\[(?:[^[\]\\]|\\.|\[[^\]]*\])*\]\(\s*)(<[^>\s]*>|[^\s()]+)((?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\))/g;

// `[label]: target "title"` at the start of a line.
const REFERENCE_LINK = /^([ \t]{0,3}\[(?:[^\]\\]|\\.)+\]:[ \t]*)(<[^>\s]*>|\S+)/gm;

// `href="…"` / `src="…"` in HTML and in an MDX component.
const ATTRIBUTE_LINK = /\b(href|src)\s*=\s*("([^"]*)"|'([^']*)')/g;

/**
 * Rewrite every link in a document.
 *
 * Fence-aware: a fenced code block that *shows* a Markdown link is sample text,
 * and rewriting it would teach the reader a URL they cannot type. Only the runs
 * of lines outside a fence are rewritten, and line numbers are preserved across
 * the split so an error still names the right line.
 *
 * @param {string} text
 * @param {(target: string, where: {line: number}) => string} rewrite
 */
export function mapLinks(text, rewrite) {
  const lines = scanLines(text);
  const out = [];
  let buffer = [];
  let bufferStart = 1;

  const flush = () => {
    if (buffer.length === 0) return;
    out.push(rewriteRun(buffer.join('\n'), bufferStart, rewrite));
    buffer = [];
  };

  lines.forEach((entry, index) => {
    if (entry.inFence) {
      flush();
      out.push(entry.line);
      return;
    }
    if (buffer.length === 0) bufferStart = index + 1;
    buffer.push(entry.line);
  });
  flush();

  return out.join('\n');
}

function rewriteRun(run, startLine, rewrite) {
  const lineAt = (offset) => startLine + (run.slice(0, offset).match(/\n/g)?.length ?? 0);

  let text = run.replace(INLINE_LINK, (match, open, target, close, offset) => {
    const mapped = rewrite(target, { line: lineAt(offset) });
    return `${open}${wrapIfNeeded(target, mapped)}${close}`;
  });

  text = text.replace(REFERENCE_LINK, (match, open, target, offset) => {
    const mapped = rewrite(target, { line: lineAt(offset) });
    return `${open}${wrapIfNeeded(target, mapped)}`;
  });

  text = text.replace(ATTRIBUTE_LINK, (match, name, quoted, double, single, offset) => {
    const target = double ?? single ?? '';
    const mapped = rewrite(target, { line: lineAt(offset) });
    const quote = double !== undefined ? '"' : "'";
    return `${name}=${quote}${mapped}${quote}`;
  });

  return text;
}

/** Keep `<…>` only while it is still needed (a target containing a space). */
function wrapIfNeeded(original, mapped) {
  if (mapped.startsWith('<') && mapped.endsWith('>')) return mapped;
  if (/\s/.test(mapped)) return `<${mapped}>`;
  return mapped;
}
