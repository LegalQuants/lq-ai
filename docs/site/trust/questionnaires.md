---
title: Questionnaires
description: A pre-filled SIG Lite starter for the questions that depend on LQ.AI's privileged-matter handling, and what the full Procurement-Readiness Pack still waits on.
audience: [evaluator, operator]
status: draft
sources:
  - docs/procurement/README.md
  - docs/procurement/sig-lite.md
  - docs/contribute/mini-prds/procurement-readiness-pack.md
  - docs/PRD.md
sidebar:
  order: 11
---

Most procurement questionnaires assume the vendor is a SaaS provider — "which AWS region is the
data in?" — and the honest answer for self-hosted software is "wherever you deployed it," which the
project cannot pre-fill on your behalf. This page starts from the format that fact drives, then
points at the one substantive starter response available today.

<!-- include: docs/procurement/README.md -->

## What's actually filled in today

The full Procurement-Readiness Pack — every SIG Lite domain plus CAIQ Lite plus a cover letter — is
tracked as an open, community-contributable item
([mini-PRD](../../contribute/mini-prds/procurement-readiness-pack.md)) and does not exist yet. What
does exist is a focused starter:
[`docs/procurement/sig-lite.md`](../../procurement/sig-lite.md) answers the SIG Lite questions whose
responses depend specifically on LQ.AI's privileged-project handling (Data Protection & Privacy
domain D) and the M3 external trust boundaries — the Word add-in OAuth flow and the Slack/Teams
light-intake bridges (domains G, I, and the audit-logging questions in L). Each answer follows the
same format as the include above: the question as it appears in SIG Lite, the project's response,
items marked `[OPERATOR-CONFIGURABLE]` where the answer depends on your specific deployment, and a
reference back into the source code or documentation that backs the claim.

If you completed a full procurement cycle for your own LQ.AI deployment, contributing your
questionnaire responses back saves every operator after you from re-deriving the same answers —
the mini-PRD linked above documents the contribution path, and procurement responses go through
counsel review before merge, the same as any other legal-substance contribution.

In the meantime, do not read the absence of `caiq.md` or a cover-letter template as an absence of
substance to work from: [PRD Appendix E](../../PRD.md#appendix-e--pre-empted-procurement-objections)
already answers seventeen of the objections a procurement reviewer is most likely to raise, in
prose rather than questionnaire-row format, and the mini-PRD explains how that content maps onto
the standard SIG Lite and CAIQ Lite structures once someone does the restructuring work.

## Next

- [Compliance mappings](compliance-mappings.md) — the framework-alignment documents this Pack cites alongside the security artifacts.
- [Audit & evidence](audit-and-evidence.md) — the audit-log questions the SIG Lite starter answers from.
- [Anonymization](anonymization.md) — the privileged-project handling most of the starter's answers depend on.
