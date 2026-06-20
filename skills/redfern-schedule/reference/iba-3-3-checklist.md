# Article 3.3 pre-flight checklist

The admissibility test for a request to produce, under the IBA Rules on the Taking of Evidence in International Arbitration (2020), Article 3.3. Apply it to every request. Each gate returns a pass or a fail with a short reason. A request that fails any gate is weak and goes in the internal flags memo. The skill describes the weakness. It does not rewrite the user's request.

This file paraphrases the rule and cites article numbers. It does not reproduce the rule text. Confirm the official wording against the IBA PDF before relying on it in a filing.

## Gate A. Identification: Article 3.3(a)

A request must identify either a single document, or a narrow and specific category of documents reasonably believed to exist.

- **A1. Single document.** Identified with enough detail to single it out (a named contract, a dated letter, a specific board minute).
- **A2. Narrow and specific category.** The working test is definability. A permitted category is bounded on these axes:
  - a date or date range,
  - named custodians, authors, or recipients,
  - a defined subject matter,
  - a defined document type (minutes, invoices, correspondence, reports).
- **A2 fail signal.** "All documents relating to X", "any and all", "concerning the dispute", or any phrasing that names a topic rather than a bounded set. This reads as a fishing expedition and fails 3.3(a). It also invites an Article 9.2(c) burden objection.
- **A2b. Reasonably believed to exist.** Grounded in the record (a contract that refers to a schedule, a meeting that logically produced minutes, a transaction that logically produced invoices). A hope that helpful documents might exist fails.
- **A3. Electronic documents: Article 3.3(a)(ii).** If the documents are electronic, the requesting party may identify specific files, search terms, custodians, or other means to make the search efficient. These are a means to make the search efficient, not a mandatory element of identification, and the tribunal may order them supplied later. So the absence of search terms or custodians is **not** a Gate A failure on its own. It is a weakness on efficiency that the tribunal may order cured and that invites an Article 9.2(g) proportionality objection from the producing party. A request that is otherwise a narrow and specific category passes Gate A on identification even without search handles. Mark it "pass on identification, weak on efficiency" and carry the efficiency point as a proportionality risk, not an identification fail. Supplying proposed custodians, a date window, search strings, and file types strengthens the request and pre-empts the 9.2(g) objection.

**Pass:** the request points at one document, or at a category a non-party could read and know what to pull.
**Fail:** the boundary is undefined, or existence is speculative. An electronic request with no search handle still passes identification if the category itself is narrow and specific, but it is weak on efficiency and exposed to a 9.2(g) proportionality objection.

## Gate B. Relevance AND materiality: Article 3.3(b)

A request must state how the documents are relevant to the case AND material to its outcome. This is a conjunctive test. Both are required.

- **Relevance** is the logical connection to a disputed issue. Does the document bear on a pleaded claim or defence.
- **Materiality** is significance to the outcome. Could the document affect the result. Materiality must be articulated, not assumed to follow from relevance.
- **Strong articulation** ties the request to a specific pleaded paragraph and states the effect on a disputed element. Example shape: "relevant to Statement of Claim paragraphs 41 to 46, material because the documents would confirm or refute whether the board acted on commercial grounds, which the tribunal must decide."
- **Fail signal.** Boilerplate ("relevant to the issues in dispute", "necessary for a fair hearing"), no named issue, or relevance asserted with materiality left silent. Mark the gate failed and name which half is missing.
- Where an issues list is present, use `issue-matching.md` to tie the request to an issue. An unmatched request is presumptively weak on relevance.

**Pass:** both relevance and materiality are stated, and the request is tied to a specific issue.
**Fail:** the tie is generic, or materiality is not articulated, or there is no pleaded issue the request maps to.

## Gate C. Possession: Article 3.3(c)

Two sub-statements, both required.

- **C1.** A statement that the documents are not in the requesting party's possession, custody, or control. If they are, a statement of why producing them from the requesting party's own files would itself be unreasonably burdensome.
- **C2.** A statement of why the requesting party reasonably assumes the documents are in the other party's, or a non-party's, possession, custody, or control. A bare assertion fails. The reason should be concrete (the other side authored or received them, ran the system, held the relationship).

**Pass:** both statements are present and C2 gives a concrete reason.
**Fail:** either statement is missing, or the request appears to seek documents the requesting party already holds.

**Non-party possession.** Where the documents are in a non-party's possession rather than the other party's, the ordinary producing-party objection menu does not fit, because the other party cannot be ordered to produce what it does not hold. The route is Article 3.9: the requesting party may ask the tribunal to take whatever steps are legally available to obtain the documents from the non-party, or authorise the requesting party to do so. Flag a request grounded on non-party possession so it is run through Article 3.9 rather than treated as an ordinary inter-party request.

## Mechanics around the gates

- **3.2** the requesting party files a Request to Produce within the time the tribunal orders, usually after the first round of submissions.
- **3.5** the party to whom the request is addressed (the producing party) states any objection in writing within the time the tribunal orders, on the grounds set out in Articles 9.2 or 9.3 or a failure to meet Article 3.3. If the tribunal so directs, the requesting party may then respond.
- **3.6** the tribunal may invite the relevant parties to consult with each other to resolve the objection before it rules.
- **3.7** the tribunal orders production only if it is satisfied that the documents are relevant and material, that none of the reasons for objection in Articles 9.2 or 9.3 applies, and that the Article 3.3 requirements are met.

## How the gates feed the output

- A request that passes all three gates goes into the schedule with its relevance-and-materiality text in the Relevance and Materiality column.
- A request that fails any gate still goes into the schedule, because the user may choose to file it, but it is named in the internal flags memo with the gate it fails and a one-line reason. The user decides whether to fix, narrow, or drop it.
