# `site/` — the LQ.AI documentation site

This directory builds the public documentation site. It holds **configuration,
theme, the transform and the generators, and never a committed copy of a page**
(ADR 0028 decision 3).

Pages live in [`../docs/site/`](../docs/site/README.md). That file is the
authoring contract: where a page goes, what its frontmatter means, how includes
and links work, and the house rules. Read it before writing a page. Nothing in
`src/content/docs/` is committed — `npm run sync` regenerates it.

You do not need Node installed to contribute a page. CI builds the site.

## Run it

```bash
cd site
npm ci          # exact versions from the committed package-lock.json
npm run dev     # sync + dev server at http://localhost:4321/lq-ai/
```

Before opening a pull request that touches the site or anything it reads:

```bash
npm run check   # build + every gate, the same set CI runs
```

`npm run check` is the merge gate. It is slower than `npm run build` because it
starts a real browser for the accessibility pass.

## The scripts

| Script | What it does |
|---|---|
| `sync` | Rebuilds `src/content/docs/` (and `public/_repo/`) from `docs/site/` plus the generators. Fails on a missing include or a link that resolves nowhere. |
| `dev` | `sync`, then Astro's dev server. |
| `build` | `sync`, then `astro build`, then the machine surface (`.md` per route, `llms.txt`, `llms-full.txt`). |
| `test` | `node --test test/*.test.mjs` — the transform and the machine surface, run against the fixture tree in `test/fixtures/`. |
| `preview` | Serves `dist/` — Astro 7 runs this as a background daemon (`astro preview stop`, `status`, `logs`). |
| `check:links` | Every internal `href` in `dist/` resolves to a built file or its `.md` twin. |
| `check:orphans` | Every page in the collection is reachable from the sidebar. No orphans. |
| `check:contrast` | Measures the theme's colour tokens against their WCAG 2.1 AA floors, in both themes. Fails on any pair below its floor. |
| `check:a11y` | pa11y-ci with the axe runner, `WCAG2AA`, over every route in `dist/`, against a real `astro preview` server. |
| `check:a11y:review` | The same run with axe's "needs review" findings included. Not a gate — see below. |
| `check:docs-links` | `docs/audits/check_doc_links.py` over every page under `docs/site/**`, so the page sources also work as plain Markdown on GitHub. `docs/site/README.md` is excluded: it is the authoring contract, not a page, and its link table shows illustrative paths that resolve nowhere on purpose. |
| `check` | `test`, `build`, and every gate above. What CI runs. |

One tool sits outside the table because it is not a gate:
`node scripts/screenshot.mjs` captures full-page PNGs of a handful of
representative routes at 1280px and 400px, in both themes, against a running
`npm run preview`. It exists so a design change can be *looked at* rather than
reasoned about; comparing screenshots is a judgement, not a pass/fail, so it is
never wired into `check`. It adds no dependency — Chrome comes from the
`puppeteer` that `pa11y-ci` already installs — and writes to `site/.screens/`
(git-ignored) unless `--out` says otherwise. `--focus` also walks the keyboard
focus through the header. See the header comment in the file for the options.

## Environment

| Variable | Default | What it sets |
|---|---|---|
| `SITE_URL` | `https://legalquants.github.io` | Astro's `site` — the origin in canonical URLs, the sitemap and the machine surface. |
| `SITE_BASE` | `/lq-ai/` | Astro's `base` — the path the site is served under. |
| `DOCS_SITE_DIR` | `../docs/site` | Where page sources are read from. The test suite points it at `test/fixtures/docs-site/`. |
| `SYNC_OUT_ROOT` | the `site/` root | Where the sync writes `src/content/docs/`, `public/_repo/` and `.sync-manifest.json`. |
| `DIST_DIR` | `dist` | What the machine surface and both checks read. |
| `SYNC_SKIP` | unset | Comma-separated page paths (relative to `DOCS_SITE_DIR`) to leave out of one run. An escape hatch for building while a page is mid-flight — never a way to ship. |
| `PYTHON` | `python3` | The interpreter the configuration generators call. |
| `PA11Y_PORT` | `4321` | Port the accessibility gate's preview server uses. |
| `CI` | unset | When set, Chrome runs with `--no-sandbox` for the accessibility gate. |

**The base path is configuration, never content.** No page source, link rewrite
or generated URL may contain `/lq-ai/`. `SITE_BASE` and `SITE_URL` have exactly
one default each, in `scripts/lib/paths.mjs`; `astro.config.mjs` imports them
from there, so Astro and the build scripts cannot drift apart. Moving the site
to a custom domain is a change to these two variables and a rebuild (ADR 0028).
Check with:

```bash
grep -rn "/lq-ai/" ../docs/site src scripts   # only paths.mjs's default, plus prose about the rule
SITE_BASE=/ npm run build                     # must also succeed
```

## Accessibility

Accessibility is a gate, not a preference: WCAG 2.1 AA, checked on every built
route including generated pages.

Two checks, because they catch different things:

- **`check:contrast`** measures the palette itself — every token pair that
  carries text, in light and dark, against its floor. It catches a bad colour
  the moment it is written, on pages that do not exist yet.
- **`check:a11y`** measures what the browser actually rendered.

`check:a11y` fails on axe **violations**. axe also returns **incomplete**
results — checks it ran but could not decide, such as `color-contrast` on an
element whose content is a single symbol. Those are capped to warnings, because
a build gate cannot adjudicate what the tool declined to judge; they are printed
in full by `npm run check:a11y:review`. There is currently one, on every page:
the `⌘` glyph in the search box's keyboard-shortcut hint. Its colours are proved
by `check:contrast` instead.

Two rendering decisions exist to keep the gate green for pages nobody has
written yet, rather than to fix the pages that exist today:

- **Code blocks wrap** (`expressiveCode.defaultProps` in `astro.config.mjs`).
  An overflowing `<pre>` is a scroll region no keyboard can reach
  (`scrollable-region-focusable`, WCAG 2.1.1). Wrapping removes the scroll
  region rather than papering over it. Copy-to-clipboard still copies the
  unwrapped source.
- **Wide tables become focusable labelled regions**
  (`src/components/ScrollableTables.astro`, rendered once per page from the
  footer). A table cannot reflow, so the scroll has to stay; instead each
  overflowing table is wrapped in a `role="region"` box with `tabindex="0"` and
  a label taken from the nearest heading above it. With the script blocked, the
  table behaves exactly as Starlight ships it.

Three things about that wrapper are design decisions, not accessibility ones,
and they are in the same file because they only make sense together:

- The table inside it takes `width: max-content`, capped at
  `--lq-table-max-width` (60rem). Without that, a table wider than the column is
  laid out shrink-to-fit *against the scroll box*, so it falls back to its
  minimum content width: every cell wraps to its longest word and the row's
  height is set by a cell the reader cannot see. On `/trust/` that made 14 rows
  150px tall each — and still cut off the last column. Letting the table take
  its natural width keeps those rows at 84px and halves the height of
  `/reference/configuration/` on a phone.
- The wrapper takes a hairline border **only while it is actually scrolling**
  (the rule is on `[tabindex]`, which the script sets on exactly that
  condition). A cut-off column with no edge beside it reads as a rendering bug;
  with an edge it reads as a table continuing past the column.
- Its focus ring is the accent, like every other focus ring on the site.

To change how wide a table may grow, change `--lq-table-max-width` in
`theme.css`. It is the only number involved.

## How it is built

**Stack.** Astro 7 with Starlight, isolated in this directory, per ADR 0028. No
UI-framework integration: Astro components and CSS only. Search is Starlight's
built-in Pagefind — a static index served from this origin, so no hosted search
service sees a reader's query.

**Configuration** is `astro.config.mjs`. It sets the deployment target, the
namespace order, the component overrides, and Expressive Code's defaults. The
sidebar is one autogenerated group per namespace, in the fixed order Start ·
Operate · Trust · Skills · Deliver · Contribute · Reference · Changelog; groups
whose directory has not been written yet are skipped, so a partial tree still
builds.

**The content schema** is `src/content.config.ts`: Starlight's `docsSchema`
extended with the site's own frontmatter — `audience`, `status`, `sources`
(written by the author) and `checkedAgainst`, `sourceFiles` (injected by the
sync from git history).

**The theme** is `src/styles/theme.css`, a single file mapping the design
language onto Starlight's CSS variables for both themes. Light is the default.
No webfonts: the type stack is what the reader's system already has, so
rendering a page makes no third-party request. Every colour decision in it
carries its measured contrast ratio in a comment, and `check:contrast` re-measures
them from the file.

Four places where the theme deliberately overrules a Starlight default, because
each one is the kind of thing a later edit would quietly undo:

- **The H2 section rule sits on `.sl-heading-wrapper.level-h2`, not on the
  `h2`.** Starlight sets the heading itself to `display: inline` so its ¶ anchor
  can sit on the last line, which means a border on the `h2` tracks the width of
  the *text* — a two-line heading gets a rule under only its second line. The
  wrapper is the block box.
- **Cards are one object.** `<Card>`, `<LinkCard>` and the previous/next pair all
  take the hairline border, the raised ground, the `xl` radius and the 3px
  accent-border lift on hover (off under `prefers-reduced-motion`). Starlight
  gives the last two a *strong* line, no ground and a grey-fill hover, so
  without this the design language would stop at the edge of the prose — and the
  hub pages and the entry page are built entirely from `<LinkCard>`.
- **The current page in the sidebar is a 3px accent rule, not a solid accent
  fill.** Starlight fills it with `--sl-color-text-accent` and inverts the text.
  That passes contrast, but it makes a saturated block the loudest object on a
  quiet page and spends the accent on "you are here" twice, since the header
  already underlines the current namespace in accent. One device now does both.
  The state is still carried three ways that are not colour: `aria-current`, the
  weight, and the rule.
- **Code frames lose their ornament.** Expressive Code draws three macOS
  "traffic light" dots on a terminal frame and a drop shadow around every frame;
  the design language has no illustration and no shadow. Both are off
  (`--ec-frm-trmTtbDotsOpa`, `--ec-frm-frameBoxShdCssVal`), and an untitled
  terminal frame's now-empty title bar collapses — but stays in the
  accessibility tree, because it also holds the "Terminal window" label.

**Component overrides** are in `src/components/`:

| Component | What it changes |
|---|---|
| `Header.astro` | The **LQ.AI** text wordmark (no logo image — the LegalQuants mark is restricted), the eight namespace links on wide screens, search, theme toggle. |
| `PageTitle.astro` | Namespace eyebrow, the H1, the status badge, audience chips. |
| `Footer.astro` | The stamp, "Edit this page", previous/next, and the project line. |
| `Stamp.astro` | "Checked against `<sha>` · date" plus every source file linked at that commit. Renders nothing when the sync has not stamped the page. |
| `StatusBadge.astro` | `draft` / `reviewed`, as text plus colour, never colour alone. |
| `Eyebrow.astro` | The mono uppercase caption primitive. |

Each override keeps Starlight's landmarks, skip link and focus order: the H1
keeps the `#_top` id the skip link targets, the header renders inside
Starlight's own `<header>`, and the namespace nav is a labelled `<nav>` that
collapses into the existing mobile menu rather than being duplicated.


### The pipeline

```
docs/site/**  ──►  npm run sync  ──►  src/content/docs/**  ──►  astro build  ──►  dist/**
   pages           includes, links,      the Starlight            HTML          ──►  postbuild
   _data/          stamps, generators    collection                                  .md twins,
                            │                                                        llms.txt,
                            └──►  .sync-manifest.json  ──────────────────────────►   llms-full.txt
                                  route → source file, sha, sources                  and both checks
```

`scripts/sync-content.mjs` is the whole transform. It runs in this order, and
the order is load-bearing:

1. **Read every page's frontmatter.** The route map has to exist before a link
   can be mapped to a route.
2. **Run the generators.** They contribute routes (`/reference/adr-index/`,
   `/changelog/v0-7-0/`, …) that authored pages link to, so those routes must be
   in the map too.
3. **Transform every page** — authored and generated take the same path:
   the page's own links, then includes, then data directives, then the intro,
   then the stamp into the frontmatter.
4. **Copy the images** the links asked for, into `public/_repo/`.
5. **Write `.sync-manifest.json`**, which everything downstream reads instead of
   re-deriving any of it.

Each chunk of text is link-mapped **as it arrives**, against its own directory:
the page's prose against the page's directory, an included file's text against
*that file's* directory, a generator's output against the routes it already
knows. Nothing is mapped twice.

Failures are loud and located — a missing include file, a `from=` heading that
is no longer in the source, a `.md` link that resolves to nothing, a page with
no `description`. Each names the page and the line and exits non-zero. A trust
centre that ships a blank section is worse than a red build.

### Directives

| Directive | What it does |
|---|---|
| `<!-- include: <path> -->` | Inserts a repository file: frontmatter stripped, H1 dropped, links resolved from **the source file's** directory. |
| `<!-- include: <path> from="## A" to="## B" -->` | The same, sliced between two exact heading lines, `to` exclusive. |
| `<!-- include: <path> shift=1 -->` | The same, with every heading demoted by N so the included outline nests under the page's own. |
| `<!-- supported-shapes -->` | Replaced by the hosting-shapes table built from `docs/site/_data/supported-shapes.yaml`. |

Every heading operation is fence-aware. A shell block that contains a line
starting with `##` is a code block, not a heading — treating it as one would
truncate an include silently, in the middle of an install procedure.

A directive inside a fenced code block is left alone, so this file and the
authoring contract can show the syntax without the build acting on it.

### Link mapping

| The target is… | It becomes |
|---|---|
| another page under `docs/site/` | that page's route, with the base |
| a `*.intro.md` beside a generated page | the generated page's route |
| the first `sources:` entry of exactly one page, with no anchor | that page's route |
| an image anywhere in the repository | a copy under `<base>_repo/…` |
| any other file in the repository | a GitHub blob URL pinned to the page's stamp |
| a directory in the repository | a GitHub tree URL pinned to the page's stamp |
| an absolute URL, a bare `#anchor`, a `mailto:` | itself, untouched |
| anything else, when it ends `.md` | **a build failure**, naming the page and line |

Anchors survive every branch. Two narrowings of the `sources:` rule are
deliberate, and `npm run sync` reports each time one fires:

- **A link carrying an anchor keeps its repository URL.** The anchor names a
  heading inside the canonical file; the page that curates it may not carry that
  heading, and landing a reader at the top of a different document loses what
  they were sent to read.
- **A file claimed by more than one page keeps its repository URL.** Ten pages
  name `README.md` as their first source. Sending every `README.md` link to
  whichever of them sorts first would be worse than not applying the rule.

### The stamp

`git log -1 --format='%h%x09%cs' -- <page> <sources…>`, run from the repository
root: the newest commit touching the page **or any file in its `sources:`**. A
canonical file moving under a page therefore moves the page's own stamp, which
is how a reader can see that a page is behind its source.

Three steps, in order: the page and its sources; the page alone; and finally the
literal string `uncommitted` with HEAD's date, for a page git has never seen.
`uncommitted` is deliberately not a sha — nothing can be verified against it,
and the page should say so rather than borrow a commit it is not in. Repository
links on such a page pin to HEAD, because a blob URL has to name a commit that
exists; the stamp is the claim, the link is a convenience.

### The manifest

`.sync-manifest.json` (gitignored) is the contract between the transform and
everything after it. One entry per route: the source file, the generated content
file, title, description, namespace, sidebar order, status, audience, the sha
and date, and the resolved source list. The machine surface, `check:links` and
`check:orphans` all read it rather than re-deriving any of it, so they cannot
disagree with the build about what a page is.

### The machine surface

`scripts/postbuild-machine-surface.mjs` writes, for every route:

- `dist/<route>.md` — the **transformed** Markdown, with a four-line header
  (title, description, canonical URL, checked-against). MDX hubs are reduced:
  a `<LinkCard>` becomes the list item it stands for, other JSX is dropped.
- `dist/llms.txt` — the site in one fetch: name, one paragraph, then every page
  as `- [title](url): description`, grouped by namespace.
- `dist/llms-full.txt` — every page concatenated, in sidebar order.

The twin is the same content the reader sees, not a parallel copy: a machine
surface that can drift from the page is a second documentation set nobody
maintains. It is built here rather than taken from a plugin (ADR 0028 decision
4) because it is a launch commitment.

### The generators

Each `scripts/gen-*.mjs` exports `id` and `generate(ctx)` and returns page
objects; the sync writes them, so a generated page goes through the same stamp,
link and frontmatter path as an authored one. A generated page is always
`status: draft` — `reviewed` is a claim only a person who has read the page can
make.

| Generator | Builds | From |
|---|---|---|
| `gen-config-reference.mjs` + `gen-config-reference.py` | `/reference/configuration/` | `api/app/config.py`, `gateway/app/config.py`, parsed with Python's `ast`; then `gateway.yaml.example` and `mcp.yaml.example` verbatim |
| `gen-skill-frontmatter.mjs` | `/reference/skill-frontmatter/` | `api/app/skills/schema.py` — the loader's own schema |
| `gen-adr-index.mjs` | `/reference/adr-index/` | `docs/adr/*.md`: number, H1, and the `Status` line rendered verbatim |
| `gen-skill-catalogue.mjs` | `/skills/catalogue/` | each skill folder's `SKILL.md` frontmatter |
| `gen-coverage-index.mjs` | `/skills/coverage/` and one page per facet | the same frontmatter plus `docs/site/_data/coverage-notes.yaml` |
| `gen-changelog.mjs` | `/changelog/` and `/changelog/<version>/` | `git tag --list 'v*'` and `docs/releases/*.md` |
| `gen-supported-shapes.mjs` | the `<!-- supported-shapes -->` table | `docs/site/_data/supported-shapes.yaml` |

`gen-config-reference.py` **parses, never imports**: generating documentation
cannot execute repository code, pull in `pydantic`, or read an `.env`. It is
stdlib-only and takes the repository root plus a list of files, so the two
JavaScript generators that need Python share one parser.

**To add a generator:** write `scripts/gen-<thing>.mjs` exporting `id` and
`generate(ctx)`; return `{ relPath, frontmatter, body, stamp }` per page, with
`intro` when a writer may supply a lead-in and `linkBaseDir` when the body was
lifted out of a repository file. Ask `ctx.stamp(sources, intro)` for the stamp
*before* rendering, and use its sha for `ctx.blob()` links so the links and the
stamp name one revision. Register it in the `GENERATORS` list in
`sync-content.mjs`, and add a case to `test/sync.test.mjs`.

Route segments must be slug-shaped (`[a-z0-9-]`): Astro slugifies a
collection id before it becomes a route, and `v0.7.0.md` would be served at
`/v070/`. The sync refuses a route that is not already slug-shaped rather than
guessing at the slugger, which is why release pages are `v0-7-0`.

### The tests

`npm test` runs the transform against `test/fixtures/docs-site/` — a small page
tree that exercises every link branch, all three include forms, the fence
handling, an MDX hub, an intro file, the data directives, and each generator —
then runs the machine surface over the result. Output goes to a temporary
directory; a test run never touches the working copy. `test/fixtures/repo/`
holds the "canonical files" those pages present, and
`test/fixtures/broken-include/` is the tree that must *fail*, asserting that
each refusal exits non-zero and names the page and the line.

## Adding a page

Write it in `docs/site/<namespace>/<slug>.md` and follow
[the authoring contract](../docs/site/README.md). It appears in the sidebar and
in the machine surface on the next `npm run sync` — there is nothing to register
here.

## CI

`.github/workflows/docs-site.yml` runs `npm run check` on every pull request
that touches the site or anything it reads, and deploys to GitHub Pages on
`push` to `main`. Its path filter includes the generators' own inputs
(`api/app/config.py`, `gateway/app/config.py`, `api/app/skills/schema.py`,
`gateway.yaml.example`, `mcp.yaml.example`, `docker-compose.yml`) as well as
`docs/**` — otherwise a settings change would ship while the published
`/reference/configuration/` still described the previous release, and nothing
would announce it.

## First draft — known gaps

What is deliberately unfinished in this first draft. None of it fails a gate;
all of it is visible on the site.

| Gap | Where | Why |
|---|---|---|
| `/trust/what-leaves-my-deployment/` is an honest stub | that page | It waits on PR #439, which measures what actually leaves a deployment. The page says so, gives the interim answer from the tier model, and ends in a decision. Planned, per the build brief. |
| `/deliver/` ships one page | `/deliver/branding-and-licensing/` | Open question 4 of the docs-site mini-PRD (PR #511) decided that only the branding-obligations page ships now. The hub says what the namespace will hold. No production-readiness matrix yet. |
| No `*.intro.md` for three generated pages | `/reference/configuration/`, `/reference/skill-frontmatter/`, `/reference/adr-index/` | The brief gives intros only to the catalogue, the coverage index and the changelog. `npm run sync` prints the three names on every run; adding the files needs no code change. |
| The skill catalogue's attested-by column reads "not recorded in frontmatter" in every row | `/skills/catalogue/` | No shipped skill records an attestation in `SKILL.md`. The attestation lives in the merging pull request. The generator checks rather than assumes, so the column fills itself the day the field appears. |
| No coverage ledger to link | `/skills/where-skills-live/` | ADR 0024 commits to `docs/contribute/coverage-map.md`; the file is not in the repository. The generated `/skills/coverage/` index is the nearest substitute and the page says so. |
| A contested `sources[0]` keeps its repository link | the sync's warnings | The brief's rule sends a link to a canonical file to the page that presents it. Ten pages name `README.md` first, so the rule cannot pick one. Each contest is printed by name on every sync; a writer settles one by reordering `sources:`. |
| Nested sidebar groups are labelled in lower case | `recipes`, `coverage`, `jurisdiction`, `practice-area` | Starlight's `autogenerate` takes a nested group's label from the directory name, and there is no way to relabel one without replacing the whole group with a hand-written item list — which would then need editing every time a page is added. Cosmetic; the entries themselves are Title Case. |
| No type-check step | — | `astro check` needs `@astrojs/check` and `typescript`, which are not in the brief's dependency list. The scripts are plain `.mjs` with JSDoc. |
| Two benign build warnings | `astro build` | `The collection "i18n" does not exist or is empty` (no translations) and `Entry docs → 404 was not found` (no custom 404 page). Starlight's defaults; both surfaces work. |
| Chrome is re-downloaded on every CI run | `.github/workflows/docs-site.yml` | pa11y pulls Chrome through puppeteer at install time (~150 MB). `setup-node`'s npm cache does not cover `~/.cache/puppeteer`. A cache step is a cheap follow-up. |

## Gotcha

Astro caches rendered Markdown across builds, in `.astro/` and in
`node_modules/.astro/`. A change to `astro.config.mjs` that affects **how**
Markdown renders — Expressive Code options in particular — will not show up
until those are cleared:

```bash
rm -rf .astro dist node_modules/.astro node_modules/.vite && npm run build
```
