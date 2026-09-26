/**
 * `/changelog/` and `/changelog/<version>/`.
 *
 * Two different things, deliberately kept apart:
 *
 *  - **The index** lists *every* `v*` tag reachable from `HEAD` (OpenWebUI's own
 *    tags, carried in by the `web/` fork rebase, are excluded), whether or not
 *    anyone wrote notes for it. A changelog that shows only the releases with
 *    notes is a changelog that hides the gap; this one shows the gap as rows.
 *    The count of tags without notes is stated in the page, computed, not typed.
 *  - **A release page** exists for each file in `docs/releases/`. Its body is
 *    that file, H1 dropped and links mapped like any other included content, and
 *    it is stamped against that file — so a release page moves when its notes
 *    move and not when some other release ships.
 *
 * The lead-in comes from `docs/site/changelog/index.intro.md`, which is where
 * the honest account of the backfill gap is written by hand. The generator does
 * not editorialise; it counts.
 */

import { compareVersionsDesc, tagDates, versionTags } from './lib/git.mjs';
import { dropFirstH1, firstH1, stripFrontmatter, table } from './lib/markdown.mjs';

export const id = 'gen-changelog';

const RELEASES_DIR = 'docs/releases';
const INTRO = 'changelog/index.intro.md';

/** `v0.7.0.md` → `v0.7.0`. */
const versionOf = (filename) => filename.replace(/\.md$/, '');

/**
 * `v0.7.0` → `v0-7-0`, the page's path segment.
 *
 * Astro slugifies a content-collection id before it becomes a route, and its
 * slugger drops the dots: a file called `v0.7.0.md` would be served at
 * `/changelog/v070/`, which is neither readable nor what any link to it would
 * say. Hyphenating up front makes the filename, the slug and the route the same
 * string, so the manifest, the sidebar and the `.md` twin cannot disagree. The
 * version itself is unchanged everywhere it is *displayed*.
 */
const segmentOf = (version) => version.replace(/\./g, '-');

export async function generate(ctx) {
  const files = ctx.list(RELEASES_DIR).filter((name) => name.endsWith('.md'));
  const notesByVersion = new Map(files.map((name) => [versionOf(name), `${RELEASES_DIR}/${name}`]));

  const pages = [];

  // --- one page per release note ---------------------------------------------
  for (const [version, relPath] of notesByVersion) {
    const raw = ctx.read(relPath);
    if (raw == null) continue;
    const text = stripFrontmatter(raw);
    const heading = firstH1(text) ?? version;
    const stamp = ctx.stamp([relPath]);

    pages.push({
      relPath: `changelog/${segmentOf(version)}.md`,
      stamp,
      frontmatter: {
        title: heading,
        description: `Release notes for ${version}, as recorded in ${relPath}.`,
        audience: ['operator', 'evaluator'],
        sources: [relPath],
        // Newest release nearest the top of the namespace. `sidebar.order`
        // takes a number, so the tag is turned into one; see `orderOf`.
        sidebar: { order: orderOf(version) },
      },
      body: dropFirstH1(text),
      // Links inside release notes are written relative to `docs/releases/`.
      linkBaseDir: RELEASES_DIR,
    });
  }

  // --- the index -------------------------------------------------------------
  const tags = versionTags();
  const dates = tagDates();
  const stamp = ctx.stamp([RELEASES_DIR], INTRO);

  const rows = tags.map((tag) => {
    const notes = notesByVersion.get(tag);
    const date = dates.get(tag);
    return [
      tag,
      date || 'unknown',
      notes
        ? `[Release notes](${ctx.route(`changelog/${segmentOf(tag)}`)})`
        : 'no release notes in the repository',
    ];
  });

  const withNotes = tags.filter((tag) => notesByVersion.has(tag)).length;
  const orphanNotes = [...notesByVersion.keys()]
    .filter((version) => !tags.includes(version))
    .sort(compareVersionsDesc);

  const body = [
    `The repository carries ${tags.length} \`v*\` tag${tags.length === 1 ? '' : 's'}, of which ${withNotes} ${
      withNotes === 1 ? 'has' : 'have'
    } structured release notes in \`${RELEASES_DIR}/\`. The remaining ${
      tags.length - withNotes
    } are listed with what the repository actually holds for them: nothing.`,
    '',
    table(['Tag', 'Tagged', 'Notes'], rows),
    ...(orphanNotes.length
      ? [
          '',
          `Release notes exist for ${orphanNotes
            .map((version) => `[${version}](${ctx.route(`changelog/${segmentOf(version)}`)})`)
            .join(', ')} without a matching tag in this repository.`,
        ]
      : []),
    '',
    '## Next',
    '',
    `- [Release versioning](${ctx.route('reference/versioning')}) — what a patch and a minor each commit to.`,
    `- [Upgrade](${ctx.route('operate/upgrade')}) — the runbook for taking one.`,
  ].join('\n');

  pages.push({
    relPath: 'changelog/index.md',
    intro: INTRO,
    stamp,
    frontmatter: {
      title: 'Release notes',
      description:
        'Every tagged release, which of them has structured release notes in the repository, and which does not.',
      audience: ['operator', 'evaluator'],
      sources: [RELEASES_DIR],
      sidebar: { order: 0 },
    },
    body,
  });

  return pages;
}

/**
 * Turn `v0.7.1` into a sidebar order that sorts newest first.
 *
 * Starlight orders a group by ascending `sidebar.order`, and the index page
 * takes `0`, so every release page has to be positive: the version is packed
 * into one integer (major·10^6 + minor·10^3 + patch) and subtracted from a
 * ceiling, which makes a newer release a smaller number. A tag that does not
 * parse sorts last, which is where an oddity belongs.
 */
const ORDER_CEILING = 1_000_000_000;

export function orderOf(tag) {
  const match = /^v(\d+)\.(\d+)\.(\d+)/.exec(tag);
  if (!match) return Number.MAX_SAFE_INTEGER;
  const [, major, minor, patch] = match.map(Number);
  return ORDER_CEILING - (major * 1_000_000 + minor * 1_000 + patch);
}
