---
name: msa-snapshot
description: >-
  Use when the user wants to compare the substantive commercial terms across N
  master services agreements side-by-side — term and renewal, payment terms,
  limitation of liability, and indemnification posture across each agreement.
  Returns a row-per-document × column-per-question grid with citations per
  cell. MSA-tuned reference skill for the M3-C `output_format - table` mode;
  intended as a fork-and-tune starting point for operators reviewing MSA
  portfolios.
lq_ai:
  title: MSA Snapshot
  version: 1.0.0
  author: LegalQuants
  tags: [msa, commercial, due-diligence, tabular, snapshot]
  jurisdiction: agnostic
  trigger_examples:
    - "compare the liability caps and payment terms across these MSAs"
    - "what are the renewal triggers in each of these 5 vendor MSAs?"
    - "show me a grid of indemnification posture across these agreements"
  output_format: table
  ensemble_verification: false
  minimum_inference_tier: 2
  columns:
    - name: Term + Renewal
      query: |
        What is the initial term of this agreement and how does it
        renew? Quote the operative clause. Identify: (a) initial term
        length, (b) renewal mechanism (auto-renew, mutual written
        consent, etc.), (c) notice period required to prevent renewal,
        and (d) cap on total renewals if any. If the agreement is
        perpetual or terminates only for cause, say so explicitly.
    - name: Payment Terms
      query: |
        What are the payment terms? Quote the operative clause.
        Identify: (a) net payment days (e.g., Net 30, Net 60), (b)
        late-fee or interest provisions, (c) right-to-suspend-services
        triggers for non-payment, (d) whether disputed amounts can be
        withheld, and (e) currency. Quote each verbatim. Do not infer
        defaults if any element is silent.
      ensemble_verification: true
    - name: Limitation of Liability
      query: |
        What is the cap on liability? Quote the limitation-of-liability
        clause. Identify: (a) the cap amount or formula (e.g., "fees
        paid in the prior 12 months"), (b) any carveouts that uncap
        liability (e.g., indemnification obligations, confidentiality
        breaches, gross negligence, willful misconduct), and (c)
        whether the cap is mutual or one-way. Quote the carveouts
        verbatim — they are the most negotiated piece of this clause.
      minimum_inference_tier: 3
    - name: Indemnification
      query: |
        What indemnification obligations does each party owe? Quote the
        indemnification clauses. Identify for each direction: (a)
        scope (IP infringement, breach of confidentiality, third-party
        claims arising from negligence, etc.), (b) whether the
        indemnifying party controls the defense, (c) any procedural
        prerequisites (prompt notice, cooperation), and (d) whether
        the indemnifying party's obligations survive termination.
        Flag whether the indemnification is one-way (vendor-favorable
        or customer-favorable) or mutual.
      minimum_inference_tier: 3
---

# MSA Snapshot

A reference skill for the M3-C `output_format: table` mode, tuned for master services agreement portfolios. Produces a side-by-side grid of MSA-specific commercial terms across N agreements — the in-house lawyer's "compare these vendor MSAs" or "diligence these target MSAs" workflow. Each cell carries a citation back to the source document; failed extractions render as `not found` rather than confidently-wrong text.

## When this skill applies

Apply when the user has a portfolio of MSAs and wants to see how key commercial terms compare across them. Examples:

- "Pull liability caps, indemnification, and payment terms across these 8 vendor MSAs before our renewal cycle."
- "For this acquisition diligence, show me the renewal trigger and termination posture across the target's top 15 MSAs."
- "Compare the liability carveouts across our SaaS MSAs vs. our commercial-purchase MSAs."

Do not apply this skill to:

- Single-MSA review — use `msa-review-saas` or `msa-review-commercial-purchase` for one document at a time.
- General contract comparison across mixed types — use `contract-snapshot` for the general Term/Survival/Carveouts/Governing-Law grid.
- NDA portfolios — use `nda-snapshot` for NDA-specific columns (Confidential Information definition, permitted recipients, etc.).

## Pairing with the synthetic corpus

This skill ships paired with the synthetic MSA corpus in `docs/quickstart/sample-msas/` (5 MSAs with varying commercial terms). Operators trying LQ.AI for the first time can attach those 5 PDFs to a Knowledge Base and run this skill to see the tabular workflow end-to-end without committing real documents to the system.

## Fork-and-tune notes

The four columns here cover the highest-frequency MSA comparison questions for in-house counsel doing portfolio review or diligence. They do not overlap with the general `contract-snapshot` columns (Term, Survival, Carveouts, Governing Law) — operators wanting both can run the two skills in sequence.

When forking for your own MSA template / counterparty patterns, common modifications include:

- Adding a **Termination for Convenience** column if your business cares about exit flexibility (notice period + fee structure).
- Adding a **SLA / Service Levels** column for SaaS-heavy MSA portfolios (credit structure + measurement period).
- Adding a **Data Processing** column if you need to compare DPA references and data-residency commitments across vendors.
- Replacing the **Indemnification** column with a narrower **IP Indemnification** column if that is the only indemnification scope you care about.
- Bumping `minimum_inference_tier` to 3 on all columns for high-stakes diligence work.

The **Limitation of Liability** and **Indemnification** columns default to `minimum_inference_tier: 3` because these clauses are dense, fragmented across the document, and most prone to silent extraction errors. The carveouts in particular are the most-negotiated piece of an MSA — surfacing them inaccurately is worse than surfacing them not-at-all.

## Output expectations

For each document × column cell:

- A quoted phrase or short paragraph from the source document, anchored by character offsets to enable the citation modal.
- A brief plain-language summary when the operative clause spans multiple paragraphs.
- An explicit "one-way (vendor-favorable)" / "one-way (customer-favorable)" / "mutual" tag where the column asks about directionality (e.g., Indemnification).
- `not found` when the requested term is genuinely absent from the document (not when extraction failed — those surface as a parse error in the cell footer).
