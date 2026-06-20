---
name: case-law-research
description: Use when the user asks to find, read, or cite U.S. case law on a question — locating controlling or persuasive decisions via CourtListener, reading the opinion text, and grounding any statement in what the source actually says.
lq_ai:
  title: Case-Law Research
  version: 1.0.0
  author: LegalQuants
  tags: [research, case-law, litigation, citations, courtlistener]
  jurisdiction: us
  tool_usage: [courtlistener]
  trigger_examples:
    - "find case law on the duty of good faith in NY"
    - "what does the Ninth Circuit say about trade-secret misappropriation"
    - "pull the leading Supreme Court cases on personal jurisdiction"
    - "is there controlling authority for fee-shifting here"
    - "read the opinion in that case and tell me the holding"
  inputs:
    required:
      - name: question
        type: text
        description: The legal question or issue to research.
    optional:
      - name: jurisdiction
        type: text
        description: Court(s)/jurisdiction to focus on (e.g., "9th Circuit", "New York", "SCOTUS"). Defaults to a broad U.S. search.
  output_format: report
  use_organization_profile: true
---

# Case-Law Research

Conduct a structured search of U.S. case law via CourtListener, read the opinion text, and produce a grounded research report. Every statement in the report must be traceable to retrieved text — do not assert what a case holds unless you have read the relevant passage.

## When this skill applies

Apply when the user asks to locate, read, or cite court decisions on a legal question. Common triggers: finding controlling or persuasive authority, confirming whether authority exists, reading specific language from an opinion, assembling citations for a brief or memo.

Do not apply this skill when:

- The user asks about statutory text, regulations, or administrative guidance. Those are not in the CourtListener corpus; direct the user to the appropriate source.
- The user asks about non-U.S. law. CourtListener covers U.S. federal and state courts only; this skill does not extend beyond that coverage.
- The user needs to confirm whether a case is still good law (overruled, distinguished, limited). This skill is **not a citator**. It does not perform Shepardizing or KeyCiting. Always recommend the user validate any case's current status in Westlaw, Lexis, or a comparable citator before relying on it.

## Inputs

**Required:** the `question` input — the legal question or issue to research. If the user has not stated a question clearly, ask before searching.

**Optional:** the `jurisdiction` input — a court or jurisdiction to focus on (e.g., "9th Circuit", "New York Court of Appeals", "SCOTUS"). When provided, weight searches toward that jurisdiction. When absent, begin with a broad U.S. search and note which courts produced the most relevant results.

If the user's question is ambiguous (e.g., "case law on good faith") and the jurisdiction materially affects which results are relevant, ask one clarifying question before searching. Do not block on optional inputs.

## Tool chain

This skill runs through the LQ.AI governed gateway. All CourtListener tool calls are tier-gated and audited; the "Sources consulted" panel (visible to the user after the run) shows the provenance trail.

### Step 1 — search_case_law

Call `search_case_law` with a query derived from the user's question. Tips:

- Use specific legal terms from the question rather than paraphrasing in lay language.
- If a jurisdiction was provided, include it as a filter.
- Prefer narrower queries first; broaden if the initial results are sparse or off-topic.
- Run multiple searches if the question has distinct sub-issues (e.g., a threshold test and a remedy standard).

`search_case_law` returns a list of candidate clusters (cases). Each cluster includes a docket identifier and case metadata. Do not assert anything about the case yet — the search result is a pointer, not a full read.

### Step 2 — get_cluster

For each promising candidate from Step 1, call `get_cluster` with the cluster identifier to retrieve the case metadata and the list of opinion documents within it. This confirms the court, date, parties, and which opinion(s) are available to read.

Select the opinion(s) most likely to contain the relevant passage (majority opinion first; concurrences or dissents only if the question specifically implicates them).

### Step 3 — read_opinion or find_in_case

To read the full opinion text, call `read_opinion` with the opinion identifier from the cluster. For long opinions or targeted lookups, call `find_in_case` with search terms to locate the specific passage.

**Ground every statement in retrieved text.** Before citing a case for a proposition, locate the supporting passage. Quote or closely paraphrase the relevant excerpt in the report. Do not summarize from memory or from the search-result snippet alone.

If `read_opinion` or `find_in_case` returns no content or an error, record the gap explicitly in the report.

## Grounding discipline

- Cite only what the tools returned. Do not add cases from training memory — the user cannot verify those through the provenance panel.
- Quote or locate the supporting passage before asserting what a case holds.
- If the retrieved text is ambiguous, say so. Present the text and note the ambiguity rather than resolving it with an interpretation the user has not authorized.
- If the search returns no relevant results, say so clearly. A "no results" finding is an honest answer; do not substitute general statements.
- When results are jurisdictionally mismatched (the user asked for 9th Circuit authority but only 7th Circuit decisions surfaced), report the mismatch. Note that the results found are from a different jurisdiction and may be persuasive but not controlling.

## Honesty and scope limits

State the following clearly in every research report:

1. **Coverage:** CourtListener covers U.S. federal and state courts; coverage depth varies by court and date range. Gaps in the corpus do not mean no authority exists — they mean it was not found in this source.
2. **Not a citator:** This skill does not validate whether a case is still good law. Before relying on any case, the user should verify its subsequent history in Westlaw, Lexis, or a comparable citator.
3. **Research assistance, not legal advice:** The report identifies authorities and what their text says. Evaluating whether those authorities govern the user's facts, and how to apply them, requires human legal judgment.

## Output

Produce the report in markdown with this structure:

```markdown
# Case-Law Research: [short restatement of the question]

**Question:** [the user's research question]
**Jurisdiction searched:** [courts/jurisdictions covered by the search]
**Date of research:** [today's date]

## Authorities found

[For each case identified as relevant:]

### [Case Name], [Court], [Year] ([Citation if available])

**What was retrieved:** [one or two sentences stating what the opinion addresses, grounded in the text retrieved]

**Relevant passage:**
> [Quoted or closely paraphrased excerpt from read_opinion / find_in_case]

**How this bears on the question:** [one or two sentences connecting the retrieved text to the user's question — descriptive, not conclusory]

---

## Gaps and caveats

- **What was searched:** [query terms and jurisdiction filters used]
- **What was not found:** [authorities the user might expect that did not surface]
- **Jurisdiction notes:** [any mismatch between the user's requested jurisdiction and what was found]
- **Currency warning:** This skill is not a citator. Each case above should be Shepardized or KeyCited before reliance.
- **Coverage note:** CourtListener's corpus has gaps; absence of results does not mean no authority exists.

## Recommended next steps

- [e.g., validate each case's current status in a citator]
- [e.g., search secondary sources for doctrinal synthesis]
- [e.g., consult a jurisdiction-specific practitioner for application to the specific facts]
```

If the search returns no relevant results, the "Authorities found" section should say so explicitly. Do not omit the section.

Keep the report as short as the results warrant. Do not pad. A one-case answer with an honest gaps section is correctly short.

## What this skill does not do

- Assert that a case is still good law. Recommend citator validation.
- Research non-U.S. jurisdictions.
- Search statutory or regulatory text.
- Apply retrieved authority to the user's specific facts. That evaluation requires human legal judgment.
- Substitute training-memory cases for tool-retrieved ones.

## Edge cases

- **User names a specific case to read:** Begin at Step 2 (`get_cluster`) rather than Step 1 if the user provides enough identification to locate the cluster directly. If the identification is incomplete, use `search_case_law` to locate the cluster first.
- **Very broad question:** Ask the user to narrow the question, or break it into sub-issues and run a search for each, then synthesize the results under separate "Authorities found" subsections.
- **Opinion is very long:** Use `find_in_case` with targeted terms rather than reading the entire text, to locate the passage efficiently.
- **Conflicting results across jurisdictions:** Report each set of results separately, note the jurisdictional split, and leave synthesis to the user.
