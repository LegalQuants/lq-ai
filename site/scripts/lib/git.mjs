/**
 * The stamp — the site's central honesty device.
 *
 * Every page says which commit it was checked against. That commit is the
 * newest one touching the page itself **or any file in its `sources:` list**,
 * so a canonical file moving under a page makes the page's own stamp move and
 * a reader can see the page is behind its source.
 *
 * `git log -1 --format='%h%x09%cs' -- <page> <sources…>` is the whole
 * computation. What matters is the fallback chain, because a page can be
 * brand new and untracked while the branch it is written on is still open:
 *
 *   1. page + sources — the normal case, and the only one that is a real claim;
 *   2. the page alone — when a source was renamed or does not exist yet, so a
 *      page still stamps against its own last commit rather than nothing;
 *   3. `uncommitted` with HEAD's date — a page that git has never seen. The
 *      word is deliberately not a sha: nothing can be verified against it, and
 *      the page should say so rather than borrow a commit it is not in.
 *
 * The sync never crashes on a new file. A missing stamp would silently drop
 * the one claim the page is required to make.
 */

import { execFileSync } from 'node:child_process';

import { REPO_ROOT } from './paths.mjs';

/** The literal sha value used when git has never seen the page or its sources. */
export const UNCOMMITTED = 'uncommitted';

function git(args) {
  try {
    return execFileSync('git', args, {
      cwd: REPO_ROOT,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return '';
  }
}

let headCache;

/** `{ sha, date }` for HEAD. Cached — it cannot change mid-build. */
export function head() {
  if (!headCache) {
    const line = git(['log', '-1', '--format=%h%x09%cs']);
    const [sha = '', date = ''] = line.split('\t');
    headCache = { sha, date };
  }
  return headCache;
}

function lastCommitTouching(paths) {
  if (paths.length === 0) return undefined;
  const line = git(['log', '-1', '--format=%h%x09%cs', '--', ...paths]);
  if (!line) return undefined;
  const [sha, date] = line.split('\t');
  return sha ? { sha, date } : undefined;
}

/**
 * The stamp for one page.
 *
 * @param {string} pagePath   repository-relative path of the page source
 * @param {string[]} sources  repository-relative `sources:` entries
 * @returns {{ sha: string, date: string, sourceFiles: string[], resolved: boolean }}
 */
export function stampFor(pagePath, sources = []) {
  const sourceFiles = [pagePath, ...sources].filter(
    (entry, index, all) => entry && all.indexOf(entry) === index
  );

  const combined = lastCommitTouching(sourceFiles);
  if (combined) return { ...combined, sourceFiles, resolved: true };

  const own = lastCommitTouching([pagePath].filter(Boolean));
  if (own) return { ...own, sourceFiles, resolved: true };

  const { date } = head();
  return { sha: UNCOMMITTED, date, sourceFiles, resolved: false };
}

/**
 * The sha a repository link is pinned to.
 *
 * A blob URL has to name a commit that exists, so a page whose own stamp is
 * `uncommitted` pins its links to HEAD instead. The stamp still says
 * `uncommitted`: the link is a convenience, the stamp is the claim.
 */
export const blobSha = (sha) => (sha && sha !== UNCOMMITTED ? sha : head().sha || 'main');

/** Every `v*` tag in the repository, newest first by semantic version. */
export function versionTags() {
  const raw = git(['tag', '--list', 'v*']);
  if (!raw) return [];
  return raw
    .split('\n')
    .map((tag) => tag.trim())
    .filter(Boolean)
    .sort(compareVersionsDesc);
}

/** `v0.10.2` sorts above `v0.9.6`; a trailing pre-release sorts below its release. */
export function compareVersionsDesc(a, b) {
  const parse = (tag) => {
    const match = /^v(\d+)\.(\d+)\.(\d+)(?:[-.](.+))?$/.exec(tag);
    if (!match) return null;
    return {
      nums: [Number(match[1]), Number(match[2]), Number(match[3])],
      pre: match[4] || '',
    };
  };
  const pa = parse(a);
  const pb = parse(b);
  // Anything that is not a plain vX.Y.Z sorts last, alphabetically among itself.
  if (!pa && !pb) return a.localeCompare(b);
  if (!pa) return 1;
  if (!pb) return -1;
  for (let i = 0; i < 3; i += 1) {
    if (pa.nums[i] !== pb.nums[i]) return pb.nums[i] - pa.nums[i];
  }
  if (pa.pre === pb.pre) return 0;
  if (!pa.pre) return -1;
  if (!pb.pre) return 1;
  return pa.pre.localeCompare(pb.pre);
}

/**
 * Tag → date (`YYYY-MM-DD`), in one call.
 *
 * `git log -1 --format=%cs <tag>` per tag would be ~170 process spawns on this
 * repository, which is most of the sync's runtime for a column of a table.
 * `for-each-ref` answers the whole question once; `creatordate` is the tag's
 * own date for an annotated tag and the commit's for a lightweight one, which
 * is the date a reader means by "when was this tagged".
 */
export function tagDates() {
  const raw = git([
    'for-each-ref',
    '--format=%(refname:short)%09%(creatordate:short)',
    'refs/tags/v*',
  ]);
  const map = new Map();
  for (const line of raw.split('\n')) {
    const [tag, date] = line.split('\t');
    if (tag) map.set(tag, date || '');
  }
  return map;
}
