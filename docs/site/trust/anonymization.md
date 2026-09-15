---
title: Anonymization
description: What the Anonymization Layer catches, what it skips by design, and — the part most competitors don't publish — exactly what has and has not been empirically measured.
audience: [evaluator, operator]
status: draft
sources:
  - docs/security/anonymization.md
sidebar:
  order: 4
---

The Anonymization Layer is the gateway middleware that pseudonymizes chat and skill content before
it leaves for a model provider, and rehydrates it back on the way in. This page exists so you can
answer the question a confidentiality-sensitive matter actually asks — not "is there an
anonymization feature" but "what does it catch, what does it deliberately leave alone, and where
is the edge of what anyone has actually measured."

:::caution[Silent failure]
A recognizer miss is silent. For citation verification, a wrong answer surfaces in the UI as an
"unverified" chip — the lawyer sees the system's uncertainty. For anonymization, a missed entity
slips through unredacted, the model provider receives it, the response comes back rehydrated as if
nothing happened, and there is no in-app signal that client confidentiality was breached.
Operational telemetry cannot recover the leak after the fact — by the time a miss is observable,
the unredacted content has already been transmitted, logged upstream, and possibly used in
provider-side training depending on the routed tier. The source below names this directly: the
Presidio default recognizers' recall and precision on legal-document text specifically are
**empirically unmeasured** — Presidio's published metrics target general English (news, social
media), not legal prose.
:::

:::note[Professional duty]
This is the layer that lets you evidence, to your client or your regulator, what happened to their
material before it reached a model provider — not "the gateway ran some redaction" but the specific
entity types it targets, the ones it deliberately does not, and the round-trip guarantee the tests
pin. Where the unvalidated recall risk is not one you can accept for a given matter, the source
below names the mitigation: route that matter to Tier 1 (local-only) inference, where the question
of what a provider sees does not arise.
:::

<!-- include: docs/security/anonymization.md -->

## Next

- [What leaves my deployment](what-leaves-my-deployment.md) — where this layer sits in the larger data-flow picture.
- [Audit & evidence](audit-and-evidence.md) — how a privileged-project's anonymization-skip decision shows up in the audit trail.
- [Verify these claims yourself](verify-these-claims.md) — the test commands that pin the round-trip guarantee.
