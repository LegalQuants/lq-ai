# Research — Docling and the document-ingestion parser: what it was for, and what should replace it

**Preserved research, committed to inform [DE-387](../PRD.md#de-387--pluggable-parser--more-powerful-document-ingestion) and any future document-ingestion work.**

**Status:** research complete, 2026-08-15, against canon `869e0cc7`. The decision it fed
was taken by the committee (2026-08-16): **remove the dead Docling integration; defer a
stronger/pluggable ingester as DE-387** — recorded in ADR
[0026](../adr/0026-document-ingestion-parser-and-docling.md). This document exists so that
whoever picks up DE-387 does not have to re-derive any of the below: the design intent, the
sufficiency of PyMuPDF, the proven Docling-2.x reintroduction path, the CPU-pin recipe, and
the alternatives survey are all here, with the executed-conversion evidence in
[`2026-08-15-docling-receipts/`](2026-08-15-docling-receipts/).

**Method:** five parallel research agents (canon/code reading, external research, OSV
verification) plus an **executed** Docling 2.120.1 conversion run in a throwaway venv against
the 10 quickstart sample contracts — no docs-only inference on the load-bearing question.
Receipts: conversion summary (`q3-conversion-summary.json`), a sample export
(`q3-sample-export-msa-1.md`), the test scripts (`q3-test-script.py`,
`q3-hyperlink-test.py`), and full per-claim findings with observed/inferred labels
(`workflow-findings.json`).

---

## Q1 — What was Docling for? A placeholder, not a specified consumer. **[HIGH, observed]**

"M2 consumption" named a real design that was never built. The one specified consumer is
PRD §3.3's Citation Engine ingestion contract — "Documents are parsed by Docling for
structural understanding" (`PRD.md:449`) feeding a `CitableChunk` schema with `bbox` for
rendering overlays (`PRD.md:458`), `structural_role` (`PRD.md:460`), hierarchy,
"structural-role filtering" in retrieval (`PRD.md:467`), and a render/highlight endpoint
(`PRD.md:503`). §3.3 shipped in M2 **without any of it**: verification runs byte-for-byte
against `documents.normalized_content` substrings (`PRD.md:423-425`), `document_chunks` has
no structural_role/bbox/hierarchy columns, no render endpoint exists, and
`docs/M2-IMPLEMENTATION-PLAN.md` contains zero mentions of Docling or `structured_content`.
ADR 0006's own language downgrades the stash to a hedge: "M2's Citation Engine work (or M2's
RAG retrieval) **may** use it. Storing it now means we don't have to re-run Docling later"
(`adr/0006:254-257`). The tables question resolves decisively: M3-C Tabular Review consumes
lexical FTS over PyMuPDF-derived `document_chunks` (`api/app/tabular/nodes.py:490-503`) and
never touches `structured_content` — its "table" is an *output grid*, not parsed table
structure (`PRD.md:1053-1075`). No starter skill references parser structure; they prompt the
LLM to read clause numbers from text (`skills/msa-review-saas/SKILL.md:92,170`). Two
corroborating details: the pyproject comment justifying the footprint cites "PRD §3 and §7.6"
— §7.6 is Security Disclosure, a dangling anchor (`api/pyproject.toml:86-92` vs `PRD.md:1736`);
and ADR 0017 already reuses `structured_content` for DOCX revision payloads, so even the
column's future is not Docling-specific (`adr/0017:57`).

## Q2 — Is PyMuPDF-only good enough? For everything shipped, demonstrably yes. **[HIGH observed for shipped capabilities; sufficiency-in-general is weaker]**

Every shipped consumer operates on the flat character stream: chunker boundaries key only on
sentence/paragraph regexes (`api/app/pipeline/chunker.py:64-66`), embeddings embed chunk text,
retrieval is pgvector + FTS, citation verification slices `normalized_content`
(`api/app/citation/verification.py:170-215`), playbook extraction reads it flat
(`api/app/playbooks/easy/extractor.py:207`). The citation invariant is *immune to layout
scrambling by construction* — it verifies against the same stream the model saw. What is
demonstrably lost: table cell structure (observed: the corpus's only tables, 2-column
signature blocks, extract row-interleaved — benign) and a latent, **untested** multi-column
reading-order risk — the committed two-column fixture asserts only offset fidelity, never
column order (`api/tests/test_pipeline_parsers.py:218-231`). No recorded complaint exists
anywhere — but this is stated as the weak evidence it is: the 10 sample contracts are
Chrome-rendered single-column Markdown whose own README admits it doesn't test extraction
edge cases; real table-heavy or multi-column contracts have never been exercised on record.

## Q3 — Would switching Docling on improve things? It works — and gate 3 still fails. **[gates 1–2 HIGH, observed; gate 3 HIGH]**

**Gate 1 clears, executed:** Docling 2.120.1 in a throwaway CPU venv converts **10/10** sample
contracts with the call site's *unmodified* idiom (`DocumentStream(name=…)`, `convert(stream)`,
`.document`, `model_dump()`). `json.dumps` on default-mode `model_dump()` succeeded on all 10
plus a purpose-built hyperlink-bearing PDF; the payload round-trips back into `DoclingDocument`
(the M2-reader path). Honest caveat: Docling attached no `hyperlink` field on any input, so
the `AnyUrl` serialization path was never *populated* — unexercised on our document class, not
proven safe in general. **Gate 2 clears:** output quality is genuinely good — correct heading
hierarchy (10–12 `section_header` items per contract), 9/10 documents' tables found with real
cell grids, clean markdown export; 0.3–0.8 s/doc on CPU after warm-up (first call 66 s
including model download). Second caveat: this ran on macOS arm64 against the synthetic clean
corpus, not the amd64 image or messy real-world scans. **Gate 3 fails, and it is the gate that
matters:** per Q1 there is no consumer, so switching it on populates a column nothing reads.
The improvement to any shipped capability is zero regardless of output quality. Turning it on
is not a deliverable; building the consumer is. *(Full run: `q3-conversion-summary.json`; a
sample export: `q3-sample-export-msa-1.md`; the scripts to reproduce: `q3-test-script.py`,
`q3-hyperlink-test.py`.)*

## Q4 — Alternatives. The cost objection largely evaporates; the value question doesn't. **[HIGH, measured, for the CPU pin; HIGH/MEDIUM per option]**

**The overlooked option works and was measured, not estimated:** pinning torch/torchvision to
the PyTorch CPU index (supported by the repo's exact uv 0.12.0) shrinks the Docling-exclusive
payload from **2.91 GB → ~0.45 GB** (−84%, all 12 `nvidia-*` SBOM entries gone), with the
existing 1.x pin byte-for-byte unchanged. One trap, proven by dry-run: `tool.uv.sources`
pinning is ignored for transitive deps — torch/torchvision must also be declared as *direct*
dependencies or the CPU index silently doesn't bite. The same pin is equally necessary and
effective under a 2.x upgrade (2.120.1 defaults to slim; OCR/VLM are opt-in extras; ~444 MB).
Residuals no pin fixes: ~0.45 GB wheels and ~80–110 SBOM packages for a feature nothing reads,
the ~696 MB runtime HF model download (DE-351), and CPU conversion cost on OCR-heavy docs.

**Alternatives** — only two are credible for "structure for legal contracts on CPU,
self-hosted":

| Option | Structure it gives | Marginal cost | Verdict |
|---|---|---|---|
| **pymupdf4llm** | headings, tables, multi-column reading order (markdown) | ~45 MB, 2 pkgs; same Artifex AGPL/commercial license we already carry | **The lightweight default** if structure is ever wanted cheaply |
| **Docling 2.x, CPU-only** | fullest: layout, reading order, TableFormer tables, OCR engines | ~1.5–2 GB incl. models | The high-capability runner-up if TableFormer-grade tables become load-bearing |
| marker | excellent markdown + block tree | Docling-class, GPU-leaning | **Eliminated** — OpenRAIL-M weight license, $5M revenue cap (incompatible with an open-source self-hosted product) |
| unstructured | real structure only via hi_res model stack | 100s of MB + models | Eliminated — a smaller Docling |
| pdfplumber / camelot | tables only, no headings/reading order | small | Complements, not replacements |
| Apache Tika | XHTML paragraphs — text, not layout structure | ~78 MB jar + JVM | Duplicates PyMuPDF; **DE-271's "fall back to Apache Tika" overstates what Tika gives and should be amended** (`PRD.md:2784`) |
| Mistral OCR / PaddleOCR-VL | real markdown structure | $4/1k pages external API, or a GPU-class Paddle stack | Keep confined to the scanned-doc lane the PRD already defines (`PRD.md:234,283`) |

## Security advisories — the claim is CONFIRMED. **[HIGH, observed]**

"Four HIGH advisories cover Docling 1.20.0" is **TRUE**, verified directly against the OSV API:
CVE-2026-31248 (METS XXE, 7.5), CVE-2026-31247 (JATS XXE, 7.5), CVE-2026-44017 (EasyOCR Zip
Slip, fixed 2.91.0), CVE-2026-47214 (HTML backend URI/path handling, 7.1, fixed 2.94.0).
Exactly four unique — a count of 8 would be double-counting PYSEC aliases. Docling 2.120.1 has
**zero** open OSV advisories. Practical exposure while the pass never executed and we feed only
PDFs was minimal — latent SBOM exposure, not an exercised path. Corollary: **CPU-pinning
1.20.0 makes Docling cheap but keeps all four advisories in the SBOM**; only removal or a
≥2.94.0 upgrade clears them.

---

## What this means for whoever picks up DE-387

1. **Reintroduction is proven cheap, not hypothetical.** Docling 2.x works on our document
   class with our exact call-site idiom, serializes, round-trips, and runs sub-second on CPU.
   The receipts are the starting point — re-run `q3-test-script.py` against the current corpus
   to reconfirm.
2. **The CPU-pin recipe is measured and has a trap.** ~84% footprint cut; torch/torchvision
   must be *direct* deps for the index pin to bite. Whoever reintroduces Docling — or any
   torch-dependent parser — starts there.
3. **pymupdf4llm is the middle path** if a consumer wants headings/tables/reading order at
   ~45 MB instead of ~1.5 GB — same license family we already carry.
4. **The real gate is the consumer, not the parser.** PRD §3.3's bbox/`structural_role` design
   is still good and is the natural first consumer; DE-387 should be scoped against a concrete
   consumer, not "turn a better parser on."
5. **A separate, independent gap:** multi-column reading order is untested (the fixture asserts
   offsets, not column order) — a PyMuPDF-quality question, cheap to test, worth its own item.

*Full per-claim citations (file:line and canon section, observed/inferred labels) in
`2026-08-15-docling-receipts/workflow-findings.json`.*
