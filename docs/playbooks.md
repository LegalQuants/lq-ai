# Playbooks

> A Playbook codifies an organization's standard positions and
> fallback positions on common contract issues. Applied to a contract,
> the executor produces a per-position verdict — matches standard,
> matches a fallback tier, deviates (with a drafted redline), or
> missing — plus the verbatim clause the verdict referenced. Per PRD
> §3.7 / §1.3 (transparency as a founding principle): a playbook is
> visible, forkable work product, not an opaque scoring engine. Every
> position, fallback tier, and redline strategy is readable and
> editable by the attorney who relies on it.

This doc describes the two halves of the Playbook engine that shipped
in M3 Phase A: the **executor** (the LangGraph workflow that runs a
playbook against a contract) and the **Easy Playbook** auto-generation
wizard (the extract → cluster → assemble pipeline that drafts a
playbook from a corpus of prior agreements). It covers the persisted
row shapes, the UI rendering, the five seeded built-ins, the legal-
substance posture, and the known limitations. It pairs with
[docs/citation-engine.md](citation-engine.md) (the Citation Engine is
referenced but, as documented below, is *not yet wired* into the
executor's per-position output).

---

## Scope

The Playbook engine has two entry surfaces that share the `playbooks`
table but run on different substrates:

1. **Executor** *(M3-A2, shipped)* — runs an existing playbook against
   one target document. A four-node LangGraph workflow
   (retrieve → classify → redline → compile) walks each position,
   classifies how the contract compares, drafts redlines for
   deviations, and persists a structured result. Verified end-to-end
   in M3-E1: a built-in `NDA — Mutual` run against a sample NDA
   produced 8 positions with verdicts, confidences, and `matched_text`
   anchored to the contract.

2. **Easy Playbook wizard** *(M3-A6, shipped)* — auto-generates a new
   playbook from a corpus of prior agreements. A three-stage algorithm
   pipeline (extract clauses per document → cluster by issue across the
   corpus → assemble a draft playbook) runs on a dedicated ARQ worker.
   Verified end-to-end in M3-E1: a run over the 5-NDA synthetic corpus
   completed in ~3.2 minutes and produced a valid draft playbook with
   fallback tiers — though with a clustering-quality caveat (see
   [Known limitations](#known-limitations)).

The two surfaces are deliberately asymmetric. The executor is
synchronous-ish (FastAPI `BackgroundTask`, in-process, no
checkpointing); the wizard is fully out-of-band (ARQ queue
`arq:m3a6`). The executor consumes a finished playbook; the wizard
*produces* a draft that a user-attorney must review and save before it
becomes one. Neither surface vets legal substance — that is the
operator's attorney's job (see [Legal-substance
posture](#legal-substance-posture)).

Two PRD §3.7 surfaces are **not** covered here because they are not
yet built on this path: playbook execution *inside Microsoft Word*
(the Word add-in shipped only a deep-link card in v0.3.0 per PRD §3.9 /
DE-287), and Citation-Engine-verified provenance on the executor's
per-position citations (deferred from M3-A2; see [Citations are chunk
references, not verified citations](#citations-are-chunk-references-not-verified-citations-today)).

---

## The executor workflow

The executor builds a LangGraph `StateGraph` in
[`api/app/playbooks/executor.py`](../api/app/playbooks/executor.py) and
runs four nodes sequentially against a shared
`PlaybookExecutionState` TypedDict
([`api/app/playbooks/state.py`](../api/app/playbooks/state.py)). The
node implementations live in
[`api/app/playbooks/nodes.py`](../api/app/playbooks/nodes.py).

```
retrieve → classify → redline → compile → END
```

| Node | What it does | LLM calls |
|---|---|---|
| `retrieve` | For each position, runs Postgres FTS (`websearch_to_tsquery`) over the target document's chunks using the position's `detection_keywords`. Top-4 chunks per position (`RETRIEVAL_TOP_K`). Falls back to the document's first chunks when a position has no keywords or FTS returns no hits. | None (pure SQL). |
| `classify` | One structured-JSON call per position → `{verdict, confidence, matched_fallback_rank, matched_text, cited_chunk_indices, justification}`. Verdict is one of `matches_standard \| matches_fallback \| deviates \| missing`. | N (one per position). |
| `redline` | For `deviates` verdicts only, one structured-JSON call per deviating position → `{old_text, new_text, justification}` drafted per the position's `redline_strategy`. Non-deviating rows pass through unchanged. | One per `deviates` verdict. |
| `compile` | Assembles the per-position results into the `playbook_executions.results` JSONB payload, computes the verdict-count summary, and flips the row to `completed` (or `error` if a prior node set `state["error"]`). Sets `completed_at`. | None. |

### Verdict and confidence

The classifier prompt (`_CLASSIFY_SYSTEM_PROMPT`) instructs the model
to bias toward `low` confidence and toward `missing` on uncertainty —
the documented rationale is that false positives ("this missing clause
matches") do more damage in contract review than false negatives.
Confidence is one of `high` / `medium` / `low`, mapped to the numeric
`0.9` / `0.7` / `0.5` (`_CONFIDENCE_NUMERIC`) — the same scale the M2-C1
paraphrase judge uses, so future telemetry can unify on one
verdict-confidence schema. Unparseable verdicts coerce to `missing`;
unparseable confidence coerces to `low` (`_coerce_verdict`,
`_coerce_confidence`).

### Retrieval is lexical-only

The retrieve node uses lexical FTS over `detection_keywords` only. The
PRD §3.7 sketch ("retrieve the matching clause(s) via hybrid search")
and the `Position` schema's `detection_examples` field both anticipate
embedding-based retrieval, but the M3-A2 executor does **not** run a
per-document embedding search — the keyword path is what shipped. The
node docstring documents this as an accepted M3-A2 scope decision; the
high-signal contract-clause case (counterparty / cap / term / governing
law) works well lexically. `detection_examples` is populated by the
Easy Playbook assembly step and stored on the position, but the
executor does not currently consume it for retrieval.

### Failure handling

Any node may set `state["error"]` to short-circuit later nodes;
`compile_node` checks for it and flips the row to `error`. A gateway
transport or JSON-parse failure inside a `classify` / `redline` call
does **not** crash the graph — `_dispatch_structured_call` returns an
empty dict, which the classifier treats as a low-confidence `missing`
(its "I have nothing to say" failure mode). The executor catches any
uncaught in-graph exception at the `graph.ainvoke` boundary and writes
`status='error'` with a truncated `error` string, so the kick-off
endpoint's poller always sees a terminal state.

### Async execution model

Per the M3-1 architectural decision, the executor runs **in-process**
via a FastAPI `BackgroundTask` (not ARQ). The kick-off endpoint returns
202 immediately; the executor opens its own DB session (the
request-scoped session closes when the handler returns) and walks the
graph out-of-band. The state is **not** checkpointed between nodes
(`langgraph.checkpoint` is deliberately unwired); a mid-flight worker
restart loses the run, and the retry path restarts from the top. The
endpoint docstring notes that operators with restart-survival
requirements can migrate this path to ARQ as a future enhancement — the
executor interface accepts the same shape either way.

The `judge_model` for the classify + redline calls defaults to the
`smart` gateway alias (`DEFAULT_JUDGE_MODEL`). There is no
per-execution model selection today; the docstring flags inheriting it
from `project.minimum_inference_tier` or playbook-level config as a
future enhancement.

## Persisted row shape (executor)

The executor writes to `playbook_executions.results` (JSONB). The
column is pre-allocated by migration 0031; the payload shape is owned
by the executor and stamped with `schema_version: "m3-a2-v1"`. Top
level:

```json
{
  "schema_version": "m3-a2-v1",
  "positions": [ ... per-position results ... ],
  "summary": {"matches_standard": N, "matches_fallback": N,
              "deviates": N, "missing": N}
}
```

Each entry in `positions` (`_PositionResult` in `state.py`):

- `position_id`, `issue`, `severity_if_missing` — denormalized from the
  playbook position.
- `verdict` — one of the four classification verdicts.
- `confidence` — `[0, 1]` numeric (the `0.9/0.7/0.5` mapping).
- `matched_fallback_rank` — `int | null`; populated only when
  `verdict='matches_fallback'`.
- `cited_chunk_ids` — the IDs of the retrieved chunks the classifier
  said supported its verdict. See the limitation below — these are
  chunk references, not Citation-Engine-verified rows.
- `matched_text` — the verbatim contract clause the classifier quoted
  (empty for `missing`).
- `redline` — `{old_text, new_text, justification} | null`; populated
  only for `deviates`.
- `justification` — the classifier's one-or-two-sentence rationale.

The `PlaybookExecution` Pydantic schema
([`api/app/schemas/playbooks.py`](../api/app/schemas/playbooks.py))
deliberately types `results` as a free-form `dict[str, Any] | None`
rather than pinning the per-position shape — the wire-level guarantee
is only "if `status='completed'`, `results` is present; if
`status='error'`, `error` is populated."

## UI rendering (executor)

The execution detail view
(`web/src/routes/lq-ai/playbook-executions/[id]/+page.svelte`) polls
`GET /api/v1/playbook-executions/{id}` until a terminal state, then
renders:

- A **summary card** with the four verdict counts from
  `results.summary`.
- A **positions table** with columns: issue, severity pill, outcome
  pill (the verdict), and a **Citations** count rendered as
  `cited_chunk_ids.length`.
- An expandable **detail row** per position showing: confidence as a
  percentage, the `matched_text` under a "Contract clause" blockquote,
  the justification, the suggested redline (old / new / justification
  blocks) when present, and the cited chunk IDs rendered as raw
  `<code>` chunk-id strings.

Severity- and outcome-filter dropdowns scope the table. There is no
"open in document" or citation-verification affordance on this surface
today — the "Citations" column is a chunk-reference count, not a
verified-citation chip like the M2 chat surface.

## Citations are chunk references, not verified citations (today)

This is the single most important honest-state caveat for the
executor. The PRD §3.7 spec ends step 5 with "compile into a structured
review report **with citations**," and `_PositionResult.cited_chunk_ids`
carries the chunks the classification referenced. But the M2 Citation
Engine cascade ([docs/citation-engine.md](citation-engine.md)) is
**not** run over the executor's output:

- `cited_chunk_ids` is the list of retrieved chunk IDs the classifier
  named in `cited_chunk_indices` — there is no `exact_match` /
  `tolerant_match` / paraphrase-judge verification of `matched_text`
  against the document's `normalized_content`.
- No `message_citations` rows are written by an execution.
- The UI renders a count and the raw chunk IDs, not the
  verified/unverified chip states the chat surface uses.

The `state.py` docstring is explicit that Citation Engine integration
was "deferred from M3-A2 per the task scope; surfaced in M3-A4" — what
surfaced in the M3-A4 UI is the `cited_chunk_ids` display, not Citation
Engine verification. When the M3-E1 verification note says the built-in
NDA run produced "`matched_text` citations anchored to the contract,"
that means the classifier quoted verbatim clause text the retrieval
surfaced — useful and inspectable, but not the same correctness
guarantee the Citation Engine provides for chat. Wiring real
Citation-Engine-backed provenance is tracked alongside the analogous
Tabular Review gap at [PRD §9
DE-309](PRD.md#de-309--tabular-cells-real-citation-engine-backed-provenance-m3-e1-finding-f6-follow-on).

## The Easy Playbook wizard

The wizard auto-drafts a playbook from a corpus of prior agreements.
It is a three-stage algorithm pipeline that runs on the ARQ worker
([`api/app/workers/easy_playbook_worker.py`](../api/app/workers/easy_playbook_worker.py),
job `easy_playbook_generation_job` on queue `arq:m3a6`):

1. **Extract** *(per document)* —
   [`extractor.py`](../api/app/playbooks/easy/extractor.py).
   One structured-JSON LLM call per character-budgeted span
   (`DEFAULT_CHARACTER_BUDGET = 50,000` chars ≈ 12K tokens, with a
   1,500-char overlap between spans for long documents) over the
   document's `normalized_content`. Emits a list of
   `{issue, clause_text, source_offsets}` entries — verbatim clause
   text plus best-effort `[start, end)` offsets (the same half-open
   offset semantics as the M2 Citation Engine). The prompt is a Python
   mirror of `skills/playbook-easy-extract/SKILL.md` — the SKILL.md is
   the human-readable, forkable source of truth; the constant in the
   module must be updated in step when the SKILL.md changes.
   Per-document extraction failures are tolerated: a bad document
   reduces clustering signal but does not kill the run.

2. **Cluster** *(across the corpus)* —
   [`clustering.py`](../api/app/playbooks/easy/clustering.py).
   Groups the union of extracted clauses into one `Cluster` per
   recurring issue. The algorithm is **label-first, embedding-second**:
   clauses are grouped by normalized issue label (lowercase + collapsed
   whitespace), then a single batched embedding call powers two further
   steps:
   - A **centroid-based label-merge pass** unions label groups whose
     member-clause-text centroids exceed
     `DEFAULT_LABEL_MERGE_THRESHOLD = 0.85` cosine similarity. The
     module's long comment documents why the *clause-text* centroid is
     the right signal and the *label string* is not (e.g., "Governing
     Law" / "Forum and Jurisdiction" share no surface tokens but
     describe the same concept).
   - Within each group, the **medoid** (the clause minimizing total
     cosine distance to the rest) becomes `standard_language`; the
     top-`DEFAULT_MAX_FALLBACK_NEIGHBORS = 2` most-distant distinct
     clauses become candidate fallback tiers.
   On embedding failure the step degrades gracefully to a length-based
   modal selection (longest clause wins) and skips the label-merge pass
   — the all-or-nothing embedding posture keeps a single corpus run
   from mixing cosine-ranked and length-ranked clusters.

3. **Assemble** —
   [`assembly.py`](../api/app/playbooks/easy/assembly.py).
   Turns the clusters into a `PlaybookCreate`. Per cluster: one
   "describe this position" LLM call fills `description`,
   `redline_strategy`, and `severity_if_missing` (the prompt biases
   toward `medium` severity); one "why is this acceptable" call per
   fallback tier fills the tier `description`. `detection_keywords` are
   derived deterministically (no LLM) from the issue label plus
   recurring content words, capped at `MAX_KEYWORD_COUNT = 8`;
   `detection_examples` are the modal + neighbor clause texts verbatim.
   Every LLM call has a defensive default so a parse/transport failure
   still yields a structurally valid playbook.

The worker writes the assembled `PlaybookCreate.model_dump(mode="json")`
into `easy_playbook_generations.draft_playbook` and flips the row to
`completed`. Critically: **worker "success" means the pipeline produced
a structurally valid draft — not that the playbook is correct,
complete, or fit for use.** The wizard's Step 3 inline editor is where
the user-attorney validates and edits before saving.

### LLM call posture (both surfaces)

Every executor and wizard LLM call routes through the gateway with
`anonymize=False` — the classifier and extractor need to see the actual
contract text verbatim to verify and quote it. Each call carries an
`lq_ai_purpose` tag (`playbook_executor`, `playbook_easy_extract`,
`playbook_easy_assemble_describe_position`,
`playbook_easy_assemble_describe_tier`) so the inference routing log can
be filtered for per-purpose cost calibration — the same per-purpose
substrate the M2-E2 Citation Engine cost calibration uses.
`temperature` is omitted intentionally: Anthropic Opus 4.x reasoning
models rejected the parameter as of 2026-05, and the gateway only
forwards non-None values to providers.

## Persisted row shape (wizard)

The wizard writes to `easy_playbook_generations` (migration 0035; ORM
in [`api/app/models/playbook.py`](../api/app/models/playbook.py)).
Lifecycle `pending → running → completed | error`:

- `document_ids` — `uuid[]` snapshot of the corpus at request time
  (deliberately not an FK, so a later soft-delete of a source file does
  not cascade-clear the audit row).
- `contract_type` — the family hint passed to the extractor/assembly
  prompts.
- `draft_playbook` — JSONB; the assembled `PlaybookCreate` shape, set
  when `status='completed'`. The wizard's Step 3 binds the inline editor
  to it; the schema types it as free-form `dict[str, Any] | None` and
  the UI re-validates via `PlaybookCreate.model_validate` on render and
  again at save.
- `error_message`, `started_at`, `completed_at` — lifecycle bookkeeping.

The saved playbook itself lands in `playbooks` + `playbook_positions`
(migration 0031) when the user-attorney clicks Save — the wizard POSTs
the (possibly edited) `draft_playbook` to `POST /api/v1/playbooks` like
any other create, so it flows through the same audit trail and
`created_by = caller.id`.

## UI rendering (wizard)

The wizard is a four-step flow in
`web/src/routes/lq-ai/playbooks/easy/+page.svelte`:

1. **Upload** — multi-file PDF dropzone (up to 50 documents per
   generation; recommended 5–20), a free-form `contract_type` field
   with datalist suggestions mirroring the five built-ins, and an
   optional playbook name. Uploads via `POST /files`, polls
   `GET /files/{id}` until every file has a `document_id` (the parse
   pipeline has run), then kicks off `POST /playbooks/easy`.
2. **Generate** — polls `GET /playbooks/easy/{id}` every 5 seconds
   until a terminal state. The progress copy warns it can take up to 10
   minutes for a 10-document corpus (the PRD §3.7 NFR). On `error`,
   surfaces `error_message` and a retry button.
3. **Review** — renders `<PlaybookEditor>` bound to `draft_playbook`.
   Every field is editable; the inline copy reminds the user the
   generated language "is a starting point, not a final answer."
4. **Save** — POSTs to `/playbooks` and shows a success screen.

A `PlaybookDisclaimerBanner` renders on every step (per the M3-A6
Decision F transparency posture). The editor exposes every editable
field precisely because Step 3 *is* the user-attorney's validation
pass — the wizard does not verify legal soundness.

## Built-in playbooks

Five built-ins ship seeded by migration, all at version `1.0.0` with
`created_by IS NULL`:

| Name | `contract_type` | Migration | Source slug |
|---|---|---|---|
| NDA — Mutual | `NDA` | 0032 | `skills/playbooks/nda/` |
| NDA — Unilateral (Discloser-favorable) | `NDA-unilateral` | 0032 | `skills/playbooks/nda-unilateral/` |
| MSA — SaaS (customer-perspective) | `MSA-SaaS` | 0033 | `skills/playbooks/msa-saas/` |
| MSA — Commercial Services (purchase-side) | `MSA-Commercial-Purchase` | 0033 | `skills/playbooks/msa-commercial-purchase/` |
| DPA — GDPR (controller-to-processor) | `DPA-GDPR` | 0033 | `skills/playbooks/dpa-gdpr/` |

The content is **filesystem-canonical**: each built-in is a
`playbook.yaml` under `skills/playbooks/<slug>/`, and the seed
migrations read those YAML files at upgrade time. This is the
transparency commitment in practice — the legal substance of a built-in
is a readable, forkable file in the repo, not a value baked into
migration code. The migrations are idempotent (keyed on
`(name, version)`) and frozen at v1.0.0; future content updates ship as
new migrations that bump the version and insert a fresh row rather than
editing the seed in place.

Built-ins are **immutable through the CRUD surface**: `PATCH` and
`DELETE` on a `created_by IS NULL` playbook return 403, including for
admins. The canonical mutation path is fork-then-edit — create a new
owned playbook (which the operator can edit/delete) rather than
modifying the shipped one. The `POST /api/v1/playbooks` endpoint always
sets `created_by = caller.id`, so the only way to mint a new built-in
is a seed migration.

## Legal-substance posture

Built-in playbooks contain legal substance the maintainer team does
**not** vet. Every built-in's `playbook.yaml` header carries an
explicit disclaimer that is also embedded in the playbook's
`description` field so it surfaces wherever the playbook renders:

> **THIS IS A STARTING POINT, NOT A VETTED TEMPLATE, AND IT IS NOT
> LEGAL ADVICE.** The maintainer team has not reviewed or validated the
> positions, fallback tiers, or redline strategies. They were drafted as
> one reasonable market position to give in-house counsel installing
> LQ.AI a head-start. You — the attorney installing this software — must
> review every position against your organization's standards and
> applicable jurisdiction before relying on this playbook for any client
> work.

The same posture applies to wizard output, doubly so: the assembled
draft is machine-generated from the operator's own prior agreements and
is explicitly intermediate. Generation completion does not mean the
playbook is fit for use — the Step 3 inline editor is where the
operator's attorney validates and corrects before saving. Across both
surfaces the validator is the operator's attorney, never the maintainer
team and never the model.

## Authorization

All endpoints sit behind the router-level active-user gate. Beyond
that:

- **Read** (`GET /playbooks`, `GET /playbooks/{id}`) — admins see
  everything; non-admins see built-ins (`created_by IS NULL`) plus
  their own authored playbooks. Unauthorized access returns **404, not
  403** (no information leakage), matching the files pattern.
- **Mutate** (`PATCH` / `DELETE`) — built-ins are 403 (fork-then-edit);
  non-built-ins require ownership or admin.
- **Execute** (`POST /playbooks/{id}/execute`) — caller must be admin
  OR the playbook's author, must own the target document's parent file,
  and (if `project_id` is supplied) must own the project. For v0.3
  built-ins this means executing a built-in requires admin.
- **Easy generation** (`POST /playbooks/easy`) — caller must own
  *every* document in `document_ids`; cross-user or missing IDs collapse
  into a single 404.
- **Poll** (`GET /playbook-executions/{id}`,
  `GET /playbooks/easy/{id}`) — caller must own the row or be admin.

Every mutating action (`playbook.created`, `playbook.updated`,
`playbook.deleted`, `easy_playbook.generation_started`) writes an audit
row.

## Known limitations

### Easy Playbook clustering over-segments and can miss a designed axis

This is the headline wizard caveat, confirmed in M3-E1 fresh-install
verification and tracked at [PRD §9
DE-308](PRD.md#de-308--easy-playbook-clustering-over-segments-and-can-miss-a-designed-axis-m3-e1-finding-f5).

A run over the 5-NDA synthetic corpus
([docs/quickstart/sample-ndas/](quickstart/sample-ndas/)) completed
cleanly (~3.2 min, valid `draft_playbook` with fallback tiers) but the
clustering quality fell short of the corpus README's target:

- It produced **~20 positions** against the README's expected ~5–10.
- It produced **redundant near-synonym position families** — three
  separate license positions ("No Transfer of Rights" / "No Implied
  License" / "No License Granted"), two jurisdiction positions, three
  confidential-information-definition-family positions — that the
  centroid label-merge pass did not collapse.
- It **missed the "Standard of Care" variant axis** — one of the five
  dimensions the corpus is explicitly designed to vary on — as a
  distinct position.
- It produced eight singleton positions (each appearing in only one
  document) with zero fallback tiers.

The engine is **functional**; this is a tuning follow-on, not a
correctness bug. DE-308 scopes the investigation (why near-synonym
families aren't merged; why "Standard of Care" didn't cluster) and
candidate fixes (a post-clustering merge/dedup pass; a
minimum-document-support threshold for singleton positions). It is the
exact kind of clustering-quality signal the corpus README flags as
file-worthy — and the Step 3 inline editor is the safety net the
quality bar relies on in the meantime.

### Executor citations are not Citation-Engine-verified

Covered in detail above — see [Citations are chunk references, not
verified citations](#citations-are-chunk-references-not-verified-citations-today).
The executor surfaces `cited_chunk_ids` + verbatim `matched_text`, not
the M2 cascade's verified/unverified rows. Tracked alongside the
Tabular Review analog at [PRD §9
DE-309](PRD.md#de-309--tabular-cells-real-citation-engine-backed-provenance-m3-e1-finding-f6-follow-on).

### Retrieval is lexical-only; `detection_examples` is unused by the executor

The PRD §3.7 "hybrid search" framing and the `detection_examples` field
both anticipate embedding-based retrieval, but the M3-A2 executor runs
FTS over `detection_keywords` only. `detection_examples` is populated by
the wizard's assembly step and persisted, but the executor does not
consume it. A position authored with no `detection_keywords` triggers
the defensive "first chunks" fallback, which usually yields a `missing`
verdict.

### No execution checkpointing or restart survival

Per the M3-1 decision, the executor runs in-process via a FastAPI
`BackgroundTask` with no LangGraph checkpointing. A worker restart
mid-execution loses the run; retry restarts from the top. Migrating
this path to ARQ for restart survival is a noted future enhancement.
(The wizard, by contrast, already runs on ARQ — but it also has no
per-stage checkpointing; a mid-run worker cancel marks the row `error`
and the user retries from Step 1.)

### No per-execution model selection or cost cap

The executor hardcodes the `smart` alias for classify + redline and has
no per-execution `max_cost_usd` cap. A "complexity dial" (single
specialist → panel → adversarial) and a per-execution cost cap are
tracked as forward-looking enhancements in PRD §9 (the Lavern prior-art
analysis and the executor-hardening DE).

## References

- **PRD §3.7** (Playbooks spec) — [docs/PRD.md](PRD.md)
- Executor: [`api/app/playbooks/executor.py`](../api/app/playbooks/executor.py),
  [`api/app/playbooks/nodes.py`](../api/app/playbooks/nodes.py),
  [`api/app/playbooks/state.py`](../api/app/playbooks/state.py)
- Easy Playbook pipeline:
  [`api/app/playbooks/easy/extractor.py`](../api/app/playbooks/easy/extractor.py),
  [`api/app/playbooks/easy/clustering.py`](../api/app/playbooks/easy/clustering.py),
  [`api/app/playbooks/easy/assembly.py`](../api/app/playbooks/easy/assembly.py)
- Worker: [`api/app/workers/easy_playbook_worker.py`](../api/app/workers/easy_playbook_worker.py) (queue `arq:m3a6`)
- Endpoints: [`api/app/api/playbooks.py`](../api/app/api/playbooks.py)
- Schemas: [`api/app/schemas/playbooks.py`](../api/app/schemas/playbooks.py)
- ORM: [`api/app/models/playbook.py`](../api/app/models/playbook.py) (migrations 0031–0035)
- Built-in content: `skills/playbooks/{nda,nda-unilateral,msa-saas,msa-commercial-purchase,dpa-gdpr}/playbook.yaml` (seeded by migrations 0032 + 0033)
- Web UI: `web/src/routes/lq-ai/playbooks/easy/+page.svelte` (wizard),
  `web/src/routes/lq-ai/playbook-executions/[id]/+page.svelte` (execution view)
- Test corpus: [docs/quickstart/sample-ndas/README.md](quickstart/sample-ndas/README.md)
- Deferred enhancements: [PRD §9 DE-308](PRD.md#de-308--easy-playbook-clustering-over-segments-and-can-miss-a-designed-axis-m3-e1-finding-f5) (clustering quality), [DE-309](PRD.md#de-309--tabular-cells-real-citation-engine-backed-provenance-m3-e1-finding-f6-follow-on) (Citation-Engine-backed provenance)
- [docs/citation-engine.md](citation-engine.md) — the verification engine the executor does not yet wire in
- [docs/skill-authoring-guide.md](skill-authoring-guide.md) — skill conventions (`skills/playbook-easy-extract/SKILL.md` is the extractor prompt's source of truth)
