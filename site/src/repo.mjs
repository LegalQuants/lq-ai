// Repository coordinates used by the config and by the components.
//
// Kept in one place because three different things need them: the "Edit this
// page" link (points at the canonical source under docs/site/), the footer
// stamp (links each `sources:` file to the commit the page was checked
// against), and the machine surface. Nothing here encodes the *site* base
// path — that is configuration (SITE_BASE), never content.

export const REPO_OWNER = 'LegalQuants';
export const REPO_NAME = 'lq-ai';
export const REPO_URL = `https://github.com/${REPO_OWNER}/${REPO_NAME}`;

/** Branch the canonical sources live on. Edit links target this branch. */
export const REPO_BRANCH = 'main';

/**
 * Base for "Edit this page". A page's path under `docs/site/` is appended.
 * Starlight appends `entry.filePath` to `editLink.baseUrl`, and our entries
 * live in the generated `src/content/docs/` tree, so `Footer.astro` derives
 * the docs/site path itself and uses this constant directly.
 */
export const EDIT_BASE = `${REPO_URL}/edit/${REPO_BRANCH}/docs/site/`;

/** Link a repository file at an exact commit: BLOB(sha) + repo-relative path. */
export const blobUrl = (sha, path) =>
  `${REPO_URL}/blob/${sha}/${String(path).replace(/^\/+/, '')}`;

/** Where the generated content collection lives, relative to the site root. */
export const CONTENT_DIR_PREFIX = 'src/content/docs/';

/** Strip the generated-collection prefix to get the `docs/site/` path. */
export const toDocsSitePath = (filePath) => {
  if (!filePath) return undefined;
  const i = filePath.indexOf(CONTENT_DIR_PREFIX);
  return i === -1 ? undefined : filePath.slice(i + CONTENT_DIR_PREFIX.length);
};
