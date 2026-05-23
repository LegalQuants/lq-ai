---
name: nda-snapshot
description: >-
  Use when the user wants to compare the substantive NDA-specific terms across
  N non-disclosure agreements side-by-side — the definition of Confidential
  Information, permitted recipients, return/destruction obligation, and
  remedies clause across each agreement. Returns a row-per-document ×
  column-per-question grid with citations per cell. NDA-tuned reference skill
  for the M3-C `output_format - table` mode; intended as a fork-and-tune
  starting point for operators reviewing NDA portfolios.
lq_ai:
  title: NDA Snapshot
  version: 1.0.0
  author: LegalQuants
  tags: [nda, confidentiality, due-diligence, tabular, snapshot]
  jurisdiction: agnostic
  trigger_examples:
    - "compare the confidentiality scope and return obligations across these NDAs"
    - "what's the definition of Confidential Information in each of these 5 agreements?"
    - "show me a grid of permitted recipients and remedies across these NDAs"
  output_format: table
  ensemble_verification: false
  minimum_inference_tier: 2
  columns:
    - name: Confidential Information
      query: |
        How does this agreement define "Confidential Information"? Quote
        the operative definition verbatim. Note any explicit carveouts
        embedded in the definition itself (e.g., "excluding information
        that is publicly available…"). If the definition is unusually
        narrow or unusually broad, flag that in a short trailing note.
    - name: Permitted Recipients
      query: |
        Who is the recipient permitted to disclose Confidential
        Information to? Quote the permitted-recipients clause. Identify
        whether the recipient must impose written confidentiality
        obligations on those downstream recipients, and whether the
        recipient remains liable for their breach. If the clause is
        silent on downstream obligations, say so explicitly — do not
        infer a default.
      ensemble_verification: true
    - name: Return / Destruction
      query: |
        On termination or upon request, must the recipient return or
        destroy Confidential Information? Quote the operative clause.
        Identify: (a) trigger (termination, written request, expiry),
        (b) timing (number of days), (c) whether destruction
        certification is required, and (d) any carveouts for archival
        or legally-required retention. If the clause is silent on any
        of these, say "not specified" rather than infer.
    - name: Remedies
      query: |
        What remedies does the agreement provide for breach? Quote the
        remedies clause. Identify whether injunctive relief is
        explicitly available (and whether the parties agree damages
        would be inadequate), whether attorneys' fees shift to the
        prevailing party, and whether monetary damages are capped or
        uncapped. Quote relevant phrases verbatim.
      minimum_inference_tier: 3
---

# NDA Snapshot

A reference skill for the M3-C `output_format: table` mode, tuned for non-disclosure agreement portfolios. Produces a side-by-side grid of NDA-specific terms across N agreements — the in-house lawyer's "compare these NDAs we have with vendors / counterparties / candidates" workflow. Each cell carries a citation back to the source document; failed extractions render as `not found` rather than confidently-wrong text.

## When this skill applies

Apply when the user has a portfolio of NDAs and wants to see how key substantive terms compare across them. Examples:

- "I have NDAs with our top 20 vendors — show me how the definition of Confidential Information varies and where the carveouts are tightest."
- "Compare the return/destruction obligations across these 10 candidate NDAs before we standardize our template."
- "What remedies are available across the 5 mutual NDAs in this M&A diligence box?"

Do not apply this skill to:

- Single-NDA review — use `nda-review` for one document at a time.
- General contract comparison across mixed types — use `contract-snapshot` for the general Term/Survival/Carveouts/Governing-Law grid.
- Free-form Q&A about an NDA — that's the regular Chat surface.

## Pairing with the synthetic corpus

This skill ships paired with the synthetic NDA corpus in `docs/quickstart/sample-ndas/` (5 mutual NDAs with varying terms). Operators trying LQ.AI for the first time can attach those 5 PDFs to a Knowledge Base and run this skill to see the tabular workflow end-to-end without committing real documents to the system.

## Fork-and-tune notes

The four columns here are deliberately NDA-specific — they don't overlap with the general `contract-snapshot` columns (Term, Survival, Carveouts, Governing Law). Operators who want both can run the two skills in sequence, or fork this skill and add a Term/Governing-Law column for a combined view.

When forking for your own NDA template / counterparty patterns, common modifications include:

- Adding a **Term** column if you care about NDA duration (often 2–5 years).
- Adding a **Notice of Compelled Disclosure** column if you negotiate that provision frequently.
- Replacing the **Permitted Recipients** column with a narrower **Affiliate Permission** column if your business has a specific affiliate-sharing pattern.
- Bumping `minimum_inference_tier` to 3 on all columns if you need higher-fidelity extraction for high-stakes deals.

The four columns chosen here reflect the questions a junior associate or paralegal would most often be asked to extract during NDA portfolio review — they are the highest-frequency, highest-value comparison points across typical mutual-NDA practice.

## Output expectations

For each document × column cell:

- A quoted phrase or short paragraph from the source document, anchored by character offsets to enable the citation modal.
- A brief plain-language summary when the operative clause is long or convoluted.
- `not found` when the requested term is genuinely absent from the document (not when extraction failed — those surface as a parse error in the cell footer).
