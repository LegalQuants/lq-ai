# Citation Engine

> The Citation Engine verifies every model-produced citation against
> its source before rendering — failed citations surface as
> "unverified" rather than as confident-looking wrong text. Per PRD
> §3.3 / §1.3 (transparency as a founding principle): a wrong answer
> the lawyer can see is wrong is dramatically more useful than a wrong
> answer that looks right.

This doc describes the production cascade, the persisted row shape,
the UI rendering states, the configuration surface, and the privacy
implications of the ensemble stage. It pairs with
[docs/security/anonymization.md](security/anonymization.md) (the
integration boundary lives in §[Integration with Anonymization](#integration-with-anonymization)).

---

## Scope

"Citation checking" can mean three different things. M2 ships the first;
the other two are tracked as M3–M4 work in PRD §9.

1. **KB-quote accuracy** *(this engine, shipped in M2)* — when the
   chat surfaces information retrieved from the operator's knowledge
   base, the engine verifies that the model's quote and the meaning
   it draws from that quote are an accurate representation of the
   cited KB document. This is a textual-fidelity question between the
   model's response and a document the operator owns.

2. **Case citation validation** *(not built; tracked at
   [PRD §9 DE-279](PRD.md#de-279--case-citation-validation-bluebook-resolution-via-courtlistener))*
   — given a case citation in Bluebook form (e.g.,
   `Smith v. Jones, 123 U.S. 456 (2020)`), verify it refers to a
   real opinion that resolves through CourtListener / the FreeLaw
   Foundation APIs. Catches fabricated citations. Tucuxi-Inc's prior
   `Legal-Week-Cite-Checker` is the reference implementation.

3. **Case-content accuracy** *(not built; tracked at
   [PRD §9 DE-280](PRD.md#de-280--case-content-accuracy-statement-vs-judicial-opinion))*
   — given a statement the model makes *about* what a case held or
   reasoned, verify the statement is an accurate, non-cherry-picked
   representation of the underlying judicial opinion. Hardest of the
   three; requires fetching the opinion text and a paraphrase-judge
   evaluation calibrated against a reviewed gold set.

The three are architecturally distinct: type 1 operates on KB documents
the operator uploaded; type 2 operates on Bluebook strings against
external case databases; type 3 operates on summary statements against
fetched opinion full text. Mixing them under one roof would be a
category error. This document covers type 1 only; references to "the
Citation Engine" elsewhere in the codebase also mean type 1 unless
explicitly qualified.

---

## Cascade

Each citation the model emits (a `"<quote>" (Source: [N])` pair)
becomes a `CitationCandidate` and runs through staged verification.
The first stage to verify wins; the persisted method names the stage.
Misses propagate to the next stage. A row that misses *every* stage
is not persisted — its absence is the unverified signal the M2-C2 UI
consumes.

| Stage | Method (DB) | Description | Cost |
|---|---|---|---|
| 1 | `exact_match` | Byte-for-byte equality of `source_text` against `documents.normalized_content[offset_start:offset_end]`. | Free (pure Python). |
| 2 | `tolerant_match` | After normalizing both sides (whitespace, smart quotes, OCR confusions when `was_ocrd=true`), `rapidfuzz.fuzz.ratio ≥ 95`. | Free (pure Python). |
| 3 | `paraphrase_judge` | LLM judge call through the gateway. Returns `yes` / `partial` / `no` with `high` / `medium` / `low` confidence (mapped to 0.90 / 0.70 / 0.50). `partial=true` persists to flag "source partially supports the claim." | One judge call per citation. |
| 4 | `ensemble_strict` / `ensemble_majority` | The paraphrase judge runs in parallel across N models (configured in `gateway.yaml`). Replaces Stage 3 when activated. Aggregation rule decides whether disagreement misses or majority wins. | N judge calls per citation (pre-flight budget check enforces a per-message cap). |

Stage 3 vs Stage 4 is exclusive: when ensemble is activated, Stage 3
does not run as a pre-flight. The cascade goes 1 → 2 → 4 (per M2-D1
decision B; the single-judge stage would be redundant with N parallel
judges already in flight).

## Persisted row shape

The `message_citations` table mirrors the result of whatever stage
verified the citation. See [docs/db-schema.md](db-schema.md) for the
column list; the citation-relevant columns are:

- `verification_method` — the stage that verified (string enum).
- `verification_confidence` — `[0, 1]`, per-stage scale.
- `partial` — Stage 3+ flag for "source partially supports."
- `tier_envelope` — Stage 4 only; the maximum (weakest) inference tier
  across the judge models that ran (1-5 per PRD §1.5.2).

Stages 1-2 always emit `partial=false` and `tier_envelope=null`.

## UI rendering (M2-C2 + M2-D1)

The M2-C2 chat surface renders citations as inline chips and a
sidecar list, with four visual states:

| State | Color | When |
|---|---|---|
| `verified-exact` | green | `verification_method='exact_match'` |
| `verified-tolerant` | green | `verification_method='tolerant_match'` |
| `verified-paraphrase` | yellow | `verification_method` in (`paraphrase_judge`, `llm_judge`, `ensemble_strict`, `ensemble_majority`) |
| `unverified` | grey (greyed text + `[unverified]` tag; dotted grey inline underline) | no row, or `verified=false`, or `verification_method='failed'` |

Per M2-D1 Decision F, Stage 4 ensemble methods render as
`verified-paraphrase` (yellow). The tooltip varies by method:

- `paraphrase_judge` → "Verified by judge ({confidence}): the source supports this claim."
- `ensemble_strict` → "Verified by ensemble ({confidence}): all judges agreed."
- `ensemble_strict` + `partial=true` → "...all judges agreed, but the source partially supports this claim."
- `ensemble_majority` → "Verified by ensemble ({confidence}): majority of judges verified."
- `ensemble_majority` + `partial=true` → "...majority of judges verified, but some disagreed."

The fifth state (`system-error`) was deferred from M2-C2 per Decision H
and is reserved in the type union for forward compatibility.

## Activation (Stage 4 only)

Stages 1-3 always run on every citation. Stage 4 is opt-in. Three
independent signals can activate it — the api/ ORs across all three:

1. **Skill frontmatter** — `lq_ai.ensemble_verification: true` on
   a skill applied to the message.
2. **Project flag** — `projects.ensemble_verification = true` on
   the chat's parent project.
3. **Deployment default** — `gateway.yaml`'s
   `citation_engine.ensemble_verification.default_enabled: true`.

When activated AND the per-message cost-budget pre-flight passes,
the cascade routes to Stage 4. When the cost estimate exceeds the
configured cap (`max_cost_per_message_usd`), the cascade falls back
to Stage 3 with a `chat_message_ensemble_budget_fallback` warning
logged — the operator's budget setting is a hard cap, not advisory.

4. **Tabular per-column** — a fourth activation path, on the Tabular
   Review surface (post-v0.4.0, #127). A `table`-mode column's
   `ensemble_verification` flag (resolved column > skill snapshot >
   deployment default) runs one Stage-4 ensemble pass per cell over the
   cell's cited chunks, persisting `verification_method` on the cell.
   Unlike the chat path, the tabular path has **no** per-cell mid-run
   cost ceiling (the pre-flight preview is the guard; [DE-331]). See
   [docs/tabular-review.md](tabular-review.md#per-column-ensemble-verification-post-v040-127).

## Configuration

The api/ pulls Stage 3 and Stage 4 config from the gateway over
`GET /v1/citation-engine/config` at startup and caches it for the
process lifetime. Operator-facing knobs:

```yaml
citation_engine:
  judge_model: fast   # Stage 3 judge alias (default 'fast')

  ensemble_verification:
    default_enabled: false
    judge_models: []                  # empty disables Stage 4
    aggregation_rule: strict           # strict | majority
    max_cost_per_message_usd: 0.05
```

`judge_models` accepts gateway aliases (`fast`, `smart`, `budget`) or
fully-qualified `provider/model` strings. The gateway computes the
envelope tier server-side (max `routed_inference_tier` across the
list) and surfaces it on the config endpoint response so the api/
can persist it on each citation row without doing its own alias
resolution.

## Cost-budget pre-flight

Stage 4 cost grows as `n_citations × Σ(per-judge cost)`. To prevent
runaway spend on a single message:

```
per_judge_costs = [estimate_judge_call_cost_usd(db, model)
                   for model in config.judge_models]
estimated_usd = n_citations × sum(per_judge_costs)
if estimated_usd > max_cost_per_message_usd:
    fall back to single-judge Stage 3
```

### Per-judge calibration (M2-E2)

`estimate_judge_call_cost_usd(db, judge_model)` in
[`api/app/citation/cost.py`](../api/app/citation/cost.py) computes a
rolling average over the most recent 100 (or last 30 days, whichever
is smaller) `inference_routing_log` rows where
`routed_model = judge_model` AND `purpose = 'judge_paraphrase'`. The
`purpose` column was added in migration 0029 and is set by the api/
side via the `lq_ai_purpose` request envelope field — the gateway
strips it from the outbound provider body and writes it to the
routing-log row.

Why per-model: judge costs span order-of-magnitude differences
(`claude-haiku-4-5` ~$0.001/call vs `claude-opus-4-7` ~$0.04/call).
A single flat constant of 0.005 is 5× too conservative for haiku
ensembles (causing unnecessary fallbacks) and 8× too permissive for
opus ensembles (risking runaway spend).

### Cold-start fallback

Models with fewer than 5 recent judge calls fall back to
`DEFAULT_PER_JUDGE_USD = 0.005` — the same conservative constant
shipped in M2-D1. Cold-start deployments see the conservative budget
posture until enough judge traffic accumulates to calibrate; that
matches the safety story of "err toward fallback rather than runaway
spend".

### Cache

The estimator caches per-model results for 300 seconds (5 min)
in-process. A 3-model ensemble pre-flight therefore costs at most 3
DB queries every 5 minutes; subsequent pre-flights in the same
window cost zero DB queries. Per-process; multi-worker deployments
accept the per-worker drift as benign noise.

### What's NOT calibrated (yet)

Two Citation Engine constants remain at conservative pre-calibration
defaults — they need empirical workload data the project hasn't
collected yet:

- `TOLERANT_MATCH_THRESHOLD = 95.0` (Stage 2 rapidfuzz threshold).
- `aggregation_rule: strict` (Stage 4 ensemble default in
  `gateway.yaml.example`).

Both are tracked at [PRD §9 DE-281](PRD.md#de-281--citation-engine-operational-telemetry-calibration-tolerant_match_threshold--aggregation_rule)
for operational-telemetry calibration once production deployments
accumulate sufficient stage-pass distribution and disagreement-rate
data. The M2-E2 per-purpose routing-log substrate generalizes
cleanly to that future work.

## Privacy implications of Stage 4

Each judge dispatch is an inference request that routes through the
gateway like any other — subject to the same tier-routing,
anonymization middleware, and audit-logging. When `judge_models`
spans multiple provider tiers, the verification's privacy envelope
is the *weakest* (highest-numbered) tier in the set. The
`message_citations.tier_envelope` column persists this per row so
operators can audit which chats had citations sent to weaker tiers.

The privacy envelope is computed eagerly at config-load time
(server-side, using the primary target of each judge alias). Fallback
targets could route weaker at runtime; those are visible through the
per-judge `inference_routing_log` rows linked by `message_id`.

## Integration with Anonymization

The Citation Engine and the Anonymization Layer coexist per **Decision
M2-1**: chat/skill content gets pseudonymized; retrieved source
documents stay un-pseudonymized. The integration boundary is the
`lq_ai_skip_anonymization` field on `ChatCompletionMessage`.

### Data flow (M2-D2)

A chat send with both layers active follows this path:

1. **User turn arrives at the api/** — `"What did Acme Corp agree to?"`.
2. **api/ retrieves source chunks** via `hybrid_search` against the
   chat's project KBs — chunks contain original entities verbatim
   (`"Acme Corp agreed to ..."`).
3. **api/ assembles the gateway request** — prepends the retrieval
   chunks as a `system` message **with `lq_ai_skip_anonymization=True`**.
   The user turn becomes a `user` message with no skip flag.
4. **Gateway pre-anonymization middleware** runs:
   - User turn → `"What did COMPANY_0001 agree to?"` (pseudonymized)
   - Retrieval system message → unchanged (skip flag honored)
   - Per-request `PseudonymMapper` carries the `COMPANY_0001 → Acme Corp`
     mapping
5. **Provider sees** pseudonymized user turn + un-pseudonymized
   retrieval — the model has the original source quotes available
   for citation grounding and can reason about `COMPANY_0001` as the
   subject of the user's question.
6. **Provider responds** with `'The agreement says "Acme Corp shall
   not compete..." (Source: [1]). COMPANY_0001 is bound for 2
   years.'` — quoting the retrieval verbatim, referring to the
   pseudonym for the entity from the user turn.
7. **Gateway post-anonymization middleware** rehydrates:
   `"COMPANY_0001"` → `"Acme Corp"`. The cited quote (already real)
   is unchanged.
8. **api/ persist_citations** extracts `"Acme Corp shall not
   compete..." (Source: [1])` from the rehydrated text; Stage 1
   verifies the quote byte-for-byte against
   `documents.normalized_content` (un-pseudonymized). Verified
   citation row lands.

### What the provider sees vs what the user sees

| Layer | Provider sees | User sees |
|---|---|---|
| User turn | `COMPANY_0001` (pseudonymized) | `Acme Corp` (original; user typed it) |
| Retrieved chunks | `Acme Corp` (un-pseudonymized, skip flag) | n/a (retrieval is gateway-internal) |
| Assistant prose with pseudonyms | `COMPANY_0001 is bound` | `Acme Corp is bound` (rehydrated) |
| Assistant citation quote | `"Acme Corp shall not compete..."` (real, came from un-pseudonymized retrieval) | `"Acme Corp shall not compete..."` (identical; no rehydration needed) |

### Why this matters for citation correctness

If the retrieval were pseudonymized too (the Option A path captured
as [DE-269](PRD.md#de-269--anonymization-option-a-pseudonymize-source-documents-too)):

- The model would see `"PERSON_0001 agreed to pay COMPANY_0001 ..."`
  in the retrieved chunk.
- The model would emit citations quoting pseudonyms: `'"PERSON_0001
  agreed to pay COMPANY_0001 ..." (Source: [1])'`.
- The post-rehydrator would have to fix the cited quote before
  citation extraction sees it; the cascade would then verify the
  rehydrated quote against the un-pseudonymized
  `documents.normalized_content`. End-to-end this works, but it
  adds a translation hop on the citation correctness path and makes
  the audit trail noisier (everything is pseudonymized; the
  `anonymization_applied` audit field stops carrying granular
  signal).

Decision M2-1 keeps the citation correctness path direct: the model
sees real source quotes, emits real source quotes, and the verifier
matches them against un-pseudonymized content with no translation
hop.

### Privileged chats (M2-B3)

When the chat's project is `privileged: true`, the gateway
pre-middleware **skips the entire request** (not just the retrieval
message) — privileged content rides un-pseudonymized end-to-end.
The skip flag is irrelevant in this case; everything bypasses
pseudonymization. M2-D3 covers privileged-project handling in
detail.

### Tests pinning the integration

- **api-side**: `tests/test_chat_citations.py::test_chat_send_marks_retrieval_context_skip_anonymization` pins that the api/ sets the skip flag on the retrieval system message and only on that message.
- **gateway-side**: `tests/anonymization/test_middleware.py::test_pre_anonymize_skips_message_marked_skip_anonymization` pins that the middleware honors the flag.
- **gateway-side**: `tests/test_openai_adapter.py::test_chat_completion_strips_per_message_lq_ai_skip_anonymization` pins that the field is stripped before reaching OpenAI (which 400s on unknown body fields).

See [docs/security/anonymization.md](security/anonymization.md) for
the anonymization-layer-side description of the same integration.

## Known limitations (M2-D4)

The Citation Engine is correctness-first but ships with several
known limitations the M2-D4 sweep documented explicitly. Each
limitation has either a regression test pinning current behavior or
a deferred-enhancement entry tracking the future fix.

### Chunk-boundary spanning quotes — silently drop today

If a citation's source quote spans the boundary between two adjacent
retrieved chunks (i.e., neither chunk alone contains the full quote),
the extractor's `_locate_in_chunk` returns `None` and the candidate
is dropped silently. The M2-C2 UI renders the absence as the
"unverified" (grey) state.

**Current scope of the bug:** the extractor searches each cited
chunk's `content` for the quote. The verifier (Stages 1–4) reads
against `documents.normalized_content` (which spans all chunks of a
document), but the verifier never sees the candidate because
extraction drops it upstream.

**When this matters:** the model usually picks the chunk containing
the full quote — the retrieval-context block tells it to. The gap
surfaces on adversarial multi-chunk paraphrases or when the model
genuinely needs to cite text that crosses a chunk seam.

**Future fix path:** [DE-277 — Citation extractor: scan full
`documents.normalized_content` when chunk-local search misses](PRD.md#de-277--citation-extractor-fallback-to-document-scan-on-chunk-boundary-miss).
The extractor falls back to scanning the full document text via FK
from the chunk to the doc when `_locate_in_chunk` misses; same
fuzzy-vs-exact two-stage logic against the full document. Pinned by
`api/tests/citation/test_edge_cases.py::test_chunk_boundary_spanning_citation_does_not_extract_today`
which flips its assertion when DE-277 lands.

### Deleted source documents — render as "unverified," not "system error"

If a chat message references a source document that gets deleted
between retrieval and citation persistence (rare but possible —
user-driven document deletion during an in-flight request), the
verifier's batch-load returns no document for that ID and the
defensive `if doc is None: continue` guard in `_persist_message_citations`
skips the candidate silently. No row is persisted; the M2-C2 UI
renders the marker as "unverified" (grey).

**The distinction the spec drew:** M2-D4 references a "system-error
state" — visually distinct from "unverified" (grey) — but the M2-C2
Decision H deferred the dedicated state-5 rendering to a future
task. Implementing state-5 means: persist a row with
`verification_method='failed'` + a details field flagging "source
deleted"; UI extends `CitationRenderState` with a fifth value;
chip color + tooltip differ from the existing unverified state.

**Future fix path:** part of [DE-275 — Embed M2 citations in
chat-message envelope](PRD.md#de-275--embed-m2-citations-in-chat-message-envelope)
(state-5 system-error rendering is grouped with the envelope
enhancement work). Pinned by
`api/tests/citation/test_edge_cases.py::test_deleted_source_file_handled_gracefully_no_row_written`.

### Empty source documents — fall through to unverified gracefully

A document with empty `normalized_content` and a citation referencing
positive offsets into it triggers the `_slice_in_range` guard in
`verify_exact_match` / `verify_tolerant_match`; both return MISS
without crashing. Stage 3 / 4 only run if `gateway` is supplied;
either way the candidate falls through to "unverified." This is
defensive-by-design rather than a future-fix item — there is nothing
to verify against an empty document.

Pinned by:

- `api/tests/citation/test_edge_cases.py::test_verify_exact_match_against_empty_normalized_content`
- `api/tests/citation/test_edge_cases.py::test_verify_cascade_against_empty_normalized_content_no_crash`

### Cross-document citations — supported

A message citing multiple distinct source documents produces one
verified row per cited document. The persistence loop batch-loads
all referenced documents in one SELECT then verifies each candidate
against its own document. Pinned by
`api/tests/citation/test_edge_cases.py::test_cross_document_citations_persist_one_row_per_verified_citation`.

## References

- PRD §3.3 (Citation Engine spec)
- [docs/M2-IMPLEMENTATION-PLAN.md](M2-IMPLEMENTATION-PLAN.md) §M2-C1, §M2-D1, §M2-D4
- [docs/db-schema.md](db-schema.md) — `message_citations` table
- [gateway.yaml.example](../gateway.yaml.example) — operator config surface
- [docs/skill-authoring-guide.md](skill-authoring-guide.md) — `ensemble_verification` frontmatter field
