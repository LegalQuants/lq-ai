/**
 * The route manifest — `docs/site/routes/*.yaml`.
 *
 * ADR 0028 decision 3 says content stays canonical where it already lives; the
 * transform injects frontmatter rather than a writer copying a page under
 * `docs/site/`. The route manifest is how a page that has no docs/site wrapper
 * at all still gets a route: one YAML file per migration group, each a list of
 * entries mapping a URL path to the repository file that **is** the page body.
 *
 *     - route: operate/backup-and-restore
 *       source: docs/operate/backup-and-restore.md
 *       title: Backup and restore                 # optional; default = the source's first H1
 *       description: One sentence for search results and llms.txt.
 *       audience: [operator]
 *       status: draft
 *       kind: how-to                                # optional; how-to | explanation | reference
 *       sources: [docker-compose.yml]              # optional extra files the stamp also checks
 *       sidebar: { order: 3 }
 *       next: [operate/upgrade, trust/threat-model] # optional onward links, rendered as "## Next"
 *       from: "## Troubleshooting"                  # optional, discouraged: one exact section
 *       to: "## Something else"                     #   ('to' exclusive; needs 'from' or 'to')
 *
 * Every entry is validated here, all at once, across every `routes/*.yaml` file
 * — a duplicate route or a source claimed twice can only be caught by looking
 * at the whole set, not one file at a time. A page is never written from an
 * entry that fails validation; the sync reports every failure it finds and
 * exits non-zero, naming the manifest file and the entry's position in it.
 *
 * What this module does **not** do: read the source file, expand it, or map
 * its links. That happens in `sync-content.mjs`, the same place every other
 * page kind is transformed, so a mapped page goes through the same stamp,
 * link and frontmatter path as an authored or generated one.
 */

import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';

import YAML from 'yaml';

import { DOCS_SITE_DIR, REPO_ROOT, repoPath } from './paths.mjs';

/** The directory under `DOCS_SITE_DIR` that holds the manifest files. */
export const ROUTES_DIRNAME = 'routes';

const REQUIRED_KEYS = ['route', 'source', 'description'];
const OPTIONAL_KEYS = [
  'title',
  'audience',
  'status',
  'kind',
  'sources',
  'sidebar',
  'next',
  'from',
  'to',
];
const ALL_KEYS = new Set([...REQUIRED_KEYS, ...OPTIONAL_KEYS]);

/**
 * How a mapped page is meant to be read — Iris's ask, so a reader can tell at
 * a glance which pages are step-by-step and which are background or lookup
 * material. Renders as a sidebar badge and a short label near the top of the
 * page (`sync-content.mjs`, `PageTitle.astro`); this array is the one place
 * the allowed values are declared, and both of those read `KIND_LABELS` below
 * rather than restating the text.
 */
export const KINDS = ['how-to', 'explanation', 'reference'];

/** Sidebar-badge and on-page label text for each `kind`. */
export const KIND_LABELS = {
  'how-to': 'How-to',
  explanation: 'Explanation',
  reference: 'Reference',
};

const DOCS_SITE_PREFIX = `${repoPath(DOCS_SITE_DIR)}/`;

const asList = (value) => {
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value : [value];
};

/** Every `routes/*.yaml` (or `.yml`) file, in a stable order. */
export function routeManifestFiles(routesDir = path.join(DOCS_SITE_DIR, ROUTES_DIRNAME)) {
  if (!existsSync(routesDir)) return [];
  return readdirSync(routesDir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && /\.ya?ml$/i.test(entry.name))
    .map((entry) => path.join(routesDir, entry.name))
    .sort((a, b) => a.localeCompare(b));
}

/**
 * Load and validate every `routes/*.yaml` file.
 *
 * @param {object} options
 * @param {string} [options.routesDir]   defaults to `<DOCS_SITE_DIR>/routes`
 * @param {(problem: object) => void} options.report
 * @returns {Array<{
 *   file: string, line: number, route: string, source: string, title?: string,
 *   description: string, audience?: string[], status?: string, kind?: string,
 *   sources: string[], sidebar?: object, next: string[], from?: string, to?: string,
 * }>} only entries that passed every check that can be made without the rest
 *     of the route table (a missing/unknown key, a missing description, a
 *     source that does not exist or sits under `docs/site/`, a duplicate
 *     route, or a source mapped twice). Whether a route collides with a
 *     docs/site page, and whether a `next:` target is a known route, need the
 *     rest of the pages and are checked by the caller once those are known.
 */
export function loadRouteManifests({ routesDir = path.join(DOCS_SITE_DIR, ROUTES_DIRNAME), report }) {
  const entries = [];
  const routeOwner = new Map(); // route -> manifest file it was first claimed in
  const sourceOwner = new Map(); // repo-relative source -> manifest file it was first claimed in

  for (const file of routeManifestFiles(routesDir)) {
    const relFile = repoPath(file);
    let raw;
    try {
      raw = YAML.parse(readFileSync(file, 'utf8'));
    } catch (error) {
      report({ level: 'error', page: relFile, line: 1, message: `does not parse as YAML: ${error.message}` });
      continue;
    }
    if (raw === null || raw === undefined) continue; // an empty file is not an error
    if (!Array.isArray(raw)) {
      report({
        level: 'error',
        page: relFile,
        line: 1,
        message: 'must be a YAML list of route entries',
      });
      continue;
    }

    raw.forEach((entry, index) => {
      const where = { page: relFile, line: index + 1 };
      const label = entry && typeof entry === 'object' ? (entry.route ?? `entry ${index + 1}`) : `entry ${index + 1}`;

      if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) {
        report({ level: 'error', ...where, message: `${label} is not a mapping of keys to values` });
        return;
      }

      const unknown = Object.keys(entry).filter((key) => !ALL_KEYS.has(key));
      if (unknown.length) {
        report({
          level: 'error',
          ...where,
          message: `"${label}" has unknown key(s): ${unknown.join(', ')}`,
        });
      }

      const missing = REQUIRED_KEYS.filter(
        (key) => entry[key] === undefined || entry[key] === null || entry[key] === ''
      );
      if (missing.length) {
        report({
          level: 'error',
          ...where,
          message: `"${label}" is missing required key(s): ${missing.join(', ')}`,
        });
      }

      if (entry.kind !== undefined && !KINDS.includes(entry.kind)) {
        report({
          level: 'error',
          ...where,
          message: `"${label}" has kind "${entry.kind}" — must be one of: ${KINDS.join(', ')}`,
        });
      }
      // `route` and `source` are what everything else below is keyed on — an
      // entry missing either cannot be validated further, so it is dropped
      // here rather than risking a route or source key of `undefined`.
      if (missing.includes('route') || missing.includes('source')) return;

      const route = String(entry.route).replace(/^\/+|\/+$/g, '');
      if (route !== String(entry.route)) {
        report({
          level: 'warn',
          ...where,
          message: `route "${entry.route}" has a leading or trailing slash — normalised to "${route}"`,
        });
      }
      if (!route) {
        report({ level: 'error', ...where, message: `"${label}" has an empty route` });
        return;
      }

      const sourceAbs = path.resolve(REPO_ROOT, String(entry.source));
      if (!existsSync(sourceAbs)) {
        report({
          level: 'error',
          ...where,
          message: `entry "${route}": source "${entry.source}" does not exist in the repository`,
        });
        return;
      }
      const source = repoPath(sourceAbs);
      if (source === repoPath(DOCS_SITE_DIR) || source.startsWith(DOCS_SITE_PREFIX)) {
        report({
          level: 'error',
          ...where,
          message: `entry "${route}": source "${entry.source}" is under docs/site/ — a route manifest maps a page's canonical home, never a docs/site wrapper (ADR 0028 decision 3)`,
        });
        return;
      }

      if (routeOwner.has(route)) {
        report({
          level: 'error',
          ...where,
          message: `route "${route}" is already mapped, by ${routeOwner.get(route)}`,
        });
        return;
      }
      routeOwner.set(route, relFile);

      if (sourceOwner.has(source)) {
        report({
          level: 'error',
          ...where,
          message: `source "${source}" is already mapped to a route, by ${sourceOwner.get(source)} — a source may be mapped by at most one route`,
        });
        return;
      }
      sourceOwner.set(source, relFile);

      entries.push({
        file: relFile,
        line: index + 1,
        route,
        source,
        title: typeof entry.title === 'string' ? entry.title : undefined,
        description: entry.description,
        audience: entry.audience !== undefined ? asList(entry.audience) : undefined,
        status: entry.status,
        kind: entry.kind,
        sources: asList(entry.sources).map(String),
        sidebar: entry.sidebar,
        next: asList(entry.next).map(String),
        from: entry.from,
        to: entry.to,
      });
    });
  }

  return entries;
}
