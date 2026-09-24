---
title: Reference
description: The generated reference material this site builds from the codebase, and what each artifact is built from.
audience: [operator, author]
status: draft
sources:
  - api/app/config.py
  - gateway/app/config.py
  - api/app/skills/schema.py
  - gateway.yaml.example
  - mcp.yaml.example
  - docs/adr/0025-release-versioning-and-pipeline-ordering.md
  - .github/workflows/docs-site.yml
sidebar:
  order: 1
---

The pages under `/reference/` are not written by hand. Each is generated at build time from
a specific file (or set of files) elsewhere in the repository, so it cannot drift from the
code the way a hand-maintained reference can — it can only be as current as the file it
reads, which the page's own commit stamp names. That stamp is the newest commit on
`main` that touched the page's source files at the time the site was published — not
the release you are running. Before you rely on a generated setting, compare the stamp
against your installed image tag: a page can describe a setting that arrived after your
release, or one that has since been renamed.

| Page | Built from | What it's for |
|---|---|---|
| Configuration reference | [`api/app/config.py`](../../../api/app/config.py), `gateway/app/config.py` (the Pydantic settings models: field, type, default, description) plus [`gateway.yaml.example`](../../../gateway.yaml.example) and [`mcp.yaml.example`](../../../mcp.yaml.example) reproduced verbatim with their comments | Every environment variable and config-file key an operator can set, in one table, instead of grepping three files |
| Skill frontmatter schema | the loader's Pydantic schema, [`api/app/skills/schema.py`](../../../api/app/skills/schema.py) | The exact fields a `SKILL.md` frontmatter block can carry — for anyone authoring a skill |
| ADR index | every file under `docs/adr/` | Every architecture decision record with its real, current status line — including ones that have drifted, which is deliberate: a stale status here is a bug to file, not a reason to hide the table |
| [Release versioning](../../adr/0025-release-versioning-and-pipeline-ordering.md) | [ADR 0025](../../adr/0025-release-versioning-and-pipeline-ordering.md) | What a version bump means before you take it — curated, not generated, because the ADR's own words are the clearest statement of the policy |

The first three rows are built by scripts, not by a writer; there is no full `docs/site/`
source page behind them to link to directly, so the table above links to the code they
read instead. Configuration reference is the one exception with hand-written material: a
short `docs/site/reference/configuration.intro.md` supplies the tier-direction and
env-forwarding notes that precede its generated tables, but the tables themselves are
still script output, not a page a writer maintains. Once the site is built, they live at
`/reference/configuration/`, `/reference/skill-frontmatter/` and `/reference/adr-index/`.

Two further references that earlier planning for this site considered — an
error-vocabulary table and a playbook-position schema reference — are not built in this
draft. Nothing on this page links to them; treat their absence as scope not yet taken up,
not as a broken link.

## Next

- [Release versioning](../../adr/0025-release-versioning-and-pipeline-ordering.md) — start here if you're deciding whether to take an
  upgrade.
- [Changelog](../changelog/index.intro.md) — per-release detail that cites the versioning
  policy on this page.
- [`api/app/config.py`](../../../api/app/config.py) — the source the configuration
  reference is generated from, if you need it before the generated page exists.
