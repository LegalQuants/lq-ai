# #563 — Gateway configuration revisions

Status: implemented and tested locally; ADR ratification and publication remain
open. Orchestration dispatch remains disabled.

## Request contract

Fresh API-side route and price checks previously left a gap before the gateway
dispatched a request: an operator could change an alias, endpoint, tier or rate
after the API read the configuration. Response metadata could detect some
changes, but could not prevent the resulting egress.

`GET /admin/v1/config` now includes an opaque `configuration_revision`: the
SHA-256 digest of the complete validated configuration and dispatch contract
version serialized as canonical JSON. The subsequent
[authority anonymization increment](issue-563-authority-anonymization.md) adds
contract version 2 so older replicas cannot ignore its required transform. The digest includes credential configuration; the response continues to
strip encrypted credential fields. Environment variable names are included,
but their resolved values are not. This is a consistency identifier, not an
authorization credential. Any configuration change, even unrelated to the
selected provider, invalidates the previous revision.

`InferenceRoutes` and `AuthoritySources` require this revision in their immutable
bindings. The binding participates in the effect identity. The gateway client
sends it in `X-LQ-AI-Config-Revision` on the bound request, separately from the
provider payload. No revision is forwarded to the upstream provider.

For checked non-streaming direct inference and named tool calls, the gateway:

1. Compares the supplied revision with its current validated configuration.
2. Checks that the selected adapter was built from the matching provider
   configuration. Startup and runtime adapter factories record this provenance.
3. Captures a deep copy of the configuration and copies of the adapter registries
   without awaiting. Routing, tier checks, configured anonymization, dispatch and
   response pricing use this request's snapshot.
4. Echoes the accepted revision in the successful response header. The API client
   refuses a missing or different acknowledgement.

Malformed or stale revisions, missing/obsolete adapters, aliases (including an
alias named like a direct route) and checked streaming requests receive HTTP 412
with `configuration_revision_mismatch` before provider dispatch. Existing callers
that omit the header retain their existing routing behavior. Older gateways
without the config revision cannot supply a bound orchestration effect.

## Updates, failures and remaining limits

An accepted call may finish using its original snapshot after a hot update;
subsequent calls must use the new revision. Existing retired-adapter handling
keeps the old adapter open until shutdown. A configuration-only reload that
changes provider settings refuses checked calls until the adapter is rebuilt or
the gateway restarts. A fresh revision alone cannot make an obsolete adapter
acceptable. Out-of-band changes to environment secrets or upstream services are
not versioned by this digest.

No control database locks are held over provider I/O. A gateway refusal currently
follows the same conservative uncertainty path as other dispatch failures: the
effect reservation stays held and the request is not automatically retried.
Missing acknowledgements likewise cannot establish whether an effect occurred.
Special handling to release a proven pre-dispatch refusal is not implemented.

The snapshot is local to one gateway request. It does not distribute current
operator policy across workers, establish a provider invoice ceiling or revoke
an already accepted call. Required authority anonymization is now implemented
for supported operations; shared capacity, worker leases and
wakeups, phase reconciliation, pre-approval planning, joining and public API/UI
remain in the [workflow](issue-563-workflow.md).

## Validation

Gateway HTTP fixtures use real startup/adapter factories and stubbed providers.
They check stale and malformed revisions, request-header isolation, successful
acknowledgements and config reload with an obsolete adapter followed by a rebuilt
adapter. A race fixture changes aliases, rates and the live adapter registry
after acceptance: the accepted call retains its original target and pricing,
while a subsequent call with the old revision is refused before provider I/O.

API-client fixtures cover matching, missing and different acknowledgements for
both inference and tools. A migrated disposable-Postgres fixture uses the real
gateway client to receive a 412, verifies the effect stays uncertain/reserved and
proves a second attempt does not dispatch again. Bindings also reject a missing
or malformed revision before admitting an effect.

Validation with locked dependencies:

- Full API: **2,930 passed, one skipped** in 219.81 seconds (`pytest -n 4 -q`).
- Full gateway after final route/obsolete-adapter checks: **809 passed, three
  skipped** in 11.93 seconds (`pytest -q`).
- Focused orchestration and gateway-client checks: **215 passed** in 10.09 seconds.
- Ruff check/format and mypy passed for both services (**200 API / 57 gateway
  source files**). Gateway OpenAPI YAML parses and all local references resolve;
  diff whitespace checks pass.

The documentation check caught a missing newline in the new OpenAPI response
header, which was corrected before validation passed. Provider requests were
stubbed and the API suite used its own disposable Postgres container. No live
providers, development/production migrations or feature flags were used.
