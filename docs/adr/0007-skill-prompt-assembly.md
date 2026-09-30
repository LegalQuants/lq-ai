# ADR 0007 — Skill prompt assembly: gateway↔backend auth, templating, and request surface

**Status:** Accepted (2026-05-08)
**Decision-makers:** Kevin Keller (initial maintainer)
**Affected components:** `api/`, `gateway/`
**Related:** [`docs/M1-IMPLEMENTATION-ORDER.md` Task C2](../M1-IMPLEMENTATION-ORDER.md), [ADR 0002 — Backend-owned auth](0002-backend-owned-auth.md), [ADR 0003 — Error handling](0003-error-handling.md), [ADR 0004 — Skill loader locus](0004-skill-loader-locus.md), [PRD §4.4 — Inference Gateway internals](../PRD.md#44-the-request-pipeline)

---

## Context

Task C2 implements gateway-side prompt assembly: when a chat request arrives at the gateway with a skill attached, the gateway must fetch the skill from the backend's registry (per ADR 0004 the canonical source is the backend), assemble the skill's body and reference files into the system prompt, apply user-supplied skill inputs, and pass the resulting messages to the provider adapter.

Three architectural questions surfaced during C2 implementation that ADR 0004 and the OpenAPI sketches did not answer:

1. **How does the gateway authenticate to the backend?** The user-facing `GET /api/v1/skills/{name}` endpoint is gated by `get_active_user` (B1 bearer token + B2 must-change-password). The gateway has no user; it has the shared `X-LQ-AI-Gateway-Key` secret that the backend already stamps on every outbound call to the gateway. We need the same secret to flow in the *reverse* direction.
2. **What templating mechanism applies skill inputs to the body?** Skills declare `inputs:` in their frontmatter (e.g., NDA-review's `document`, `perspective`, `jurisdiction`). User-supplied values must land in the assembled prompt. The substitution surface needs a defined syntax, escaping rules, and an explicit security posture (template injection is a real concern when the substitution targets the model's instruction stream).
3. **How does a chat-completion request declare which skills to attach and which input values to bind?** The gateway already accepts `skill_name: string` as an extension on `ChatCompletionRequest` for audit-log tagging (B3-era), but that's a single string with no input binding and no documentation around what the gateway *does* with it.

## Decisions

### 1. Backend↔gateway auth: new internal endpoint (Path A)

**The backend exposes `GET /api/v1/internal/skills/{name}` authenticated by `X-LQ-AI-Gateway-Key`** (no user token). The user-facing `GET /api/v1/skills/{name}` is unchanged — it stays under `get_active_user`. Path A keeps a clean separation: user-facing endpoints authenticate by user token; internal/service-to-service endpoints authenticate by the shared gateway secret. The two trust domains never mix on a single route.

The alternative (Path B — accept either auth mode on the user-facing endpoint) was considered and rejected on the grounds that mixing auth modes on a single route makes the contract harder to reason about (security review must examine both paths) and harder to audit (one log line cannot tell you which trust domain originated the call).

**Wire shape:** the internal endpoint returns the same `Skill` schema as the user-facing one, so the gateway-side client can reuse the same response model. The path differs (`/api/v1/internal/skills/{name}`); the auth scheme differs; the response shape is identical.

**Header trust posture:** the backend trusts any caller that presents a valid `X-LQ-AI-Gateway-Key`. Per the existing B5 deferred item, *the gateway does not yet enforce this header on its own incoming requests* — that's separate (D-phase hardening) from the *backend's* enforcement here. The backend MUST enforce on the internal route from day one because ADR 0002 makes the backend the auth-canonical service.

**Configuration:** the gateway reads the existing `LQ_AI_GATEWAY_KEY` env var (already set on the gateway service for incoming-request auth, even though the gateway doesn't enforce it yet) and stamps it on outbound calls to the backend. The backend reads the same env var (already wired) and compares constant-time on the internal route.

### 2. Templating: regex-based `{{var}}` substitution

**Skill-input substitution uses a regex-based `{{name}}` matcher.** No Jinja2; no control flow; no expressions; no filters. Substitution is bounded to literal variable names that match `[a-zA-Z_][a-zA-Z0-9_]*`. Unknown variables that appear in the skill body are left as-is (a permissive posture — the model sees the literal `{{unknown}}` and can ignore it; we don't fail the request because a skill author put an unrecognised placeholder somewhere). User inputs that the body never references are also tolerated (the substitution is one-pass; surplus inputs are not errors).

Why not Jinja2 (or a Jinja2 subset)?

- **Smaller attack surface.** Jinja2's expression evaluator (`{{ obj.attr }}`, `{{ func() }}`) is not relevant to skill substitution and would have to be deliberately disabled. The cleanest disabler is "don't include Jinja2 at all".
- **No new dependency.** `httpx`, `pydantic`, `fastapi` cover the substitution surface. Jinja2 adds an SBOM entry without measurable benefit at M1 scale.
- **Predictability.** A template engine's parse/compile pipeline is its own debugging surface. A regex is one line; failures are obvious.

**Escaping:** values are inserted verbatim. Skill authors who want to escape model-meaningful tokens in a value (e.g., `<system>`-shaped tags) handle that in the skill body's prose around the placeholder, not in the substitutor. The substitutor treats values as opaque strings.

**Required vs optional inputs:** the skill frontmatter declares `inputs.required` and `inputs.optional` (per the M1 corpus convention; the schema-authoring guide has been silent on this). The assembler enforces *required* inputs at request time — a missing required input is a 400 with a structured `validation_error` envelope naming the missing fields. Optional inputs that aren't supplied are simply not substituted; their `{{name}}` placeholders remain in the body if present.

### 3. Skill-attachment surface: request-extension on the body

**Two new extension fields on `ChatCompletionRequest`:**

- `lq_ai_skills: list[str]` — ordered list of skill names to attach. The order matters: the assembler concatenates each skill's body in order (with separators between them), so a request that attaches `["nda-review", "us-state-overlay"]` will see `nda-review` first.
- `lq_ai_skill_inputs: dict[str, dict[str, Any]]` — per-skill input bindings. The outer key is the skill name; the inner dict is the input variable bindings for that skill. Per-skill scoping means two attached skills with overlapping input variable names don't collide.

The pre-existing `skill_name: str` extension (for audit-log tagging) is preserved unchanged. When `lq_ai_skills` is set, `skill_name` defaults to the first element of `lq_ai_skills` if not explicitly set (so the audit log gets the right tag without forcing the caller to set both).

**Why body-extension and not a header (e.g., `X-LQ-AI-Skills`):**

- Body extension matches the existing B3/B4 pattern (`routed_inference_tier` / `routed_provider` / `cost_estimate` are all body fields).
- Headers are fragile for structured data: representing `lq_ai_skill_inputs` as a header requires JSON-encoding then base64-encoding to survive HTTP-header restrictions, and the result is harder to read in logs.
- A header-only approach also fragments the contract surface — the backend would have to construct headers separately from the body, and the gateway would have to read both.

The downside is that callers who only emit "OpenAI-format" requests (without LQ.AI extensions) cannot attach skills — but that's already true of every other LQ.AI extension (`minimum_inference_tier`, `chat_id`, etc.), so the surface is consistent.

### 4. Cache TTL: 60 seconds (in-memory)

**The gateway caches fetched skills in a process-local dict with a 60-second TTL.** Keys are skill names; values are the parsed `Skill` shape plus a fetched-at timestamp. On cache miss (or on TTL expiry), the gateway fetches fresh from `api/`. The cache is process-local; multiple gateway replicas hold independent caches. The skill-content human-attestation pipeline tolerates seconds-to-minutes of staleness, so a 60-second TTL is comfortably below the operationally-meaningful window.

We deliberately avoid Redis here. The gateway already touches Redis via the `api/` service (rate limits), but cross-subsystem state for a 60-second cache is over-engineered for M1. If profiling shows a hot enough fetch pattern that 60s is too aggressive, we'd revisit by *raising* the TTL, not by adding a shared cache.

## Consequences

### Positive

- **Clean trust-domain separation.** User-facing routes stay under user-token auth; service-to-service routes stay under shared-secret auth. Security review is straightforward.
- **No new dependencies.** Regex substitution + httpx (already in gateway) + dict cache. SBOM unchanged.
- **Predictable substitution.** No template engine to learn or debug; the substitution surface is one regex.
- **Request shape is recognisably "OpenAI plus extensions".** Anyone reading a recorded request payload sees the OpenAI fields plus a clearly-namespaced `lq_ai_*` extension block.

### Negative

- **One extra HTTP hop per uncached skill fetch.** ~1ms intra-cluster; not material against an inference-latency budget measured in seconds. Cache amortises across requests-per-skill.
- **Cache invalidation is implicit (TTL).** The skill-corpus-changes-while-running case (operator pushed a new skill, didn't reload the gateway) sees up-to-60s of staleness. Acceptable per the human-attestation pipeline's pace; documented for operators.
- **No template features.** Skills cannot conditionally include/exclude sections via `{% if %}` blocks or filter values via `{{ value | upper }}`. The decision is to keep the substitution surface minimal; if a skill author needs conditional content, they write the conditional logic in prose for the model.

### Neutral

- **Tool-use translation is not exercised.** None of the 11 starter skills declare `tools:` in their frontmatter. C2 ships without bidirectional tool-call translation in the Anthropic adapter (B3's deferred item). When a skill that declares tools lands, that work picks up — likely C3 (chat persistence forces the tool-call/tool-result message-shape question) or later.

## Notes on alternatives

- **Path B (dual-auth on the user-facing endpoint) reconsidered.** Tempting because it's one fewer route. Rejected because the resulting `if user_token: ... elif gateway_key: ...` branch in the handler conflates two trust domains; security review then has to reason about both paths together. The "one route, two paths" pattern is also harder to lock down when one of the paths needs to be temporarily disabled for incident response.
- **Jinja2 reconsidered.** A whitelist-only Jinja2 environment (no `{% %}` tags, no expressions) is technically possible. We measured: the disablement code is longer than our entire regex implementation, and a Jinja2 dep adds an SBOM entry. The safety-positive choice is "don't include the engine".
- **Header-based skill attachment reconsidered.** Documented above. JSON-in-base64-in-header is technically a thing; it's not a thing we want to live with.

## What this ADR does not commit to

- **Long-running skill execution.** The current shape is request-scoped: skill content is fetched, prompt is assembled, request is dispatched, response returns. Future capability for skills to run multi-turn (e.g., a skill that fetches additional reference material based on the model's first turn) is out of scope for C2 and would warrant its own ADR.
- **Skill versioning at request time.** Skills carry a free-form `version` field (`"1.0.1"`). C2 attaches whatever version is currently in the registry. Pinning a request to a specific version is a future enhancement (filed as a candidate DE-XXX in PRD §9 if/when it surfaces).
- **Skill-output post-processing.** The skill `output_format` field is informational; the gateway does not enforce a particular output shape. Post-processing the model's response per the declared format is a future skill-execution-engine concern.

---

## Amendment — 2026-05-14: Dual-Invocation Model (Wave D.2)

**Status:** Accepted addendum.
**Decision-maker:** Kevin Keller.
**Implementing commits:** Wave D.2 Tasks 3–6 (slash-command popover, capture-as-skill modal, audit-log versions endpoint, SkillWizard).

### Context

ADR 0007 was written for the C2 gateway path: a single, server-side invocation of a skill by name embedded in a `lq_ai_skills` request body field. Wave D.2 shipped two additional, user-facing invocation paths that ride the same skill-provenance model but expose it through different UI surfaces.

### New invocation paths

**Path A — Slash command (`/skill-alias` in the composer).**

The user types `/` followed by a skill's `slash_alias` in the chat composer. `ChatPanel.svelte` detects the leading slash, opens the `SlashPopover` (skill typeahead), and — on selection — calls `GET /api/v1/skills/autocomplete` to narrow the results. On pick, the selected skill is attached to the outgoing `POST /api/v1/chats/{id}/messages` body as:

```json
{ "attached_skills": [{ "slug": "<slug>", "source": "slash" }] }
```

The gateway receives this and routes the request through the C2 prompt-assembly pipeline. The `source: "slash"` tag flows through the backend receipt event log so the Receipts drawer can surface "Skill applied: … (via slash command)" for transparency (PRD §1.3).

**Path B — Capture-as-skill modal.**

After an AI message arrives, the user clicks the inline 📝 button (or the overflow menu "Capture as skill" item). The `CaptureSkillModal` pre-populates name/slug/description from the message content and offers two sub-paths:

- **Save** — calls `POST /api/v1/user-skills` with `source_message_id` set to the source message's id. The `source_message_id` value is documentary (it rides the `user_skill.created` audit-log row; there is no `source_message_id` column on `user_skills`). This preserves forensic lineage: any skill created from a chat can be traced back to the specific message that inspired it.
- **Edit in wizard** — stashes a `CaptureStash` JSON snapshot in `localStorage` under `lq-ai:capture-stash:<uuid>` (key format owned by `stashStorageKey()` in `CaptureSkillModal.svelte`) then navigates to `/lq-ai/skills/new?capture=<uuid>`. The `/skills/new` page reads the stash on mount and seeds the `SkillWizard` with it.

### How skill provenance flows through both paths

The provenance record for a skill invocation or creation consists of three elements:

1. **The skill row itself** — `user_skills` table, with `forked_from` (source built-in slug) and `slash_alias` (invocation handle). Both are write-once at create time; subsequent edits cannot overwrite them.
2. **The audit-log row** — `audit_log` table, `resource_type = 'user_skill'`. Every state change (created / updated / deleted) writes an audit row. The `details` JSONB column on `user_skill.created` rows carries `forked_from`, `slash_alias`, and `source_message_id` when those fields were set at creation.
3. **The receipt event** — for slash-invoked skills, the receipt event log (per PRD §1.7) records `kind = 'skill'` with `source = 'slash'`. This lets users answer "which skill was used, and how was it invoked?" for any historical chat turn without reading raw DB records.

### What this amendment does not change

- The C2 gateway-side assembly pipeline is unchanged. Both new UI paths ultimately produce the same `attached_skills` list in the message POST body that the gateway already processes.
- The `{{var}}` templating mechanism (ADR 0007 §2) is unchanged.
- The cache TTL (ADR 0007 §4) is unchanged.
- Skill versioning at request time remains a future enhancement (the `version` field is still documentary-only at invocation).

---

## Amendment — 2026-09-02: Untrusted-input envelope and marker neutralisation

**Status:** Accepted addendum.
**Trigger:** external security report (credit `rips4w`), 2026-08-25.

### What changed in §2's escaping rule

§2 said *"values are inserted verbatim … skill authors who want to escape
model-meaningful tokens in a value handle that in the skill body's prose
around the placeholder."* Two facts made that posture inoperative: none
of the 15 shipped skills uses a `{{placeholder}}`, so there is no prose
around a placeholder anywhere in the corpus; and the DE-328 leftover-input
block (Option A) appended unconsumed inputs as raw `- key: value` lines, so
a value containing a newline continued as further system-prompt text and
could reproduce the assembler's own `## Operator system instructions`
separator verbatim, impersonating the operator's block.

The substitutor now does two things it did not do before:

1. **Unconsumed inputs are rendered as a one-line JSON envelope**, not as
   list items: `{"source": "skill_input", "skill": <name>, "inputs":
   {...}}` inside a fenced block, under a fixed policy line that the
   values are data, not instructions. JSON encoding removes every raw line
   break (U+2028/U+2029 are escaped explicitly), so a value cannot start a
   new prompt line, close the fence, or forge a heading.
2. **Assembler-owned boundary headings inside any interpolated value are
   backslash-escaped** at line start (`# Skill:`, `## Reference:`,
   `### Provided inputs for`, `## Operator system instructions`). This
   includes all line separators and markers formed partly by a template
   or another input. Markers authored entirely in the template remain
   intact, as does ordinary document markdown.

### What this amendment does not claim

This is **envelope integrity, not isolation**. The values still sit in the
`role="system"` message. A model that reads attacker prose under a
correctly labelled "untrusted" heading can still follow it. Relocating
untrusted content — skill inputs, retrieved chunks, attachments,
filenames — into a data channel per provider is a separate
architectural decision, tracked as DE-388 and requiring its own ADR and an
adversarial evaluation corpus (DE-110). PRD Appendix E previously claimed
"skill-prompt isolation conventions" in the authoring guide; no such
conventions existed, and that sentence has been corrected to describe
this envelope and its limits.
