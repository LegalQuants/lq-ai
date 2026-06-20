# Issue matching (separable module)

A self-contained relevance matcher. It ties items (here, document requests) to a pleaded-issues list. It is kept separate from the Redfern body on purpose. A later cross-examination skill will reuse the same logic to tie witness-statement passages to issues and to surface inconsistencies. That skill should reference this file rather than reimplement the logic. If the skill moves to an agent runtime, this is the natural seam to lift into a shared `issue_matcher` module.

## Interface

- **Inputs:**
  - `issues`: the pleaded-issues list. Each issue has an identifier (an issue number, or a pleading paragraph reference) and a short statement.
  - `items`: the things to tie. For the Redfern skill, each item is a document request with its ID and text.
- **Output:** for each item, one or more issue ties, each with:
  - the issue identifier it maps to,
  - a one-line reason for the tie,
  - a confidence note: `tied` (a clear, specific connection to a pleaded issue), `weak` (a plausible but generic connection), or `untied` (no issue maps).

## How to match

1. Read each issue and hold its subject and the element it goes to (liability, causation, quantum, jurisdiction, a specific factual allegation).
2. For each item, find the issue whose element the item would actually bear on. A tie needs a specific connection, not a topical overlap.
3. Record the tie with its reason and confidence.
4. An item that maps to no issue is `untied`. For a document request, `untied` is a relevance weakness under Article 3.3(b) and goes in the flags memo.
5. A `weak` tie is a generic connection (the item touches the general subject but not a specific pleaded element). Name it weak so the user can sharpen the relevance statement.

## When there is no issues list

If no issues list was provided, do not invent one. Mark every tie `unverified` and tell the user that relevance cannot be checked against the pleadings, so the relevance case is weaker and the flags memo cannot test Gate B fully. Recommend supplying the list or the pleading paragraphs.

## What this module does not do

- It does not decide materiality. Materiality (significance to the outcome) is a separate judgment that stays with counsel. This module ties relevance to issues. It does not weigh how much a document would move the result.
- It does not rank or score requests beyond the three-level confidence note.
