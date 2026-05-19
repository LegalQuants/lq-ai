# Example — Mutual NDA extraction

A worked example of the `playbook-easy-extract` skill applied to a routine mutual non-disclosure agreement. Demonstrates the structural contract — what the model emits, not what the model believes about the clauses' quality.

The user-attorney does NOT evaluate this output directly; it is consumed by the M3-A6 clustering step which aggregates per-clause results across the corpus.

## Input

> *Excerpt — Mutual Non-Disclosure Agreement between ACME, Inc. and Globex Corp., dated 2025-04-01.*
>
> 1.  **Definitions.** "Confidential Information" means any non-public information disclosed by either party (the "Disclosing Party") to the other (the "Receiving Party"), whether orally, in writing, or in electronic form, that is marked "Confidential" or is reasonably identifiable as confidential by its nature.
>
> 2.  **Exclusions.** Confidential Information does not include information that (a) was publicly known at the time of disclosure; (b) became publicly known through no fault of the Receiving Party; (c) was already in the Receiving Party's possession prior to disclosure; or (d) was independently developed by the Receiving Party without use of the Disclosing Party's Confidential Information.
>
> 3.  **Term.** The obligations of confidentiality set forth in this Agreement shall survive for a period of three (3) years following the termination of this Agreement.
>
> 4.  **Permitted Disclosures.** The Receiving Party may disclose Confidential Information to its employees, advisors, and counsel who have a need to know and are bound by written confidentiality obligations no less restrictive than those set forth herein.
>
> 5.  **Return or Destruction.** Upon termination, the Receiving Party shall return or destroy all Confidential Information of the Disclosing Party within thirty (30) days, and shall certify such return or destruction in writing.
>
> 6.  **Equitable Remedies.** The parties acknowledge that monetary damages may be insufficient to remedy a breach of this Agreement, and that the non-breaching party shall be entitled to seek injunctive relief without the necessity of posting bond.
>
> 7.  **Governing Law.** This Agreement shall be governed by and construed in accordance with the laws of the State of Delaware, without regard to its conflict of laws principles.

## Expected output

```json
{
  "extracted_clauses": [
    {
      "issue": "Definition of Confidential Information",
      "clause_text": "\"Confidential Information\" means any non-public information disclosed by either party (the \"Disclosing Party\") to the other (the \"Receiving Party\"), whether orally, in writing, or in electronic form, that is marked \"Confidential\" or is reasonably identifiable as confidential by its nature.",
      "source_offsets": {"start": 38, "end": 350}
    },
    {
      "issue": "Exclusions from Confidentiality",
      "clause_text": "Confidential Information does not include information that (a) was publicly known at the time of disclosure; (b) became publicly known through no fault of the Receiving Party; (c) was already in the Receiving Party's possession prior to disclosure; or (d) was independently developed by the Receiving Party without use of the Disclosing Party's Confidential Information.",
      "source_offsets": {"start": 367, "end": 740}
    },
    {
      "issue": "Term of Confidentiality Obligation",
      "clause_text": "The obligations of confidentiality set forth in this Agreement shall survive for a period of three (3) years following the termination of this Agreement.",
      "source_offsets": {"start": 753, "end": 910}
    },
    {
      "issue": "Permitted Disclosures",
      "clause_text": "The Receiving Party may disclose Confidential Information to its employees, advisors, and counsel who have a need to know and are bound by written confidentiality obligations no less restrictive than those set forth herein.",
      "source_offsets": {"start": 935, "end": 1160}
    },
    {
      "issue": "Return or Destruction of Confidential Information",
      "clause_text": "Upon termination, the Receiving Party shall return or destroy all Confidential Information of the Disclosing Party within thirty (30) days, and shall certify such return or destruction in writing.",
      "source_offsets": {"start": 1183, "end": 1380}
    },
    {
      "issue": "Equitable Remedies",
      "clause_text": "The parties acknowledge that monetary damages may be insufficient to remedy a breach of this Agreement, and that the non-breaching party shall be entitled to seek injunctive relief without the necessity of posting bond.",
      "source_offsets": {"start": 1403, "end": 1622}
    },
    {
      "issue": "Governing Law",
      "clause_text": "This Agreement shall be governed by and construed in accordance with the laws of the State of Delaware, without regard to its conflict of laws principles.",
      "source_offsets": {"start": 1640, "end": 1795}
    }
  ]
}
```

## What's intentionally NOT in the output

- **No severity, no risk rating.** The downstream pipeline does not consume per-clause judgments from this skill.
- **No paraphrasing.** Every `clause_text` is verbatim from the source.
- **No invented issues.** Each entry corresponds to a clause that actually appears.
- **No commentary on quality.** A 3-year survival term might be unusually long for some industries; this skill does not flag it.

The clustering step (Phase 4 of M3-A6) takes outputs like this from each contract in the corpus, groups by `issue`, identifies the modal `clause_text`, and surfaces the variants. The assembly step then drafts a playbook position per cluster. The user-attorney edits and approves the final playbook.
