/**
 * Every path and every deployment constant the build scripts share.
 *
 * Two rules hold here and nowhere else:
 *
 *  - The *base path is configuration.* `SITE_BASE` and `SITE_URL` have exactly
 *    one default each, below, and `astro.config.mjs` imports them from here —
 *    so no script and no page can carry a second, drifting copy of `/lq-ai/`
 *    (ADR 0028).
 *  - Every root is overridable by an environment variable, so the whole
 *    pipeline can be pointed at a fixture tree and an output sandbox without
 *    touching the working copy. That is what `site/test/` runs against.
 *
 * | Variable        | Default              | What it moves                        |
 * |-----------------|----------------------|--------------------------------------|
 * | `DOCS_SITE_DIR` | `../docs/site`       | where page sources are read from     |
 * | `SYNC_OUT_ROOT` | the `site/` root     | where the sync writes everything     |
 * | `DIST_DIR`      | `site/dist`          | what postbuild and the checks read   |
 * | `SYNC_SKIP`     | empty                | page paths to leave out of this run  |
 * | `SITE_BASE`     | `/lq-ai/`            | the deployed base path               |
 * | `SITE_URL`      | `https://legalquants.github.io` | the deployed origin       |
 * | `SITE_LAYOUT`   | `classic`            | `pathways`: Iris's four-pathway UI   |
 * | `SITE_EXPERIENCE` | `explore`          | `cards`: B; `explore`: C             |
 * | `SITE_COMPARE`  | empty                | `<label>|<url>`: a compare banner    |
 *
 * `REPO_ROOT` is deliberately *not* overridable: includes, `sources:` entries
 * and stamps are repository-relative by definition, and a fixture run still
 * resolves them against the real repository.
 */

import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** `site/` — this file lives at `site/scripts/lib/paths.mjs`. */
export const SITE_ROOT = fileURLToPath(new URL('../../', import.meta.url));

/** The repository root. Includes, links and stamps are relative to it. */
export const REPO_ROOT = path.resolve(SITE_ROOT, '..');

const resolveFrom = (base, value) => (path.isAbsolute(value) ? value : path.resolve(base, value));

/** Canonical page sources. */
export const DOCS_SITE_DIR = resolveFrom(
  SITE_ROOT,
  process.env.DOCS_SITE_DIR || path.join('..', 'docs', 'site')
);

/** Everything the sync writes hangs off this root. */
export const OUT_ROOT = resolveFrom(SITE_ROOT, process.env.SYNC_OUT_ROOT || '.');

/** The generated content collection. Gitignored; never hand-edited. */
export const CONTENT_DIR = path.join(OUT_ROOT, 'src', 'content', 'docs');

/** Images copied out of the repository, served under `<base>_repo/…`. */
export const PUBLIC_REPO_DIR = path.join(OUT_ROOT, 'public', '_repo');

/** Route → source file, sha, sources. Read by postbuild and both checks. */
export const MANIFEST_PATH = path.join(OUT_ROOT, '.sync-manifest.json');

/** The built site. */
export const DIST_DIR = resolveFrom(SITE_ROOT, process.env.DIST_DIR || 'dist');

/**
 * Pages to leave out of this run, as paths relative to `DOCS_SITE_DIR`
 * (`operate/install-helm.md`). The escape hatch for building the rest of the
 * pipeline while one page is mid-flight — never a way to ship a broken page.
 */
export const SKIP_PAGES = new Set(
  String(process.env.SYNC_SKIP || '')
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean)
);

/** The deployed base path, always with both slashes. */
export const SITE_BASE = (() => {
  const raw = process.env.SITE_BASE || '/lq-ai/';
  const withLeading = raw.startsWith('/') ? raw : `/${raw}`;
  return withLeading.endsWith('/') ? withLeading : `${withLeading}/`;
})();

/** The deployed origin, without a trailing slash. */
export const SITE_URL = (process.env.SITE_URL || 'https://legalquants.github.io').replace(/\/+$/, '');

/**
 * Which navigation the site is built with. `classic` is the eight-section
 * sidebar; `pathways` is the four-pathway layout from Iris's UI review
 * (`src/pathways.mjs`). Both render the same pages from the same sources — the
 * layout is the only thing that differs, which is what lets the two be
 * compared side by side. Anything else is a typo, and a typo that silently
 * built the wrong layout would defeat the comparison.
 */
export const SITE_LAYOUT = (() => {
  const raw = process.env.SITE_LAYOUT || 'classic';
  if (raw !== 'classic' && raw !== 'pathways') {
    throw new Error(`SITE_LAYOUT must be "classic" or "pathways", not "${raw}"`);
  }
  return raw;
})();

/** Keep B's cards/tabs and C's search/reader independently rebuildable. */
export const SITE_EXPERIENCE = (() => {
  const raw = process.env.SITE_EXPERIENCE || 'explore';
  if (!['cards', 'explore'].includes(raw)) throw new Error('SITE_EXPERIENCE must be "cards" or "explore"');
  return raw;
})();

/**
 * An optional one-line banner pointing at the other layout while the two are
 * being compared: `SITE_COMPARE="Layout A|https://example.vercel.app"`. Unset
 * for any real deployment.
 */
export const SITE_COMPARE = (() => {
  const raw = process.env.SITE_COMPARE;
  if (!raw) return undefined;
  const [label, url] = raw.split('|');
  if (!label || !/^https:\/\//.test(url ?? '')) {
    throw new Error('SITE_COMPARE must be "<label>|https://<url>"');
  }
  return { label: label.trim(), url: url.trim() };
})();

/** `start/quickstart/` → `/lq-ai/start/quickstart/`. Route `''` is the root. */
export function withBase(route) {
  const clean = String(route ?? '').replace(/^\/+/, '');
  if (!clean) return SITE_BASE;
  return SITE_BASE + (clean.endsWith('/') ? clean : `${clean}/`);
}

/** `start/quickstart/` → `https://origin/lq-ai/start/quickstart/`. */
export const canonicalUrl = (route) => SITE_URL + withBase(route);

/** A repository path, normalised to forward slashes with no leading slash. */
export const repoPath = (absolutePath) =>
  path.relative(REPO_ROOT, absolutePath).split(path.sep).join('/');

/** Posix-style join for repository-relative paths. */
export const posix = (...parts) => parts.join('/').replace(/\/{2,}/g, '/');
