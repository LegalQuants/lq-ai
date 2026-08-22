# ADR 0026 — Document-ingestion parsing: remove the dead Docling integration; defer pluggable ingestion (DE-387)

**Status:** Proposed
**Date:** 2026-08-16
**Owner:** Maintainer team (houfu)
**Origin:** Committee call 2026-08-16 action item — *"Draft ADR question on Docling:
keep, replace, or make OCR pluggable; share for group decision at next meeting."*
Grounded in the preserved research
[`docs/research/2026-08-15-docling-ingestion-research.md`](../research/2026-08-15-docling-ingestion-research.md)
(a five-agent study plus an **executed** Docling 2.120.1 conversion run against the
10 quickstart contracts; receipts co-located).

**Relates to:** ADR [0006](0006-document-pipeline-architecture.md) (the pipeline
that specifies the Docling→PyMuPDF fallback), ADR [0017](0017-docx-ingest-via-pandoc.md)
(reuses the `structured_content` column for DOCX revision payloads), DE-351
(first-run ingestion timeout — root-caused here), DE-271 (the Tika fallback claim
this ADR corrects), and PRD §3.3 (the Citation Engine ingestion contract that
named Docling).

## Context

**Docling has shipped in the api image since May and has never once produced
output.** The call site (`api/app/pipeline/parsers.py`) is written against
Docling **2.x** idioms while `api/pyproject.toml` pins **`docling>=1.16,<2`**;
every invocation raises before conversion, the exception is swallowed by a broad
`except` (working as ADR 0006 designed — occasional Docling flakiness is meant to
fall through to PyMuPDF), and the row silently degrades to PyMuPDF-only. Both the
pin and the mismatched call site were introduced in the same commit (`4f228061`,
2026-05-08) and neither line has changed since — broken from the moment it was
written, ~3 months. Confirmed against the dev corpus: **6/6 rows `docling=fallback`,
zero successes, ever.**

Because Docling runs by default (`lq_ai_docling_enabled` defaults to `True`),
every PDF ingested has paid its cost — a ~696 MB HuggingFace model download
(DE-351's root cause) and **2.91 GB of Docling-exclusive wheels** in the amd64
image, of which **1.88 GB is a CUDA stack** (12 `nvidia-*` packages) for a parser
that runs on no GPU and has parsed nothing. Meanwhile PDF ingestion works: the
whole shipped pipeline (chunking, embedding, retrieval, citation verification,
playbook extraction) operates on PyMuPDF's flat character stream.

The committee raised this on 2026-08-16 and framed the decision as **keep,
replace, or make OCR pluggable**; the research, run in advance, independently
concluded **remove**. This ADR reconciles the two and records the decision — remove
now, defer the pluggable/stronger ingester as DE-387 — for committee ratification.

## Decision drivers

1. **Wrong to ship dead weight.** Three months of a 1.88 GB CUDA stack + a 696 MB
   model download for a code path that has produced output zero times, feeding a
   column no code reads, is exactly the "don't overclaim / don't carry
   unjustified SBOM surface" posture CLAUDE.md and the dependency policy set.
2. **No consumer exists today.** The one named design that would read
   `structured_content` — PRD §3.3's Citation Engine `CitableChunk`
   (bbox/`structural_role`/hierarchy) — shipped in M2 *without any of it*;
   verification runs byte-for-byte on `normalized_content`. M3-C Tabular Review
   uses lexical FTS over PyMuPDF chunks and never touches Docling. No starter
   skill assumes parser structure. (Memo Q1, HIGH/observed.)
3. **OCR/extraction quality is genuinely foundational** (Joel, 2026-08-16): if the
   model doesn't receive the full contract, that is an *input* problem, not a
   hallucination problem. A decision here must not read as "we don't care about
   ingestion quality" — it must leave a clean path to the *best* parser when a
   consumer needs one.
4. **Operators differ** (Houfu / Peter, 2026-08-16): a local-models power user and
   an in-house team scanning image-PDFs want different parsers. One bundled choice
   serves neither well; pluggability serves both.
5. **Reintroduction must stay cheap.** Whatever we do now must not burn the option
   of bringing a strong parser back. (Memo Q3: Docling 2.120.1 already works on our
   document class with the *unmodified* call-site idiom — proven, not inferred.)
6. **Security hygiene.** Docling 1.20.0 carries four HIGH OSV advisories (two XXE,
   EasyOCR Zip Slip, HTML-backend URI) — confirmed against the OSV API. CPU-pinning
   1.x keeps all four in the SBOM; only removal or a ≥2.94.0 upgrade clears them.
7. **License posture is part of the dependency question** (Artur, 2026-08-19): the
   parser we are left with, PyMuPDF, is AGPL-3.0 — carried inside an Apache-2.0
   project on a server-side-only boundary (PRD Appendix B; the AGPL boundary is the
   HTTP API). That boundary is sound, but enterprise operators read copyleft
   anywhere in the dependency tree as a procurement flag, and the alternatives
   survey behind this ADR ranked candidates on weight and capability while using
   license only to *eliminate* — it never asked whether a permissively licensed
   parser should be preferred on its own merits. The question is legitimate and
   unanswered; it does not block the removal, and it should not be lost with it.

## The options

Four options were on the table (the committee's three plus the memo's). Two of
them — **Repair** and **Replace** — hit the same wall: there is no consumer to
serve *today*, so either one spends real effort populating a column nothing reads.

### Option A — Repair (keep Docling, fix the integration)
Fix the call site to the pinned version (or land the #521 bump inside a *fix* PR),
CPU-pin torch/torchvision (2.91 GB → ~0.45 GB, memo Q4a — with the direct-deps
trap), add a real-fixture conversion test, populate `structured_content`.
**Against:** delivers zero improvement to any shipped capability (driver 2); still
carries ~0.45 GB + ~80–110 SBOM packages and the 696 MB model download for an
unread column; CPU-pinning 1.x retains all four advisories (driver 6).

### Option B — Remove (the memo's recommendation)
Drop the dependency and `_run_docling`; keep the `structured_content` column
(all-`null`, no reader → no migration); `@dependabot ignore`; park #521; close
DE-351 at the root; make the doc corrections. Reclaims ~2.9 GB and retires four
HIGH advisories in one move.
**Against, stated honestly:** if a consumer lands soon, we removed and re-add. The
memo answers this: reintroduction is a known-quantity PR (driver 5), and no
roadmap item names a date.

### Option C — Replace (swap Docling for a lighter/better parser)
Two credible targets (memo Q4b): **pymupdf4llm** — headings, tables, multi-column
reading order as markdown for ~45 MB, same Artifex license family we already carry
— the lightweight structure default; or an **OCR route** (Mistral OCR / PaddleOCR-VL)
confined to the scanned-document lane the PRD already defines. Eliminated on
license/weight/capability: marker (OpenRAIL revenue cap), unstructured (a smaller
Docling), pdfplumber/camelot (tables only), Apache Tika (paragraphs, not layout —
and DE-271 overstates it).
**Against:** same as Repair — no consumer today, so a straight swap still feeds an
unread column. Replacement is the *right instance* of Option D, not a standalone move.

### Option D — Make the parser pluggable
Define a small parser/OCR adapter seam behind ADR 0006's ingestion step: ship
**PyMuPDF as the always-present default** (zero added weight, sufficient for
everything shipped), and let an operator opt into a heavier parser
(Docling-2.x-CPU, pymupdf4llm, or an external OCR) by configuration when their
documents or a consumer need it. This is the "fabric / big-tent" answer (driver 4)
and the direct home for driver 3's quality concern — the best OCR becomes
available *without being bundled on everyone*.
**Against:** the adapter interface is net-new work, and with no consumer for
structured output today it is not an immediate deliverable — so it is **deferred as
DE-387**, welcomed but uncommitted, rather than adopted as architecture now.

## Decision

**Remove the dead Docling integration now (Option B). Defer a stronger / pluggable
ingester as a deferred enhancement ([DE-387](../PRD.md#de-387--pluggable-parser--more-powerful-document-ingestion)),
not a commitment made here. Preserve the research in a committed location so DE-387
is actionable.**

Concretely:

1. **Remove now** (Option B) — Docling is broken, unused, expensive, and carries four
   HIGH advisories. This is not a bet against OCR quality; it is stopping the
   shipment of a bundled parser that has never run. **The `structured_content`
   column is retained, not dropped** — ADR 0017 and the proposed DOCX-ingest work
   (`docs/contribute/mini-prds/docx-ingest-support.md`) both write to it via
   Pandoc, independently of Docling; removing Docling removes the *parser*, not the
   sidecar column.
2. **File DE-387 — "pluggable parser / more powerful document ingestion."** This is
   where drivers 3 (foundational OCR) and 4 (operators differ) are answered — a
   parser/OCR adapter seam with PyMuPDF as the always-present default and heavier
   parsers (Docling 2.x-CPU, pymupdf4llm, external OCR) as opt-in adapters. It is a
   **welcomed future enhancement, not a committed architecture**: the seam's design,
   and whether it lives in core `lq-ai` or as an operator-supplied adapter, are for
   DE-387's own design ADR — scoped against a concrete consumer (PRD §3.3's
   structured-chunk design), not "turn a better parser on."
3. **Preserve the research** so DE-387 loses nothing: the full memo and its
   executed-conversion receipts are committed to
   [`docs/research/2026-08-15-docling-ingestion-research.md`](../research/2026-08-15-docling-ingestion-research.md)
   (+ `docs/research/2026-08-15-docling-receipts/`). Docling 2.x is proven to work on
   our corpus with the exact call-site idiom (re-runnable scripts included); the
   CPU-pin recipe and its direct-deps trap; the alternatives survey; and the untested
   multi-column reading-order gap are all there for whoever picks up DE-387.

Repair (Option A) and Replace (Option C) are not chosen as standalone moves — they
resurface as *candidate adapters under DE-387* when a consumer exists.

## Consequences

- **Removal PR** (the drafted bug issue becomes the implementation): drop
  `docling` + `_run_docling`, keep the column, `@dependabot ignore`, park #521,
  close DE-351. Also fix the independently-found `none_as_null` defect
  (`structured_content` stores JSON `null`, not SQL NULL) whichever way the vote
  goes.
- **Doc honesty corrections** (worth making regardless of the vote): `README.md`,
  `docs/HONEST-STATE.md` ("PDF (PyMuPDF/Docling)"), `docs/db-schema.md`
  (`structured_content … M2 reads` — nothing reads it; the impossible
  `parser_version` example), and a Revisions note on ADR 0006 recording that the
  fallback became the only path.
- **DE-271 amended** to soften the Apache Tika fallback claim, name pymupdf4llm, and
  record the ingestion-stack license posture — PyMuPDF's AGPL-3.0 boundary, the
  withdrawal of the Docling-based PyMuPDF-free build (below), and the permissive
  parser candidates DE-387 should evaluate.
- **PRD Appendix C risk 3 loses its named mitigation.** That risk — PyMuPDF's AGPL
  boundary — is mitigated in the record by "a PyMuPDF-free build configuration …
  using only Docling for offsets," a fallback this ADR removes. Two things follow.
  First, honesty: that fallback was never a capability, since Docling has produced
  output zero times; the build configuration described was a plan, so removing it
  corrects the record rather than deleting a working escape hatch. Second, the risk
  is now unmitigated beyond the server-side boundary itself, so **Appendix C risk 3
  is rewritten here to point at DE-387** — the adapter seam is the mechanism by
  which a differently licensed parser becomes reachable — and DE-387 carries a
  license preference so the seam is not rebuilt on AGPL by default (driver 7).
- **Appendix B** keeps its Docling row until the removal PR lands (the dependency is
  still in `api/pyproject.toml` today) but is corrected to state that the
  integration is dead and its removal pending, rather than presenting it as a
  working parser.
- **A new small item** filed for the untested multi-column reading-order risk (a
  PyMuPDF-quality question, independent of Docling).
- **DE-387 filed** ("pluggable parser / more powerful document ingestion") as the
  home for the pluggable seam — welcomed, uncommitted, scoped against a concrete
  consumer, with its own design ADR when picked up. Until then, ingestion is
  PyMuPDF-only by default with no bundled alternative — an honest, lighter image.
- **Research preserved** at `docs/research/2026-08-15-docling-ingestion-research.md`
  (+ receipts) so DE-387 is actionable without re-deriving anything.
- **Security:** four HIGH advisories leave the SBOM; ~2.9 GB leaves the amd64 image.

## Alternatives considered (and why not the standalone versions)

- **Keep + CPU-pin (Option A alone).** Cheapest way to stop the bleeding without
  removal, but it still ships ~0.45 GB + the model download for an unread column
  and retains all four advisories. Pays cost for zero delivered value. Rejected as
  the answer; the CPU-pin recipe is preserved (in the committed research) for
  whoever reintroduces a torch-parser under DE-387.
- **Replace now (Option C alone).** Swapping in pymupdf4llm or an OCR engine today
  feeds the same unread column; it is a candidate adapter under DE-387 once a
  consumer exists, not a standalone move now.
- **Defer everything (no removal).** The memo's Q1 is not ambiguous and nothing is
  left that a named future check would settle; deferring the *removal* just keeps
  paying the cost. (What is legitimately deferred is the *pluggable seam* — DE-387 —
  not the removal.)
- **Adopt pluggable as a committed architecture now (Option D as a decision, not a
  DE).** Considered and set aside: with no consumer for structured output today,
  committing to build the seam now would be building ahead of need. DE-387 keeps it
  welcomed and researched without over-committing scarce contributor time.

## Open questions (for DE-387's design ADR, not this ADR)

1. Does the pluggable seam belong in core `lq-ai` or as an operator-supplied adapter
   (touches the chassis-vs-product question the committee is separately working
   through)?
2. Which consumer scopes it first — PRD §3.3's structured-chunk design is the
   natural candidate.
3. Should a **permissively licensed** parser be preferred as the seam's default, and
   is one capable of character-precise offsets (driver 7)? The alternatives survey
   used license only to eliminate, so `pypdf` (BSD) and `pdfminer.six` (MIT) were
   never evaluated, and the lightweight candidate named in DE-387 (pymupdf4llm) is
   the same AGPL family as the incumbent. Byte-precision for the citation invariant
   is the constraint; the license is the preference.

## Cross-references

- **Preserved research (committed, actionable for DE-387):**
  [`docs/research/2026-08-15-docling-ingestion-research.md`](../research/2026-08-15-docling-ingestion-research.md)
  and `docs/research/2026-08-15-docling-receipts/`.
- **DE-387** (pluggable parser / more powerful ingestion) — the deferred enhancement
  this ADR opens.
- ADR [0006](0006-document-pipeline-architecture.md), [0017](0017-docx-ingest-via-pandoc.md);
  PRD §3.3 (Citation Engine ingestion contract), DE-351 (closed by the removal),
  DE-271 (Tika claim amended per the research; license posture added).
- **License record:** PRD Appendix B (license matrix — the Docling row is corrected
  here, and drops out with the removal PR) and Appendix C risk 3 (the PyMuPDF AGPL
  boundary — its Docling-based mitigation is withdrawn here and repointed at
  DE-387). Raised by Artur, `#lqai`, 2026-08-19.
- **Adjacent ingestion work (a small family, keep coherent):** the DOCX-ingest
  mini-PRD [`docs/contribute/mini-prds/docx-ingest-support.md`](../contribute/mini-prds/docx-ingest-support.md)
  (a Pandoc parser branch that *writes* `structured_content` — a concrete reason
  the column stays; independent of Docling, so unaffected by this removal), DE-332
  (text/markdown ingest), and DE-387 (pluggable PDF parser / OCR). ADR 0006's
  "PyMuPDF canonical + Docling structured" cascade language goes stale on removal
  (the PDF path is PyMuPDF-only again) and its Revisions note should say so.
- Committee minutes 2026-08-16 (lq-ai-community, once published) — the keep/replace/pluggable framing.
