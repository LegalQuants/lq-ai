---
title: On-ramp for a compliance or procurement professional
description: The compliance and procurement mini-PRDs that fit this profile, and how review is routed.
audience: [contributor]
status: draft
sources:
  - docs/contribute/mini-prds/procurement-readiness-pack.md
  - docs/contribute/mini-prds/nist-ai-rmf-profile.md
  - docs/contribute/mini-prds/owasp-llm-top10-mapping.md
  - docs/procurement/README.md
  - docs/compliance/README.md
  - .github/CODEOWNERS
  - docs/contribute/EASIEST-CONTRIBUTIONS.md
sidebar:
  order: 4
---

If you evaluate vendors for a living, or you run an AI-governance program, LQ.AI's contribution board has two items written for exactly that background.

## The two items on the board

**The [Procurement-Readiness Pack](../../../docs/contribute/mini-prds/procurement-readiness-pack.md)** turns the project's existing procurement objections and compliance mappings into pre-filled SIG Lite and CAIQ Lite questionnaire responses, plus a cover letter explaining why a self-hosted open-source deployment is an unusual procurement. The structure and the `[OPERATOR-CONFIGURABLE]` marker convention already exist in [`docs/procurement/README.md`](../../../docs/procurement/README.md), and a starter SIG Lite response covering the privileged-matter-handling domain is already merged; the gap is the remaining ~15 SIG Lite domains, the full CAIQ Lite response, and the cover letter.

**The [NIST AI RMF 1.0 Profile mapping](../../../docs/contribute/mini-prds/nist-ai-rmf-profile.md)** maps the project's design and operational practices against the NIST AI Risk Management Framework (AI 100-1) and its Generative AI Profile (AI 600-1), function by function — Govern, Map, Measure, Manage. This document does not exist yet in [`docs/compliance/`](../../../docs/compliance/README.md); federal and federal-adjacent procurement reviewers look for it specifically, and its absence currently reads as a gap rather than a neutral omission.

Both are scoped as **M** effort with **High** foundation readiness — you read existing source, fill the gap, and submit the pull request, rather than inventing structure from nothing. The board's effort key reads M as a few days; the NIST mini-PRD sets its own expectation higher, at roughly one to two focused weeks, so take that figure for that item.

## A cross-profile item worth knowing about

The **[OWASP LLM Top 10 mapping](../../../docs/contribute/mini-prds/owasp-llm-top10-mapping.md)** is scoped for a security-aware engineer, but its output — a risk-by-risk mapping of prompt injection, sensitive-information disclosure, and the rest of the OWASP LLM list against the project's actual mitigations — is a document your review process will also want. If you can pair with an engineer, this is a natural joint contribution: you bring the framework fluency, they bring the code citations.

## Where review happens

Both `docs/compliance/` and `docs/procurement/` are routed by [CODEOWNERS](../../../.github/CODEOWNERS) to the project's counsel reviewers in addition to the maintainer team, because these documents affect what an operator can tell their own procurement or governance function. A pull request against either directory does not merge on maintainer approval alone.

## How to claim

Follow [the contribution board](board.md)'s claim process: open a GitHub issue titled with the mini-PRD's slug (for example, `procurement-readiness-pack`), comment that you would like to take it, and wait for a maintainer response — typically within a week. Each mini-PRD's own "Where to start" section is the working brief once you begin.

## Next

- [The contribution board](board.md)
- [The trust centre](../trust/index.md) — where these documents surface to an evaluator
- [Compliance framework mappings](../trust/compliance-mappings.md)
