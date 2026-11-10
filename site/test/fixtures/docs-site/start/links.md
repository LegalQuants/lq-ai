---
title: Fixture link cases
description: One page carrying every link case the transform has to get right.
audience: [agent]
status: draft
sources:
  - CONTRIBUTING.md
sidebar:
  order: 3
---

Each bullet is one branch of the link table in `scripts/lib/links.mjs`.

- Another site page: [the namespace hub](index.md)
- The entry hub, which is MDX: [home](../index.mdx)
- A generated page, reached through its intro file: [ADR index](../reference/adr-index.intro.md)
- The primary source of a site page: [the fixture guide](../../repo/guide.md)
- A route-manifest source, mapped with no docs/site wrapper: [the manifest basic page](../../repo/route-mapped/basic.md)
- The same file with an anchor, which keeps its repository URL: [the install section](../../repo/guide.md#install)
- Any other repository file: [the project README](../../../../../README.md)
- A repository directory: [the ADR folder](../../../../../docs/adr)
- An image, copied into the site: ![the launcher home screen](../../../../../docs/images/launcher-home.png)
- An external URL, untouched: [the repository](https://github.com/LegalQuants/lq-ai)
- A bare anchor, untouched: [back to the top](#fixture-link-cases)

## Next

- [Curation](curation.md)
