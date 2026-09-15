---
title: Published gaps
description: What LQ.AI ships today, what is deferred, and how to verify each — the project's own honest inventory, surfaced here rather than left to a footnote.
audience: [evaluator, operator]
status: draft
sources:
  - docs/HONEST-STATE.md
sidebar:
  order: 7
---

Most vendors' gap list, if one exists at all, is something you have to ask for. This one is a
committed file in the repository, maintained per release, and almost every row names a
verification path — a file, a test command, or both — rather than asking you to take the status
word on faith. Its status column reads `M1`–`M4` for capabilities that shipped in the milestone
named, `partial` for shipped-with-caveats, `scaffold` for plumbing-only, and `deferred-Mx` /
`deferred (community-friendly)` for roadmap items not yet wired in source. This site uses the plain
words shipped, partial, scaffold and deferred the same way, everywhere a claim about product state
appears — a page here never says "supports" when the honest word is "partial," and never rounds
"scaffold" up to "shipped." A few engineering-discipline rows in §8 use looser words of their own —
`committed`, `not yet`, `not enforced` — and where this site relies on one of those rows it says
which. Where this site's own pages state a capability's status, that status word is drawn from this
document — not from a separate, looser judgment made page by page.

Read this document the way a security or procurement reviewer would: not front to back, but as a
lookup table for whatever capability your evaluation actually turns on. Almost every capability's
row carries a status and a place to check it — a source file, a test command, or both — so a claim
you doubt is a `grep` or a `pytest` invocation away from confirmed or refuted, not a support ticket.
The exceptions are the forward-looking rows in §8 (the annual pen test, the mutation/eval-harness
roadmap), whose "verification" is a commitment rather than a check you can run today. The
"Capabilities not yet started in source" table near the end is worth reading in full before you
assume a feature exists because a marketing page elsewhere implies it does; it is verifiable by
absence, the same discipline the rest of the document applies to what does exist.

<!-- include: docs/HONEST-STATE.md -->

## Next

- [Threat model](threat-model.md) — where the STRIDE coverage's own "out of scope" section sits alongside this inventory.
- [Supply chain](supply-chain.md) — the one gap this site found that this document does not yet name precisely (the SLSA-provenance claim).
- [Verify these claims yourself](verify-these-claims.md) — how to re-run the verification path for any row above.
