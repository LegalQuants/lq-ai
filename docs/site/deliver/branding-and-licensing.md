---
title: Branding and licensing obligations
description: The upstream branding clause, the fifty-user threshold, and the compliant pattern for a client-branded LQ.AI deployment.
audience: [partner]
status: draft
sources:
  - docs/adr/0001-openwebui-fork-pin.md
  - LICENSE
  - web/LICENSE
  - NOTICES.md
  - docs/db-schema.md
  - docs/api/backend-openapi.yaml
  - .gitmodules
sidebar:
  order: 2
---

This page is for whoever signs off on what a client is told about a branded LQ.AI
deployment — a deploying firm, an internal legal-ops lead, or the lawyer reviewing the
arrangement. It answers one question: what can you lawfully promise about removing or
replacing the software's own branding, and what do you have to keep in place if you can't.

## Two licenses, not one

LQ.AI's own code — `api/`, `gateway/`, the skills, this documentation — is licensed
[Apache License 2.0](../../../LICENSE). The web chat client (`web/`) is a fork of
[OpenWebUI](https://github.com/open-webui/open-webui), pinned per
[ADR 0001](../../adr/0001-openwebui-fork-pin.md), and it carries OpenWebUI's own license,
not Apache 2.0: [`web/LICENSE`](../../../web/LICENSE). Rebranding a deployment means dealing
with both — Apache 2.0's own obligations (below), and the branding clause below, which is
OpenWebUI's, not LQ.AI's.

## The branding clause

`web/LICENSE` clause 4 reads, in full:

> Notwithstanding any other provision of this License, and as a material condition of the
> rights granted herein, licensees are strictly prohibited from altering, removing,
> obscuring, or replacing any "Open WebUI" branding, including but not limited to the name,
> logo, or any visual, textual, or symbolic identifiers that distinguish the software and
> its interfaces, in any deployment or distribution, except in the following circumstances:
> (i) deployments or distributions where the total number of end users (defined as
> individual natural persons with direct access to the application) does not exceed fifty
> (50) within any rolling thirty (30) day period; (ii) the licensee has obtained specific
> prior written permission from the copyright holder; or (iii) where the licensee has
> obtained a duly executed enterprise license expressly permitting such modification. For
> all other cases, any removal or alteration of the "Open WebUI" branding shall constitute
> a material breach of license.

Three lawful positions, and only three:

1. **Under the threshold.** Fifty or fewer end users — natural persons with direct access
   to the deployed application, not service accounts or API callers — in any rolling
   30-day window.
2. **Written permission** from the OpenWebUI copyright holder, obtained specifically for
   your deployment.
3. **An enterprise license** from OpenWebUI, executed and covering the modification you
   intend to make.

Above the threshold, without (ii) or (iii), you cannot remove, obscure, or replace
OpenWebUI's name, logo, or other identifiers anywhere in the deployment. That is a
condition of `web/`'s license, not a policy LQ.AI chose — ADR 0001 records it as
significant enough to require its own documentation, and this page is that documentation.

## The compliant pattern: dual-branding

The obligation-compliant way to put your own brand on a deployment above the threshold is
**dual-branding**: add your firm's or client's branding — banner, footer, chrome — *alongside*
OpenWebUI's identifiers, never in place of them. ADR 0001 names this as the intended
pattern for LQ.AI's own branding work and it applies equally to any further client
branding layered on top. LQ.AI's own UI customizations already isolate branding changes
into dedicated files for exactly this reason (ADR 0001, "How customizations are
organized").

:::note[Professional duty]
"May we remove the Open WebUI logo for this client" is a licensing question a client or a
partner will ask you directly, in those words. Answering it from this page rather than
from memory is a competence question, not a formality — the compliant pattern above the
threshold is dual-branding, not silence about the obligation.
:::

## Determining your current end-user count

The license's carve-out (i) is time-bound — a rolling 30-day count, not a one-time check.
LQ.AI has no report that answers the license's question directly, but it does have one
that gets close. `GET /api/v1/admin/usage?group_by=user&date_from=<30 days ago>` returns
one row per user who ran an inference call in the window (`docs/api/backend-openapi.yaml`,
`api/app/api/admin.py`); the number of rows is a rolling-30-day active-user count. It
counts users who ran inference, not every person with access to the application, and rows
with no user id are coalesced into a single `anonymous` bucket — so it is a floor, not the
license's test.

:::caution[Silent failure]
Crossing fifty end users produces no in-app signal. The deployment keeps running exactly
as before; nothing warns you that the license carve-out you were relying on has lapsed —
`/admin/usage` has to be pulled and read deliberately, on a schedule you set yourself.
:::

An operator with database access can approximate the count directly: the `users` table
carries `last_login_at` (`docs/db-schema.md`), so

```sql
SELECT count(*) FROM users
WHERE last_login_at > now() - interval '30 days'
  AND deleted_at IS NULL;
```

gives the number of accounts that actually used the deployment in the trailing 30 days —
the closest available proxy for "end users…within any rolling thirty (30) day period."
This is a manual query against your own database, not a maintained report, and it counts
authenticated accounts, not the license's "individual natural persons with direct access"
test exactly — a shared account undercounts, several accounts for one person overcounts.
Treat it as a floor to check periodically, not a compliance instrument.

## Skills you bundle

If a branded delivery includes skills pulled from the community catalog
(`skills/community/`, a submodule of [`LegalQuants/lq-skills`](https://github.com/LegalQuants/lq-skills)),
those carry their own license and attribution terms — independent of the OpenWebUI
branding clause above. [NOTICES.md](../../../NOTICES.md) carries one row for the whole
community submodule and points elsewhere for the detail: the license is the per-skill
`LICENSE` file in each skill's own folder, and the attribution requirement is the author
named in that skill's `SKILL.md` frontmatter `author` field. There is no per-skill row in
this repository to check — open the skill's folder in
[`LegalQuants/lq-skills`](https://github.com/LegalQuants/lq-skills) before promising a
client that a skill's authorship or licensing is resolved.

## Apache 2.0, for LQ.AI's own code

If you redistribute a modified copy of LQ.AI's own code (outside `web/`), Apache 2.0
requires you to retain the copyright and license notices and state, in the modified files,
that you changed them (LICENSE §4). The repository does not currently carry a root-level
`NOTICE` file, so there is nothing to propagate under that specific clause today — if one
is added later, redistributing under a different license without carrying it forward would
itself be a license violation.

## Next

- [Deliver to a client](index.md) — what else this namespace does and does not cover yet.
- [`web/LICENSE`](../../../web/LICENSE) and [`LICENSE`](../../../LICENSE) — the source texts.
- [ADR 0001](../../adr/0001-openwebui-fork-pin.md) — the fork decision and the branding
  clause's full context.
