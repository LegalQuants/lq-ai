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
| `unverified` | red | no row, or `verified=false`, or `verification_method='failed'` |

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

Stage 4 cost grows as `n_citations × n_judges`. To prevent runaway
spend on a single message:

```
estimated_usd = n_citations × n_judges × FLAT_PER_JUDGE_USD
if estimated_usd > max_cost_per_message_usd:
    fall back to single-judge Stage 3
```

`FLAT_PER_JUDGE_USD = 0.005` is a deliberately conservative constant
(haiku-tier rates + generous token estimates) so the check errs on
the side of falling back rather than overrunning. M2-E2 (ensemble
calibration pass) replaces it with measured numbers from the
acceptance corpus.

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

The Citation Engine and the Anonymization Layer coexist per Decision
M2-1 (chat/skill content pseudonymized; retrieved source documents
left un-pseudonymized). This means:

- Citations operate on **un-pseudonymized** source text on both
  extraction and verification sides — the Stage 3/4 judge sees the
  real cited content and the real source chunk.
- The model may emit citations that reference real entities (from
  retrieved sources) AND prose that references pseudonyms (from
  pseudonymized chat content). The post-anonymization middleware
  rehydrates pseudonyms; citations need no rehydration step.

M2-D2 ships the integration tests and documents the data flow in
detail. See [docs/security/anonymization.md](security/anonymization.md)
for the corresponding anonymization-side description.

## References

- PRD §3.3 (Citation Engine spec)
- [docs/M2-IMPLEMENTATION-PLAN.md](M2-IMPLEMENTATION-PLAN.md) §M2-C1, §M2-D1
- [docs/db-schema.md](db-schema.md) — `message_citations` table
- [gateway.yaml.example](../gateway.yaml.example) — operator config surface
- [docs/skill-authoring-guide.md](skill-authoring-guide.md) — `ensemble_verification` frontmatter field
