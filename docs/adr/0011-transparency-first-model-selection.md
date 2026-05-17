# ADR 0011 — Transparency-first model selection posture

**Status:** Accepted
**Date:** 2026-05-10
**Owner:** D-phase wave-3 (D2 tier UI + live model discovery + encrypted gateway keys)

## Context

LQ.AI's reason for existing is transparency (PRD §1.3, CLAUDE.md): every
artifact that shapes the user's experience is visible work product. That
applies at the skill layer (SKILL.md is readable, forkable), at the
prompt-assembly layer (Skill Inspector + raw markdown endpoint), and —
this ADR argues — at the **model-selection** layer.

The D0/D0.5/D1 wave shipped an **alias-based routing** system: a chat
sends `model: "smart"` and the gateway resolves `smart` against
`gateway.yaml` to a primary `provider+model` plus an ordered fallback
chain. Aliases are admin-managed via `/admin/v1/aliases` (D0.5 hot-
reload, ADR 0010). Tier-floor enforcement (D1) layers on top to refuse
any routing that would land the call below a skill's declared
`minimum_inference_tier`.

This shipped as the only routing primitive. In review (2026-05-10) we
found two transparency gaps:

1. **The user's chat shows the alias label, not the provider/model.**
   A user sees "smart" in the picker, the message they got back, and
   no per-message indicator of which provider+model the gateway
   actually called. The information is in `inference_routing_log` and
   in `Message.routed_provider` / `routed_model`, but the chat UI
   doesn't surface it.

2. **Aliases are the only way to pick a model.** A user who knows they
   want `claude-opus-4-7` specifically (or wants to verify their
   chat is hitting `gpt-4o` and not falling through to a cheaper
   alternative) has no way to express that. They have to ask an
   admin to create a new alias, then pick it. That makes aliases an
   opacity layer — admin-mediated indirection between user intent
   and what the LLM actually sees.

Both are inconsistent with PRD §1.3's framing. The transparency
principle requires visibility *plus* the ability for the user/admin
to set the models/inference, not just to read what the system chose.

This ADR pulls model selection into the same posture as skills: the
artifact is visible by default; the user can override the default;
aliases are *convenience*, not *gating*.

## Decision

Model selection becomes a **two-mode** API with full disclosure on
both sides.

### Mode 1 — Direct provider/model selection

Chat-completion requests can send a fully-qualified model identifier:

```
model: "anthropic/claude-opus-4-7"
model: "openai/gpt-4o"
model: "ollama/qwen3.5:9b"
model: "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
```

The gateway parses `<provider>/<model>` and dispatches directly to
that provider with no fallback chain. If the provider is misconfigured
(no key, unreachable) or the model is unavailable, the call fails
loudly rather than silently routing somewhere else. Tier-floor
enforcement (D1) still runs: a tier-1 model attempted against a
skill that declares `minimum_inference_tier: 3` 422s.

### Mode 2 — Alias selection (existing)

Existing aliases (`smart`, `fast`, etc.) keep their fallback semantics.
They're useful: an admin who wants every chat without an explicit
override to land on Anthropic Opus with Sonnet/Haiku fallbacks gets
that with a single alias entry. But:

* Aliases must **publish their resolved mapping** to the user surface.
  The model picker shows `smart → anthropic/claude-opus-4-7 (+2 fallbacks)`,
  not just `smart`. Resolution is read-through-the-config — not a
  separate cache.
* The alias picker UI groups under a "Defaults" optgroup; direct
  provider/model entries group under their provider name. Users see
  both at once and pick whichever matches their intent.
* The alias' fallback chain is also visible: clicking an alias opens
  a panel that lists the resolved primary + each fallback provider/
  model. No hidden indirection.

### Per-message routing disclosure

Every assistant message records and displays the resolved
`routed_provider`, `routed_model`, and `routed_inference_tier` —
already populated on `Message` by D1 + B5. The D2 tier badge in the
chat header surfaces all three. Users can always answer "what just
ran?" by looking at the message they received.

### Encrypted-at-rest provider keys

Provider keys in `gateway.yaml` are wrapped at rest. The current
state (env-var interpolation) gets the secret out of the file but
not out of the host's environment listing or backup snapshots. The
encrypted-at-rest path:

* `gateway.yaml` supports both `api_key: ${ANTHROPIC_API_KEY}`
  (existing path; deprecated but still loaded) and
  `api_key_encrypted: <fernet-token>` (new).
* The gateway reads `LQ_AI_GATEWAY_MASTER_KEY` (operator-supplied,
  bound at process start; never written to disk by the gateway) and
  uses it to decrypt `api_key_encrypted` values in-memory.
* A CLI helper (`python -m gateway.cli encrypt-key --provider
  anthropic`) wraps a plaintext key for the operator to paste into
  `gateway.yaml`.
* Decrypted keys live only in `GatewayConfig.providers[*].api_key`
  in-memory; never logged, never serialized, never exposed via the
  admin API surface (the admin alias UI never reveals the resolved
  provider key — only metadata).

This gives operators "encrypted at rest" without locking them out of
the existing env-var path during migration.

### What stays the same

* The Inference Gateway is still the only component that holds
  privileged provider keys (PRD §1.3, ADR 0002 / 0007 framing).
  Per-user keys are out of scope; that's a multi-tenancy / SaaS
  story this project explicitly defers.
* Aliases stay editable via the existing admin UI (D0.5).
* Tier-floor enforcement (D1) still runs on every dispatch.
* `gateway.yaml` is still the runtime config artifact (ADR 0010
  hot-reload still applies).

## Consequences

**Positive.**

* Users gain a real "I want this exact model" affordance without
  asking an admin.
* The chat UI can answer "what ran?" without operator help.
* Aliases become honest defaults — visible mappings, not opacity.
* Encrypted keys close a procurement-readiness gap (some
  enterprise security reviews flag plaintext provider keys in
  config files even when the file is mode 0600).

**Negative.**

* The alias system is now one of two routing modes. The gateway
  config schema, the `/v1/chat/completions` model-resolution path,
  and the OpenAPI sketch all need to handle both.
* Live model discovery (calling each provider's `list_models`) is
  a new dependency surface. Provider outages will cause the picker
  to render a stale catalog rather than the live one; the gateway
  caches with a short TTL and surfaces a "stale list" indicator
  rather than failing the chat.
* Encrypted-keys path adds a master-key bootstrap step to the
  gateway lifecycle. Documented in `docs/security/`; quickstart
  needs a one-liner about generating + setting
  `LQ_AI_GATEWAY_MASTER_KEY`.
* Existing tests against the alias-only path stay green; new
  direct-mode dispatch paths get their own test surface.

**Neutral.**

* The deprecated `api_key: ${...}` env-var path stays loadable
  through M1 + M2. We will warn operators in M3 and drop it in M4
  unless real-world friction shows otherwise.

## Implementation references

| Concern | Location |
|---|---|
| Direct-mode model parsing | `gateway/app/router.py` (alias-resolution branch extended) |
| Live model discovery | `gateway/app/clients/discovery.py` (new) + `/v1/models` enrichment |
| Encrypted-keys decoding | `gateway/app/config/secrets.py` (new) |
| Admin alias UI showing resolved mappings | `web/src/lib/lq-ai/components/ModelPicker.svelte` (rewrite) |
| Tier badge | `web/src/lib/lq-ai/components/TierBadge.svelte` (existing) wired into `MessageList` |

## Out of scope

* **Per-user provider keys.** Not in M1's threat model — the
  Inference Gateway is the security boundary; provider keys belong
  to the operator. A multi-tenant deployment that needs per-user
  billing/keys is a separate architecture (see PRD §1.6 boundaries
  with Streamline AI).
* **Role-based routing** (separate models for generation vs judge
  vs Socratic, à la SmarterClaw). Aliases + skill `lq_ai:`
  frontmatter already cover the use cases this would address.
  Adding role-routing as a third mode would dilute the picker UX
  without obvious value at M1 scope.
* **Tool-use / function-calling per provider.** Each adapter would
  need its own tool-format translation. M1 doesn't have a tool-
  use surface yet; revisit when one lands.

## References

* PRD §1.3 — Transparency as a founding principle
* PRD §3.13 / §3.14 — Inference tier model + tabular output
* ADR 0002 — Backend-owned auth (sets the gateway-as-boundary
  framing this ADR builds on)
* ADR 0007 — Skill prompt assembly (path-A internal endpoint;
  same trust posture as model dispatch)
* ADR 0010 — Gateway config hot-reload (the write path direct-mode
  + encrypted keys both ride on top of)
