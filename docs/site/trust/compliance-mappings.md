---
title: Compliance mappings
description: What the Compliance Alignment Pack is (and is not), which frameworks it targets, and the AI-specific mappings that are planned but not yet written.
audience: [evaluator, operator]
status: draft
sources:
  - docs/compliance/README.md
  - docs/HONEST-STATE.md
  - docs/contribute/mini-prds/nist-ai-rmf-profile.md
  - docs/contribute/mini-prds/owasp-llm-top10-mapping.md
  - docs/contribute/mini-prds/openssf-scorecard-and-badges.md
sidebar:
  order: 12
---

A compliance mapping for open-source software is not a certification — LQ.AI is code you deploy
and operate; your deployment is what gets certified, not the project. What the Compliance Alignment
Pack *will* offer is a pre-mapped set of control responses, each citing a PRD section, a code
module, or a documentation file. As of the checked commit none of the six per-framework documents
exists — `docs/compliance/` holds only the README included below, and `docs/HONEST-STATE.md` §7
records SOC 2 / ISO 27001 / ISO 42001 / GDPR / HIPAA / FedRAMP alignment as **stub**. What is
published today is the format the documents will follow and the scope commitment behind them.

<!-- include: docs/compliance/README.md -->

## Planned, not published: none of the mappings exist yet

Every framework document in the table above is a stub — none has a written control mapping yet.
Three mappings that would matter most to an AI-governance or AppSec reviewer specifically are
scoped as open community-contribution items and **do not exist as documents yet** — each has a
mini-PRD describing exactly what the finished document would contain, but no `docs/compliance/*.md`
file behind it today:

- **NIST AI RMF 1.0 Profile** (AI 100-1 plus the Generative AI Profile, AI 600-1) — the framework a
  federal or federal-adjacent AI-governance reviewer looks for first. See the
  [mini-PRD](../../contribute/mini-prds/nist-ai-rmf-profile.md) for the planned structure.
- **OWASP Top 10 for LLM Applications mapping** — the de facto framework an AppSec reviewer asks
  for when blessing an LLM-touching tool. See the
  [mini-PRD](../../contribute/mini-prds/owasp-llm-top10-mapping.md).
- **OpenSSF Scorecard and Best Practices Badge** — an independently-computed, continuously-updated
  engineering-discipline signal (branch protection, signed releases, dependency automation, and
  similar, scored 0–10) rather than a written mapping document, plus a self-attested Best Practices
  Badge. See the [mini-PRD](../../contribute/mini-prds/openssf-scorecard-and-badges.md).

Each of these is deliberately named here rather than left undiscovered: an evaluator who searches
this site for "NIST AI RMF" or "OWASP LLM Top 10" should find this honest "not yet" rather than
nothing, and a reviewer whose organization requires one of these mappings before a procurement
decision proceeds sees the concrete scope of what is missing, with a document describing exactly
what a contributor would need to produce, rather than an unexplained absence.

## Next

- [Published gaps](published-gaps.md) — where these same three items sit in the project's full honest inventory.
- [Questionnaires](questionnaires.md) — the pre-filled SIG Lite starter, which exists today alongside these planned mappings.
