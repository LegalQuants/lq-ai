# #563 — Bound authority-source effects

Status: local implementation under proposed ADR 0035. No public dispatch or
ordinary worker enables this adapter. Publication remains held for ratification.

## Binding and dispatch

`AuthoritySources` resolves one approved configured **provider name** and operation
against the current operator policy and a fresh gateway admin-config read. This
read runs outside both control and outcome transactions. It refuses missing,
duplicate, disabled, retyped or retiered entries. A provider of the same type is
never a substitute for the selected provider. The resolver and dispatch must use
the same gateway client. Policy is checked again after configuration I/O, and the
store refreshes authority and remaining lease time before guarded admission.

GovInfo and EDGAR support their registered search/retrieval operations; EUR-Lex
supports retrieval only. CourtListener's service has composite operations and no
authority response adapter, so it remains closed here. MCP is outside the research
profile. A selected source does not establish a task's jurisdiction or skill
coverage; the plan builder still owes that check.

Each binding carries the selected source policy, operation, explicit Decimal
per-call rate and a hash of public routing/accounting configuration. The effect
identity includes that binding. Equivalent decimal spellings hash consistently;
changed routing/pricing cannot silently reuse a prior effect key. No admin payload,
credential field, internal run ID or policy/budget object is sent as provider args.

`GuardedEffects.authority()` copies bounded arguments before its first await and
calls the existing `guarded_tool_call` chokepoint. R5/R6 and durable R4 admission
remain required. The same binding supplies the governance audit marker, actual
gateway provider/operation, tier check and configured accounting charge. It does
not call legacy provider discovery, tier caches or pricing resolvers. The approved
maximum egress tier is sent on the gateway request as well as checked locally.

The response's provider, operation and tier must match the binding, and its payload
must be an object. Search preserves all returned candidates. An explicit empty
results array is successful work; absent or malformed results are uncertain after
dispatch. Retrieval normalizes through the existing source adapter. Evidence stays
in the bounded durable effect receipt; this path does not write the shared
authority cache or perform a second object-storage action. Successful search does
not imply exhaustive coverage or verified legal conclusions.

The existing effect adapter commits the tool-call audit, outcome receipt, account
settlement and session charge together. Cancellation or untrustworthy responses
roll back that outcome transaction, retain the admitted reservation, fence the
worker and require reconciliation. A completed receipt avoids another provider
call and charge. Current authority/configuration checks still apply to recovery;
this increment does not permit replay under revoked or changed configuration.

## Accounting and enablement limits

- `cost_per_call` must be explicit, finite, nonnegative and representable in the
  existing four-decimal money contract. Explicit zero is valid, including JSON
  numeric zero; missing pricing never means free for orchestration. Nonzero or
  malformed `cost_per_unit` is refused because no variable-unit meter is bound.
- The price is a configured **accounted** per-call charge, not a measured provider
  invoice. The later [direct inference binding](issue-563-inference-bindings.md)
  supplies current token pricing; inference aliases/fallbacks remain closed.
- The subsequent [authority anonymization increment](issue-563-authority-anonymization.md)
  binds a required transform to current provider/configuration capability and
  checks its acknowledgement. Search prose is pseudonymized; sensitive or
  malformed reference arguments refuse. Public response evidence stays verbatim.
  Arbitrary legacy/MCP argument anonymization remains outside this profile.
- The subsequent [gateway revision increment](issue-563-configuration-revisions.md)
  checks the API-bound configuration revision before tool dispatch, requires the
  selected adapter to match its provider configuration and pins both for the
  request. Shared policy distribution remains a production gate. Configuration
  changes after acceptance affect subsequent calls; the configured per-call
  charge still does not establish an invoice cap.
- Shared capacity, the arq/LangGraph worker topology, lifecycle/reconciliation,
  pre-approval planning, visible orchestration instructions, child joining and the
  public API/UI remain in the main workflow. Evidence exceeding the receipt size
  bound is not silently truncated or reported as complete.

## Validation

Tests use migrated disposable Postgres and stubbed gateway configuration/provider
responses. They cover exact selection among providers of the same type, explicit
free/unknown/invalid/variable pricing, changed configuration and reused effect
keys, equivalent decimal spellings, all three authority adapters, empty and
multiple search results, source/operation scope refusal, required anonymization,
halt and policy revocation during configuration I/O, cancellation, response
mismatch, atomic accounting/audit and completed-receipt reuse.

Full API regression (`pytest -n 4 -q`): **2,881 passed, one skipped** in 210.96
seconds. Final orchestration and guard checks, including the subsequent numeric
rate magnitude guard: **155 passed** in 11.58 seconds, including **35** source
cases. Ruff check/format, mypy (**199 source files**) and `git diff --check` passed.
The [workflow](issue-563-workflow.md) records remaining work. No live providers,
production migrations, feature enablement or publication were involved.
