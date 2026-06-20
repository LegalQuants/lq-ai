# Schedule format, IDs, status, and merge discipline

The column model and the rules that hold the schedule together across rounds. On the LQ.AI platform these rules are model-applied. There is no code enforcing them, so follow them exactly and tell the user the discipline is applied by the model and worth a quick check each round.

## Columns

The schedule is a Markdown table with these columns, in this order, following the ICSID Redfern Schedule template. Refer to columns by their header name, never by a number: the number of columns and their position can change, but the names and their owners do not.

| Header | Owner | Filled |
|---|---|---|
| No. | requesting | the request ID, immutable |
| Document(s) or Category Requested | requesting | the request text |
| Relevance and Materiality | requesting | the relevance-and-materiality statement, tied to a pleaded issue |
| Objections | producing | the Article 9.2 grounds and basis |
| Reply | requesting | the answer to the objections |
| Tribunal's Decision | tribunal | left blank until the tribunal rules |

This six-column split, with Relevance and Materiality in its own column, is the orthodox ICSID Redfern layout and the default. The tribunal rules line by line, so keep relevance and materiality readable in its own column. For a very compact Markdown view the request text and the relevance-and-materiality text may be combined into the Document(s) or Category Requested column, but say so when you do, and keep the separate column as the default.

## Request IDs

- Assign a stable ID to each request at first draft (R1, R2, R3, and so on).
- In a simultaneous (joint) exchange, where both sides serve requests at once, prefix the ID with the party so the two tracks never collide: the Claimant's requests are C-R1, C-R2, and the Respondent's are R-R1, R-R2. Keep each track ID-stable and consolidate both into one tribunal-facing schedule without renumbering either.
- IDs are immutable. Never renumber. The objection, the reply, the decision, and the eventual production all reference a request by its ID. Renumbering breaks the chain.
- If a request is withdrawn, keep its row and mark its status withdrawn. Do not reuse its ID.
- If a request is split, give the parts new IDs (R4 becomes R4a and R4b) and note the split.

## Column ownership

- A role writes only its own columns, named here, never another role's.
  - The **requesting party** writes *No.*, *Document(s) or Category Requested*, *Relevance and Materiality*, and *Reply*.
  - The **producing party** writes *Objections*.
  - The **tribunal** writes *Tribunal's Decision*.
- Every column the current role does not own is reproduced verbatim from the input. Never edit another party's text. If their text contains an apparent error, note it in your own column or the memo, and leave their column as written.
- The *Tribunal's Decision* column stays blank until the tribunal rules. Party text must never appear in it.

## Status vocabulary

Track each request's lifecycle, shown in a small status note beside the row or in a status column when the user wants one:

`requested` to `objected` to `replied` to `granted`, `denied`, `granted-in-part`, then `produced` or `withdrawn`.

## Merge discipline

When merging a returned schedule into the working file:

- Match rows by request ID, not by position.
- Reproduce the other side's column verbatim into the working file.
- If an ID in the returned file does not match a row in the working file, stop and report the mismatch. Do not drop the row, invent a match, or reorder.
- Keep row order stable across rounds. One request keeps one row.
- After a merge, confirm back to the user: the count of rows, the IDs touched, and any mismatch found.

## Deadlines and the production timetable

Document production runs on a timetable, usually fixed in Procedural Order No. 1 or a later procedural order: a date for requests, a date for objections, a date for replies, a date for the tribunal's decision, and a date for production. These dates are optional input. When the user supplies them, record them in the version or calibration note at the top of the output, and flag any step that is out of time (for example, a request served after the request deadline, or an objection past the objection date). When they are absent, proceed without them and say the run is not calibrated to a timetable. Under the Prague Rules the relevant marker is the case-management conference rather than a request deadline (see `regimes.md`).

## Version note

Each exchange is a new version. State the round and version at the top of the output (for example, "Requesting party, first draft, round 1" or "Producing party objections, round 2, merged onto the requesting draft"). This is how a reader knows which columns are new and which are carried over.
