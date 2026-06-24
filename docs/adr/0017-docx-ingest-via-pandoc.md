# ADR 0017 — DOCX ingest via Pandoc (canonical text) with an OOXML comment fallback

**Status:** Accepted (2026-06-23) — maintainer approved the Pandoc dependency and the redline policy; implementation lands in a separate build PR per the [mini-PRD](../contribute/mini-prds/docx-ingest-support.md).
**Decision-makers:** Kevin Keller (maintainer)
**Affected components:** `api/` (`pipeline/`, `ingest`, tests), `api` + `ingest-worker` container images
**Related:** [ADR 0006 — Document pipeline](0006-document-pipeline-architecture.md), [DE-332 — Text/markdown ingest](../PRD.md#9-deferred-enhancements-and-identified-future-work), [Mini-PRD — DOCX ingest support](../contribute/mini-prds/docx-ingest-support.md), [PRD §3 — Knowledge Bases](../PRD.md#3-capability-specifications), `api/app/citation/verification.py`

---

## Context

The ingest pipeline is PDF-only. `api/app/pipeline/ingest.py:155` gates on `is_pdf_mime` (`api/app/pipeline/parsers.py:134`); a non-PDF upload is marked `ingestion_status='failed'` with `ingestion_error='unsupported_type'` before any parser runs. DE-332 proposes the trivial text/markdown branch; DOCX is the heavier cousin this ADR addresses.

DOCX matters because it is the format legal teams *negotiate* in — the markup (tracked changes, comments, footnotes) is the signal, not noise. Three constraints shape the decision:

1. **The offset-fidelity contract (ADR 0006).** Every chunk must satisfy `canonical_text[char_offset_start:char_offset_end] == chunk.content`, and `documents.normalized_content` is coupled to that canonical text at write time (`ingest.py:318`) so the Citation Engine re-reads byte-for-byte. Any DOCX reader must yield a deterministic canonical character stream.
2. **DOCX has no fixed pagination.** The PDF "page" anchor has no DOCX analogue; anchoring must be char-offset-based.
3. **Redline fidelity.** Insertions, deletions, comments, and footnotes must be retained — and citable — not silently flattened.

Candidates considered:

| Option | Reads redlines | Reads comments | Char-precise canonical | New dep | Notes |
|---|---|---|---|---|---|
| **A. Pandoc** (`--track-changes=all`) | ✅ ins/del + author/date | ✅ (one #9833 gap) | ✅ (flat Markdown string) | Pandoc binary (GPLv2+) | Footnotes → `[^1]`; tables grid/lossy |
| B. python-mammoth | ❌ dropped | ❌ dropped | text only | mammoth (BSD) | lavern's path; unfit for redline review |
| C. OOXML-direct (`zipfile`+`lxml`) | ✅ w:ins/w:del | ✅ comments.xml | ✅ | `lxml` (already transitive) | MikeOSS's approach; most code |
| D. Docling DOCX | partial | ❌ | ❌ not char-precise | (already present) | Same offset problem PyMuPDF solved for PDF |
| E. LibreOffice → PDF → existing pipeline | flattened | ❌ | ✅ (via PyMuPDF) | libreoffice | Loses author/date; heavy; "accept all" destroys the redline |

## Decision

### 1. Pandoc is the primary reader; its Markdown is the canonical text.

`parse_docx()` runs **one** `pandoc -f docx -t markdown --track-changes=all --wrap=none --markdown-headings=atx --sandbox` pass. The Markdown output is the canonical character stream the existing `chunk_document` slices — the same role PyMuPDF's text plays for PDF in ADR 0006. The offset contract holds trivially because the canonical text is a deterministic string and the chunker owns the offsets.

#### Why Pandoc over OOXML-direct (C)

C is the most complete and is proven tractable (MikeOSS), but it means hand-writing the entire body-text walker (paragraphs, tables, lists, footnote resolution) before any of the legal-markup work begins. Pandoc gives that body text — with footnotes resolved to `[^1]` and tracked changes already parsed into spans — out of the box, mature and tested. We adopt C only for the narrow case Pandoc is documented to miss (Decision 3). This is the same "use the mature tool for the canonical stream, reconcile the gap" shape as ADR 0006 (PyMuPDF primary, not a hand-rolled extractor).

#### Why Pandoc over python-mammoth (B)

Mammoth drops tracked changes and comments by design — fatal for redline review (this is lavern's limitation).

#### Why Pandoc over Docling-DOCX (D)

Docling's output is not character-precise against the source — the exact reason ADR 0006 drives the chunker off PyMuPDF, not Docling, for PDF. The same logic rejects Docling as the DOCX canonical source.

#### Why Pandoc over LibreOffice-to-PDF (E)

Converting DOCX→PDF and reusing the PDF pipeline forces "accept all changes," destroying the redline and the author/date provenance that is the whole point. It also adds a far heavier dependency than a single Pandoc binary.

### 2. Redline policy: retain the tracked changes and cite accordingly.

From the single `--track-changes=all` pass:

- **`canonical_text` / `normalized_content`** = the *changes-accepted* final text, reconstructed by keeping insertions and dropping deletions. Validated in the Phase-0 spike to be byte-identical to a separate `--track-changes=accept` pass. This is the operative text citations verify against.
- **revision layer** → `documents.structured_content` (JSONB, reused — no migration): each insertion / deletion / comment with `text`, `author`, `date`, and a char anchor into `canonical_text`.
- **deletions and comments are also emitted as separately-citable chunks**, provenance-tagged in `metadata_json`, so a citation can land on removed or commented text and report "deleted/flagged by X on date Y."

`parser="pandoc"`, `parser_version=f"pandoc={version}"`, `page_count=1`, `was_ocrd=False` — mirroring the synthetic `ParsedDocument` at `api/app/autonomous/guard.py:588`.

### 3. OOXML-direct is a fallback, not a parallel parser.

Pandoc reads Word comments (validated by round-trip), but is documented to drop a comment anchored to an *unaccepted insertion* ([#9833](https://github.com/jgm/pandoc/issues/9833)) — common in live redlines. A small `api/app/pipeline/docx_ooxml.py` (`zipfile` + `lxml`, already a transitive dep) recovers **only** those comments by reading `comments.xml`. It does not re-extract body text. We borrow MikeOSS's OOXML-direct *idea*; we do not copy its code (AGPL-3.0 — incompatible with Apache-2.0).

### 4. Determinism via version pinning.

Pandoc output is byte-identical for a fixed input on a fixed version (spike-confirmed) but the manual makes no cross-version guarantee. We pin the exact Pandoc version in the `api`/`ingest-worker` images and record it in `parser_version` — the field exists precisely for re-ingest-on-drift decisions (`parsers.py` docstring).

### 5. Untrusted-input safety.

`.docx` is attacker-controlled. Pandoc runs as a **separate subprocess** with `--sandbox` (restricts IO), a wall-clock timeout, and an upload-size guard. Failures map to `parse_failed`; the worker never hangs or crashes on a malformed file.

### 6. License posture: Pandoc is GPLv2+, invoked at arm's length.

Pandoc is GPL-2.0-or-later. We invoke it as a **separate executable via subprocess** — never linked or imported. Under the GPL, calling an independent program at arm's length (fork/exec/pipe, like calling `grep`) is mere aggregation; the GPL does not extend to the Apache-2.0 calling code. This is **cleaner** than ADR 0006's PyMuPDF posture (PyMuPDF is AGPL and *imported as a library*, handled via the network-service boundary in PRD §7.2). Pandoc, as a separate process, raises no such linking question. The posture is documented alongside the PyMuPDF rationale in PRD §7.2.

## Consequences

### Positive

- Offset-fidelity contract holds unchanged; the Citation Engine needs no modification.
- Tracked changes, comments (bar #9833), and footnotes are retained with author/date — a capability the comparable OSS stacks drop.
- One `all` pass yields canonical text + revision layer (spike-validated reconstruction).
- No DB migration (reuses `structured_content` + `metadata_json`); no new routes.
- Pandoc is a single mature binary invoked at arm's length — lighter and license-cleaner than the alternatives.

### Negative

- A new system dependency (Pandoc) in two images — the decision this ADR asks the maintainer to accept. Mitigated by in-repo precedent (`web/` ships `pypandoc`).
- Tables with merged/nested cells degrade to grid/linearised text (a Markdown limitation).
- The #9833 comment-on-insertion gap requires the OOXML fallback; threaded comment replies remain deferred.
- Cross-version Pandoc drift could change output; mitigated by pinning + `parser_version`.

### Neutral

- Section-anchor citations ("§4.2") are deferred — anchoring stays char-offset-based, and the spike found many real contracts carry no Word heading styles, so heading-derived anchors are unreliable as a primary mechanism anyway.

## Companion artifacts

- `api/app/pipeline/parsers.py` — `SUPPORTED_DOCX_MIMES`, `is_docx_mime()`, `parse_docx()`.
- `api/app/pipeline/docx_ooxml.py` — `zipfile`+`lxml` comment fallback (#9833).
- `api/app/pipeline/ingest.py` — extended gate (155) + dispatch branch (192).
- `api/tests/test_pipeline_parsers_docx.py`, `api/tests/test_pipeline_ingest.py` — offset-fidelity + redline/comment/footnote fixtures; the unsupported-type test flips for DOCX.
- `api/Dockerfile` / `docker-compose*.yml` — pinned Pandoc in `api` + `ingest-worker`.
- `docs/api/backend-openapi.yaml`, `docs/PRD.md` (§3 + a new DOCX DE in §9), `HONEST-STATE.md`, `parsers.py` docstring — doc reconciliation.

## Alternatives considered

### python-mammoth as the reader
Rejected: drops tracked changes and comments by design (lavern's limitation). Unfit for redline review.

### OOXML-direct (`zipfile`+`lxml`) for everything
Rejected as the *primary* path: it means hand-writing the full body-text/footnote/table walker before any legal-markup work. Adopted only as the narrow #9833 fallback. (MikeOSS proves it tractable but is AGPL — idea borrowed, code not.)

### Docling DOCX
Rejected: not character-precise against the source — the same reason ADR 0006 drives the PDF chunker off PyMuPDF rather than Docling.

### LibreOffice headless → PDF → existing pipeline
Rejected: "accept all changes" flattens the redline and discards author/date provenance; far heavier dependency than a single Pandoc binary.

### Copy MikeOSS's DOCX reader
Rejected: AGPL-3.0, incompatible with the Apache-2.0 codebase. We reimplement the OOXML-direct idea clean.
