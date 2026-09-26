---
title: Find the instructions you need
description: Route straight to the namespace that matches what you're trying to do, and permission to skip everything else.
audience: [operator, evaluator, contributor, agent]
status: draft
sources:
  - README.md
sidebar:
  order: 5
---

You do not need to read this site in order, and you do not need to read all of it. Find your goal below and go straight there — nothing elsewhere on the site is a prerequisite for it, except a running deployment for anything that says "in a running deployment."

| Your goal | Start here |
|---|---|
| Decide whether LQ.AI is worth trying | [Is LQ.AI right for your team?](../../start/is-it-for-you.md) |
| Get a deployment running today | [Set up LQ.AI and try your first document](../../quickstart.md) |
| Install on a specific topology (macOS, Docker Compose, Kubernetes, air-gapped, behind a reverse proxy) | [Operate](../operate/index.md) |
| Run it day to day: back up, upgrade, rotate a leaked key, recover from a failure | [Operate](../operate/index.md) |
| Convince a security or procurement reviewer | [Trust](../trust/index.md) |
| Understand or write a skill, or judge whether to trust one | [Skills](../skills/index.md) |
| Package a client-facing, branded deployment | [Deliver](../deliver/index.md) |
| Contribute code, a skill, or a review | [Contribute](../contribute/index.md) |
| Work with a coding assistant on the repository | [Coding agents](../../contribute/coding-agent-onboarding.md) |
| Look up a generated spec: configuration keys, skill frontmatter, the ADR index | [Reference](../reference/index.md) |
| Find out what changed in a release | [Changelog](../changelog/index.intro.md) |

This table exists because the site is organized by namespace (`Operate`, `Trust`, `Skills`, and so on), not by reader role, and the theme grouping is deliberate: it's the same flat shape a coding agent reading the machine surface (`/llms.txt`) needs, not a guided tour that assumes you'll read every page in a role-based sequence. A goal that spans two namespaces — installing behind a reverse proxy while also satisfying a security review, say — legitimately sends you to two rows, in either order.

If your goal isn't on this list, the eight top-level namespaces (Start, Operate, Trust, Skills, Deliver, Contribute, Reference, Changelog) are each a hub page with their own onward links — [the entry page](../index.mdx) lists all eight.

## Next

- [What gets installed and where data goes](../../start/what-it-touches.md) — if you haven't installed yet
- [Where to find help](../../start/where-help-lives.md) — for day-to-day product questions once it's running
