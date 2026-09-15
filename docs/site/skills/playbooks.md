---
title: Playbooks
description: The artifact that codifies an organization's standard and fallback positions against a contract, rather than a workflow.
audience: [author, evaluator]
status: draft
sources:
  - docs/playbooks.md
  - skills/CONTRIBUTING.md
sidebar:
  order: 8
---

A playbook is a different kind of open-source work product from a skill.
Where a skill's `SKILL.md` is a workflow the model follows, a playbook is a
set of positions — one per issue, with fallback tiers — that a fixed executor
applies to a contract and reports a verdict against, position by position.
Both are equally readable, forkable files; the shape underneath is what
differs. A playbook isn't invoked through the chat composer the way a skill
is — it runs against one target document through the dedicated Playbook
executor, producing a per-position verdict (matches standard, matches a
fallback tier, deviates with a drafted redline, or missing) plus the clause
the verdict referenced, rather than a chat-style report.

<!-- include: docs/playbooks.md from="## Scope" to="## The executor workflow" -->

Five built-ins ship, one `playbook.yaml` per contract type, and the same
transparency commitment applies: the content is filesystem-canonical, not a
value baked into a database migration.

<!-- include: docs/playbooks.md from="## Built-in playbooks" to="## Authorization" -->

:::caution[Silent failure]
Playbook execution is not run through the Citation Engine's verified-citation
path today — its per-position citations are chunk references, not
character-verified quotes. There is no in-product warning. Where the chat
surface shows verified/unverified citation chips, a playbook execution
renders only a citation count and the raw chunk IDs, and writes no
`message_citations` rows — so a per-position citation that was never
verified looks exactly like one that was. Open the cited clause text
yourself before relying on a verdict. Read
[`docs/playbooks.md`](../../../docs/playbooks.md#citations-are-chunk-references-not-verified-citations-today)
for the detail.
:::

## Forking a playbook

A built-in playbook is immutable through the CRUD surface — `PATCH` and
`DELETE` on any of the five seeded built-ins return 403, including for
admins. The canonical way to make one your own is fork-then-edit: create a
new playbook (every `POST` sets you as its owner), starting from a built-in's
`playbook.yaml` as a template, and edit the position-by-position content to
match your own organization's standard and fallback stances. That's the same
forking posture [`skills/CONTRIBUTING.md`](../../../skills/CONTRIBUTING.md)
sets for skills — fork, modify, run your version — applied to positions
rather than to a workflow: a starting point drafted to give you a head
start, not a vetted template, and never a substitute for your own attorney
reviewing every position before you rely on it for client work.

## Next

- [Author your first skill](author-your-first-skill.md)
- [The attestation bar](attestation.md)
