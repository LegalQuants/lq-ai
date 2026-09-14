# ADR 0036 — Documentation-site generator and hosting: Astro Starlight on GitHub Pages

**Status:** Proposed (2026-09-14) — for the weekly call
**Date:** 2026-09-14
**Owner:** Maintainer team (houfu)
**Origin:** The documentation-site mini-PRD (PR #511) records the stack as
"Astro/Starlight and hosted on GitHub Pages (maintainer decision, 2026-08-11)". That
sentence is the only record of the generator choice — no minutes, Slack thread, or
decisions-log row names it — so this ADR puts the choice up for acceptance under the
ADR-first workflow rather than letting a PRD sentence stand in for it.

**Relates to:** ADR [0022](0022-committee-governance-and-meeting-records.md) (ADR-first
review), ADR [0023](0023-uv-lockfiles-gateway-api.md) (lockfiles and supply-chain
posture, extended here to a new npm tree), ADR
[0025](0025-release-versioning-and-pipeline-ordering.md) (release versions; the site is
latest-only until 1.0), ADR 0031 (headless / API-only use, proposed in PR #564: the site
does not document building against LQ.AI), PR #511 (the mini-PRD whose requirements this
ADR tests against).

## Context

### What the record says so far

- **2026-06-30** — the maintainer asked in the committee channel whether the docs should
  be hosted on GitHub Pages.
- **2026-07-02** — a committee member voted for GitHub Pages ("docs live in the repo,
  version with the code … free and low-maintenance") and named MkDocs or Docusaurus as
  "the well-trodden path", deferring the tool choice to the maintainer.
- **2026-07-05** — the committee call resolved hosting toward GitHub Pages.
- **2026-08-09** — the committee's public minutes left tooling, scope, location, and
  ownership open; actions were for the maintainer to draft the PRD and for a committee
  member to consult a systems engineer on tooling. No outcome of that consultation is
  recorded.
- **2026-08-11/12** — the mini-PRD (PR #511) names Astro Starlight. **2026-08-16** —
  the minutes record the PRD as open for community review; it has not been adopted.

**Hosting has recorded committee support. The generator does not.** That gap is what this
ADR closes.

### What the site has to do

From the mini-PRD (PR #511, parent document and Annex C). The generator is judged against
these, not against general popularity:

1. **Content stays in this repository.** The site is a curated façade over canonical repo
   files. Every page is stamped with the commit it was checked against, taken from the
   file's own git history. CODEOWNERS review routing keeps applying to the source files.
   A build-time transform (Annex C item C2) injects frontmatter, rewrites links, adds
   commit stamps, and applies exclusion rules.
2. **A machine surface is a launch gate, not an extra.** That means `/llms.txt`, a `.md`
   version at every page URL, and an offline full-text bundle (Annex C item C3).
3. **Reference pages are generated.** They are built from the Pydantic config models,
   skill frontmatter, and the ADR directory (C17, C18, C22). No API reference is published
   (ADR 0031).
4. **Accessibility is gated in CI** at WCAG 2.1 AA, including on generated pages.
5. **`/trust/` URLs stay stable** because procurement memos cite them. GitHub Pages
   cannot configure redirects between a site's own pages, so stability comes from naming
   discipline.
6. **Latest-only until 1.0**, with per-page status badges and no versioned docs.
7. **Non-engineers author pages.** Practising lawyers and compliance professionals write
   and review in plain Markdown.

### The state of the options (as of 2026-09-14)

- **MkDocs with Material for MkDocs.** Material entered maintenance mode on 2025-11-05 and
  is scheduled for **end of life on 2026-11-05**, with critical fixes and security
  updates only until then
  ([squidfunk/mkdocs-material#8523](https://github.com/squidfunk/mkdocs-material/issues/8523)).
  MkDocs 1.x has not released since 1.6.1 (August 2024). A separate MkDocs 2.0
  rewrite is under active development but has no stable release.
- **Zensical**, the successor from the Material team, is pre-1.0 (0.0.62, released
  2026-09-13). `llms.txt` generation is an open feature request
  ([zensical/zensical#252](https://github.com/zensical/zensical/issues/252)).
- **Docusaurus.** 3.10 (April 2026) is the last 3.x release, and v4 is in progress. It
  builds on React and MDX, and has versioned docs built in.
- **Astro Starlight.** It is pre-1.0 but releasing actively (0.42.0 on 2026-09-02, on
  Astro 7). The Astro team joined Cloudflare in January 2026; Astro remains
  MIT-licensed with open governance.
  - `llms.txt` comes from a community plugin, `starlight-llms-txt`.
  - Astro removed the `llms.txt` pipeline from **its own** docs in April 2026. It cited
    low uptake, and is investing in an MCP server and possibly per-page Markdown instead.
  - Starlight's built-in loader reads content from `src/content/docs/` only.

### What already exists

- **Pages is enabled on `LegalQuants/lq-ai`.** It uses the GitHub Actions source and
  serves at `https://legalquants.github.io/lq-ai/`. A `github-pages` environment was
  created on 2026-07-29, and its deployment branch policy allows `main` only. Nothing has
  been deployed.
- **CI already sets up Node 22** (for `web`) and Python 3.12 (for `api` and `gateway`).
  Dependabot covers npm for `/web`, uv for `/api` and `/gateway`, and GitHub Actions.
- **`main` has no site directory and no deploy workflow.** The link checker the PRD gates
  on, `docs/audits/check_doc_links.py`, already exists.

## Decision

1. **Hosting: GitHub Pages on `LegalQuants/lq-ai`.** A GitHub Actions workflow deploys
   the site from `main` only, matching the existing `github-pages` environment rule. The
   repository's maintainers operate the deployment as they operate CI. No third-party
   hosting or build service sits in the publishing path.

2. **Generator: Astro Starlight, isolated in a top-level `site/` directory.**
   - `site/` has its own `package.json` and committed lockfile, with exact version pins
     and its own Dependabot npm entry.
   - The site is built from Astro components and Markdown. Adding a UI-framework
     integration (React, Svelte, Vue) needs its own justification.

3. **Content stays canonical where it lives today.** That means `docs/`, `skills/`, and
   the other source trees. `site/` holds configuration, theme, the transform, and the
   generators, and **never a committed copy of a page**. The transform builds Starlight's
   content collection during the build, and that output is not committed. Source files
   do not need Starlight-specific frontmatter, because the transform injects it.

4. **The project build owns the machine surface.**
   - The transform writes the `.md` version of each page URL from the same source as its
     HTML page.
   - The offline bundle is a build output.
   - A plugin may produce `/llms.txt` if its output meets the PRD's requirements. The
     `.md` routes and the bundle must not depend on a plugin continuing to exist.
   - Astro dropping `llms.txt` from its own docs is the reason for this rule. Upstream
     priorities for agent-facing output move quickly, and here that output is a launch
     gate.

5. **Search is static and first-party**, using Starlight's default client-side index. No
   hosted search service receives reader queries.

6. **Revisit triggers.** Because content is plain Markdown in the repo and the site layer
   is confined to `site/`, changing generator means replacing `site/`. It does not touch
   content. The decision is reopened if any of these happens:
   - Starlight stops being maintained, or its licence changes.
   - A generator on the Python toolchain reaches a stable 1.0 that meets requirements
     1–7, including per-page Markdown. Zensical is the named candidate.
   - Keeping `site/` building starts taking more than occasional pin bumps.

## Consequences

- **A new build-time npm dependency tree enters the SBOM.** It is never shipped in a
  release image. The justification CLAUDE.md asks for:
  - The PRD needs a machine surface, generated references, and an accessibility gate
    across roughly 60 pages.
  - Building and maintaining a generator for that is not a reasonable use of project
    capacity.
- **The deploy workflow lives under `.github/workflows/`**, so CODEOWNERS routes it to
  security review. Its actions are pinned by SHA, like the existing workflows.
- **Starlight is pre-1.0.** Minor releases can break things, so upgrades are deliberate
  pin bumps with a local build, not auto-merged.
- **The launch URL base is `/lq-ai/`.** One later move to a custom domain is cheap.
  GitHub answers every `legalquants.github.io/lq-ai/<path>` request with a permanent
  redirect to `<custom-domain>/<path>` (observed on two such project sites on
  2026-09-14), so cited URLs keep resolving for as long as that domain stays set.
  A second move, from one custom domain to another, is expensive. A Pages site holds one
  custom domain and cannot redirect a previous one, so the old domain would have to stay
  registered and be redirected outside GitHub for as long as anyone cites it. The final
  domain is therefore chosen once, before `/trust/` is offered as a citable reference,
  and verified at the organization level before use. This ADR does not choose it (see
  below).
- **The base path is configuration, never content.** Nothing in page content, link
  rewriting, or generated absolute URLs (`/llms.txt`, canonical tags, the offline
  bundle) hard-codes `/lq-ai/`, so the one move above is a configuration change and a
  rebuild.
- **Previews cannot deploy to Pages.** The environment rule refuses deploys from branches
  and PRs. Until preview hosting is decided, PR builds are checked in CI and made
  available as build artifacts.
- **Authors write Markdown in the repo** as they do today. Nobody needs Node installed to
  contribute a page; CI builds the site.
- **Stewardship is concentrated in one company.** Astro is maintained by a team inside
  Cloudflare. The MIT licence and the `site/` isolation in decision 3 limit the cost if
  that changes.

## Alternatives considered

- **MkDocs with Material for MkDocs**, the path suggested on 2026-07-02.
  - For: it fits the Python toolchain and reads a `docs/` directory natively.
  - Against: the theme reaches end of life on 2026-11-05, before the site's planned
    delivery. Launching on an end-of-life theme with a stalled core would leave the
    project running unmaintained code on day one.
  - **Rejected on maintenance, not capability.**
- **Zensical.** The natural successor to Material. **Not chosen yet** because it is pre-1.0
  and has no `llms.txt` support. It is named as a revisit trigger in decision 6.
- **Docusaurus**, the other path suggested on 2026-07-02.
  - For: mature, widely used, and its capability is comparable for this PRD.
  - Against: its main advantage, versioned docs, is explicitly out of scope before 1.0.
    It brings a React/MDX toolchain into a docs layer that doesn't need one, and it is
    midway through a major-version change.
  - **Not rejected on capability.** If the committee prefers it, decisions 1, 3, 4 and 5
    carry over unchanged.
- **Keep reading Markdown on GitHub (status quo).** There is no machine surface, no
  generated references, and no audience-indexed navigation, so it fails requirements 2, 3
  and 5 outright.
- **A hosted documentation platform** such as Mintlify, GitBook or ReadMe. Content or
  publishing would move to a third party. Review routing would weaken, a
  vendor would sit inside a transparency-first project's public record, and it would cost
  money. **Rejected.**

## Explicitly not decided

- **Custom domain and final URL shape** (an open question in PR #511; the site launches
  at `legalquants.github.io/lq-ai/`).
- **Preview hosting for docs PRs** (open in PR #511; until then, PR builds are CI
  artifacts).
- **The accessibility tool** used for the WCAG 2.1 AA gate. That is chosen at scaffold
  (Annex C item C1).
- **The site's scope, page plan and priorities.** PR #511 holds those; they are not
  architectural and do not need an ADR.

## References

PR #511 (documentation-site mini-PRD) · lq-ai-community minutes
[2026-08-09](https://github.com/LegalQuants/lq-ai-community/blob/main/meetings/2026-08-09-weekly/notes.md)
and
[2026-08-16](https://github.com/LegalQuants/lq-ai-community/blob/main/meetings/2026-08-16-weekly/notes.md)
· [Material for MkDocs end of life](https://github.com/squidfunk/mkdocs-material/issues/8523)
· [Zensical `llms.txt` request](https://github.com/zensical/zensical/issues/252)
· [Docusaurus 3.10](https://docusaurus.io/blog/releases/3.10)
· [Astro joins Cloudflare](https://astro.build/blog/joining-cloudflare)
· [Starlight 0.39](https://astro.build/blog/starlight-039)
· [Starlight plugins, including `starlight-llms-txt`](https://starlight.astro.build/resources/plugins)
· [Analysis of Astro's `llms.txt` removal](https://dacharycarey.com/2026/05/04/astro-removed-llms-txt)
