---
name: playbook-easy-extract
description: Use when extracting the negotiated positions from a single prior contract as input to the Easy Playbook auto-generation pipeline. Reads a contract's text, identifies the clauses that take a substantive position on a contract issue (definition of confidential information, limitation of liability, indemnification, payment terms, etc.), and emits a structured list of {issue, clause_text, source_offsets} for downstream clustering. Output is intermediate; the in-house attorney evaluates the final assembled playbook, not this stage.
lq_ai:
  title: Playbook Easy Extract
  version: 1.0.0
  author: LegalQuants
  tags: [contracts, playbooks, extraction, internal]
  jurisdiction: regime-aware
  trigger_examples:
    - "(internal — invoked by the Easy Playbook generation pipeline)"
  inputs:
    required:
      - name: document
        type: document
        description: One contract to extract negotiated positions from. The pipeline calls this skill once per uploaded corpus document.
    optional:
      - name: contract_type
        type: text
        description: The contract family the document belongs to ("NDA", "MSA-SaaS", "DPA", etc.). Helps the model recognize family-appropriate issues. Defaults to general extraction if not provided.
  output_format: structured
  self_improvement: false
  internal: true
---

# Playbook Easy Extract

Extract the **negotiated positions** from a single contract — the clauses where the parties take a substantive stance on a recurring contract issue — and emit a structured list the Easy Playbook generation pipeline can cluster.

## When this skill applies

This skill is **internal to the Easy Playbook generation pipeline (M3-A6)** — it is not a user-facing skill. The pipeline calls it once per uploaded corpus document; the per-document output is then clustered across the corpus to detect modal positions, and the result is assembled into a draft playbook the user-attorney reviews and edits.

Apply when given a single contract text and asked to enumerate the negotiated positions it takes. Do not apply for contract review, redlining, or any user-facing task — those are the job of the per-contract-type skills (`nda-review`, `msa-review-saas`, etc.).

## Workflow

Read the contract end-to-end before emitting any output. Identify every clause that:

1. **Takes a substantive position on a recurring contract issue.** Recurring issues are those that appear across most contracts of the same family: confidentiality definition, term, limitation of liability, indemnification, payment terms, governing law, etc. A clause that imposes an obligation, defines a key term, allocates risk, or sets a threshold is "substantive."
2. **Is recognizable as a position (not boilerplate).** Skip pure mechanical clauses (notices, severability, integration) — they don't represent a negotiated stance worth clustering. Include them only when the contract takes an unusual position on them.
3. **Is contained in identifiable, contiguous text.** Don't emit overlapping or fragmentary spans — pick the section/sentence that captures the position.

For each identified clause, emit one entry. The same contract typically yields 5–20 entries depending on length and complexity.

### Issue labeling

The `issue` field is a **short, descriptive label** the downstream clustering step uses to group like clauses across the corpus. Use common contract-issue vocabulary. Examples:

- `"Definition of Confidential Information"`
- `"Term of Confidentiality Obligation"`
- `"Limitation of Liability"`
- `"Indemnification — Mutual"`
- `"Payment Terms"`
- `"Governing Law"`
- `"Permitted Disclosures"`
- `"Service Level Agreement"`

Do NOT invent novel labels when a common one fits — clustering depends on label consistency. If a clause genuinely doesn't match a common issue, pick the most descriptive short noun phrase ("Audit Rights", "Data Retention Period", "Sub-processor Approval").

### Clause text

The `clause_text` field is a **verbatim quote** of the clause from the source document. Preserve the original wording, casing, and punctuation. Do not paraphrase or summarize — the clustering step embeds and compares these strings literally.

If the position spans multiple sentences, include all of them. If the position appears in a numbered list, include the list header and the relevant items. Don't include unrelated surrounding text.

### Source offsets

The `source_offsets` field is a pair `{start, end}` of 0-based character offsets into the normalized document text. The pipeline uses these to render highlights in the UI and to support the future "open in document" drilldown (Citation Engine integration).

If you cannot identify exact offsets, omit the field (`null`); the downstream pipeline tolerates missing offsets but will not show the in-document highlight.

## Output

Emit **strictly valid JSON** in this exact shape:

```json
{
  "extracted_clauses": [
    {
      "issue": "Definition of Confidential Information",
      "clause_text": "\"Confidential Information\" means any information disclosed by either party that is marked \"Confidential\" or is reasonably identifiable as confidential by its nature.",
      "source_offsets": {"start": 1842, "end": 2010}
    },
    {
      "issue": "Term of Confidentiality Obligation",
      "clause_text": "The obligations of confidentiality survive for three (3) years after termination of this Agreement.",
      "source_offsets": {"start": 5510, "end": 5610}
    }
  ]
}
```

Wrap the JSON object in a single fenced code block if your output format requires markdown. The pipeline tolerates a leading ` ```json ` fence.

## Constraints

- **Output is intermediate, not authoritative.** Do not opine on whether a clause is favorable, unusual, or non-standard. That is the user-attorney's job downstream.
- **Do not invent clauses.** Every entry must correspond to text actually in the document.
- **Do not fix or rewrite clauses.** Quote verbatim, even if the drafting is messy.
- **Do not classify confidence.** The clustering step will quantify cross-corpus consistency; per-clause confidence is not part of this skill's contract.
- **Skip pure-boilerplate** unless the contract takes an unusual position on it. Standard severability / notice / integration clauses are not worth extracting; non-standard versions of those clauses are.

## Edge cases and refusals

- **Document is not a contract.** Emit an empty `extracted_clauses` list rather than fabricating positions.
- **Document is a contract template with placeholders** (e.g., `[INSERT TERM]`, `[CUSTOMER]`). Extract what's there but note in the placeholder that the clause is a template; downstream consumers may filter these out.
- **Document is in a language other than English.** Extract as best-effort; flag in the `clause_text` with a `[non-English source]` prefix on the issue label. The clustering step will probably collapse these into their own cluster.
- **Document is heavily redacted.** Emit only the unredacted positions; do not speculate about redacted content.

## Reference materials

- `examples/example_nda_mutual.md` — worked example of a 6-clause extraction from a routine mutual NDA.

## What this skill does not do

- Render a review or assessment. That's `nda-review` / `msa-review-saas` / etc.
- Compare a clause to a standard. That's the M3-A2 playbook executor's job.
- Cluster clauses across documents. That's the downstream `clustering.py` step (M3-A6 Phase 4).
- Compose a playbook. That's the `assembly.py` step (M3-A6 Phase 4).
