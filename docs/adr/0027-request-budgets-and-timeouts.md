# ADR 0027 — Request budgets and timeouts: sane defaults, per-request tuning, operator escape hatches

**Status:** Proposed (2026-09-13) — for the weekly call
**Date:** 2026-09-13
**Owner:** Maintainer team (houfu)
**Origin:** Issue #489 (the position put up for challenge on 2026-08-04) and the four
contributor PRs that answered issue #503 on the same lines: #317, #318, #535
(@sergiomaldo) and #504 (@SaifAlYounan). The 2026-08-23 review of #504 ruled the
split and three of the four residuals; this ADR records the whole.

**Relates to:** ADR [0003](0003-error-handling.md) (the cross-subsystem error-code
enum this ADR reuses rather than extends), ADR [0025](0025-release-versioning-and-pipeline-ordering.md)
(the defaults change ships under the next version), DE-391 (exclude attached-document
content from the history trim), DE-392 (enforce or remove `max_max_tokens`), DE-393
(per-request timeout — filed with this ADR), issue #512 and DE-355 (the rest of the
"documents never fail silently" train), PRD §4.4.

## Context

Five shipped defaults were found short for long-document work, and one defect hid
the fact that they were short.

- **The defect (#503 item 1, fixed in #504):** a streaming turn that produced no
  content fell through to the *success* tail of the gateway's SSE path — routing-log
  row with `usage=None`, clean `[DONE]`, HTTP 200 — so a provider outage, an
  exhausted output budget, and a model with nothing to say all rendered
  identically. For a legal tool that ambiguity is the bug: the user blames the
  model. It caused a published benchmark of the `redfern-schedule` skill to carry a
  wrong finding.
- **The defaults:** Anthropic injected `max_tokens` 4096; three independent
  60-second timeouts on one request path (api→gateway client, Anthropic adapter,
  OpenAI adapter; Ollama at 120s); chat-history token budget 6,000.

Two contributors surfaced these independently, from opposite ends:

| Evidence | Source |
|---|---|
| A production self-hosted deployment (law firm, BYOK Anthropic) saw every large request die at 60–63s and read it as a flaky provider; long template drafts truncated at ~4K output tokens and a review pass "correctly" flagged the never-generated sections as absent. Drafting workloads routinely need 8–16K output. | @sergiomaldo, #317 / #318 (July 2026), #535 (August 2026) |
| A controlled five-model benchmark through the full web→api→gateway path: at an identical 4,096 budget `claude-opus-4-7` spent 0 thinking tokens and returned 11,518 characters; `claude-opus-5` spent all 4,096 on thinking and returned **nothing**. One document-production turn took **370s**. A ~47,000-token case file supplied in turn 1 was silently gone by turn 2 at the 6,000 history budget. | @SaifAlYounan, #503 / #504 (August 2026) |

Issue #489 put a position up for challenge: *tune by use case at the call site; the
gateway ships a sane default plus a hard ceiling; per-provider operator knobs are a
narrow deployment escape hatch, not the tuning axis.* It promised an ADR and said
#317/#318 would be resolved to match. No challenge came; #504 then bundled the same
decisions and #535 added a fourth PR on the same lines. This is that ADR.

The 2026-08-23 review of #504 ruled: split the fix from the defaults; take both
#535's knob and #504's 900s value (R-1); take the `max_tokens` docstring correction
then and decide the value with #317 (R-2); ratify the 64,000 history budget (R-3);
file the attachment-budget idea as a DE credited to its author (R-4, DE-391). The
remaining values were ruled on 2026-09-13 and are recorded here.

## Decision

**D1 — Defaults.** The gateway and api ship these defaults. Each is anchored to a
measurement above, not chosen because it sounded reasonable.

| Setting | Was | Now | Anchor |
|---|---|---|---|
| Gateway adapter request timeout (Anthropic, OpenAI/Azure, Ollama) | 60 / 60 / 120 s | **600 s** | 370 s measured turn (#503); 4–16K-token drafts exceed 60 s (#318); local models on modest hardware run for minutes (#535) |
| api → gateway client timeout (`LQ_AI_GATEWAY_TIMEOUT_SECONDS`) | 60 s | **900 s**, connect leg capped at 10 s | Must stay the loosest of the three or it truncates first and the gateway's more specific label never appears (#503; #535 review) |
| Anthropic injected `max_tokens` when the caller omits it | 4096 | **16384** | Covers both measured needs (8–16K drafting; opus-5 spent 4,096 on thinking) and equals the documented `request_validation.max_max_tokens` example, so the default never exceeds the documented ceiling |
| Chat-history token budget (`LQ_AI_CHAT_HISTORY_TOKEN_BUDGET`) | 6,000 | **64,000** | ~47K-token case file dropped by turn 2 (#503); ratified 2026-08-23 |

**D2 — Tuning axis.** Per-request values always win: a caller that knows its use
case sets `max_tokens` on the request (already honoured). Per-provider operator
fields are escape hatches, not the tuning surface: `timeout_s` (existing),
`default_max_tokens` (#317), and the api's `LQ_AI_GATEWAY_TIMEOUT_SECONDS` (#535).
They exist so an operator who has diagnosed a deployment-specific limit can keep
the fix across container recreates without patching an image. Use-case-aware
callers (skills, playbooks, drafting jobs) asking for their own budgets is the
direction; it is not built by this ADR (DE-393 for the timeout half).

**D3 — Honest failure, not silent degradation.** A contentless stream is a failure:
the gateway raises `ProviderEmptyResponseError` (wire code `provider_unavailable`
per ADR 0003 — no new enum entry), emits an error frame, and writes a routing-log
failure row labelled `empty_response:`; `finish_reason: length` with no visible
text is named as an exhausted output budget. A client-side timeout is
`ProviderTimeoutError` on every adapter, labelled `client_timeout:` in the routing
log, so a too-tight `timeout_s` is never mistaken for an outage. The api never
emits a success `complete` frame whose content is empty, and its guard runs
*before* the assistant row is persisted so the stored `error_code`, the wire, and
history replay agree.

**D4 — Ordering invariant.** api timeout > adapter timeouts. Documented in
`.env.example` and the settings description; not validated in code, because the
api does not read gateway config and a validator would couple them.

**D5 — The declared-but-unenforced ceiling.** `request_validation.max_max_tokens`
is declared in the gateway config schema and enforced on no request path. #317's
clamp of the injected default against a freshly constructed
`RequestValidationConfig()` (not the operator's loaded value) is dropped rather
than fixed; D1 keeps the default at the documented ceiling instead.
Enforce-or-remove is DE-392, to be decided before the ceiling is advertised
further.

## Consequences

- **Operators inherit new defaults on upgrade** (PRs labelled `breaking-change`;
  release notes under ADR 0025's next version): a deployment that changed nothing
  gets a 4× default output ceiling, a ~10× larger replayed history in the worst
  case, and connections held up to 900 s. `max_tokens` is a ceiling not a spend, so
  the output raise costs nothing on turns that do not use it; the history raise
  does cost replayed input on long sessions and is the one to lower for chat-only,
  cost-sensitive deployments.
- **Fallback timing:** the router treats a client timeout as fallback-eligible, so a
  hung connection now waits 600 s before the next provider is tried. Deliberate;
  `timeout_s` still tightens it per provider.
- **Docs:** PRD §4.4's example config now shows the defaults and
  `default_max_tokens` (this PR); `gateway.yaml.example` and `.env.example`
  document the knobs (#317, #535); both `ProviderUnavailable` docstrings carry the
  accepted-but-empty clause (#504).
- **Deferred:** DE-392 (enforce or remove `max_max_tokens`, filed in #317), DE-393
  (per-request / per-use-case timeout, filed with this ADR).

## Alternatives considered

- **Per-provider knobs as the tuning axis** (#317 as filed): rejected as the axis —
  one provider serves every use case — and kept as the escape hatch (D2).
- **Keep 4096:** rejected — a newer model with adaptive thinking on returns nothing,
  silently, with no code change (#503).
- **32000** (#504 as filed): deferred — exceeds the documented ceiling while the
  ceiling is unenforced (D5). Revisit with DE-392.
- **Fixed 900 s without a knob** (#504) or **knob without a raise** (#535): rejected
  in favour of both — complementary once stated side by side (2026-08-23, R-1).
- **A new `provider_timeout` / `provider_empty` wire code:** rejected — ADR 0003's
  cross-subsystem enum is a contract and both failures fall inside
  `provider_unavailable`'s documented meaning; internal subclasses give the
  precision.

## Credits

- **@sergiomaldo** — first surfaced both asymmetries from a production self-hosted
  deployment (#317, #318, July 2026) and the api-side knob (#535); the
  `ProviderTimeoutError` / `client_timeout:` design that D3 generalises.
- **@SaifAlYounan** — the masked-failure defect and its fix (#503, #504); the
  controlled measurements every value in D1 is anchored to; the attachment-budget
  idea (DE-391).

## References

Issue #489 (position) · issue #503 · PRs #317, #318, #504, #535 · issue #512 and
DE-355 (the rest of the honest-documents train) · ADR 0003 · ADR 0025
