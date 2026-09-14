# #563 — Direct inference pricing and tier enforcement

Status: local implementation under proposed ADR 0035; orchestration remains
disabled and publication remains held for ratification.

## Correct tier direction

The gateway's authoritative tier convention is **lower number = stronger
protection**. A requirement of tier 2 permits routes at tiers 1 or 2 and refuses
tiers 3–5. Inspection of `gateway/app/tier_floor.py` exposed reversed comparisons
in the unpublished orchestration contracts/store/current-policy checks. Those
comparisons are corrected:

- A child cannot use a numerically higher, weaker requirement than its root.
- Scope must satisfy the numerically lowest requirement among operator and skill.
  Missing skill metadata adds no extra restriction; it does not imply tier 1.
- Plan preparation, revision, approval and execution check the project's current
  requirement. Tightening a project from tier 3 to tier 2 blocks further effects
  under a tier-3 plan. A stricter plan remains valid under a weaker project floor.
  An unset project floor adds no restriction beyond the explicit plan.

These corrections precede connecting the new inference adapter to workers. They
do not change the established gateway or ordinary single-session tier semantics.
The separate external-tool egress ceiling remains a separate constraint.

## Direct route and current price

`OperatorPolicy.inference` is optional and disabled when absent. Its immutable
`InferencePolicy` names one provider/native-model pair and bounds input bytes and
output tokens. These selections form part of the operator-policy approval hash.
The production binding uses these fields, never model-authored route suggestions
or the fixture adapter's model/quote settings.

`InferenceRoutes` reads fresh gateway configuration outside control/outcome
transactions. It refuses missing, duplicate or disabled providers, a slash-named
alias shadowing the direct model key, a weaker-than-approved routed tier, disabled
pricing, and missing, negative, nonfinite or unrepresentable rates. Tier derivation
matches gateway precedence: pair override, provider override, provider-type
default, provider tier. Explicit zero input/output rates are valid.

The existing gateway direct `provider/model` route has one target and no fallback
chain. Orchestration does not implement its own alias resolver or select another
provider after an error. Policy is checked again after configuration I/O, and the
store refreshes authority and remaining lease time before the guarded call.

Approved anonymization and privilege fields still reach the gateway. If
anonymization is required for a non-privileged request, configuration must enable
it at the chosen tier. Privileged requests retain the gateway's existing behavior:
they deliberately skip rewriting. This check is not a claim that entity detection
removes every sensitive value or supports every language.

The binding includes the exact pinned-message digest, direct route, derived tier,
rates, estimated input count, reservation and a public configuration fingerprint.
The guarded boundary checks the message/route/output-limit match. Those fields
also form part of the durable effect identity. Equivalent rate spellings hash
consistently; changed pricing cannot silently reuse an existing effect key.

## Accounted estimates and observed usage

The declared estimate uses UTF-8 input bytes plus 96 units for two-message and
completion framing, with the approved maximum output tokens. This is a conservative
**accounting convention**, not a universal tokenizer bound. Rates use exact Decimal
arithmetic and costs round upward to the existing four-decimal money quantum.

Reservation and settlement follow the existing durable guard transactions. The
accounted charge is the greater of the reserved estimate and the cost calculated
from gateway-reported usage at the bound rates. Reported usage cannot prove that
all provider-billable work was measured, so a lower observation does not refund
the estimate. A larger observation is recorded in full; if it exceeds the account
allocation, the store records the overrun and stops further work. Free configured
routes remain zero-cost.

The internal receipt labels the accounting basis and records estimated input,
reservation, reported-usage cost, charge, provider/model and configuration digest.
Reported usage is not labeled a provider-invoice actual. Completion finish reason
is retained separately: truncated/filtered output does not establish complete or
verified research. Receipt bounds and current authority still apply on recovery.

The gateway now stamps `routed_model` on non-streaming responses from its resolved
target. Upstream `model` may contain a different version label; orchestration uses
the gateway's target metadata instead. The backend mirror and gateway OpenAPI
sketch include the additive response field. No new request metadata goes to the
provider. A bound response must match provider, resolved model, tier and expected
anonymization state, with valid content, usage observations and finish reason.
Older gateways missing that metadata cannot complete bound effects.

Cancellation, failed/malformed responses, changed response routing or failed
settlement preserve uncertain reservations. Bound transport errors do not copy
provider error text into logs or persisted observations. Completed receipts avoid
another provider call and charge, subject to current configuration/authority.

## Remaining gates and validation

The subsequent [gateway revision increment](issue-563-configuration-revisions.md)
checks the API-bound revision before dispatch and pins the gateway configuration
and matching adapter through the request. This covers aliases added after API
resolution, provider configuration and configured rates. Coordinated policy
distribution remains a production gate. A configuration snapshot cannot establish
actual provider billing or a guaranteed invoice ceiling; dispatch remains disabled. Runtime/policy semantics have changed on
this unpublished branch; recreate local fixture runs rather than assume existing
checkpoint compatibility.

[Required authority anonymization](issue-563-authority-anonymization.md) is now
implemented for supported operations. CourtListener composite operations, worker topology,
shared capacity, leases/wakeups, pre-approval planning, child joining and public
API/UI remain in the [workflow](issue-563-workflow.md).

Tests use disposable Postgres and stub providers. They cover direct route/price
binding, tier precedence, approval/resource enforcement, invalid/free rates,
shadowing aliases, input limits, anonymization requirements, halt/revocation
during configuration reads, uncertain outcomes, cancellation, completed-effect
reuse and full observed overrun accounting. Gateway HTTP fixtures prove
`routed_model` comes from the selected target for aliases and direct routes even
when upstream reports a different model label.

Validation with locked dependencies and disposable Postgres:

- API: **2,919 passed, one skipped** in 221.82 seconds (`pytest -n 4 -q`).
- Gateway: **796 passed, three skipped** in 12.05 seconds (`pytest -q`).
- Orchestration/contracts: **250 passed** in 9.04 seconds.
- Final bound-inference checks, including the typed transport-error regression:
  **31 passed** in 2.24 seconds.
- Ruff check/format, mypy (**200 API / 56 gateway files**) and diff checks passed.

The initial focused run caught an incorrect ORM field name in the test assertions;
those assertions were fixed. The first gateway run could not load the existing
spaCy model in the new virtual environment; the model was installed and the full
suite then passed, including real local anonymization tests. Provider responses
remained stubbed throughout. No feature was enabled or code published.
