# Mini-PRD: Readable document formats in chat and knowledge bases

> **Status:** **Draft — not yet open for contribution.** Maintainer direction recorded 2026-11-06 (below); this document becomes "Open for contribution" when the maintainer approves it.
> **Effort:** Phase 1 (benchmark) M · Phase 2 (decision docs) S · Phase 3 (build) M · Phase 4 (visibility) S. Each phase is its own PR.
> **Contributor profile:** Python engineer comfortable with async workers, untrusted-input handling and writing a reproducible evaluation. Phase 1 also suits a contributor who knows legal documents well: building the corpus and its expected-text assertions is half the work.
> **Mentor:** Maintainer (houfu, via PR review)
> **Replaces:** [`docx-ingest-support.md`](docx-ingest-support.md) as the contributor pickup. Through the Phase 2 ADR, it proposes revising [ADR 0017](../../adr/0017-docx-ingest-via-pandoc.md)'s converter choice. ADR 0017's redline goal stays (see "Scope cuts").
> **Depends on / relates to:** [ADR 0006](../../adr/0006-document-pipeline-architecture.md), [ADR 0017](../../adr/0017-docx-ingest-via-pandoc.md), [ADR 0026](../../adr/0026-document-ingestion-parser-and-docling.md), [ADR 0033](../../adr/0033-document-pipeline-honesty-and-ocr.md), [PRD §9](../../PRD.md#9-deferred-enhancements-and-identified-future-work) DE-332, DE-352, DE-387, DE-320, DE-391

## What this is

Users upload ordinary office documents, and LQ.AI cannot read most of them. Ingestion handles PDF (PyMuPDF) and plain text or Markdown (`parse_text`). Anything else is marked `ingestion_status='failed'` with `ingestion_error='unsupported_type'` before any parser runs (`api/app/pipeline/ingest.py:160-181`). The upload itself still succeeds (DE-352), so the failure shows up late.

The failure is the same in both places documents are used. A chat attachment's text comes from `Document.normalized_content` (`_load_attached_file_contexts`, `api/app/api/chats.py:605`). A file with no `Document` row is **silently omitted** from the turn, so the model never sees the document, and nothing tells the user. Knowledge-base retrieval searches the chunks of the same `Document`. If one route produces a `Document` for a new format, both workflows can read it.

This work adds that route in four phases:

1. **Benchmark.** Compare candidate converters on a committed corpus of LQ-relevant documents, and publish the results and receipts under `docs/research/`.
2. **Decision docs.** Write a new ADR that revises ADR 0017's converter choice, citing the benchmark. Amend ADR 0033 decision 3, and update the PRD and HONEST-STATE.
3. **Build.** Add one converter adapter in the ingest worker for the formats the benchmark clears, starting with DOCX.
4. **Visibility.** Make processing and failure states visible, and set the attachment-size behaviour.

## Maintainer direction (2026-11-06)

These were decided after the 1 Nov committee call, where the [deck](#references) was discussed and no decision was taken:

- **Benchmark first.** This follows the committee's ask for research-driven choices: compare the options, publish the opinion, and re-run it as tools improve. The deck proposes Firecrawl's **anydoc** as the first converter. The benchmark tests that proposal; it does not assume it.
- **ADR 0017 is revised, not thrown away.** The new ADR replaces its converter choice for readable body text. Its redline goal stays as a named follow-up: accepted text is canonical, and deletions and comments can be cited with author and date.
- **The converter is on by default.** A converter that only runs when enabled would leave DOCX broken on a default install, which defeats the purpose. ADR 0033 decision 3 says "adapters are opt-in". It gets amended so that readable office formats are part of the core. Heavy or ML adapters, such as OCR and Docling, stay opt-in.
- **Already settled, not open in this work.** PDF stays on PyMuPDF, because the citation engine relies on its offsets and page spans. No hosted OCR is wired up (see Phase 3). Removing Docling stays its own PR under ADR 0026.

## Phase 1 — Benchmark

### Candidates

| Converter | Licence | Shape | Why it is in |
|---|---|---|---|
| **anydoc** (`firecrawl-anydoc` on PyPI) | MIT | Rust library with a Python wheel; no models; local conversion | The deck's proposal |
| **Pandoc** | GPL-2.0+ (binary, run as a subprocess) | Single binary | The converter ADR 0017 accepted |
| **MarkItDown** | MIT | Python library | A widely used permissive alternative |
| **Docling 2.x** (CPU-only pin) | MIT | Python, with ML models | The high-capability option already researched in [`2026-08-15-docling-ingestion-research.md`](../../research/2026-08-15-docling-ingestion-research.md) |

Pin an exact version of every candidate and record it in the results. A contributor may add a candidate with a short justification. Do not drop any of the four.

### Corpus

The corpus is committed to `docs/research/<date>-document-converter-receipts/corpus/`, following the existing `<date>-<topic>-receipts/` convention. The decompression bomb and the large XLSX are **generated by the run script at run time**, not committed. The corpus must be **redistributable**: synthetic documents, or public documents whose licence allows it. **No client, matter or employer documents**, even anonymised ones. A corpus nobody else can re-run is a claim, not a benchmark. (anydoc's own published benchmark used a corpus that is not redistributable, which is why we don't simply cite it.)

| Category | Minimum | What it must contain |
|---|---|---|
| Clean DOCX contracts | 3 | Numbered clauses, defined terms, a table, footnotes, a schedule |
| **Redlined DOCX** | 3 | Insertions and deletions by two authors. At least one comment anchored on an *unaccepted insertion* (the Pandoc [#9833](https://github.com/jgm/pandoc/issues/9833) case). A moved paragraph. |
| Commented DOCX | 1 | Comments on accepted text, including a reply thread |
| Legacy `.doc` | 1 | Any clean contract |
| PPTX | 2 | Speaker notes, a table, a slide that is only an image |
| XLSX | 2 | Several sheets, merged cells, formulas; one large sheet (≥ 5,000 rows) |
| ODT, RTF | 1 each | Any clean contract |
| EPUB, CSV | 1 each | Low priority; include if cheap |
| **Failure cases** | 1 each | Encrypted DOCX, truncated ZIP, a decompression bomb, an empty DOCX, a DOCX whose only content is a pasted scan image, a PDF renamed `.docx` |

### What to measure

Each document carries hand-written **expected-text assertions** in a sidecar file: phrases that must appear in the output, and for redlines, phrases that must *not* appear in the accepted view. Scoring is mechanical against those assertions. An LLM judge may be added as a secondary column but is never the primary score.

| Measure | How |
|---|---|
| Text survival | % of must-contain assertions met, per document and per format |
| Redline handling | Classify each converter's default output on redlined files: accepted-only / all changes inline / deletions dropped silently / garbled. Note whether author and date are recoverable at all. |
| Comments | Retained / dropped, including the #9833 case |
| Tables | Cell text present; header row identifiable |
| Failure honesty | For each failure case: typed error / empty "success" / crash / hang. **An empty success is the worst outcome** (ADR 0033 decision 1). |
| Determinism | Two runs give byte-identical output |
| Resource use | Wall time and peak memory per document, including the bomb |
| Network | Run with no network (`docker run --network none` or equivalent) and record any attempted egress |
| Weight | Installed size added to the `ingest-worker` image; transitive dependencies; licences |

### Decision rule — agree it before running

Phase 1's PR states the rule *before* the results, so the results cannot shape it. Proposed rule, for the maintainer to confirm or change:

1. **Eligibility** (pass or fail). No network access in the configuration we would ship. A permissive licence, or one an existing ADR already accepts. A typed error or clear failure for every failure case: no empty successes, no hangs. Deterministic output.
2. **Per-format clearance.** A format is advertised only if the chosen converter meets **≥ 90% of must-contain assertions** across that format's documents. Formats below the bar stay `unsupported_type` and are listed as such.
3. **Choice.** Among eligible converters: most formats cleared first, then installed weight, then speed.

### Deliverables

- `docs/research/<date>-document-converter-benchmark.md`: the rule, the results table, per-format verdicts, and what each converter does with redlines.
- `docs/research/<date>-document-converter-receipts/`: corpus, assertion sidecars, the run script (re-runnable with one command, versions pinned) and the raw outputs as receipts.

## Phase 2 — Decision docs

- **A new ADR** (numbered at PR time) that revises ADR 0017. It names the converter and the advertised formats, citing the benchmark. It states what the accepted view does with tracked changes, from the benchmark's redline findings. It names the revision layer as the follow-up. ADR 0017 gets a status notice pointing to the new ADR, and is not rewritten.
- **An ADR 0033 amendment** to decision 3: readable office formats ship in core, while heavy or ML adapters stay opt-in. It records the SBOM entry and its justification.
- **PRD:** a DE for multi-format ingestion in §9 (or DE-387 rescoped), plus the §3 format note. Update DE-352, which becomes "reject what we still can't read".
- **HONEST-STATE:** the ingest-formats row (`docs/HONEST-STATE.md:78`).
- **This mini-PRD** and `docx-ingest-support.md` get status lines reconciled with the ADR.

## Phase 3 — Build

```
api/app/pipeline/
├── parsers.py    # + office-format detection + parse_office() returning ParsedDocument
└── ingest.py     # + route beside route_pdf / route_text; error mapping
api/tests/
├── test_pipeline_parsers_office.py   # NEW — corpus subset as fixtures
└── test_pipeline_ingest.py           # DOCX flips from unsupported_type to ready
api/pyproject.toml + uv.lock          # pinned converter
```

Behaviour:

- **Shape.** Copy `parse_text`: store the converter's Markdown **verbatim** as `canonical_text` / `normalized_content`, as one page span (`parsers.py:248`). This keeps the chunker invariant `canonical_text[start:end] == chunk.content` and exact-match citation verification unchanged.
- **Routing.** Detect the format from the bytes, not the browser MIME. anydoc exposes `format_from_bytes`, and the existing text route already distrusts the MIME (`ingest.py:160-166`). Today `route_pdf` is decided by MIME type. A PDF uploaded under an office name or MIME could either be redirected to PyMuPDF by byte detection, or stay `unsupported_type`. Redirecting changes the existing PDF route, so the Phase 2 ADR makes that choice explicitly. Either way, PDF never goes through the new converter.
- **Provenance.** Record the converter in `parser` and its exact version in `parser_version`, so a later converter upgrade can trigger re-ingest decisions.
- **Errors.** Map every converter failure to an `ingestion_error`. Encrypted → `unsupported_content`, the code encrypted PDFs already get (`ParserUnsupported`, `ingest.py:263`). If the ADR wants a distinct `encrypted` code, it applies to both routes and the PDF mapping changes in the same PR. Then: resource limit → `parse_failed`; malformed or missing part → `parse_failed`; no extractable text → `unsupported_content`; a needs-OCR result → `needs_ocr` if ADR 0033 T1 has landed, otherwise `unsupported_content`. Formats the benchmark did not clear stay `unsupported_type`.
- **Bounds.** Keep the existing upload cap (`LQ_AI_MAX_UPLOAD_SIZE_MB`), add a conversion timeout with the same `asyncio.wait_for` pattern as the PDF path, and rely on the converter's own decompression limits only after the benchmark's bomb case shows they work.
- **User-facing copy.** `ingestion_error` is a free-text column (`api/app/models/file.py:69`), so a new code needs no migration. But the web client names the readable formats in its copy: `UNREADABLE_REASONS` in `web/src/lib/lq-ai/run/composer.ts` says "Runs read PDF with text, plain text and Markdown." Update that copy, and give every new error code a reason string there.
- **No egress.** Never pass anydoc's `ocr="hosted"` (or any equivalent option). It sends the **whole document** to Firecrawl Parse. A test asserts that the adapter never sets it. Turning hosted OCR on would be a separate decision with its own review, because it means documents leave the operator's environment.

## Phase 4 — Visibility

- The user can see whether an attached document is still processing, failed, or ready, and the failure reason uses the error codes above. Coordinate with the existing ingestion-state work (#512) rather than duplicating it.
- **Attachment size.** `_load_attached_file_contexts` injects the whole `normalized_content` with no cap. A 5,000-row spreadsheet converted to Markdown may exceed the model's context. Measure it with the corpus's large XLSX, then either cap it with a visible "document truncated" notice or document the limit. Do not truncate silently. A related problem is already filed: **DE-391**. Attached-document content counts against the chat-history budget and can drop out between turns. Larger converted documents make DE-391 more likely to bite, so link the two rather than fixing DE-391 here.

## How we'd know it's done

- [ ] **Phase 1:** the decision rule is merged or stated in the PR before the results. The corpus is redistributable and committed. One command re-runs the benchmark. Every candidate is version-pinned. The results report text survival, redline handling, failure honesty, determinism, network and weight for all four candidates.
- [ ] **Phase 2:** the new ADR cites the benchmark; ADR 0017 carries a status notice and is not edited in place; ADR 0033 decision 3 is amended on the record; the PRD DE and HONEST-STATE row match what Phase 3 ships.
- [ ] **Phase 3:** for every advertised format, a fixture reaches `ready` with a `Document` and chunks.
- [ ] **Phase 3:** the chunk offset-fidelity invariant holds for each new-format fixture.
- [ ] **Phase 3:** a chat turn with a DOCX attached includes its text (test at the `_load_attached_file_contexts` level).
- [ ] **Phase 3:** a knowledge base holding the DOCX returns a passage from it in retrieval.
- [ ] **Phase 3:** each failure-case fixture gets its mapped `ingestion_error`. None ends `ready` with empty text, and none is left in `processing`.
- [ ] **Phase 3:** a test asserts the hosted-OCR option is never passed.
- [ ] **Phase 3:** the dependency is pinned in the `api` and `ingest-worker` images.
- [ ] **Phase 4:** processing and failure states are visible in chat and on the knowledge base. Oversized attachments are capped with a notice, or the limit is documented.

## Where to start

1. Read [ADR 0033](../../adr/0033-document-pipeline-honesty-and-ocr.md) decisions 1 and 3, and [ADR 0017](../../adr/0017-docx-ingest-via-pandoc.md) (the redline policy this work keeps as its follow-up).
2. Read `api/app/pipeline/parsers.py` (`ParsedDocument`, `parse_text`) and `api/app/pipeline/ingest.py:160-285` (routing, timeout and error mapping).
3. Read `_load_attached_file_contexts` in `api/app/api/chats.py:605` to see how chat gets document text.
4. Read the Docling research and receipts in `docs/research/2026-08-15-docling-*` for this project's existing benchmark style.
5. Build the corpus and the assertion sidecars **before** running any converter.

## Scope cuts

- **The revision layer.** Citable deletions and comments with author and date, as ADR 0017 specifies, are the **named follow-up**, not part of this work. The benchmark's redline findings feed that follow-up's design.
- **PDF.** Stays on PyMuPDF. The permissive-PDF-parser evaluation is ADR 0033 decision 4's separate track.
- **OCR,** local or hosted. ADR 0033's T1/T2 tiers own it.
- **Structured output,** such as headings, tables as structure, or `structured_content`. That is DE-387 T3.
- **A document viewer** in the UI.
- **Removing Docling.** That is ADR 0026's own PR.

## References

- Meeting deck: *Readable documents in chat and knowledge bases*, LQ.AI committee call, 1 November 2026 (maintainer's copy)
- anydoc README: https://github.com/firecrawl/anydoc (reviewed 2026-11-06: MIT; error variants `Unsupported`, `NeedsOcr`, `Malformed`, `Encrypted`, `ResourceLimit`, `MissingPart`; hosted OCR is opt-in and sends the whole document; its README does not describe tracked-change handling)
- `api/app/pipeline/parsers.py`, `api/app/pipeline/ingest.py`, `api/app/api/chats.py`, `api/app/citation/verification.py`
- [coding-agent-onboarding](../coding-agent-onboarding.md): build loop, dependency justification, merge gating

## Definition of "merged"

Each phase merges on its own. The contributor owns the work end to end on their own fork, opens each PR, and responds to CI and review. Phase 1 merges when the maintainer has accepted the decision rule and the results are re-runnable. Phase 3 does not start until Phase 2's ADR is accepted, because a new default dependency is a maintainer decision.
