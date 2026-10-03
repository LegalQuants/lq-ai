---
title: Fixture curation page
description: Exercises all three include forms — whole file, from/to slice, and shift.
audience: [agent]
status: draft
sources:
  - site/test/fixtures/repo/guide.md
sidebar:
  order: 2
---

A curation page: entry prose, the include, onward links. The prose is the page;
the include is the canonical file.

## The whole file

<!-- include: site/test/fixtures/repo/guide.md -->

## Only the install section

<!-- include: site/test/fixtures/repo/guide.md from="## Install" to="## Troubleshooting" -->

## The whole file, demoted

<!-- include: site/test/fixtures/repo/guide.md shift=1 -->

A fenced block on the page itself, whose contents must not be rewritten:

```markdown
[not a real link](../../../../../README.md)
<!-- include: site/test/fixtures/repo/guide.md -->
```

## Next

- [Links](links.md)
