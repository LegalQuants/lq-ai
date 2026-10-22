# `site/` — the LQ.AI documentation site

This directory builds the public documentation site. It holds **configuration,
theme, the transform and the generators, and never a committed copy of a page**
(ADR 0028 decision 3).

A page's own Markdown lives at its **canonical repository location** — under
`docs/`, or wherever else the repository already keeps it — with no
Starlight frontmatter at all; a **route manifest**
(`docs/site/routes/*.yaml`) maps it onto a URL. `docs/site/` itself holds
only navigation and a generated page's companions: the entry hub, namespace
hubs, `start/choose-your-path.md`, `*.intro.md` files, `_data/`, and the
manifests. [`../docs/site/README.md`](../docs/site/README.md) is the
authoring contract: where a page's Markdown goes, the manifest schema,
alerts, `## Next`, and when a file belongs under `docs/site/` at all. Read it
before writing a page. Nothing in `src/content/docs/` is committed —
`npm run sync` regenerates it.

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
| `sync` | Rebuilds `src/content/docs/` (and `public/_repo/`) from `docs/site/`, every `docs/site/routes/*.yaml` route manifest, and the generators. Fails on a missing include, a link that resolves nowhere, or an invalid manifest entry. |
| `dev` | `sync`, then Astro's dev server. |
| `build` | `sync`, then `astro build`, then the machine surface (`.md` per route, `llms.txt`, `llms-full.txt`). |
| `test` | `node --test test/*.test.mjs` — the transform and the machine surface, run against the fixture tree in `test/fixtures/`. |
| `preview` | Serves `dist/` — Astro 7 runs this as a background daemon (`astro preview stop`, `status`, `logs`). |
| `check:links` | Every internal `href` in `dist/` resolves to a built file or its `.md` twin. |
| `check:orphans` | Every page in the collection is reachable from the sidebar. No orphans. |
| `check:tables` | At 1280px and 400px, over every route, nothing inside the prose scrolls horizontally. |
| `check:single-source` | `docs/site/` holds only navigation and generated-page companions, and no route-manifest `source:` sits under `docs/site/` — one Markdown source per page (ADR 0028 decision 3). |
| `check:contrast` | Measures the theme's colour tokens against their WCAG 2.1 AA floors, in both themes. Fails on any pair below its floor. |
| `check:a11y` | pa11y-ci with the axe runner, `WCAG2AA`, over every route in `dist/`, against a real `astro preview` server. |
| `check:a11y:review` | The same run with axe's "needs review" findings included. Not a gate — see below. |
| `check:docs-links` | `docs/audits/check_doc_links.py` over every page under `docs/site/**` and every route-manifest `source:` file, so a page's Markdown also works as-is on GitHub, wherever it lives. `docs/site/README.md` is excluded: it is the authoring contract, not a page, and its link table shows illustrative paths that resolve nowhere on purpose. |
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

### Product screenshots

Product screenshots are part of the **site transformation**. The canonical
guides remain plain repository Markdown. Keep real browser captures in
`site/public/product/`, and their alt text, captions, capture revision, and
placement rules in `site/product-captures/screenshots.json`. Do not add copied
guide text, screenshot paths, or site components to the canonical documents.

`scripts/lib/product-screenshots.mjs` matches the owning source file, route, and
exact heading, then adds the captures after that section's first paragraph.
The sync uses the same metadata for full guides, the selected landing-page
introduction, and the Markdown exports. An agent gets every image description,
qualification, and image link, including captures that the human page puts
inside a native disclosure. Missing assets or renamed headings fail the build.

Capture and refresh instructions live in `site/product-captures/README.md`.
Captures use fictional material and retain the original UI pixels. They load
lazily, reserve their dimensions, scale to the reading column, and link to the
full-size image. No screenshot gallery runtime or model call runs during a
site build.

The A/B/C comparison builds share these captures and canonical guides. C is the
site: the committee adopted it on 18 October 2026, so a build with no layout
variables (`npm run build`, CI, GitHub Pages) is C — `SITE_LAYOUT=pathways` and
`SITE_EXPERIENCE=explore` are both defaults. A (`SITE_LAYOUT=classic`) and B
(`SITE_EXPERIENCE=cards`) stay buildable for comparison; the gates run on C.
B retains Iris's card landing and top pathway tabs; C uses the persistent sidebar,
search composer and a contextual right sidebar. B's introduction is selected from the same
canonical overview as C. The classic homepage, both pathway homepages, quickstart,
tier explanation and table-mode skill section project the relevant captures.

### Build variables

| Variable | Default | What it sets |
|---|---|---|
| `SITE_URL` | `https://legalquants.github.io` | Astro's `site` — the origin in canonical URLs, the sitemap and the machine surface. |
| `SITE_BASE` | `/lq-ai/` | Astro's `base` — the path the site is served under. |
| `SITE_LAYOUT` | `pathways` | `pathways` navigation (B/C) or the classic eight-section documentation (A). |
| `SITE_EXPERIENCE` | `explore` | Within pathways, `cards` preserves B and `explore` selects C. |
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

One rendering decision exists to keep the gate green for pages nobody has
written yet, rather than to fix the pages that exist today: **code blocks
wrap** (`expressiveCode.defaultProps` in `astro.config.mjs`). An overflowing
`<pre>` is a scroll region no keyboard can reach (`scrollable-region-focusable`,
WCAG 2.1.1). Wrapping removes the scroll region rather than papering over it.
Copy-to-clipboard still copies the unwrapped source.

Tables no longer need a decision like this one: they are classified into a
shape that fits the column, rather than scrolled. See
["Tables" under "How it is built"](#tables).

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

**The theme** is the proposed LQ.AI interface redesign (October 2026), so the
documentation reads as part of the same product as the app: ink on white in
light, near-black in dark, pills and round buttons for every control, and colour
spent on two meanings only. Its palette departs from ADR 0043's and is still
with the committee (its flag F1). Two files carry it:

- `src/styles/theme.css` — the palette for both themes and every content style
  (prose, tables, asides, chips, cards, code), shared by all layouts. Colours the
  redesign's mockups never needed are marked *derived*.
- `src/styles/theme-pathways.css` — Version C's layout and per-pathway wiring,
  loaded after it. Each page still takes its pathway's tone, but every tone is
  ink. On wide screens there is no full-width header: the pathways sidebar runs
  the full height with the wordmark and search at its top, and the header is a
  52px page bar over the reading column with the three round buttons.

Light is the default. No webfonts: the type stack is what the reader's system
already has (SF on Apple devices, Segoe UI on Windows), so rendering a page makes
no third-party request; the pathways layout's Source Sans 3 file is gone. Every
colour decision carries its measured contrast ratio in a comment, and
`check:contrast` re-measures them from both files.

Where colour goes, because it is the rule a later edit is most likely to bend:

- **Ink is the accent.** Links are the prose colour with an underline (the
  underline is what marks them, so it is never removed); headings, the focus
  ring, the current pathway and filled buttons are ink.
- **Orange marks governance only** (the redesign's C15): the Security & privacy
  pathway — the trust centre — gets the orange dot on its sidebar row, its
  Explore card and its breadcrumb (`governance: true` in `src/pathways.mjs`).
  `#e8590c` (`--lq-orange`) is the mark, never text; `check:contrast` fails if
  it is ever measured as passing for text.
- **Red is for danger only** (C26): Starlight's `danger` aside. Note, tip and
  caution asides are monochrome — caution is told apart by an ink rule — and so
  are status chips (C28): done is an ink outline, in motion a dashed line, not
  live a quiet fill. Build-time diagrams use the same greys
  (`scripts/lib/diagrams.mjs`).

The classic layout (A) shares `theme.css` and so the palette, but none of
Version C's chrome; it is kept for comparison, not styled further.

Four places where the theme deliberately overrules a Starlight default, because
each one is the kind of thing a later edit would quietly undo:

- **The H2 section rule sits on `.sl-heading-wrapper.level-h2`, not on the
  `h2`.** Starlight sets the heading itself to `display: inline` so its ¶ anchor
  can sit on the last line, which means a border on the `h2` tracks the width of
  the *text* — a two-line heading gets a rule under only its second line. The
  wrapper is the block box.
- **Cards are one object.** `<Card>`, `<LinkCard>`, the previous/next pair and
  the Explore pathway cards all take the hairline border, the raised ground and
  the 16px radius; on hover the line darkens and the fill lifts one step —
  nothing moves. Starlight gives the previous/next pair a *strong* line, no
  ground and a grey-fill hover, so without this the design language would stop
  at the edge of the prose.
- **The current pathway is a grey pill, not a solid accent fill.** With an ink
  accent, a filled row would be a black block — the loudest object on the page.
  The pill is the redesign's selected row, at weight 600 rather than its 500,
  because the fill is soft and the weight has to carry the state. The state is
  carried three ways that are not colour: `aria-current`, the weight, and the
  pill.
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
| `StatusBadge.astro` | `draft` / `reviewed`, as a word in a chip whose outline repeats it, never colour alone. |
| `Eyebrow.astro` | The small caption primitive (the classic layout's section label). |

Each override keeps Starlight's landmarks, skip link and focus order: the H1
keeps the `#_top` id the skip link targets, the header renders inside
Starlight's own `<header>`, and the namespace nav is a labelled `<nav>` that
collapses into the existing mobile menu rather than being duplicated.

### Tables

A Markdown table stays a table in its source — GitHub and the `.md` twin both
still render it as one — but the built page renders it as whichever of three
shapes actually fits a 632px reading column. The rewrite is
`scripts/lib/rehype-lq-tables.mjs`, a dependency-free hast transform. Astro 7's
Markdown processor is Sätteri, not remark/rehype, so `astro.config.mjs` wires it
through `satteri({ hastPlugins: [rehypeLqTablesSatteri()] })` — the adapter that
unwraps Sätteri's `raw` comment nodes and applies edits through `ctx.replaceNode`
— and it runs on every Markdown and MDX table.

The rule, applied to each table in order:

1. An explicit directive wins outright (below).
2. Two columns become a definition list (`.lq-dl`): a caption naming the two
   original headers, then a hairline-separated `dt`/`dd` pair per row.
3. Otherwise, if the table is both short and narrow — every column's longest
   cell is 36 characters or under, the columns sum to 72 or under, and there
   are no more than 5 of them — it stays a plain, wrapped `<table>`
   (`.lq-table`): the minority of tables that are genuinely tabular.
4. Otherwise it becomes a set of records (`.lq-records`): one `<article>` per
   row, titled from its first column (a stable, citable `#slug` anchor), its
   short columns collected into a meta line and its long, prose columns
   stacked in a body — this is most of the tables in the docs, because most of
   them are one-row-per-entity data with a paragraph in at least one cell, not
   a grid.

A writer overrides the classification for one table with an HTML comment
immediately above it:

```markdown
<!-- table: grid -->
<!-- table: dl -->
<!-- table: records -->
<!-- table: records key=2 -->
```

`key=N` (1-based) picks which column becomes a record's title; it defaults to
the first column. The comment is removed from the rendered page.

**`check:tables`** is the gate: at 1280px and 400px, over every route, it
asserts nothing inside `.sl-markdown-content` scrolls horizontally and that no
`[tabindex="0"][role="region"]` scroll wrapper remains — the shapes exist so
that a table never needs one.

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

Write plain Markdown at the file's canonical repository location, add an
entry to a `docs/site/routes/*.yaml` route manifest, and follow
[the authoring contract](../docs/site/README.md) for the entry's fields. It
appears in the sidebar and in the machine surface on the next `npm run sync`
— there is nothing to register here. A hub page (`docs/site/index.mdx`,
`docs/site/<namespace>/index.md`) is still written directly under
`docs/site/`, with its own frontmatter, exactly as before.

## CI

`.github/workflows/docs-site.yml` runs `npm run check` on every pull request
that touches the site or anything it reads, and deploys to GitHub Pages on
`push` to `main`. Its path filter includes the generators' own inputs
(`api/app/config.py`, `gateway/app/config.py`, `api/app/skills/schema.py`,
`gateway.yaml.example`, `mcp.yaml.example`, `docker-compose.yml`) as well as
`docs/**` — otherwise a settings change would ship while the published
`/reference/configuration/` still described the previous release, and nothing
would announce it.

It also rebuilds and deploys `main` when the **Release** workflow finishes
(`workflow_run`), and on demand (`workflow_dispatch`). The release-notes index
lists the `v*` tags reachable from the commit being built (`git tag --merged
HEAD`), and a release's notes reach `main` before its tag is cut — so the deploy
at that merge cannot list the new tag yet, and without the Release trigger the
index would read "Release notes exist for vX.Y.Z without a matching tag" until
the next docs change. A release page itself comes from `docs/releases/vX.Y.Z.md`,
written in the release PR.

**Local builds and tags.** Version tags are read from the clone you build in. A
clone that also fetches Open WebUI (the `upstream` remote of the `web/` fork)
can hold Open WebUI's tag of the same name — it used `v0.9.0` and `v0.9.1` before
LQ.AI did — and git does not overwrite an existing tag on fetch, so a local
build silently leaves that release out of the index. CI's fresh checkout has
only LegalQuants' tags. Locally, `git fetch <LegalQuants remote> --tags --force`
repoints the colliding names at LQ.AI's releases.

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

## Source-backed Explore and agent tasks

### LiquidUI interaction layer

The Explore experience uses persistent navigation from `src/pathways.mjs`,
rendered by `components/pathways/Sidebar.astro`. Starlight supplies the native
mobile popover and focus behavior. Explore renders every introductory answer,
diagram, screenshot, status badge, and source link as ordinary static HTML.

`DocsSearch.astro` and `scripts/docs-search.ts` adapt Iris's composer to the
existing Pagefind index. Search runs on this origin, loads the engine on demand,
and presents matching excerpts with section, Markdown and status links; a
result's title opens the guide's own page. No model request or additional
ranking engine is used. The conversation outlives a visit to a guide: this
tab's questions and the result last selected or opened are kept in
`sessionStorage` (never sent anywhere; `rememberSearches`/`recallSearches` in
`src/lib/explore-state.mjs`), the searches run again when Explore loads, and
Back returns to that result.

**Version C has one search, in one place.** The composer is fixed to the bottom
of the reading column on every page, and nothing else on the page searches:
there is no search control in the sidebar or the top bar, and Starlight's
Pagefind modal is not rendered (B keeps it). On Explore it is `DocsSearch.astro`
and its results join the conversation; on every other page it is
`DocsComposer.astro` (rendered from the footer, so it is last in keyboard
order), which hands the question to Explore in the URL fragment — `/#q=…`,
never sent to the server — where it runs as if typed there, and Back returns to
the page. Command/Ctrl K focuses the composer on every page. `exploreSearchHref`
and `searchFromHash` in `src/lib/explore-state.mjs` are the hand-off's
contract, pinned by `test/explore.test.mjs`.

**Guides are read on their own pages; the right sidebar says what they are.**
Version C follows the interface redesign's rule for the app's right sidebar
(C19): it shows details of whatever is open or selected, can be closed, and is
not drawn when there is nothing to show. It appears from 72rem wide, the width
at which Starlight shows a page's contents column; narrower screens keep the
same facts in the page.

- **On Explore** (`GuideDetails.astro`, `scripts/guide-details.ts`), a search
  result can be selected: click its free space or its **Details** button. The
  sidebar shows the guide's kind and status, its one-line description, Open
  guide and Markdown, its sections ("In this guide"), who it is written for, its
  source files and the commit it was checked against. A new search selects its
  first result; the close button or Escape closes the sidebar.
- **On a guide page** (`TableOfContents.astro` and `GuideFacts.astro`, which
  wrap Starlight's own "On this page"), the column reads: About this page (kind,
  status, readers, the commit it was checked against — above the contents, so a
  draft's status stays in view), On this page, Sources, Related (the other pages
  of its pathway group, leading with the next; `relatedRoutes` in
  `src/pathways.mjs`) and Text copies (Markdown, Docs for agents). While the
  column is on screen, the title area's chips and text links and the footer
  stamp give way to it.

After Astro and the machine exports finish, `scripts/gen-guide-details.mjs`
writes `dist/_guides/index.json`: one entry per guide and navigation page, which
Explore loads with its first search. The facts come from the sync manifest; the
sections are read from each full page's compiled HTML
(`scripts/lib/guide-details.mjs`), so a section link always matches an anchor
the page has. The page builds the sidebar from that text with `textContent`.
Cheerio 1.0.0 is an explicitly pinned build dependency, matching the version
already installed through the site's QA tooling; it is not shipped to browsers
and introduces no additional transitive packages.

Explore scrolls the window like every other page; it has no inner scroll box of
its own.

Playback is an explicit opt-in. `scripts/tour-playback.ts` highlights and visits
the three source-backed answers; it never removes content or search results.
Pause, resume, and replay retain context, and reduced-motion settings suppress
animated scrolling. Every answer and all guide links remain usable without
JavaScript; without it there is no search and no sidebar, only ordinary links.

Iris's design/code attribution and the original license are retained under
`third-party/iris-liquidui/`. `docs.js` from the ZIP is not a source dependency.
Changing a repository guide rebuilds its full page, sidebar details, search
index, and agent Markdown in the same build.

The sync resolves `docs/site/_data/explore.yaml` and `journeys.yaml` against the
canonical Markdown route registry. It writes generated answer fragments under
`src/content/explore/` and normalized Markdown/view data under `src/generated/`.
Neither directory is committed. Astro renders the answer collection; the
quickstart navigation reads the same resolved journey data.

Postbuild writes `tasks.json` with direct Markdown URLs and prerequisite, step,
alternative, and verification heading references. `llms.txt` adds goal discovery
and Markdown links. The pathways landing, pathway pages, and All documentation
also receive text twins; the 404 page is excluded from the text corpus. Exported
alternatives keep their labels and complete instructions independently of what
a human has expanded. MDX component examples in code fences are preserved.

Run `npm test` for source-selection, disclosure, export, and route regressions,
then `npm run check` for the complete site gates (C is the default build). Inspect
the introduction and quickstart in a browser, including opening optional details
and following the text links. The introduction and quickstart include static diagrams compiled from the
canonical Markdown. The LiquidUI interaction layer above adds local search,
optional playback, and the contextual right sidebar; a complete guided fictional
document walkthrough remains a later increment.

## Build-time diagram rendering

`npm run diagrams` runs after sync and before Astro. It renders Mermaid fences
with `accTitle` and a one-line `accDescr`, using the existing Puppeteer/Chrome
tooling. The build uses Mermaid 11.15.0, exactly pinned to match the web app's
locked version. This build dependency provides graph parsing, layout, labels,
and accessible SVG output; maintaining a separate graph renderer would duplicate
that substantial work. Mermaid is not imported into browser components.

The renderer uses a local bundle, blocks network requests, and keeps strict
Mermaid settings. It writes assets under `public/_diagrams/` and caches them in
`.diagram-cache/`, keyed by source, theme, and renderer version. Both directories
are ignored by Git. A sync resets the generated HTML inputs; repeating the
diagram step reuses the saved pre-diagram inputs safely. The normalized machine
Markdown and generated navigation text are never replaced with SVG markup.

Chrome must be available for an uncached render, as it already is for the
layout/accessibility gates. The renderer follows those tools' local sandbox
settings and existing CI launch settings. Check the diagrams in desktop/mobile
and light/dark views, then run the full site gates.
