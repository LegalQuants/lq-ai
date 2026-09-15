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
