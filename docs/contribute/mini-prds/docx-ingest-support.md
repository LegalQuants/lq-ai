# Mini-PRD: DOCX ingest support (Word documents into the knowledge base)

> **Status:** **Proposed — pending maintainer decision.** Unlike the other entries in this folder, this one is *not yet* "open for contribution": it carries an architectural choice (a second parser branch in the ingest cascade) and a new runtime dependency (Pandoc), both of which are explicit "stop and ask" items per [coding-agent-onboarding §8](../coding-agent-onboarding.md). This document is the artifact for that decision. If the maintainer approves the dependency and the redline policy, it becomes an open mini-PRD plus a companion ADR and a new DE.
> **Effort:** L (vs. the M of its sibling [DE-332](../../PRD.md#9-deferred-enhancements-and-identified-future-work), because of the tracked-changes/comment layer and the new dependency)
> **Contributor profile:** Mid-to-senior Python engineer comfortable with FastAPI, async workers, OOXML/`lxml`, and subprocess handling of untrusted input. Not a "good first issue."
> **Mentor:** Maintainer (Kevin Keller, via PR review)
> **Depends on / relates to:** [ADR 0006 — Document Pipeline Architecture](../../adr/0006-document-pipeline-architecture.md), [DE-332 — Text/markdown ingest-parser support](../../PRD.md#9-deferred-enhancements-and-identified-future-work)

## What this is

Today the ingest pipeline is PDF-only. `api/app/pipeline/ingest.py` gates every upload on `is_pdf_mime` (`api/app/pipeline/parsers.py:134`); anything else is marked `ingestion_status='failed'` with `ingestion_error='unsupported_type'` *before* a parser runs. This mini-PRD proposes a **second parser branch, `parse_docx()`**, that brings `.docx` files into the same `Document` + `DocumentChunk` + Citation-Engine path that PDFs use today — with first-class handling of the features that make Word the format legal teams actually negotiate in: **tracked changes, comments, and footnotes**.

The design deliberately mirrors the existing PDF cascade (ADR 0006): a primary tool produces the canonical character stream that the chunker slices and the Citation Engine re-reads, and a richer structural representation rides alongside in `documents.structured_content`. Concretely:

- **Pandoc** (`--track-changes=all`, run once) produces the Markdown the chunker treats as `canonical_text`, and carries insertions/deletions/comments inline as spans we parse out.
- A small **OOXML pass** (`zipfile` + `lxml`) is a **fallback only** for the comments Pandoc is documented to drop (see "Prior art & the comment question" below). It is not a parallel parser.

The work is well-anchored because the hard part — preserving character-offset fidelity so citations re-verify byte-for-byte — is already solved by the chunker, and the exact `ParsedDocument` shape to build already exists in the autonomous artifact handler (`api/app/autonomous/guard.py:588`, the same construction DE-332 points to).

## Why it matters

PDF is what contracts are *sent* as; `.docx` is what they are *negotiated* in. An in-house team's live working set — the redlined drafts, the clause a partner commented on, the footnoted carve-out — is Word, and the markup *is* the signal. A legal-AI tool that can only read the flattened PDF can tell you what the contract says; it cannot tell you **what changed, who changed it, and what they flagged**, which is most of in-house review.

This is also where LQ.AI's transparency thesis pays off. The two comparable open-source legal stacks read DOCX in ways that quietly lose legal signal (see Prior art). LQ.AI's Citation Engine already verifies a quote against an exact character span (`api/app/citation/verification.py`); extending that guarantee to Word — *including a citation that lands on an inserted clause and reports "inserted by X on date Y"* — is a capability a closed SaaS presents as a black box and the other OSS tools drop on the floor.

## What we'd ship

No new tables (the revision/comment layer reuses the existing `documents.structured_content` JSONB; chunks reuse `metadata_json`). No new routes (upload is the existing `POST /api/v1/files`). The change is a parser branch + a fallback extractor + the gate + tests + docs:

```
api/app/pipeline/
├── parsers.py        # + SUPPORTED_DOCX_MIMES, is_docx_mime(), parse_docx()  [NEW funcs]
├── docx_ooxml.py     # NEW — zipfile+lxml fallback: recover comments Pandoc drops (#9833)
└── ingest.py         # extend the gate (155) + dispatch branch (192) to call parse_docx
api/tests/
├── test_pipeline_parsers_docx.py   # NEW — offset-fidelity + redline/comment/footnote fixtures
└── test_pipeline_ingest.py         # flip: a .docx now SUCCEEDS (was unsupported_type)
docs/
├── adr/0014-docx-ingest-via-pandoc.md     # NEW — the structural decision + alternatives
├── api/backend-openapi.yaml               # accepted-mime documentation for POST /files
├── PRD.md                                 # register DE for DOCX (§9) + §3 format note
└── HONEST-STATE.md                        # DOCX = shipped, with honest caveats
deploy/ + docker-compose*.yml + api/Dockerfile  # pin pandoc in api + ingest-worker images
```

**`parse_docx()` behaviour (the redline policy — needs maintainer sign-off):** one `pandoc --track-changes=all --wrap=none --markdown-headings=atx --sandbox -t markdown` pass, then:

- **`canonical_text` / `normalized_content`** = the *final* (changes-accepted) text, reconstructed from the `all` output by keeping insertions and dropping deletions. This is the operative text citations verify against, and it is byte-identical to a separate `--track-changes=accept` pass (validated in the Phase-0 spike). The Citation Engine's re-read invariant (`chunk.content == normalized_content[char_offset_start:char_offset_end]`, coupled at write time in `ingest.py:318`) holds unchanged.
- **revision layer** (→ `structured_content`) = the parsed insertions, deletions, and comments, each with `text`, `author`, `date`, and a character anchor into `canonical_text`. Deletions and comments are *retained*, not discarded.
- **deletions and comments are also emitted as separately-citable chunks**, tagged with provenance in `metadata_json`, so "what was the original fee?" / "what did the reviewer flag?" are answerable and cite back to author + date. This is the concrete meaning of *retain the tracked changes and cite accordingly*.
- `parser="pandoc"`, `parser_version=f"pandoc={<binary version>}"` (the existing field exists precisely so re-ingest decisions can be made against version drift — see `parsers.py` module docstring), `page_count=1`, `was_ocrd=False`.

## How we'd know it's done

- [ ] `is_docx_mime()` accepts `application/vnd.openxmlformats-officedocument.wordprocessingml.document`; the gate in `ingest.py` admits both PDF and DOCX and still rejects everything else as `unsupported_type`.
- [ ] **Offset-fidelity test passes for DOCX** — the load-bearing contract `canonical_text[c.char_offset_start:c.char_offset_end] == c.content` holds for every chunk on at least three fixture `.docx` files of increasing complexity (mirrors `test_offset_fidelity_against_fixture_pdfs`).
- [ ] A redlined fixture asserts: `canonical_text` equals the changes-accepted text; every insertion and deletion appears in the revision layer with correct `author` + `date`; deletions are independently citable.
- [ ] A commented fixture asserts comments are recovered with `author` + `date` — via Pandoc where it works, via the OOXML fallback for the comment-on-insertion case Pandoc drops ([#9833](https://github.com/jgm/pandoc/issues/9833)).
- [ ] A footnote fixture asserts footnotes survive into `canonical_text`.
- [ ] Pandoc output is pinned and reproducible: same fixture + same pinned `pandoc` version ⇒ byte-identical (the spike confirmed determinism on a fixed version; cross-version drift is mitigated by pinning + `parser_version`).
- [ ] Untrusted-input safety: `parse_docx` runs Pandoc with `--sandbox`, a wall-clock timeout, and a size guard; a malformed/zip-bomb `.docx` fails as `parse_failed`, not a hang or crash. A non-DOCX byte stream with a spoofed mime fails cleanly.
- [ ] `pandoc` is pinned (exact version) in the `api` **and** `ingest-worker` images; the SBOM/justification note is in the ADR.
- [ ] Docs are part of the change: `backend-openapi.yaml` accepted-mimes, the PDF-only statements in the file-upload docs and `parsers.py` docstring, `HONEST-STATE.md`, the new ADR, and the DOCX DE registered in PRD §9.
- [ ] No new DB migration (reuses `structured_content` + `metadata_json`); if that turns out false, the migration is verified on a throwaway `pgvector/pgvector:pg16` container, never host alembic against the dev DB.

## Where to start

1. Read [ADR 0006](../../adr/0006-document-pipeline-architecture.md) — it sets the "PyMuPDF canonical + Docling structured" cascade this mirrors, and the offset-fidelity rationale.
2. Read `api/app/pipeline/parsers.py` (the `ParsedDocument`/`PageSpan` dataclasses, `is_pdf_mime`, the `parse_pdf` cascade) and `api/app/pipeline/chunker.py` (the invariant the Citation Engine depends on).
3. Read `api/app/pipeline/ingest.py:155-196` — the exact gate + `asyncio.to_thread(parse_pdf, …)` dispatch `parse_docx` slots beside.
4. Read `api/app/autonomous/guard.py:588` — the synthetic single-page `ParsedDocument` construction (same shape, the one DE-332 also reuses).
5. Read [DE-332](../../PRD.md#9-deferred-enhancements-and-identified-future-work) — the text/markdown sibling; DOCX is the heavier cousin.
6. Reproduce the Phase-0 spike: `pandoc --track-changes=all --wrap=none --markdown-headings=atx --sandbox -t markdown <file>.docx`; confirm the insertion/deletion/comment span syntax and the accept-reconstruction on your pinned Pandoc version before writing the parser.

## Scope cuts (what's out of scope for this PR)

- **Legacy `.doc` (binary Word 97-2003)** — `.docx` (OOXML) only.
- **OCR / scanned or image-only content** — unchanged from M1; `was_ocrd=False`. (No-text DOCX is out of scope, same posture as PDFs.)
- **Lossless complex tables** — merged/nested cells degrade to grid/linearised text (a Markdown limitation, documented in the ADR). Text is captured and citable; cell-geometry fidelity is not promised.
- **Threaded comment replies** (`commentsExtended.xml` parent/child structure) — the base anchored comment is captured; reply-thread reconstruction is deferred to its own DE.
- **A `.docx`/PDF rendition for the document panel** — this PR is the *ingest/extraction* path (what the LLM and Citation Engine read), not a viewer. Frontend rendering is a separate concern.
- **Section-anchor citations ("§4.2")** — anchoring stays char-offset-based. Deriving section anchors from headings is a nice-to-have deferred to a DE, *and* the spike found many real contracts carry no Word heading styles, so it is unreliable as a primary anchor.

## How this strengthens the project

The capability a closed SaaS demonstrates as a black box, and the two open-source legal stacks drop, LQ.AI would do **in the open and verifiably**: read a Word redline, keep every insertion/deletion/comment with its author and date, and let the existing four-stage Citation Engine prove a quote against the exact source span — including a quote that lands on an inserted clause, reported with its provenance. Every claim above re-verifies against `api/app/pipeline/` and `api/app/citation/`. The bet of the project (PRD §1.3) is that an operator who can read the code trusts the answer; extending that guarantee from "what the contract says" to "what changed and who changed it" is where in-house review actually lives.

## Prior art & the comment question (why Pandoc, honestly)

Two comparable OSS legal stacks were reviewed for how they read DOCX:

- **lavern** (`AnttiHero/lavern`, Apache-2.0) reads via **mammoth**, which **drops tracked changes and comments by design** — collaborative redlines are invisible. Patterns are copyable (permissive), but the reader is unfit for redline review.
- **MikeOSS** (`willchen96/mike`, **AGPL-3.0**) walks `document.xml` directly (JSZip + fast-xml-parser) and handles tracked changes with `w:id`-level precision — but its server *reading* layer uses "accepted view" (drops deletions) and explicitly leaves comments/footnotes "alone," and its **AGPL licence means we cannot copy its code** into Apache-2.0 LQ.AI. We borrow the *idea* (OOXML-direct for what convenience tools miss), reimplemented clean.

On comments specifically — a correction worth recording so the next contributor doesn't repeat it: **Pandoc *does* read Word comments** with `--track-changes=all` (validated by round-trip in the spike), emitting `[body]{.comment-start id author date} … []{.comment-end id}`. An earlier claim that "Pandoc can't read real-file comments" was a measurement error (the test files had an *empty* `comments.xml`). Pandoc's real, documented limitations are narrow: it drops a comment anchored to an *unaccepted insertion* ([#9833](https://github.com/jgm/pandoc/issues/9833)), mishandles some multi-line comments ([#4270](https://github.com/jgm/pandoc/issues/4270)), and doesn't reconstruct reply threads. The `#9833` case is common in live redlines (a reviewer commenting on the very clause being inserted), which is the **sole** reason for the small `zipfile`+`lxml` comment fallback — not a full parallel parser.

**The decision this PRD asks the maintainer to make:** accept **Pandoc** as a new runtime dependency in the `api`/`ingest-worker` images. It is a mature, single binary; `web/` already ships `pypandoc` (`web/pyproject.toml`), so there is in-repo precedent; the alternative (hand-rolled OOXML for everything) is materially more code for the body-text path. Per [§8](../coding-agent-onboarding.md), a new dependency is a maintainer call; this is the call.

## References

- [ADR 0006 — Document Pipeline Architecture](../../adr/0006-document-pipeline-architecture.md)
- [PRD §9 — DE-332 Text/markdown ingest-parser support](../../PRD.md#9-deferred-enhancements-and-identified-future-work) (sibling)
- `api/app/pipeline/parsers.py`, `api/app/pipeline/ingest.py`, `api/app/pipeline/chunker.py`, `api/app/autonomous/guard.py` (the construction to mirror)
- `api/app/citation/verification.py` — the re-read invariant DOCX must preserve
- [coding-agent-onboarding §5–§8](../coding-agent-onboarding.md) — DCO, both-remotes, merge gating, stop-and-ask
- Pandoc: [MANUAL — track-changes](https://pandoc.org/MANUAL.html) · comment limitations [#9833](https://github.com/jgm/pandoc/issues/9833), [#4270](https://github.com/jgm/pandoc/issues/4270)
- Prior art: `AnttiHero/lavern` (Apache-2.0, mammoth), `willchen96/mike` (AGPL-3.0, OOXML-direct)

## Definition of "merged"

The PR is merged when (a) the acceptance checklist is fully checked off; (b) the maintainer has approved **the dependency decision (Pandoc) and the redline policy** recorded in the companion ADR 0014; (c) CI is green including the DOCX offset-fidelity test and the redline/comment/footnote fixtures; and (d) the docs in the same PR (OpenAPI accepted-mimes, HONEST-STATE, PRD DE registration, the PDF-only statements that become stale) are reconciled. Because this touches `api/` (non-authz) the change is self-mergeable after CI per [§6](../coding-agent-onboarding.md) — **except** that the dependency + architectural decision must be maintainer-approved first, which is the entire purpose of this document. Commits carry DCO sign-off and the co-author trailer; the branch is pushed to both `origin` and `tucuxi` and preserved after merge.
