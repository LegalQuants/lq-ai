# Word redline library: contract, document representation and limits

> **Status:** Proposal. For discussion on [#697](https://github.com/LegalQuants/lq-ai/issues/697).
> **Scope:** The reusable Word capability: reading the document, addressing paragraphs, proposing tracked-change edits and writing them back, and the endpoint that returns those edits. The note proposes #314 as the canonical lane for [ADR 0032](../adr/0032-word-add-in-1.0-slice.md) decision 2. Skill execution and the agent harness are outside this note.

## Summary

The redline library is a set of pure TypeScript functions on WordprocessingML (OOXML). A caller supplies the document's XML, a list of operations, a revision author and date, and the paragraph texts the operations were written against. The library returns new XML with the edits as native tracked changes (`w:ins` and `w:del`). If the document no longer matches the supplied texts, the library throws and returns nothing.

The library has no concept of chat, skills, tools or approval. Any caller that can produce a list of operations can use it: a chat panel, a skill-execute endpoint, an agent harness or a review screen. Office.js access sits in one separate adapter file that makes one read call and one write call to Word.

## Layers

The work splits into four layers. Layers 1 and 2 are the reusable capability. Layer 3 is the candidate document representation for the ADR 0032 decision 3 endpoint contract. Layer 4 is the integration that needs coordination.

| Layer | Modules | Depends on | Purpose |
|---|---|---|---|
| 1. Library | `docxDocumentEdits.ts`, `docxTrackedEdits.ts`, `DocxToJson.ts`, `docxComments.ts`, `docxXml.ts`, `docxTypes.ts` | `fast-xml-parser` | Reads paragraphs and comments from XML into the internal representation. Applies operations as tracked changes. Previews operations. Runs in Node and the browser. |
| 2. Word adapter | `WordDocx.ts` | Office.js, layer 1 | `readActiveWordForEditing`, `readActiveWordSelectionAnchor`, `editActiveWordDocument`. |
| 3. Model-facing representation | `liveDocumentChat.ts`, `liveDocumentCache.ts` | layer 1 | The document the model sees, stable paragraph ids, the flat operation input, selection anchoring. |
| 4. Chat integration | `ChatPanel<T>`, the approval card, the selection chip | layers 1 to 3, React, Mantine | Approval cards, tool wiring, the selection chip, prompt caching. |

The modules would live under `word-addin/src/`. Layer 1 does not import UI code, stores, Office.js, provider SDKs or server modules, and a purity test enforces the rule. Layer 1 reads only the Flat OPC package that Word's `body.getOoxml()` returns. Layer 1 does not open `.docx` files.

The backend would define the model-facing schemas in Pydantic and in `docs/api/backend-openapi.yaml`. The add-in would mirror them as plain TypeScript types.

## Document representation

The design uses two representations. The model never receives the first one.

1. **The internal representation (Jxml)** comes from `DocxToJson.ts`. Jxml keeps everything an edit needs to map text back to XML: runs, offsets and source positions. Only the client uses it.
2. **The model document** comes from layer 3. The model document is a small JSON projection of Jxml: paragraph ids, text and a few attributes, plus comment threads. The model sees only this representation, and the operation contract addresses paragraphs in its terms.

### Paragraph order

Both representations list the body as a flat sequence of paragraphs. Table-cell paragraphs appear in reading order, nested tables included. Word's `body.paragraphs` uses the same order, so an index from the library and an index from Word name the same paragraph. Tests cover this order only against the parser. See [Live-Word checks](#live-word-checks-still-open).

### Internal representation (Jxml)

`readDocumentParagraphs` and `readDocumentWithComments` return one `JxmlParagraph` per paragraph:

| Field | Content |
|---|---|
| `index` | Position in the flat paragraph list. |
| `id` | `p:<index>`. Valid for one read only. Not a Word identifier. |
| `text` | Current text. Tracked insertions count. Tracked deletions and moved-from text do not. `w:tab` becomes `\t`, and `w:br` and `w:cr` become `\n`. Images, equations and fields become the placeholders `<jxon:image>`, `<jxon:equation>` and `<jxon:field>`. Offsets count UTF-16 code units. |
| `runs` | One entry per run. Each holds its `text`, its `type` (`run`, `insertion`, `deletion`, `image`, `math`, `field` and others), its `offset` into `text`, its source position in `document.xml`, and its raw run and `w:rPr` XML. |
| `xml`, `source` | The paragraph's exact XML and its start and end position in `document.xml`. `spliceParagraphs` uses these positions to put edited paragraphs back. |
| `formatting` | The list label Word shows (for example `6.` or `(i)`), with its list id and level, when `numbering.xml` and `styles.xml` are supplied. |
| `commentMarkers` | Comment start, end and reference positions as offsets into `text`. Markers add no characters. |
| `cell` | For table paragraphs: table index in document order, row, cell, nesting depth, and `lastInCell`. |

`readDocumentWithComments` also returns the comments: each comment's anchor (start and end paragraph and offset, and the selected text), body, author, date, parent comment and resolved state.

### Model document (sent to the model)

Layer 3 projects Jxml into this shape:

```json
{
  "blocks": [
    { "id": "a1f3", "text": "6. Termination", "ref": "§6" },
    { "id": "9c2e", "text": "Either party may terminate on 30 days' written notice.", "ref": "§6.a", "revisions": true },
    { "id": "77b0", "text": "Fee", "cell": { "table": 0, "row": 1, "cell": 0 } }
  ],
  "comments": [
    { "id": "4", "paragraph": "9c2e", "quote": "30 days'", "author": "R. Reviewer", "date": "2026-11-02T10:14:00Z",
      "text": "Client wants 60.", "replies": [{ "author": "J. Lawyer", "text": "Agreed." }] }
  ],
  "commentWarnings": []
}
```

- `id` names the paragraph for the model. `assignParagraphIds` keeps a paragraph's id while its text is unchanged, including after edits elsewhere and after the paragraph moves. A new paragraph gets an id built from a hash of its text, with a suffix when that id is taken. The library never gives a used id to different text.
- `text` is the Jxml `text`, placeholders included.
- `ref` is the full list reference built by `paragraphReferences` from the labels of the parent levels, for example `§6.a.(i)`.
- `revisions` marks a paragraph that already holds tracked changes.
- `cell` gives the table, row and cell. See [Tables](#tables).
- Each comment thread names its paragraph by id and carries the quoted text, clipped to 500 characters, and its replies.

The model document carries no runs, offsets, XML or formatting.

#### Tables

The model document includes tables, flattened into blocks. A table does not get a block of its own. Each paragraph inside a cell is one block, in reading order: row by row, and cell by cell within a row. Each of those blocks carries `cell: { table, row, cell }`, counted from 0. `table` counts every table in document order, nested tables included. A cell with three paragraphs gives three blocks with the same `cell` value. The model rebuilds the grid from those coordinates.

The model document leaves out the rest of the table structure that Jxml holds:

- Nesting depth. A paragraph in a nested table carries the nested table's own `table` number, and nothing marks that table as sitting inside a cell of another.
- Merged cells: `gridSpan` (horizontal) and `vMerge` (vertical).
- Row and column counts, header rows, column widths and table styles.

Operations on table paragraphs work like operations on any other paragraph, with two rules from layer 1. Inserting after a paragraph in a cell puts the new paragraph in the same cell. Deleting the last paragraph of a cell only empties it, because its mark ends the cell. No operation adds, removes, merges or splits rows, columns or cells.

Every request sends the full model document. No request sends a partial document or a list of changes since an earlier request.

The model names paragraphs by `id` or `ref`. Layer 3 resolves both to Jxml indexes before it calls layer 1.

## The operation contract

Layer 1 accepts four operations. Every index refers to the document as read, before any operation in the same call applies.

```ts
type DocumentOperation =
  // Literal text within one paragraph. occurrence is 1-based; omitted means every match.
  | { kind: "replace"; paragraph: number; find: string; replace: string; occurrence?: number }
  // New full text for a paragraph. The library diffs it word by word and redlines only the changed words.
  | { kind: "rewrite"; paragraph: number; text: string }
  // New paragraphs after paragraph `after` (-1 inserts before the first), one per line of `text`.
  | { kind: "insertParagraph"; after: number; text: string }
  | { kind: "deleteParagraph"; paragraph: number };
```

`replace` and `rewrite` both reduce to `{ start, end, insert }` edits on `paragraph.text`. `applyParagraphEdits` then rewrites only the runs those edits touch. The function leaves other runs, bookmarks, comment ranges, hyperlink wrappers and other authors' revisions unchanged byte for byte. New text takes the formatting of the run it joins. A new paragraph copies the paragraph properties and first-run formatting of the paragraph before it, without its section break.

The model-facing form in layer 3 (`documentOperationInput`) is one flat object with optional fields, because some providers handle a union in a tool schema poorly. The flat form addresses paragraphs by id, by `ref`, or by the id of a selection the user attached. `toDocumentOperation` converts it into a `DocumentOperation` against a given snapshot, or throws a message the model can act on.

The endpoint returns the id form. An id such as `9c2e` names a paragraph by its text, so the id stays valid when the user adds or removes paragraphs elsewhere. An index such as `12` names a position, and any paragraph added above it shifts every later index. The add-in converts ids to indexes against the snapshot it sent, just before it calls layer 1.

## Using the library without a chat panel

The caller supplies four things:

1. The document's `document.xml`. In Word, the adapter reads the body with `body.getOoxml()`, and `parseFlatOpcParts` extracts `document.xml`, `numbering.xml`, `styles.xml` and the comment parts from the result.
2. The operations to apply, already filtered to the approved ones.
3. A revision: `{ author, date, ids }`, where `ids = createRevisionIds(xml)` starts above every existing `w:id`. `null` instead makes plain, untracked edits.
4. `expectedTexts`: the text of every paragraph as the caller read it when the operations were written.

```ts
import { readDocumentParagraphs, editDocumentXml, previewDocumentOperation } from "@/docx/docxDocumentEdits";
import { createRevisionIds } from "@/docx/docxTrackedEdits";

// Read: the representation the operations are written against.
const paragraphs = readDocumentParagraphs(documentXml, numberingXml, stylesXml);
const expectedTexts = paragraphs.map(p => p.text);

// Preview one operation through the same code that applies it.
const preview = previewDocumentOperation(expectedTexts, operation);
// -> { kind: "edit" | "insert" | "delete", segments } or { kind: "error", message }

// Apply the approved operations as tracked changes.
const revision = { author: "Jane Lawyer", date: "2026-11-07T15:00:00Z", ids: createRevisionIds(documentXml) };
const updatedXml = editDocumentXml(documentXml, approvedOperations, revision, expectedTexts);
```

In Word, `editActiveWordDocument(operations, author, expectedTexts)` performs the same steps inside one `Word.run`. The function reads the body OOXML, calls `editDocumentXml`, turns change tracking off, writes the body back with `insertOoxml(…, "Replace")`, and restores the user's tracking mode. Tracking is off during the write, so Word records only the library's revisions and does not add its own.

Node can run the full read, preview and apply cycle against XML fixtures, with no Word host. The library's tests use that method.

### How approved operations are passed in

The library does not model approval. The caller passes only the operations the user approved, in one call. An operation the user rejected never reaches the library.

The chat integration in layer 4 works this way. The approval card keeps a set of operation positions the user unchecked. When the user presses Apply, the tool drops the unchecked operations and any operation that fails to resolve. The tool records a reason for each dropped operation. The tool then calls `editActiveWordDocument` once with the rest, plus the texts of the snapshot taken when the proposal arrived. A different approval mechanism (an agent-harness gate, a review screen, a skill-execute response) needs to produce the same two inputs: the approved `DocumentOperation[]` and the paragraph texts it showed the user.

`previewDocumentOperation` uses the same code path as `editDocumentXml`. A preview that shows an error therefore corresponds to an operation that would fail on apply.

### How the library handles a changed document

`editDocumentXml` checks the document before it writes anything. Every failure throws, and the call writes nothing. A call never applies only some of its operations.

| Check | Result when it fails |
|---|---|
| The document has the same paragraph count as `expectedTexts`. | Throws "The document has N paragraphs, not the M that were read. Read it again." Any paragraph added or removed anywhere fails this check. |
| Each paragraph an operation touches has the text in `expectedTexts`. | Throws "Paragraph N has changed since it was read." |
| Each index exists. | Throws "There is no paragraph N." |
| A `replace` finds its text, and the requested occurrence exists. | Throws and names the missing text, or the number of matches when the occurrence is out of range. |
| No paragraph is both edited and deleted. | Throws. |
| Each edited paragraph is still at its source position when spliced back (`spliceParagraphs`). | Throws. |
| Each edited paragraph, read back, gives the expected new text. | Throws. |

The library checks text only for paragraphs an operation touches. A user edit to another paragraph's text does not block the write. A change in paragraph count blocks every write. After a refusal, the caller re-reads the document. Layer 3 then keeps the ids of unchanged paragraphs, so a model can re-address its edits against the new snapshot without starting over.

The check and the write run inside one `Word.run`. That run includes one `context.sync()` round trip between the read and the write. A user edit made during that round trip would not be in the XML the library edited, and the body write would overwrite it. No test covers that window.

## API contract

The library applies edits in the add-in, so the server never reads or writes the document. The server's job is to give the model the document and the instruction, and to return the model's proposed operations.

### Proposed endpoint

The proposal is a one-shot, stateless, non-streaming endpoint that replaces #314's `document-chat`. `document-chat` answers with citations that scroll to a paragraph. `document-edits` answers with edits, and approved edits appear in the document as tracked changes. The endpoint matches ADR 0032 decision 3: a skill-execute endpoint that returns structured redlines. The path is a placeholder.

`POST /api/v1/word-addin/document-edits`. The endpoint uses the same `authenticated_router` and `_active` auth that `document-chat` uses today.

**Request body (`DocumentEditsCreate`):**

```ts
{
  instruction: string;            // what the user asked, 1 or more characters
  document: ModelDocument;        // as described under "Model document"
  selection?:                     // the user's Word selection, pinned by the add-in
    | { id: string; kind: "text"; paragraph: string; find: string; occurrence: number }
    | { id: string; kind: "paragraphs"; first: string; last: string };
  skills?: string[];              // skill names, at most 16
  model?: string;                 // defaults to "smart"
}
```

**Response body (`DocumentEditsResponse`, 200):**

```ts
{
  content: string;                // Markdown explanation for the user
  proposal: {
    reason: string;               // one sentence on what the edits do
    operations: DocumentOperationInput[];   // the flat, id-addressed form; may be empty
  };
  errors: { operation: number; message: string }[];  // operations the server could not resolve
}
```

**Server behaviour:**

1. The server builds the prompt in this order: the document instructions, the `ModelDocument`, then the skills. The document comes before the skills so the provider can cache it across skills. The selection, when present, goes into the user message as a `<context kind="selection">` tag with its id.
2. The server forces one tool call, `emit_document_edits`, whose arguments are `{ response, reason, operations }`. #314's `emit_answer` uses the same forced-tool pattern.
3. The server sets `lq_ai_restore_tool_arguments: true` on the gateway request. Without the flag, the gateway rehydrates message content only. Pseudonyms would then stay in `find` and `text`, so a `replace` would fail to match and a `rewrite` would write pseudonyms into the document. The gateway does not restore arguments longer than 65,536 characters (`_MAX_RESTORED_ARGUMENT_CHARS`). The endpoint must refuse such a proposal instead of returning it unrestored.
4. The server validates each operation with Pydantic. Each operation needs the fields its `kind` requires. Each `paragraph`, `after`, `ref` and `selection` must resolve in the request's `ModelDocument` or `selection`. An operation that fails validation goes into `errors` by position and stays out of `proposal.operations`.
5. The server writes nothing to `chats` or `messages`. The gateway writes its usual `inference_routing_log` row.
6. A request body above a size bound returns 422. #314 uses 300,000 characters for `document-chat`.

The server cannot run the full preview, because it has no Jxml. The add-in's `previewDocumentOperation` remains the authoritative check before approval.

**Add-in flow:**

1. Read the document: `readActiveWordForEditing`, then `toCommentedSnapshot`.
2. Send `toModelDocument(snapshot)` with the instruction, the selection and the skills.
3. Resolve each returned operation against the same snapshot with `toDocumentOperation`, then preview it.
4. Show the proposal. The user approves some or all operations.
5. Call `editActiveWordDocument(approved, author, snapshot.paragraphs.map(p => p.text))`.
6. If the library refuses because the document changed, re-read the document and send a new request.

The endpoint needs no second request to record an approval.

### Multi-turn alternative

A multi-turn chat would use a streaming endpoint instead. The model would get three tools that run in the add-in: `read_document`, `read_selection` and `propose_document_edits`. The server would declare the tools but not implement them.

- `propose_document_edits` takes `{ reason, operations: DocumentOperationInput[] }` and requires approval. Its result is `{ applied, message?, skipped?: [{ operation, reason }] }`.
- The run pauses at `propose_document_edits`. The add-in shows the proposal, applies the approved operations, and sends a second request that resumes the run with the tool result.
- Each request carries the full model document.

The pause-and-resume approval is part of the agent harness, so this note does not propose it for 1.0.

When the endpoint is built, the PR will add it to `docs/api/backend-openapi.yaml`, `IMPLEMENTED_ROUTES` and `EXPECTED_PATHS`, and remove `document-chat` from all three.

## Behaviour already tested

The tests run in Node with Vitest against XML fixtures.

- **Edits** (`docxTrackedEdits.test.ts`): tracked replacements that keep run formatting; runs split mid-word; runs that start with a space; tabs and breaks written as elements; XML entities; refusal to split a surrogate pair; hyperlink wrappers and comment ranges kept around an edit; refusal to remove a field; writes into an empty paragraph, including `<w:p/>`; plain writes with no revision; refusal of a run the library cannot rewrite exactly.
- **Other authors' revisions** (`docxTrackedEdits.test.ts`): other revisions left unchanged; a deletion nested inside another author's insertion; another author's insertion split around a new insertion; the caller's own insertion changed in place with no new revision; revision ids numbered above existing ids.
- **Document operations** (`docxDocumentEdits.test.ts`): all four operations as tracked changes; inserted paragraphs that copy style and run formatting and drop the section break; refusal of operations against changed text, while other operations still apply; occurrence selection and the error for a missing one; refusal to edit and delete the same paragraph; paragraph deletion as a plain write.
- **Tables** (`docxDocumentEdits.test.ts`): reading-order numbering with cell positions; empty self-closing cells; deleting a cell's last paragraph empties it instead of removing the end-of-cell mark, for both tracked and plain writes.
- **Comments** (`docxDocumentEdits.test.ts`, `DocxToJson.comments.test.ts`): threads, replies and resolved state read against the paragraphs edits address; anchors across table cells; overlapping and point anchors; comment markers kept through a rewrite and a delete; warnings for missing bodies, ambiguous anchors and invalid dates; refusal of malformed comment XML.
- **Objects** (`docxDocumentEdits.test.ts`): edits around an equation that keep it; refusal to remove, add or copy an image, equation or field.
- **References and previews**: numbered-paragraph references built from parent labels and matched however the user writes them; previews that report the same error the apply step would raise.
- **Word adapter** (`WordDocx.test.ts`): Office.js is mocked. The tests confirm the adapter calls the shared parser and makes no writes on read. The tests do not establish how a real Word host behaves.

## Live-Word checks still open

Nobody has yet checked the following items in a running Word. Each item lists what the library assumes and what guards exist today.

1. **Table paragraph order for complex layouts.** The library assumes its order matches `body.paragraphs` for vertically merged cells, nested tables and empty self-closing cells. When it anchors a selection, layer 3 compares each end of the selection with `parentTableOrNullObject` and refuses a mismatch.
2. **Comment parts in `getOoxml()`.** `readActiveWordForEditing` expects `body.getOoxml()` to include `comments.xml` and `commentsExtended.xml`. If Word omits those parts, every comment reads as having no body. The fallback would read comment bodies through `body.getComments()`. That fallback is not built.
3. **Accepting a deletion that covers a whole comment's range.** The effect on the comment in Word is unknown.
4. **A document that ends in a table.** After a whole-body `insertOoxml`, Word may add a paragraph after the table. The caller re-reads after each write, so indexes stay correct, but nobody has observed this case in Word.
5. **The body's last paragraph mark.** The library tracks its deletion like any other paragraph mark. Word never removes the final mark, so accepting the deletion probably leaves an empty paragraph.
6. **A user edit during the write.** See the race described above.

Text boxes are a known mismatch rather than an open check. The library folds a text box's paragraphs into the anchoring paragraph's text. Word does not count them in `body.paragraphs` and leaves them out of that paragraph's text, so a selection in that paragraph may not match.

## Limits

**Current limits** that further work could remove:

- Images and equations reach the model only as placeholders. Their content does not enter inference.
- Footnotes and endnotes are not included. The library does not read `footnotes.xml` or `endnotes.xml`, so the model does not see their text and no operation can edit them. A footnote reference in the body adds no characters to the paragraph text, and edits around it keep it in place. Reading and editing footnotes and endnotes is future work.
- Comments are read-only. The library cannot add, answer or resolve comments.
- Newer comment parts (`commentsExtensible.xml`, `commentsIds.xml`) are not read.
- Comment images do not load their own media relationships.

**Design limits** that come from the approach:

- An edit cannot span two paragraphs. A merge or split is a delete plus an insert.
- The library edits only the main body. Headers, footers and text boxes are out of scope.
- Images, equations and fields can stay in place. The library refuses to edit, add, copy or move them.
- The adapter writes back the whole body, not a range.
- The library refuses rather than guesses. It refuses edits that overlap, split a character, remove an object, insert placeholder text, or touch a run holding content other than text, tabs, breaks and a few zero-width elements.

## Dependencies

The library adds one runtime dependency to `word-addin/`: `fast-xml-parser`. No tracked-changes library is involved, which bears on the SBOM review in ADR 0032 decision 3.

## Plan

The work builds on #314, which this note proposes as the canonical lane. #314 already has the add-in shell, sign-in, the version handshake and a document-grounded endpoint. The steps below adapt #314 to the redline slice. Each step can follow the new endpoints or agent harness once the maintainers agree them.

1. Add layers 1 and 2 to `word-addin/` with their tests, ahead of the lane decision and before any change to the chat UI. The step changes no user-facing behaviour.
2. Add layer 3 and the `document-edits` endpoint, and remove `document-chat` and its citations.
3. Change #314's Chat tab to show proposed edits and write the approved ones into the document as tracked changes.

## Open questions for the maintainers

1. Why would the approval step sit in the proposed agent harness? This is a purely UI step: the add-in shows the edits, the user accepts or declines, and the library writes the accepted edit in one step.  
