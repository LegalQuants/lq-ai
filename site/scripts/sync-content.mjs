#!/usr/bin/env node
/**
 * `docs/site/**` → `src/content/docs/**`.
 *
 * This is the whole transform. Writers author ordinary Markdown with ordinary
 * relative links under `docs/site/`; this script turns that tree into the
 * Starlight content collection, and in doing so it is the only place three
 * promises of the site are actually kept:
 *
 *  - **A curation page never holds a copy.** `<!-- include: … -->` pulls the
 *    canonical file in at build time (`lib/includes.mjs`).
 *  - **Nothing links nowhere.** Every relative link is resolved against the
 *    repository and mapped to a route, a pinned GitHub URL, or a copied image;
 *    a `.md` link that resolves to nothing fails the build (`lib/links.mjs`).
 *  - **Every page says what it was checked against.** The stamp is computed
 *    from git history over the page and its `sources:` (`lib/git.mjs`).
 *
 * Order of work, and why it is this order:
 *
 *   1. read every page's frontmatter — the route map has to exist before any
 *      link can be mapped;
 *   2. run the generators — they add routes (`/reference/adr-index/`,
 *      `/changelog/v0.7.0/`, …) that authored pages link to, so they have to
 *      be in the route map too;
 *   3. transform every page, authored and generated, through the same path:
 *      includes → directives → links → stamp → frontmatter;
 *   4. copy the images the links asked for;
 *   5. write `.sync-manifest.json`, which the postbuild machine surface and
 *      both checks read instead of re-deriving any of this.
 *
 * Failures are loud and located. A missing include file, a `from=` heading that
 * is not in the source any more, a dead `.md` link, a page with no
 * `description` — each names the page and the line and exits non-zero. The
 * alternative is a trust centre that ships a blank section, which is worse than
 * a red build.
 *
 * Environment overrides are listed in `lib/paths.mjs`; `SYNC_SKIP` is the one
 * to know about — a comma-separated list of page paths to leave out of this
 * run, for building the rest of the pipeline while one page is mid-flight.
 */

import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { cp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

import {
  CONTENT_DIR,
  DOCS_SITE_DIR,
  MANIFEST_PATH,
  OUT_ROOT,
  PUBLIC_REPO_DIR,
  REPO_ROOT,
  SITE_BASE,
  SITE_URL,
  SKIP_PAGES,
  repoPath,
  withBase,
} from './lib/paths.mjs';
import { head, stampFor } from './lib/git.mjs';
import { blobUrl, createResolver, mapLinks, treeUrl } from './lib/links.mjs';
import { expandIncludes, includedFiles } from './lib/includes.mjs';
import {
  convertGithubAlerts,
  dropFirstH1,
  firstH1,
  parsePage,
  plainCheckboxes,
  serializePage,
  sliceBetweenHeadings,
  stripFrontmatter,
} from './lib/markdown.mjs';
import { loadRouteManifests, ROUTES_DIRNAME } from './lib/routes.mjs';
import { NAMESPACES } from '../src/namespaces.mjs';

import * as adrIndex from './gen-adr-index.mjs';
import * as skillCatalogue from './gen-skill-catalogue.mjs';
import * as coverageIndex from './gen-coverage-index.mjs';
import * as configReference from './gen-config-reference.mjs';
import * as skillFrontmatter from './gen-skill-frontmatter.mjs';
import * as changelog from './gen-changelog.mjs';
import { renderSupportedShapes } from './gen-supported-shapes.mjs';

/** Run in the order the sidebar shows them; the log reads like the site. */
const GENERATORS = [
  configReference,
  skillFrontmatter,
  adrIndex,
  skillCatalogue,
  coverageIndex,
  changelog,
];

const problems = [];
const report = (problem) => problems.push(problem);

// --- Reading the page tree ---------------------------------------------------

/** `README.md`, `_data/` and `*.intro.md` are not pages. */
function isNotAPage(relPath) {
  const base = path.basename(relPath);
  if (base === 'README.md') return true;
  if (base.endsWith('.intro.md')) return true;
  return relPath.split(path.sep)[0] === '_data';
}

async function pageFiles(dir = DOCS_SITE_DIR, prefix = '') {
  if (!existsSync(dir)) return [];
  const found = [];
  for (const entry of (await readdir(dir, { withFileTypes: true })).sort((a, b) =>
    a.name.localeCompare(b.name)
  )) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      if (rel.split('/')[0] === '_data') continue;
      found.push(...(await pageFiles(path.join(dir, entry.name), rel)));
    } else if (/\.mdx?$/.test(entry.name) && !isNotAPage(rel)) {
      found.push(rel);
    }
  }
  return found;
}

/** `start/quickstart.md` → `start/quickstart`; `operate/index.md` → `operate`. */
export function routeFor(relPath) {
  const parts = relPath.replace(/\.mdx?$/, '').split('/');
  if (parts[parts.length - 1] === 'index') parts.pop();
  return parts.join('/');
}

/**
 * Astro slugifies a content-collection id before it becomes a route, and the
 * slugger is not the identity: `v0.7.0.md` is served at `/v070/`, and an
 * uppercase or accented filename changes too. When that happens the route in
 * the manifest stops matching the route Astro built, and every downstream
 * artifact — the sidebar check, the `.md` twin, `llms.txt` — is quietly wrong.
 *
 * Rather than re-implement the slugger, the sync refuses to guess: a page whose
 * path is not already slug-shaped is reported, and the fix is to rename the
 * file. The orphan check is the backstop if one ever slips through.
 */
const SLUG_SAFE = /^[a-z0-9][a-z0-9/-]*$/;

const namespaceOf = (relPath) => {
  const first = relPath.split('/')[0];
  return NAMESPACES.some((ns) => ns.dir === first) ? first : '';
};

// --- The generator contract --------------------------------------------------

/**
 * What a generator gets. Everything it needs to build a page from the
 * repository, and nothing that would let it write one directly — the sync owns
 * writing, so generated pages go through exactly the same stamp, link and
 * frontmatter path as authored ones.
 */
function generatorContext() {
  return {
    repoRoot: REPO_ROOT,
    docsSiteDir: DOCS_SITE_DIR,
    report,
    head: head(),
    /**
     * The stamp for a generated page: the newest commit touching the sources it
     * was built from, plus its intro file when it has one. The generator asks
     * for it before it renders, because its repository links pin to that same
     * commit — the links and the stamp always name one revision.
     */
    stamp: (sources, introRelPath) =>
      stampFor(
        introRelPath ? repoPath(path.join(DOCS_SITE_DIR, introRelPath)) : '',
        (sources ?? []).filter(Boolean)
      ),
    /** Read a repository file, or `null` when it is not there. */
    read(relPath) {
      const absolute = path.resolve(REPO_ROOT, relPath);
      return existsSync(absolute) ? readFileSync(absolute, 'utf8') : null;
    },
    /** List a repository directory, sorted, or `[]`. */
    list(relDir) {
      const absolute = path.resolve(REPO_ROOT, relDir);
      if (!existsSync(absolute)) return [];
      return readdirSync(absolute).sort((a, b) => a.localeCompare(b));
    },
    route: (route) => withBase(route),
    blob: (relPath, sha) => blobUrl(sha, relPath),
    tree: (relPath, sha) => treeUrl(sha, relPath),
  };
}

// --- Transform ---------------------------------------------------------------

async function main() {
  const startedAt = Date.now();

  await rm(CONTENT_DIR, { recursive: true, force: true });
  await rm(PUBLIC_REPO_DIR, { recursive: true, force: true });
  await mkdir(CONTENT_DIR, { recursive: true });

  const skipped = [];
  const all = await pageFiles();
  const authoredPaths = all.filter((rel) => {
    if (SKIP_PAGES.has(rel)) {
      skipped.push(rel);
      return false;
    }
    return true;
  });

  // 1. Frontmatter first — the route map has to exist before any link maps.
  const authored = [];
  for (const rel of authoredPaths) {
    const raw = await readFile(path.join(DOCS_SITE_DIR, rel), 'utf8');
    let parsed;
    try {
      parsed = parsePage(raw);
    } catch (error) {
      report({
        level: 'error',
        page: rel,
        line: 1,
        message: `frontmatter does not parse: ${error.message}`,
      });
      continue;
    }
    authored.push({
      kind: 'authored',
      relPath: rel,
      route: routeFor(rel),
      sourcePath: repoPath(path.join(DOCS_SITE_DIR, rel)),
      baseDir: path.dirname(path.join(DOCS_SITE_DIR, rel)),
      data: parsed.data,
      body: parsed.content,
    });
  }

  // 2. Generators — they contribute routes that authored pages link to.
  const context = generatorContext();
  const generated = [];
  for (const generator of GENERATORS) {
    let produced = [];
    try {
      produced = (await generator.generate(context)) ?? [];
    } catch (error) {
      report({
        level: 'error',
        page: generator.id ?? 'generator',
        line: 1,
        message: `generator failed: ${error.stack || error.message}`,
      });
      continue;
    }
    for (const page of produced) {
      // A generated page can be skipped too: the changelog index carries a
      // hand-written intro, and an intro that links a page nobody has written
      // yet fails the sync exactly like an authored page would.
      if (SKIP_PAGES.has(page.relPath)) {
        skipped.push(page.relPath);
        continue;
      }
      generated.push({
        kind: 'generated',
        generator: generator.id,
        relPath: page.relPath,
        route: routeFor(page.relPath),
        // A generated page has no single hand-written source file, so its
        // "page path" for stamping purposes is the intro when it has one and
        // nothing when it does not — the stamp then rests entirely on
        // `sources:`, which is what the page is actually built from.
        sourcePath: page.intro
          ? repoPath(path.join(DOCS_SITE_DIR, page.intro))
          : undefined,
        // Where relative links in the generated body resolve from. A release
        // page's body *is* `docs/releases/v0.7.0.md`, so its links are relative
        // to that directory, not to `docs/site/changelog/`.
        baseDir: page.linkBaseDir
          ? path.resolve(REPO_ROOT, page.linkBaseDir)
          : path.dirname(path.join(DOCS_SITE_DIR, page.intro ?? page.relPath)),
        linkBaseDir: page.linkBaseDir,
        intro: page.intro,
        data: { ...page.frontmatter, status: 'draft' },
        body: page.body,
        stamp: page.stamp,
      });
    }
  }

  // 2b. Route manifests — a page whose body is a plain Markdown file at its
  // canonical repository path, with no docs/site wrapper at all (ADR 0028
  // decision 3; the docs-site mini-PRD's "it curates and routes; it does not
  // fork content the repo already holds"). `loadRouteManifests` validates
  // everything it can see on its own — a missing or unknown key, a missing
  // description, a source that does not exist or sits under `docs/site/`, a
  // duplicate route, a source mapped twice; what is left needs the rest of
  // the route table, which is what the loop below checks as it builds each
  // page.
  const routesDir = path.join(DOCS_SITE_DIR, ROUTES_DIRNAME);
  const routeEntries = loadRouteManifests({ routesDir, report });
  const knownRoutes = new Set([...authored, ...generated].map((page) => page.route));

  const mapped = [];
  for (const entry of routeEntries) {
    const where = { page: entry.file, line: entry.line };

    if (knownRoutes.has(entry.route)) {
      report({
        level: 'error',
        ...where,
        message: `route "${entry.route}" collides with an existing docs/site page`,
      });
      continue;
    }

    const sourceAbs = path.resolve(REPO_ROOT, entry.source);
    const stripped = stripFrontmatter(readFileSync(sourceAbs, 'utf8'));
    const derivedTitle = entry.title ?? firstH1(stripped);
    if (!derivedTitle) {
      report({
        level: 'error',
        ...where,
        message: `entry "${entry.route}" has no \`title\` and its source "${entry.source}" has no H1 to default it from`,
      });
    }

    let body = dropFirstH1(stripped);
    if (entry.from || entry.to) {
      const sliced = sliceBetweenHeadings(body, entry.from, entry.to);
      if (!sliced.ok) {
        const wanted = sliced.missing === 'from' ? entry.from : entry.to;
        report({
          level: 'error',
          ...where,
          message: `entry "${entry.route}": heading ${sliced.missing}="${wanted}" is not in "${entry.source}"`,
        });
      } else {
        body = sliced.text;
      }
    }
    body = convertGithubAlerts(body);

    const relPath = `${entry.route}.md`;
    // Only keys the entry actually set: an `undefined` value survives into
    // YAML frontmatter as nothing serialisable, and gray-matter throws on it.
    const data = {
      title: derivedTitle ?? entry.route,
      status: entry.status ?? 'draft',
      sources: entry.sources,
    };
    if (entry.description !== undefined) data.description = entry.description;
    if (entry.audience !== undefined) data.audience = entry.audience;
    if (entry.sidebar !== undefined) data.sidebar = entry.sidebar;

    mapped.push({
      kind: 'mapped',
      relPath,
      route: routeFor(relPath),
      sourcePath: entry.source,
      baseDir: path.dirname(sourceAbs),
      manifestFile: entry.file,
      nextRoutes: entry.next,
      data,
      body,
    });
    knownRoutes.add(entry.route);
  }

  // `next:` may point forward to an entry read later in this same loop (or in
  // a later routes/*.yaml file), so it can only be checked once every route —
  // authored, generated and mapped — is known.
  for (const page of mapped) {
    for (const target of page.nextRoutes) {
      if (!knownRoutes.has(target)) {
        report({
          level: 'error',
          page: page.manifestFile,
          line: 1,
          message: `entry "${page.route}": next: "${target}" is not a known route`,
        });
      }
    }
  }

  const pages = [...authored, ...generated, ...mapped];
  const titleByRoute = new Map(pages.map((page) => [page.route, page.data.title]));

  // 3. Route maps.
  const routeByRepoPath = new Map();
  for (const page of pages) {
    // A mapped page's body *is* a repository file outside `docs/site/` — that
    // is the whole point of the route manifest — so it is the file a writer
    // actually links to, and it is registered directly rather than under a
    // notional docs/site path that does not exist.
    if (page.kind === 'mapped') {
      routeByRepoPath.set(page.sourcePath, page.route);
      continue;
    }
    // A generated page has no file under `docs/site/`, but a writer still links
    // to it as one (`../changelog/index.md`), so its notional path is in the map
    // alongside the real ones.
    routeByRepoPath.set(repoPath(path.join(DOCS_SITE_DIR, page.relPath)), page.route);
    // A link to `changelog/index.intro.md` means the page the intro introduces.
    if (page.intro) {
      routeByRepoPath.set(repoPath(path.join(DOCS_SITE_DIR, page.intro)), page.route);
    }
  }

  // "A link to a canonical file that some page presents resolves to that page."
  // The rule only holds while exactly one page presents the file. Seven pages
  // name `README.md` as their first source, and sending every `README.md` link
  // to whichever of them sorts first would be worse than not applying the rule
  // at all — so a contested file keeps its repository link, and the contest is
  // reported once so a writer can settle it by reordering `sources:`.
  const claims = new Map();
  for (const page of authored) {
    // The entry hub curates eight namespaces, not its first source file.
    if (page.route === '') continue;
    const primary = Array.isArray(page.data.sources) ? page.data.sources[0] : undefined;
    if (!primary) continue;
    if (!claims.has(primary)) claims.set(primary, []);
    claims.get(primary).push(page);
  }

  const routeBySourceFile = new Map();
  for (const [primary, claimants] of [...claims].sort((a, b) => a[0].localeCompare(b[0]))) {
    if (claimants.length === 1) {
      routeBySourceFile.set(primary, claimants[0].route);
      continue;
    }
    report({
      level: 'warn',
      page: claimants[0].relPath,
      line: 1,
      message: `"${primary}" is the first \`sources:\` entry of ${claimants.length} pages (${claimants
        .map((entry) => entry.relPath)
        .join(', ')}) — links to it keep their repository URL rather than picking one`,
    });
  }

  // 4. Transform each page.
  const assets = new Set();
  const resolve = createResolver({
    routeByRepoPath,
    routeBySourceFile,
    copyAsset: (rel) => assets.add(rel),
    report,
  });

  const manifest = [];
  const missingIntros = [];

  for (const page of pages) {
    const where = { page: page.relPath };
    const title = page.data.title;
    const description = page.data.description;
    if (page.route && !SLUG_SAFE.test(page.route)) {
      report({
        level: 'error',
        ...where,
        line: 1,
        message: `route "${page.route}" is not slug-shaped — Astro will serve this page at a different URL than the one recorded here. Rename the file to lower-case letters, digits and hyphens.`,
      });
    }
    if (!title) {
      report({ level: 'error', ...where, line: 1, message: 'frontmatter has no `title`' });
    }
    if (!description) {
      report({ level: 'error', ...where, line: 1, message: 'frontmatter has no `description`' });
    }

    // 4a. The stamp, first: repository links are pinned to it.
    const declared = Array.isArray(page.data.sources) ? page.data.sources : [];
    const resolvedSources = declared.filter((source) => {
      const exists = existsSync(path.resolve(REPO_ROOT, source));
      if (!exists) {
        report({
          level: 'warn',
          ...where,
          line: 1,
          message: `sources entry "${source}" is not in the repository — dropped from the stamp`,
        });
      }
      return exists;
    });

    const stamp =
      page.stamp ??
      stampFor(page.sourcePath ?? '', resolvedSources);
    if (!stamp.resolved) {
      report({
        level: 'warn',
        ...where,
        line: 1,
        message:
          'git has no commit for this page or any of its sources — stamped `uncommitted`',
      });
    }

    const mapChunk = (text, baseDir) =>
      mapLinks(text, (target, at) =>
        resolve(target, baseDir, { ...where, line: at.line }, stamp.sha)
      );

    // 4b. The page's own links FIRST, from the page's own directory.
    //
    // Order matters and is not obvious. Everything that arrives later —
    // included text, the supported-shapes table, the intro — is mapped as it
    // arrives, against its own directory, and lands already absolute. Mapping
    // the page last instead would walk over all of it a second time and warn
    // about the very URLs this transform had just written.
    //
    // A generator's own body is exempt for the same reason: it already writes
    // final URLs through `ctx.route()` and `ctx.blob()`. The exception is a
    // body lifted out of a repository file — a release page is
    // `docs/releases/v0.7.0.md`, whose links are relative to that directory and
    // are named by `linkBaseDir`.
    const mapsOwnBody = page.kind === 'authored' || page.kind === 'mapped' || Boolean(page.linkBaseDir);
    let body = mapsOwnBody ? mapChunk(page.body, page.baseDir) : page.body;

    // 4c. Includes, resolving their links from the included file's directory.
    if (page.kind === 'authored') {
      const included = includedFiles(body);
      for (const file of included) {
        if (!declared.includes(file)) {
          report({
            level: 'warn',
            ...where,
            line: 1,
            message: `includes "${file}" but does not list it in \`sources:\` — the stamp does not move when that file changes`,
          });
        }
      }
      body = expandIncludes(body, {
        baseDir: page.baseDir,
        mapLinks: mapChunk,
        report,
        page: page.relPath,
      });
    }

    // 4d. Data-driven directives.
    body = await expandDirectives(body, { page, stamp, report });

    // 4e. The intro a generated page may carry, mapped from its own directory.
    // `SYNC_SKIP` may also name an intro file, which drops the lead-in and
    // keeps the generated table — the smaller cut when it is the intro, not the
    // generated page, that links somewhere unwritten.
    if (page.intro && SKIP_PAGES.has(page.intro)) {
      skipped.push(page.intro);
      page.intro = undefined;
    }

    if (page.intro) {
      const introPath = path.join(DOCS_SITE_DIR, page.intro);
      if (existsSync(introPath)) {
        const intro = parsePage(await readFile(introPath, 'utf8'));
        if (intro.data.title) page.data.title = intro.data.title;
        if (intro.data.description) page.data.description = intro.data.description;
        if (Array.isArray(intro.data.audience)) page.data.audience = intro.data.audience;
        const introText = mapChunk(intro.content.trim(), path.dirname(introPath));
        // A hand-written intro may end in its own "## Next". That section
        // belongs after the generated content, not before it — and it replaces
        // the generator's generic Next, because the writer's onward links are
        // the curated ones. Both sections are final in their documents.
        const NEXT_SECTION = /\n## Next\b[\s\S]*$/;
        const introNext = introText.match(NEXT_SECTION)?.[0] ?? '';
        const introHead = introNext ? introText.replace(NEXT_SECTION, '') : introText;
        const bodyMain = introNext ? body.replace(NEXT_SECTION, '') : body;
        body = `${introHead}\n\n${bodyMain}${introNext ? `\n${introNext}` : ''}`;
      } else {
        // Not a warning: the brief gives an intro to three generated pages and
        // leaves the rest to stand on their own table. The summary line names
        // which ones a writer could still add a lead-in to.
        missingIntros.push(page.intro);
      }
    }

    // 4f. A GFM task list becomes a plain one: an unlabelled disabled checkbox
    // fails the accessibility gate, and the reader could never tick it anyway.
    body = plainCheckboxes(body);

    // 4f2. A route-manifest entry's own onward links. Written as routes in the
    // manifest, not as Markdown links in the source, because the titles have
    // to come from whatever page each route actually resolved to — a writer
    // names `operate/upgrade`, not "Upgrade" spelled out and hoped to match.
    if (page.kind === 'mapped' && page.nextRoutes?.length) {
      const items = page.nextRoutes
        .filter((target) => titleByRoute.has(target))
        .map((target) => `- [${titleByRoute.get(target)}](${withBase(target)})`);
      if (items.length) {
        body = `${body.trimEnd()}\n\n## Next\n\n${items.join('\n')}\n`;
      }
    }

    // 4g. Frontmatter the build owns.
    const data = { ...page.data };
    data.checkedAgainst = { sha: stamp.sha, date: stamp.date };
    data.sourceFiles = stamp.sourceFiles.filter(Boolean);

    const target = path.join(CONTENT_DIR, page.relPath);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, serializePage(data, body), 'utf8');

    manifest.push({
      route: page.route,
      url: withBase(page.route),
      kind: page.kind,
      generator: page.generator,
      namespace: namespaceOf(page.relPath),
      order: typeof page.data.sidebar?.order === 'number' ? page.data.sidebar.order : null,
      title: title ?? page.relPath,
      description: description ?? '',
      status: data.status ?? 'draft',
      audience: data.audience ?? [],
      page: page.sourcePath ?? null,
      contentFile: path.relative(OUT_ROOT, target).split(path.sep).join('/'),
      isMdx: page.relPath.endsWith('.mdx'),
      sha: stamp.sha,
      date: stamp.date,
      sources: stamp.sourceFiles.filter(Boolean),
    });
  }

  // 5. Images the links asked for.
  for (const rel of assets) {
    const target = path.join(PUBLIC_REPO_DIR, rel);
    await mkdir(path.dirname(target), { recursive: true });
    await cp(path.resolve(REPO_ROOT, rel), target);
  }

  // 6. The manifest, ordered the way the sidebar is.
  manifest.sort(comparePages);
  await mkdir(path.dirname(MANIFEST_PATH), { recursive: true });
  await writeFile(
    MANIFEST_PATH,
    `${JSON.stringify(
      {
        base: SITE_BASE,
        siteUrl: SITE_URL,
        head: head(),
        namespaces: NAMESPACES,
        pages: manifest,
      },
      null,
      2
    )}\n`,
    'utf8'
  );

  printReport({ manifest, assets, skipped, missingIntros, startedAt });

  if (problems.some((problem) => problem.level === 'error')) process.exitCode = 1;
}

/** Sidebar order: the entry hub, then namespace by namespace, `order` then title. */
function comparePages(a, b) {
  if (a.route === '') return -1;
  if (b.route === '') return 1;
  const ai = NAMESPACES.findIndex((ns) => ns.dir === a.namespace);
  const bi = NAMESPACES.findIndex((ns) => ns.dir === b.namespace);
  if (ai !== bi) return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  // A namespace hub (`/operate/`) leads its namespace.
  const aHub = a.route === a.namespace;
  const bHub = b.route === b.namespace;
  if (aHub !== bHub) return aHub ? -1 : 1;
  const ao = a.order ?? Number.MAX_SAFE_INTEGER;
  const bo = b.order ?? Number.MAX_SAFE_INTEGER;
  if (ao !== bo) return ao - bo;
  return a.title.localeCompare(b.title);
}

/**
 * Directives that pull in a `_data/` file rather than a repository document.
 * Today there is one: the supported-shapes table on the `/operate/` hub.
 */
async function expandDirectives(body, { page, stamp, report: emit }) {
  if (!/<!--\s*supported-shapes\s*-->/.test(body)) return body;
  const rendered = await renderSupportedShapes({
    docsSiteDir: DOCS_SITE_DIR,
    sha: stamp.sha,
    report: (problem) => emit({ ...problem, page: page.relPath }),
  });
  return body.replace(/^[ \t]*<!--\s*supported-shapes\s*-->[ \t]*$/gm, rendered);
}

function printReport({ manifest, assets, skipped, missingIntros, startedAt }) {
  const errors = problems.filter((problem) => problem.level === 'error');
  const warnings = problems.filter((problem) => problem.level !== 'error');

  const line = (problem) =>
    `  ${problem.page ?? '?'}:${problem.line ?? 1}${
      problem.file && problem.file !== problem.page ? ` (in ${problem.file})` : ''
    } — ${problem.message}`;

  if (warnings.length) {
    console.warn(`sync: ${warnings.length} warning(s)`);
    warnings.forEach((problem) => console.warn(line(problem)));
  }

  if (errors.length) {
    console.error(`sync: ${errors.length} error(s)`);
    errors.forEach((problem) => console.error(line(problem)));
  }

  if (skipped.length) {
    console.warn(`sync: SYNC_SKIP left out ${skipped.length} page(s): ${skipped.join(', ')}`);
  }

  if (missingIntros.length) {
    console.log(
      `sync: ${missingIntros.length} generated page(s) have no intro file — a writer may add ${missingIntros.join(', ')} under docs/site/.`
    );
  }

  const authored = manifest.filter((entry) => entry.kind === 'authored').length;
  const mapped = manifest.filter((entry) => entry.kind === 'mapped').length;
  const generated = manifest.length - authored - mapped;
  console.log(
    `sync: ${manifest.length} page(s) — ${authored} authored, ${mapped} mapped, ${generated} generated; ` +
      `${assets.size} image(s) copied; ${Date.now() - startedAt}ms`
  );
}

await main();
