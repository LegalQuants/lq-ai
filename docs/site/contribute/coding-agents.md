---
title: Point a coding agent at LQ.AI
description: The cold-start guide a coding agent (or a human working alongside one) reads before its first contribution, plus how to fetch this site as plain text.
audience: [contributor, agent]
status: draft
sources:
  - docs/contribute/coding-agent-onboarding.md
sidebar:
  order: 6
---

The community's actual advice for onboarding a new contributor's coding agent is: point it at the repository. The guide below is written for that agent directly — read it whole before a first contribution, whether you are the agent or the human running it.

It exists because the tribal knowledge that makes a contribution land cleanly the first time — the read-order, the test-suite collision guards that crash the whole suite at collection rather than failing one test, the dev-environment rules that corrupt a shared stack — used to live only in reviewers' heads and in scattered code comments. This page is where an agent (or a human working alongside one) gets that context in one read, in the order it is actually needed, rather than accumulating it one failed pull request at a time.

<!-- include: docs/contribute/coding-agent-onboarding.md -->

## Reading this site as plain text

Everything above concerns the repository. If your agent's first contact with the project is this documentation site rather than a clone, it does not need to render HTML to read it: every page on this site is also served as plain Markdown at its own URL with `.md` appended, so a page's URL and its machine-readable twin differ only by that suffix. Two additional entry points cover the whole site in one fetch each: `llms.txt` at the site root, listing every page with a one-line description grouped by namespace, and `llms-full.txt`, concatenating every page's full text in sidebar order for an agent that wants the entire site in one request rather than one page at a time.

This is a build requirement of the site itself, not a page any of these pages links to individually — it applies uniformly, to every route the site publishes, including this one. The mechanism is specified in the docs-site mini-PRD (PR #511); it is not yet documented in any file this page can cite by commit, because the mini-PRD lives on its own branch.

## Next

- [Dev-environment guide](dev-environment.md)
- [On-ramp for engineers](engineers.md)
- [The reference hub](../reference/index.md) — the generated artifacts an agent will want: configuration schema, skill frontmatter schema, ADR index
