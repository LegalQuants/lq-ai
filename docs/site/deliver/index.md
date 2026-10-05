---
title: Hand over LQ.AI to a client
description: Agree who will maintain and manage a delivered deployment, check the license and branding requirements, and see what this namespace does not answer yet.
audience: [partner]
status: draft
sources:
  - docs/adr/0001-openwebui-fork-pin.md
  - LICENSE
  - web/LICENSE
  - docs/security/encrypted-keys.md
  - docs/adr/0011-transparency-first-model-selection.md
  - docs/api/backend-openapi.yaml
sidebar:
  order: 1
---

Before handing over an installation, agree who will maintain it, manage access, and choose the
AI services it can use — and check the license and branding requirements for the version you're
delivering. You are here because you run LQ.AI for someone else — a client, a portfolio company, an
internal business unit that is not "you" — and you need to know what you can promise
them about the deployment before you promise it. That is a narrower question than "how do
I install it" (`/operate/`) or "is the data handling sound" (`/trust/`); this namespace is
about the commercial and licensing surface of delivering a *branded* deployment.

## What ships here today

Only one page: [branding and licensing obligations](../../adr/0001-openwebui-fork-pin.md). It answers
the question that has an actual answer in the repository right now — what the upstream
license lets you do with LQ.AI's chrome, and where the line sits. It does not supply a complete
production-readiness assessment, support contract, theming manual, or multi-client operating plan
— use the installation, maintenance, and privacy guides to assemble the rest of the handover, and
agree the remaining responsibilities with the client.

The rest of this namespace — a stitched deployment guide across `/operate/`, `/skills/`
and `/trust/`; the theming mechanics (which CSS variables a branded deployment actually
sets); multi-deployment operations; a production-readiness matrix; what you may and may
not claim to a client; a hand-off pack for a client's security team — does not exist yet.
The docs-site mini-PRD (PR #511) leaves the framing for this namespace as an open question
(its open question 4) and ships only the branding page independently while that question
is unresolved. That is a deliberate scope decision, not an oversight: the pages above
assume answers (a support-tier taxonomy, a claims policy) that no canonical file in this
repository states today.

If your question is closer to "are we ready to turn a pilot into a program" — support
tiers, what an enterprise IT function will ask for — there is no production-readiness
matrix here yet. Usage and cost for a period is the one part of that question the
repository does answer today: `GET /api/v1/admin/usage` (admin-only) aggregates
`inference_routing_log` by user, provider, model, tier or day over a `date_from`/`date_to`
range and returns request counts, token sums and an estimated cost per group plus
deployment-wide totals — see `docs/api/backend-openapi.yaml`. Refused calls are excluded
from the aggregation by default. Beyond that, the nearest honest answers live scattered
across [the trust centre](../trust/index.md) (what is measured and evidenced),
[Operate](../operate/index.md) (what is actually running and how you back it up), and
[Published gaps](../../HONEST-STATE.md) (what is explicitly not built). None of those
is a substitute for a readiness matrix; treat this paragraph as a pointer, not an answer.

## Forking as a multi-tenant SaaS

LQ.AI's own code is Apache 2.0 (see [branding and licensing](../../adr/0001-openwebui-fork-pin.md)),
and Apache 2.0 does not prohibit running a fork as a hosted, multi-tenant service. That
makes a fork-based SaaS offering **legal** — for LQ.AI's own code. The web client is not
Apache 2.0: `web/LICENSE` clause 4 binds *any* deployment or distribution, and a
multi-tenant service is the likeliest way to pass its fifty-end-user / rolling-30-day
threshold. Above the line you keep OpenWebUI's branding alongside yours, or you hold
written permission or an enterprise license from OpenWebUI. Read
[branding and licensing obligations](../../adr/0001-openwebui-fork-pin.md) before you price the
offering. A fork-based SaaS offering is not, however, something this project
builds or supports: the Inference Gateway's key model assumes one operator holding
provider keys for their own deployment, and billing individual end users to their own
provider accounts is, in the architecture's own words, "a different architecture"
(`docs/security/encrypted-keys.md`, citing ADR 0011). Nothing in the codebase, the PRD, or
this site documents how to build that architecture. If you are evaluating it, read that as
a real gap, not a hidden feature.

## Next

- [Branding and licensing obligations](../../adr/0001-openwebui-fork-pin.md) — the page that ships today.
- [Trust centre](../trust/index.md) — what you can already hand a client's security or
  procurement team.
- [Operate](../operate/index.md) — what actually runs, and how to back it up before you
  put a client's data through it.
