---
title: Every failure the sync must refuse
---

This fixture is never built. It exists so the test suite can prove that each
failure exits non-zero and names the page and the line, rather than shipping a
page with a hole in it.

It has no `description`, which is itself one of the failures.

<!-- include: docs/does-not-exist.md -->

<!-- include: site/test/fixtures/repo/guide.md from="## Nowhere" -->

A link to a page nobody has written: [nowhere](does-not-exist.md).
