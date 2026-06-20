# Worked Example: Research Trail

> **Purpose:** Illustrates the tool-call sequence and report format for `case-law-research`.
> All case names, citations, and passages are **illustrative placeholders** — they demonstrate
> procedure, not legal conclusions. Do not treat quoted text as real holdings.

---

## User question

"What does the Ninth Circuit say about the implied duty of good faith and fair dealing in commercial contracts — specifically, does it allow a separate tort claim?"

**Jurisdiction input:** "9th Circuit"

---

## Tool-call sequence

### search_case_law — initial search

```
query: "implied covenant good faith fair dealing tort commercial contract"
jurisdiction: "9th Circuit"
```

**Result:** Returns 8 candidate clusters. The top 4 appear on-point based on case names and snippets. Cluster IDs: [C-001], [C-002], [C-003], [C-004].

---

### get_cluster — retrieve metadata for top candidates

```
cluster_id: C-001
```

**Result:** [Case A] v. [Case B], 9th Cir. [year]. Three opinions: majority (opinion ID: OP-001-maj), concurrence (OP-001-con). The majority opinion is most likely to contain the relevant analysis.

```
cluster_id: C-002
```

**Result:** [Case C] Corp. v. [Case D] Inc., 9th Cir. [year]. One opinion (OP-002-maj).

---

### find_in_case — locate the relevant passage

```
opinion_id: OP-001-maj
query: "implied covenant tort separate claim"
```

**Result:** Passage located at paragraph [N]:

> "[Illustrative placeholder: The retrieved text at this location addresses whether the implied covenant of good faith and fair dealing gives rise to a tort claim separate from breach of contract under the law of the state whose law governs the agreement. The court's analysis at this location discusses the conditions under which the covenant is enforceable and the remedies available.]"

```
opinion_id: OP-002-maj
query: "implied covenant tort damages"
```

**Result:** Passage located at paragraph [M]:

> "[Illustrative placeholder: The retrieved text at this location discusses damages available for breach of the implied covenant and distinguishes the contract claim from a potential tort theory, noting the relevant state-law rule the court applies.]"

---

### search_case_law — second search to check for contrary authority

```
query: "implied covenant good faith fair dealing tort claim rejected"
jurisdiction: "9th Circuit"
```

**Result:** Returns 3 clusters. Two appear to address contexts where the claim was not recognized; one addresses a different contract type. Cluster IDs: [C-005], [C-006].

```
get_cluster + find_in_case on C-005
```

**Result:** [Case E] v. [Case F], 9th Cir. [year]. Retrieved passage at paragraph [P]:

> "[Illustrative placeholder: The retrieved text at this location states the condition under which the Ninth Circuit declined to recognize a separate tort theory, and explains the reasoning.]"

---

## Research report (output)

```markdown
# Case-Law Research: Ninth Circuit — implied covenant of good faith as a tort claim

**Question:** Does the Ninth Circuit allow a separate tort claim for breach of the implied duty of good faith and fair dealing in commercial contracts?
**Jurisdiction searched:** 9th Circuit (U.S. Court of Appeals)
**Date of research:** [today's date]

## Authorities found

### [Case A] v. [Case B], 9th Cir. [year] ([Citation])

**What was retrieved:** The opinion addresses whether the implied covenant of good faith gives rise to a tort claim separate from breach of contract under the governing state law.

**Relevant passage:**
> "[Illustrative placeholder: the retrieved paragraph from OP-001-maj at paragraph N — procedure demonstration only.]"

**How this bears on the question:** The retrieved text describes the court's analysis of the conditions for a separate tort theory. Whether those conditions apply to the user's facts requires the user's legal judgment.

---

### [Case C] Corp. v. [Case D] Inc., 9th Cir. [year] ([Citation])

**What was retrieved:** The opinion discusses damages for breach of the implied covenant and distinguishes the contract-law claim from a potential tort theory.

**Relevant passage:**
> "[Illustrative placeholder: the retrieved paragraph from OP-002-maj at paragraph M — procedure demonstration only.]"

**How this bears on the question:** The retrieved text addresses the damages available and how the court characterizes the claim. Application to the user's specific contract and facts requires the user's legal judgment.

---

### [Case E] v. [Case F], 9th Cir. [year] ([Citation])

**What was retrieved:** The opinion states a condition under which the Ninth Circuit declined to recognize a separate tort theory, with reasoning.

**Relevant passage:**
> "[Illustrative placeholder: the retrieved paragraph from C-005 at paragraph P — procedure demonstration only.]"

**How this bears on the question:** The retrieved text identifies a limiting condition the court applied. Whether that condition applies here requires the user's legal judgment.

---

## Gaps and caveats

- **What was searched:** Two queries — (1) "implied covenant good faith fair dealing tort commercial contract" and (2) "implied covenant good faith fair dealing tort claim rejected" — both filtered to the 9th Circuit.
- **What was not found:** No results addressed specific industry contexts (e.g., insurance, employment) that may have distinct rules under the governing state's law. If the contract is in one of those sectors, a sector-specific search is advisable.
- **Jurisdiction notes:** Results are Ninth Circuit federal decisions applying state law. The applicable state's law governs; the results should be checked against the specific state's courts for any divergence between the federal circuit's application and the state supreme court's current rule.
- **Currency warning:** This skill is not a citator. Each case above should be Shepardized or KeyCited before reliance. Cases may have been overruled, distinguished, or limited after the dates above.
- **Coverage note:** CourtListener's corpus has gaps, particularly for older decisions and some state courts. Absence of additional results does not mean no further authority exists.

## Recommended next steps

- Validate each case's subsequent history in Westlaw (KeyCite) or Lexis (Shepard's) before citing.
- Identify the specific state whose law governs the contract; run a targeted search in that state's courts for any divergence from the Ninth Circuit's characterization.
- If the contract is in a specialized sector (insurance, employment, franchise), run a sector-specific search — those areas often have distinct rules.
- Consult a practitioner familiar with the governing state's law to evaluate whether the retrieved authorities apply to the specific facts.
```

---

## Notes on this example

- All case names, citations, opinion IDs, and quoted passages above are **illustrative placeholders**. The format shows the procedure; the content shows what a real run would surface.
- The tool-call sequence (search → cluster → read/find → second search for contrary authority) reflects the standard methodology. Real runs may require more or fewer searches depending on the question.
- The gaps section is not optional. Every research report must explicitly state what was searched, what was not found, and the currency/citator warning.
