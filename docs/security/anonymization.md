# Anonymization Layer — operator's guide

> **Purpose.** Document the entity types LQ.AI's Anonymization Layer (PRD §4.7) recognizes by default, the deliberately-disabled defaults, and how to customize the recognizer set for a specific deployment's matter-numbering convention or domain-specific entities.
>
> **Status (2026-05-17).** M2-B3 complete: the gateway middleware now pseudonymizes outbound chat/skill content and rehydrates the response (streaming and non-streaming). M2-D2 wires the retrieval-context skip flag so source chunks reach the provider un-pseudonymized (see [Retrieval-context skip](#retrieval-context-skip-m2-d2) below). M2-B2's custom legal recognizers + Presidio `AnalyzerEngine` configuration remain unchanged; M2-A3's `PseudonymMapper` is the request-scoped substitution table.

---

## What gets pseudonymized

Per the **M2-1 decision** locked at M2 kickoff, anonymization applies only to **chat and skill content** sent to the model. Retrieved source documents stay un-pseudonymized so the model sees intact source quotes for citation grounding and the user-facing retrieval surface continues to render real document text. The skip mechanism is the `lq_ai_skip_anonymization` field on `ChatCompletionMessage`: the api/ marks the retrieval-context system message with `True`; the gateway middleware honors the flag and leaves that message's content alone. See [Retrieval-context skip](#retrieval-context-skip-m2-d2) below for the data flow. The alternative (Option A — pseudonymize the document corpus too) is filed as **[DE-269](../PRD.md#de-269--anonymization-option-a-pseudonymize-source-documents-too)** for future consideration.

## Recognizer set

The gateway's `AnalyzerEngine` runs with this configuration (`gateway/app/anonymization/engine.py`):

### Enabled by default

| Entity type | Source | What it catches | Notes |
|---|---|---|---|
| `PERSON` | Presidio default (spaCy NER) | Names of parties, judges, counsel, witnesses. | The single highest-value detector. |
| `ORGANIZATION` | Presidio default (spaCy NER) | Corporate entities, firms, agencies. | Surfaces under Presidio's `ORG` label internally. |
| `EMAIL_ADDRESS` | Presidio default | Counsel email, party email in correspondence. | Requires a recognized TLD; `.example` test addresses won't match. |
| `PHONE_NUMBER` | Presidio default | Contact numbers in correspondence. | US conventions catch best; international support varies. |
| `US_BANK_NUMBER` | Presidio default | Bank account numbers in settlement statements, escrow docs. | Mapped to the `ACCOUNT_NUMBER` pseudonym domain so the operator's mental model is generic. |
| `LOCATION` | Presidio default (spaCy NER) | Addresses, courthouses, jurisdictions. | Mapped to the `ADDRESS` pseudonym domain. |
| `CASE_NUMBER` | **Custom** — `CaseNumberRecognizer` | Federal/state reporter cites (`Smith v. Jones, 123 F.3d 456 (9th Cir. 2024)`), `In re X` form, docket numbers (`Case No. 1:24-cv-00123`). | Requires structural anchoring; bare case captions intentionally not matched. |
| `MATTER_NUMBER` | **Custom** — `MatterNumberRecognizer` | Alpha-year-sequence (`LQ-2026-0042`), dotted (`2026.0042`). | Deployment-specific; defaults are conservative — extend per the "Customizing" section below. |

### Disabled by default

These recognizers ship in Presidio's default set but produce a high false-positive rate on legal corpus or cover entity types that are irrelevant to in-house legal practice. The gateway removes them from the analyzer's registry so they don't fire even when an operator's text accidentally pattern-matches.

| Recognizer | What Presidio would catch | Why disabled |
|---|---|---|
| `UsPassportRecognizer` | US passport numbers | High false-positive rate on contract numbers, exhibit indexes, dates. Real passports are rare in routine corpus; the downside of redacting "Exhibit A-1234567" as a passport outweighs the upside. |
| `UsLicenseRecognizer` | US driver's license numbers | Same reasoning — wide pattern, low actual presence in legal corpus. |
| `UsSsnRecognizer` | US Social Security numbers | The `123-45-6789` shape collides with case numbers (`Case 12-345-6789`), exhibit IDs, and pinpoint cites. Real SSNs in briefs are rare and ought to be redacted by other means before reaching the model. |
| `CryptoRecognizer` | Bitcoin/Ethereum addresses | Irrelevant for legal corpus; the patterns collide with random hex strings. |
| `IbanRecognizer` | IBAN bank identifiers | US-centric deployments rarely see them; when they do, `US_BANK_NUMBER` covers the use case. |
| `IpRecognizer` | IPv4/IPv6 addresses | Incidental in evidence logs but extremely high false-positive rate against version numbers (`192.168.1.1` as a section reference), page references, and dotted numeric identifiers. |
| `MedicalLicenseRecognizer` | Medical license numbers | Niche to healthcare practice areas; the shape collides with case numbers in unrelated corpora. |

A healthcare-practice deployment can re-enable `MedicalLicenseRecognizer` via the operator-customization pattern below.

---

## Customizing the recognizer set

### Re-enabling a disabled default

Edit `gateway/app/anonymization/engine.py` and remove the entry from `DISABLED_DEFAULT_RECOGNIZERS`. Rebuild the gateway image.

```python
# Before:
DISABLED_DEFAULT_RECOGNIZERS: tuple[str, ...] = (
    "UsPassportRecognizer",
    "UsLicenseRecognizer",
    "UsSsnRecognizer",
    "CryptoRecognizer",
    "IbanRecognizer",
    "IpRecognizer",
    "MedicalLicenseRecognizer",  # ← remove this line for healthcare deployments
)
```

The disabled list is currently a compile-time constant. A future task (M2-C3 or later) could surface it via `gateway.yaml` for runtime configuration.

### Adding a deployment-specific recognizer

The `MatterNumberRecognizer` defaults catch the two most common shapes, but every firm's numbering convention is different. Add a recognizer file at `gateway/app/anonymization/recognizers/<name>.py` mirroring the existing pattern:

```python
# gateway/app/anonymization/recognizers/custom_matter.py

from presidio_analyzer import Pattern, PatternRecognizer


class CustomMatterRecognizer(PatternRecognizer):
    """Recognize ``YYYY/NNNN``-style matter numbers (slash-separated)."""

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="slash_year_sequence",
                regex=r"(?<![\d/])(?:19|20)\d{2}/\d{3,6}(?![\d/])",
                score=0.8,
            ),
        ]
        super().__init__(
            supported_entity="MATTER_NUMBER",  # Reuse the existing entity type
            name="CustomMatterRecognizer",
            patterns=patterns,
        )
```

Then register it in `engine.py`:

```python
from app.anonymization.recognizers.custom_matter import CustomMatterRecognizer

# Inside get_analyzer_engine():
registry.add_recognizer(CustomMatterRecognizer())
```

Add a unit test in `gateway/tests/anonymization/test_recognizers.py` covering both positive matches (the matter numbers you expect to see) and negatives (similarly-shaped non-matter strings the regex must reject).

### Adding a new entity type

If the deployment needs an entity type that isn't in Presidio's vocabulary (e.g. `CLIENT_CODE`):

1. Create the recognizer with `supported_entity="CLIENT_CODE"`.
2. Register it in `engine.py`.
3. The new entity type flows through to `PseudonymMapper.assign("CLIENT_CODE", ...)` and gets pseudonyms like `CLIENT_CODE_0001`.

No further configuration is needed — the pseudonym format is generic per-entity-type.

### Calibrating against your corpus

The plan §M2-F2 explicitly calls for an acceptance corpus of legal documents to measure the false-positive / false-negative trade-off at the analyzer level. Until that ships, the conservative-by-default posture means:

- The defaults under-match (some real entities slip through unredacted).
- They almost never over-match (false positives are rare in normal prose).

If your deployment surfaces under-matching in practice (the M2 Anonymization round-trip tests in M2-C3 will help), the right response is to add deployment-specific recognizers rather than loosening the existing patterns globally.

---

## Middleware behavior (M2-B3)

The gateway runs two passes around the provider call:

```
Auth → Router → Rate Limit → Tier Derivation
                 → Anonymization-Pre  (substitute)
                 → Provider Adapter
                 → Anonymization-Post (rehydrate)
              → Cost Tracker → Telemetry
```

### When the middleware fires

All four conditions must hold; the first that fails short-circuits to a no-op for the entire pass (provider receives unmodified content; response is not touched; audit row records `anonymization_applied = false`).

| Condition | Source | Default |
|---|---|---|
| `gateway.yaml` `anonymization.enabled = true` | Operator config | **false** — feature flag stays off until the deployment opts in. |
| Request's routed tier is in `anonymization.apply_at_tiers` | Operator config | `[3, 4, 5]` — local Tier 1 / Tier 2 inference skips because the data never leaves the operator's environment. |
| Request's `lq_ai_privileged` is `false` | Backend forwards `Project.privileged` | False for chats outside any project, or in non-privileged projects. |
| Request's `anonymize` is `true` | Per-call body field | True. Callers send `anonymize: false` only when they need the raw text on the provider call (evaluation, raw-passthrough scenarios). |

### What the pre-pass touches

- Every `messages[*]` whose role is `user`, `assistant`, or `system` and whose `content` is non-null. Tool-call shaped messages (`content: null`) are left alone.
- Every string leaf inside `lq_ai_skill_inputs` (recursive — dicts and lists are walked). Numbers, booleans, and `null` pass through untouched.

### What the post-pass touches

**Non-streaming.** Each `choices[*].message.content` is rehydrated in place. The response body the caller sees has only originals, never pseudonyms.

**Streaming.** Each SSE chunk's `choices[*].delta.content` is fed through a per-stream `StreamingRehydrator`. The rehydrator holds the tail of the stream when it ends in a partial pseudonym (e.g. `PERSON_` or `PERSON_0001` with no trailing space — could grow to `PERSON_00010`). Held text emits as soon as the pattern crystallizes or fails to grow. At `[DONE]`, any held tail flushes as a synthesized terminal chunk so the caller doesn't lose the last fragment. The buffer is bounded by the length of one in-flight pseudonym (~25 chars in practice), so streaming latency is unaffected.

Per **Decision D**: the middleware rehydrates response **content** only. Citation rehydration is incidental — the api/'s downstream citation extraction operates on already-rehydrated content, so cite quotes naturally carry originals. The gateway never touches `message_citations` rows directly.

### Audit log

Every routed request writes one row to `inference_routing_log`. The middleware sets `anonymization_applied = true` on every row whose request passed all four firing conditions — including rows where the upstream later failed (the substitution did happen; the provider just then returned an error). Tier-floor refusals (which short-circuit before the pre-pass) leave the flag `false` because no substitution happened.

### Where mappings live

Per **Decision A** and **Decision B (i)** locked in M2-B3 kickoff: a fresh `PseudonymMapper` is constructed inside the request scope, populated by the pre-pass, read by the post-pass, and dropped on function exit. **It is never persisted, never logged, and never serialized to any side channel.** A new request gets a new mapper; counters reset every time.

### Privileged chats — why we skip

The privileged-Project skip (Decision A) is a deliberate trade-off. Privileged chats are work product the attorney-client privilege protects; replacing names with pseudonyms before the model sees them — even with the rehydration on the way back — risks corrupting that work product if any step in the pipeline behaves unexpectedly. The conservative posture is to leave privileged content untouched. Operators who want pseudonymization in privileged chats can flip `lq_ai_privileged` off at the api/ layer per chat, but the default protects the legal-work-product invariant.

### Retrieval-context skip (M2-D2)

Per **Decision M2-1**, retrieved source documents are NOT pseudonymized when sent to the provider. The api/ marks the retrieval-context system message (the one carrying chunks returned from `hybrid_search`) with `lq_ai_skip_anonymization=True`; the pre-middleware honors the flag and leaves the message's content unchanged. The model therefore sees:

- **User turn**: pseudonymized — `"What did COMPANY_0001 agree to?"`
- **Retrieval context system message**: un-pseudonymized — `"Acme Corp agreed to ..."` from the source file
- **Other system messages** (chat system instructions, skill-assembled prompts): pseudonymized normally — only the retrieval-context message bears the skip flag

The skip flag is api-internal: the gateway strips it from each message before serializing the request to upstream providers (the OpenAI adapter is the only one where this matters — Anthropic and Ollama adapters build per-message dicts field-by-field and ignore unknown attributes implicitly).

**Why this design.** The Citation Engine (§3.3 / [docs/citation-engine.md](../citation-engine.md)) verifies model-emitted quotes byte-for-byte against `documents.normalized_content` (un-pseudonymized). When the model sees real source quotes in retrieval, it emits real source quotes in its citations — Stage 1 verification matches directly with no translation hop. When the model emits pseudonyms in its prose (referencing entities from the pseudonymized user turn), the post-rehydrator on this layer substitutes originals back. The two layers compose cleanly: the model reasons about a consistent set of pseudonyms for chat-side entities and real names for source-side entities.

The alternative — Option A, pseudonymize source documents too — is filed as [DE-269](../PRD.md#de-269--anonymization-option-a-pseudonymize-source-documents-too) for future consideration. Option A adds a translation hop on the citation correctness path and makes the audit trail less granular; the spot-check is whether the model produces materially better/worse output when reasoning against pseudonymized vs un-pseudonymized retrieval.

Pinning tests:

- `gateway/tests/anonymization/test_middleware.py::test_pre_anonymize_skips_message_marked_skip_anonymization` — middleware honors the flag.
- `gateway/tests/test_openai_adapter.py::test_chat_completion_strips_per_message_lq_ai_skip_anonymization` — flag is stripped before reaching OpenAI.
- `api/tests/test_chat_citations.py::test_chat_send_marks_retrieval_context_skip_anonymization` — the api/ sets the flag on the retrieval system message and ONLY on that message.

---

## Pseudonym format

Every assigned pseudonym follows `{ENTITY_TYPE}_{NNNN}` with a 4-digit zero-padded counter (`PERSON_0001`, `MATTER_NUMBER_0042`). Counters increment per entity type independently within a single request; mappings never persist across requests (the `PseudonymMapper` instance is dropped on response).

The format is locked by M2-A3. Operators who need a different format (longer counter, different separator) can fork the `PseudonymMapper.assign` implementation, but the existing format is what M2-B3 middleware + M2-C3 round-trip tests target.

---

## Round-trip correctness (M2-C3)

The M2-C3 round-trip test suite (`gateway/tests/anonymization/test_round_trip.py`) pins four invariants the Anonymization Layer must hold. Each runs against the **real** Presidio `AnalyzerEngine` so the tests catch real entity-detection regressions, not just substitution-logic regressions. The suite is `pytest -m slow` because the first spaCy load is ~2-3s; CI runs it on every PR touching `gateway/app/anonymization/`.

1. **Byte-for-byte round-trip.** Any text that runs through `pseudonymize_into(text, mapper)` followed by `rehydrate(substituted_text, mapper)` returns the original `text` byte-for-byte. The mapper carries the round-trip; no information is lost in the substitution step.
2. **Cross-conversation stability within a request.** A single `PseudonymMapper` shared across multiple message-content passes assigns the same pseudonym to the same `(entity_type, original)` pair every time. Same name in messages 1 and 5 of one request → same pseudonym in both.
3. **Per-request isolation.** Two independent `PseudonymMapper` instances produce independent pseudonym spaces — `mapper_A.assign("PERSON", "John")` and `mapper_B.assign("PERSON", "John")` both yield `PERSON_0001` but the mappings live in disjoint state. Production request scoping (one mapper per request, dropped on response) is verified by this invariant.
4. **In-process-only persistence.** After a representative request completes, no pseudonym-shaped string appears in `caplog`-captured log records OR in the `inference_routing_log` audit row payload. The mapper is in-process, in-memory, and never escapes to any persistent surface (logs, DB, MinIO/S3, telemetry).

The suite also covers entity-overlap handling (`John Smith Jr.` collapses to one substitution per the longest-span-wins resolution in `Anonymizer._resolve_overlaps`) and the edge cases the M2-C3 plan §M2-C3 calls out.

---

## Known limitations and roadmap

### Pseudonym-collision surfaces — DE-274

The current pseudonym format `{ENTITY_TYPE}_{NNNN}` is deterministic and operator-readable, which is the right trade-off for legibility. The cost is two distinct collision surfaces, both pinned by the M2-C3 round-trip test suite so a future change is visible in CI:

**1. Source-document collision.** If a source document happens to **literally** contain a string matching this pattern (e.g., a contract template using `PERSON_0001` as a placeholder, or a procedural doc referencing `EMAIL_ADDRESS_0023` from a different system), the rehydrator's behavior today is best-effort: `Anonymizer.rehydrate` uses `str.replace` per known mapping; a literal `PERSON_0001` in source text that does NOT match an active mapper entry passes through unchanged (the safe path). The literal string is preserved in the user-visible content. The risk is forward-looking: as the engine evolves (e.g., adding logging of unmatched pseudonym-shaped strings for operator debugging), a literal source pseudonym could surface in logs as a (minor) leak path.

**2. Cross-mapper collision.** Two parallel mappers both produce `PERSON_0001` for their respective first PERSON span — there is no per-request salt in the format, so the pseudonym strings are not globally distinct across mappers. Production isolation works today **only because mappers are per-request and dropped on function exit** — there is no production path that rehydrates one request's output against another request's mapper. A future architectural change that, for any reason, cached or shared mappers across requests would silently leak originals across the request boundary. Isolation is currently **scope-enforced**, not collision-prevented.

**Tracked as [PRD §9 / DE-274](../PRD.md#de-274--anonymization-pseudonym-collision-in-source-documents).** Recommended path: per-request random salt on the pseudonym format (e.g., `PERSON_0001_a3f7`). One change closes both collision surfaces — literal pseudonym patterns in source documents will no longer match any active mapper entry, and two parallel mappers will produce structurally distinct pseudonym strings even at the same counter slot. This is **on the roadmap** but deliberately deferred until either an operator hits the collision in practice OR until a future change to the rehydrator's logging surface or mapper lifecycle makes either leak path real.

If you operate a deployment whose source corpus contains literal `{UPPERCASE}_{DIGITS}` patterns at risk of collision and you want resolution sooner than the roadmap, the simplest deployment-side mitigation is to override `PseudonymMapper.assign` with a salted format (e.g., `f"{entity_type}_{counter:04d}_{secrets.token_hex(2)}"`) and rebuild the gateway image.

---

## Related

* `PRD.md` §4.7 — Anonymization Layer architectural overview.
* `gateway/app/anonymization/` — module source.
* M2 plan §M2-A3, §M2-B2, §M2-B3 — milestone task scope.
* M2 decision **M2-1** — pseudonymize chat/skill content only; documents stay un-pseudonymized.
