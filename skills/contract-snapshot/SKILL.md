---
name: contract-snapshot
description: Use when the user wants to compare the same handful of terms across N contracts side-by-side in a grid — what is the term, survival period, carveouts, and governing law in each of these 5 NDAs? Returns a row-per-document × column-per-question grid with citations per cell. Reference skill for the M3-C output_format - table mode; intended as a starting point for operators to fork and tune for their own contract types.
lq_ai:
  title: Contract Snapshot
  version: 1.0.0
  author: LegalQuants
  tags: [contracts, due-diligence, tabular, snapshot]
  jurisdiction: agnostic
  trigger_examples:
    - "compare the term length and governing law across these NDAs"
    - "show me a side-by-side of these 5 contracts on key terms"
    - "I want a grid of these contracts' material terms"
  output_format: table
  ensemble_verification: false
  minimum_inference_tier: 2
  columns:
    - name: Term
      query: |
        What is the term length of this agreement? Quote the operative
        clause exactly and surface the duration in plain language
        (e.g., "3 years from the Effective Date"). If the agreement
        is open-ended or runs until termination, say so.
    - name: Survival
      query: |
        What confidentiality or other obligations survive termination
        or expiration of this agreement? Quote the survival clause
        if one exists. If no survival period is specified, return
        "not specified" (do not infer a default).
      ensemble_verification: true
    - name: Carveouts
      query: |
        What carveouts to the confidentiality obligation does this
        agreement permit (e.g., already-known information, independently
        developed, required by law)? List each carveout as a bullet
        with a quoted phrase from the agreement.
    - name: Governing Law
      query: |
        What jurisdiction governs this agreement, and which courts
        have venue for disputes? Quote the governing-law and
        forum-selection clauses verbatim.
      minimum_inference_tier: 3
---

# Contract Snapshot

A reference skill for the M3-C `output_format: table` mode. Produces a side-by-side grid of the same questions across N contracts — the in-house lawyer's "compare clauses across N agreements" workflow. Each cell carries a citation back to the source document, and failed extractions render as `not found` rather than confidently-wrong text.

## When this skill applies

Apply when the user wants to compare a small number of well-defined questions across a corpus of similar contracts:

- "What is the term, survival, and governing law across these 5 NDAs we're tracking?"
- "Pull out the payment terms, IP ownership, and termination triggers across these 10 MSAs."
- "For my Q3 portfolio review, I need a grid of these 30 vendor contracts' liability caps."

Do not apply this skill to:

- Single-document review — use the appropriate document-specific skill (`nda-review`, `msa-review-saas`, etc.).
- Free-form chat against contracts — that's the regular Chat surface.
- Tasks where the questions aren't well-defined upfront — the column queries must be specific enough to extract from each row's source document; vague queries produce poor cells.

## Inputs

The skill takes a set of documents (selected via the Tabular Review UI from a Knowledge Base, a Project, or a free file selection). The four columns above run as Citation Engine-grounded extractions against each document.

To adapt this skill for a different contract type (e.g., MSAs), fork the skill and rewrite the four column queries. Keep them short, specific, and quote-asking — the Citation Engine works best when the model is encouraged to quote rather than paraphrase.

## Per-column overrides

This skill demonstrates the two per-column overrides M3-C1 supports:

- **`ensemble_verification: true`** on the Survival column. Survival is the load-bearing economic term in confidentiality agreements (a 3-year confidentiality term with a 10-year survival is very different from one with no survival), so cells in this column run through Stage 4 of the Citation Engine cascade — three judges debating whether the cell value is faithful to its citation. Higher cost, higher confidence.
- **`minimum_inference_tier: 3`** on the Governing Law column. The skill-level floor is Tier 2 (commercial inference). Governing-law extraction is the column most likely to surface counterintuitive answers (e.g., a contract drafted under California law but with a Delaware forum-selection clause); routing this column to Tier 3+ avoids the cheapest models' tendency to collapse the two into one answer.

Other columns inherit the skill-level `ensemble_verification: false` and `minimum_inference_tier: 2` defaults — appropriate for the lower-stakes, more-extractive Term and Carveouts columns.

## Output format and downstream surfaces

The grid renders in the Tabular Review UI (`/lq-ai/tabular/`) with sticky-first-row and sticky-first-column. Each cell shows the extracted value + a small confidence chip; click anywhere on the cell to open the existing M2-C2 citation drawer with the source document highlighted at the cited chunk.

From the result view, operators can:

- **Export the grid as XLSX** — each cell carries its citation as an Excel comment with a clickable link back to the deployment.
- **Export as CSV** — citations are flattened to sibling `{column_name}_citation_url` columns.
- **Run a bulk operation** — e.g., "Redline the Survival column in all rows" runs the `nda-review` skill against each row's source document with the survival value as context.

## Disclaimer (per Decision F)

This skill is a **starting point**, not a vetted template. The four columns are appropriate for many NDAs but won't be right for every corpus. Before relying on the output of a Tabular Review run on this skill, the user-attorney should:

1. Review the column queries — do they match the questions you actually want answered for this corpus?
2. Spot-check at least one cell per column against the source document — does the extraction faithfully represent the source?
3. Treat any `not found` cell as a signal to investigate, not as definitive evidence that the clause is absent.

The output is a draft for an in-house lawyer to validate, not a final compliance artifact.

## Fork and tune

This skill is intentionally minimal so operators can fork it as a starting point:

```yaml
# skills/my-org/msa-snapshot/SKILL.md (operator's fork)
output_format: table
columns:
  - name: Payment Terms
    query: What are the payment terms (frequency, days-to-pay, late-fee provisions)?
  - name: IP Ownership
    query: Who owns IP created during the engagement (work-for-hire, license-back, joint)?
  - name: Termination
    query: List each termination right (for cause, for convenience, notice periods).
  # ... more columns
```

The Tabular UI accepts both saved skills (like this one) and ad-hoc column specs entered directly in the wizard's column step.
