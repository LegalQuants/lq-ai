# ADR 0033 — Document-pipeline honesty, the OCR un-deferral, and a local embedding path

**Status:** Proposed (2026-09-09; opened for comment, not for decision at the 2026-09-13 call)
**Date:** 2026-09-09
**Owner:** Maintainer team (houfu)
**Affected components:** `api/` (ingestion), `gateway/` (embedding alias — security path)
**Related:** [ADR 0029 decisions 1 and 9](0029-definition-of-1.0.md),
[ADR 0026 — parser deferral (DE-387)](0026-document-ingestion-parser-and-docling.md),
[ADR 0008 — embedding model and OpenAI adapter](0008-embedding-model-and-openai-adapter.md),
[ADR 0006 — document pipeline architecture](0006-document-pipeline-architecture.md),
[HONEST-STATE.md](../HONEST-STATE.md)

---

## Context

Scanned-PDF / OCR handling was the **highest-voted candidate on the ballot (6 for 1.0)**. Chat
attachments drew 3, fully-local operation 3. Two of the ballots that endorsed the operator-trust
definition of 1.0 while asking for "a marquee capability" named *document-pipeline* work as that
capability. The downstream fork runs OCR in production today. One comment asked for
"government-grade on-prem."

Against that, the pipeline currently fails **silently** in at least four ways:

- A **scanned PDF** uploads "successfully", produces no extractable text, and never enters
  retrieval context. The user is told it worked.
- An operator with **no embedding provider configured** degrades to FTS-only search with no
  message at upload time (DE-355). Search gets quietly worse.
- A **still-ingesting attachment** has no visible state (#512), so a question asked too early is
  answered from nothing.
- A **provider failure** can surface as an empty HTTP 200 rather than an error (#504, #503).

[ADR 0026](0026-document-ingestion-parser-and-docling.md) removed the dead Docling integration and
**deferred** the pluggable/stronger ingester as DE-387, explicitly leaving open whether the seam
belongs in core or in operator configuration. The survey overturned that deferral's priority — not
its reasoning. This ADR takes up the question ADR 0026 parked, with the vote behind it.

The relationship to [ADR 0029](0029-definition-of-1.0.md) matters. Decision 9 there keeps the
candidates out of the gate but rules that **the honest-labeling duty binds at 1.0**. So tier 1
below is not a new gate row; it is what the operating principle already requires, made concrete.

---

## Decision

### 1. The principle: no silent failure in the document pipeline

**Every ingestion outcome is visible — in chat and on the Knowledge Base.** Concretely:

| Today | At 1.0 |
|---|---|
| Scanned PDF uploads "successfully", never enters context | An explicit `needs_ocr` state on the document |
| No embedding provider → silent FTS-only degradation | An actionable message **at upload time** (DE-355) |
| Still-ingesting attachment has no visible state | Visible ingestion state (#512) |
| Provider failure → empty HTTP 200 | An error (#504, #503) |

This binds at 1.0 under ADR 0029's operating principle. It is the cheapest work in this ADR and
the only part of it that gates the tag.

### 2. OCR in three tiers

Reversing the **priority** of the 2026-08-23 DE-387 / DE-320 deferral, which the survey overturned:

- **T1 — honest flagging.** 1–2 person-days. The `needs_ocr` state from decision 1. **Gate-true**
  under ADR 0029; not a new gate row.
- **T2 — an opt-in scanned-PDF OCR adapter** behind a small parser seam. 5–7 person-days.
  **Default off**; models fetched only when enabled, so the air-gap story and the image size are
  both intact. A champion is confirmed. This is the tier ADR 0029 decision 9 flags as the one
  defensible candidate for admission to the gate as F4 — the committee's call, and the schedule
  is the same either way.
- **T3 — the full pluggable parser** with a structured-output consumer. 12–20 person-days.
  **Post-1.0** unless a champion lands it.

### 3. The seam lives in core; adapters are opt-in

This closes the core-vs-operator question [ADR 0026](0026-document-ingestion-parser-and-docling.md)
left open. The seam is small and in core so that adapters are *possible*; the adapters themselves
are opt-in so that the default install carries neither their weight nor their supply-chain
surface. The fork's repaired OCR lane is the reference implementation — as prior art and a
working target, reviewed on its merits like any contribution.

### 4. A permissive-license parser evaluation, not a swap

The licensing question raised on 2026-08-23 — PyMuPDF is AGPL — becomes a **scoped evaluation** of
a permissively-licensed default parser that can hold character offsets (which the citation engine
requires). This is an evaluation with a written outcome, not a commitment to replace anything.

### 5. A local embedding path — a revision of ADR 0008

The gateway's `embedding` alias gains a **local (Ollama) path**, so an Anthropic-only or
air-gapped operator gets working semantic search instead of silent FTS-only degradation.

This **revises [ADR 0008](0008-embedding-model-and-openai-adapter.md)**, which chose the OpenAI
adapter and rejected local embeddings on three grounds. Two of them still hold and are respected
here; one has changed:

- *Dimension mismatch* (ADR 0008's strongest objection) — **still holds, and constrains the
  design**: the local path must serve a 1536-dimension output, or carry its own migration story.
  `document_chunks.embedding` is `vector(1536)` and re-sizing it is a destructive ALTER. Any
  adapter that cannot meet the dimension is out of scope here.
- *SBOM weight* — **respected**: the path is opt-in and the models are fetched only when enabled,
  so the default install is unchanged.
- *Operator inconsistency* — **this is what changed.** ADR 0008 assumed an operator holding an
  OpenAI key is "overwhelmingly likely." The survey says otherwise for a meaningful slice of the
  membership: fully-local operation drew 3 votes for 1.0, and Anthropic-only installs are real.
  ADR 0008 itself anticipated this — it kept the alias switchable "without changing any
  application code" precisely so a future local adapter could land. This is that adapter.

**This is a `gateway/` change and therefore a security path** under
[CODEOWNERS](../../.github/CODEOWNERS): it routes to security review, and it does not merge on a
single maintainer approval.

---

## Consequences

- **ADR 0026 is amended** in its DE-387 disposition: the deferral's *priority* is reversed and the
  core-vs-operator seam question is answered (decision 3). Its reasoning about removing the dead
  integration stands untouched.
- **ADR 0008 is revised** by decision 5, on the record above rather than by silent extension.
- DE-320, DE-355 and DE-387 status lines are updated; HONEST-STATE's ingest rows change from
  "works" to what actually happens.
- The *Honest Documents* train (ADR 0030) carries this work: the honesty audit first — enumerate
  every silent-failure path and record a baseline count — then T1, T2 and the embedding path.
- The audit's count is published and tracked down. "No silent failure" is a claim that needs a
  number behind it, or it is the same kind of unenforced promise ADR 0029 exists to stop.

## Alternatives considered

- **Admit full OCR (T3) into the 1.0 gate** — rejected: 12–20 person-days of senior work against a
  gate the survey already said is too big for current capacity. T2 gets the operator a working
  scanned PDF; T3 gets the project a better architecture, and only the first is urgent.
- **Keep the DE-387 deferral as-is** — rejected: it was the ballot's top candidate, a champion is
  confirmed, and the honest-flagging tier is required by ADR 0029's operating principle whether or
  not the deferral holds.
- **Put the parser seam in operator configuration rather than core** — rejected: an operator
  cannot configure a seam that does not exist. Core carries the seam; operators carry the
  adapters.
- **Swap PyMuPDF out on license grounds now** — rejected as premature: the citation engine's
  character-offset requirement is a real constraint and no evaluated alternative is in hand.
  Decision 4 makes it an evaluation with an outcome instead of a standing complaint.
- **Ship local embeddings as a default rather than an opt-in path** — rejected: it would re-open
  every objection ADR 0008 raised about SBOM weight and first-run latency, for operators who do
  hold a provider key.

## Explicitly not decided

- **Which OCR engine T2 adapts** — an implementation choice for the champion, against the SBOM bar
  and the air-gap requirement.
- **Whether T3 ever ships** — champion-dependent, post-1.0.
- **The outcome of the permissive-parser evaluation** — that is what the evaluation is for.
- **Whether T2 becomes ADR 0029's F4** — put to the committee in ADR 0029 decision 9.
