# ADR 0016 — Transparency and governance invariants (the engineering posture, made enforceable)

**Status:** Proposed
**Date:** 2026-06-20
**Owner:** Maintainer team (transparency-posture hardening)

## Context

LQ.AI's reason for existing is **transparency**: every artifact that shapes the
user experience is visible, auditable work product, and the operator/admin keep
complete visibility and control over their data ([PRD §1.3](../PRD.md#13-transparency-as-a-founding-principle),
[§1.8](../PRD.md#18-security-posture)). That posture is real in the code today —
the single audited egress boundary (ADR [0014](0014-gateway-egress-boundary-for-tool-providers.md)),
the closed-set governed tool-calling model (ADR [0015](0015-governed-tool-calling-model.md)),
the counts-and-types-only audit logs ([audit-logging.md](../security/audit-logging.md)),
and the fail-restrictive governance substrate (`api/app/tools/governance.py`).

But it is enforced almost entirely by **review culture** (CLAUDE.md, the ADRs,
[CODEOWNERS](../../.github/CODEOWNERS)) rather than by **gates**. CI runs ruff +
mypy + pytest + the OpenAPI/route collision guards — none of which fail when a
change quietly violates the posture: nothing stops a contributor from adding a
raw-payload column to an audit table, making the backend call a third-party
endpoint directly, or committing an audit row outside its state-change
transaction.

This ADR does two things. It **names the invariants** that, taken together, *are*
the product — so they have the same decision-record status as the architecture
they protect — and it **makes the cheap-to-check ones enforceable in CI** so the
posture survives contributors and coding agents who have not internalised the
culture. Each invariant restates an existing decision; this ADR is a
consolidation and a hardening, not a new direction.

## Decision drivers

1. **An invariant the reviewer must remember is an invariant that eventually
   slips.** The recurring-pitfalls history in CLAUDE.md (the 204-DELETE
   assertion, the route-count collision guards) shows the pattern: a rule that
   lives only in prose or code comments re-breaks. The fix that holds is a test
   that fails at collection.
2. **Transparency is a property of the *whole* codebase, not just `gateway/`.**
   Security review is routed to `gateway/**` and `docs/security/**`, but the
   backend now holds half the governance surface (`api/app/tools/`,
   `api/app/autonomous/guard.py`). The invariants must bind there too.
3. **A gate with false positives gets disabled.** Every enforced check here is
   designed to be green on current `main` and to trip only on a genuine
   violation, with an explicit, documented escape hatch (an allowlist a
   contributor must consciously extend) rather than a blunt grep.
4. **Contributors and agents need one place to check themselves.** The
   pre-flight checklist (the PR template) and these invariants are the same list,
   stated once.

## Decision

The following ten invariants are binding for every change to this codebase. Each
cites the prior decision it restates and the enforcement that backs it.
"Enforced" = a CI-failing test exists; "reviewed" = checked by humans/CODEOWNERS
and the PR-template checklist (no automated gate yet — candidate for a follow-up).

### P1 — One audited egress boundary

All outbound calls to anything outside the operator's own infrastructure go
through the Inference Gateway. The backend (`api/`) holds no third-party
credentials and makes no third-party calls — including OAuth token exchange,
which is gateway-passthrough (ADR-0014-pure). *Restates ADR 0014 D1; rejects the
backend-direct-egress shape.*
**Enforced:** `api/tests/test_transparency_invariants.py::test_backend_makes_no_direct_third_party_egress`
— scans `api/app/` for outbound HTTP clients (`httpx`/`requests`/`aiohttp`/
`urllib.request`) and fails unless the only user is the gateway client
(`app/clients/gateway.py`, the documented allowlist).

### P2 — Closed set, operator-configured — never an open surface

The model and the autonomous layer choose *among* an operator-enabled allowlist;
they can never reach beyond it. A new model-invokable capability is a new
bounded, declared entry on an operator-controlled list, not a general-purpose
hook. *Restates ADR 0015 alternative A / D1; rejects open function-calling.*
**Reviewed.**

### P3 — Counts and types, never payloads

Audit and log rows record *that* something happened, its shape, and its
outcome — never the content. No raw arguments, tool results, message bodies,
fetched text, or cryptographic material lands in any row or log line; only ids,
counts, tiers, digests, and outcome labels. *Restates ADR 0014 D3, ADR 0015 D2,
[audit-logging.md](../security/audit-logging.md) "What is NOT logged".*
**Enforced:** `test_audit_models_have_no_raw_payload_columns` — introspects the
audit/log ORM models (`ToolCallLog`, `AuditLog`, `ToolEgressLog`,
`InferenceRoutingLog`) and fails if a column name implies content (`*_body`,
`*_payload`, `*_content`, `raw_*`, `args`, `result`, …). The OTel span-hygiene
case is already covered by
`api/tests/test_tool_governance.py::test_tier_refusal_annotates_span`.

### P4 — Fail restrictive, never open

Missing config, an unknown provider, or a failed lookup resolves to the
*most-restrictive* outcome, not a permissive fallback. A guard that fails open is
a bug even when every happy-path test passes. *Restates the `governance.py`
`_MAX_TIER` fail-safe (ADR 0015 D-a2).*
**Enforced:** `test_fail_safe_tier_is_most_restrictive` (the most-restrictive
tier is the ceiling 5) plus the existing
`test_tool_governance.py::test_resolve_provider_tier_fail_safe_*`.

### P5 — Atomic audit: no state change without its audit row, and vice-versa

Audit/governance writes `flush()` inside the caller's transaction; the handler
commits the state change and the audit row in one boundary. There is no
"did-it-but-didn't-log-it" and no "logged-it-but-didn't-do-it" failure mode.
*Restates `app/audit.py` and `governed_tool_invocation` flush-not-commit.*
**Enforced:** `test_governance_and_audit_helpers_do_not_commit` — AST-parses
`app/audit.py` and `app/tools/governance.py` and fails if either calls
`.commit()` (AST, so docstring/comment mentions of commit don't false-positive).

### P6 — One governance path, not two

Chat and the autonomous layer share a single substrate
(`governed_tool_invocation`; `guarded_tool_call` delegates to it). A new caller
reuses the helper; it does not re-derive tier/cost/audit logic. *Restates ADR
0015 L6.* **Reviewed** (CODEOWNERS should route `api/app/tools/` +
`api/app/autonomous/guard.py` to security — see "Follow-ups").

### P7 — A human gate for every irreversible action

Anything `destructive` / `requires_confirmation` cannot fire unattended: it is
gated behind explicit human approval in chat and excluded from autonomous grants
entirely in v1. *Restates ADR 0015 D4.*
**Enforced:** the destructive-exclusion behaviour is covered by
`api/tests/autonomous/test_guard_external_tool_intents.py`.

### P8 — Operator visibility and control over every capability

Every tool / provider / data source has an explicit operator-owned enable/disable
and appears on an admin surface. A capability the operator cannot see or turn off
does not ship. *Restates the `mcp_tools.enabled` + `/admin/mcp` +
`gateway.yaml` `tool_providers:` design.* **Reviewed.**

### P9 — The user owns their data

Outbound matter context is anonymized by default; public inbound text stays
verbatim only because citation grounding requires it. Users can export and delete
their own data; deletion anonymizes the actor but preserves the audit trail.
*Restates ADR 0014 D5 and the user-export/deletion behaviour in
[audit-logging.md](../security/audit-logging.md).* **Reviewed.**

### P10 — The contract is the source of truth; surface forks, don't decide silently

The OpenAPI sketches, the DB schema doc, and the relevant ADR are updated in the
*same* PR as the code. A change that hides an architectural / authz / scope
decision stops and puts options to a maintainer rather than choosing
unilaterally. *Restates CLAUDE.md decision-routing.*
**Enforced (partial):** the OpenAPI/route collision guards
(`test_openapi.py`, `test_endpoints.py`) already pin the API contract;
documentation/ADR currency is **reviewed** via the PR-template checklist.

## Enforcement summary

| Invariant | Status | Backing |
|---|---|---|
| P1 one egress boundary | Enforced | `test_backend_makes_no_direct_third_party_egress` |
| P2 closed set | Reviewed | CODEOWNERS + PR template |
| P3 no raw payloads | Enforced | `test_audit_models_have_no_raw_payload_columns` + span-hygiene test |
| P4 fail restrictive | Enforced | `test_fail_safe_tier_is_most_restrictive` + governance fail-safe tests |
| P5 atomic audit | Enforced | `test_governance_and_audit_helpers_do_not_commit` |
| P6 one governance path | Reviewed | CODEOWNERS (follow-up) + PR template |
| P7 human gate | Enforced | `test_guard_external_tool_intents` |
| P8 operator control | Reviewed | PR template |
| P9 user owns data | Reviewed | PR template |
| P10 contract is truth | Enforced (partial) | OpenAPI/route guards + PR template |

## Follow-ups (out of scope for this ADR; tracked for a maintainer-buy-in PR)

These are higher-value but heavier or touch the security-gated
`.github/workflows/**` surface, so they ship separately:

- **CODEOWNERS** — route `api/app/tools/` and `api/app/autonomous/guard.py` to
  `@legalquants/security` so the backend half of the governance surface gets the
  same review as `gateway/**` (P6).
- **Audit-coverage gate** — assert every state-changing (non-GET) route emits an
  `audit_action` (allowlist of `action=` literals) or is explicitly annotated
  no-audit (P5/P10).
- **Capability enable/disable gate** — assert every registered tool provider
  exposes an `enabled` flag and appears on the admin surface (P8).
- **CI infrastructure** (`.github/workflows/**`, security-gated): secret
  scanning (gitleaks/trufflehog), dependency audit (`pip-audit`), and coverage
  no-decrease — none exist in `ci.yml` today.
- **mypy --strict** for `api/app/tools/` even while the rest of `api/` stays
  standard mode (P6).

## Cross-references

- ADR [0013](0013-autonomous-layer-design-influences.md) (closed `ToolIntent`,
  `PHASE_GRANTS`, R5→R6→R4, audit/OTel counts-only),
  [0014](0014-gateway-egress-boundary-for-tool-providers.md) (egress boundary),
  [0015](0015-governed-tool-calling-model.md) (governed tool-calling).
- PRD [§1.3](../PRD.md#13-transparency-as-a-founding-principle),
  [§1.8](../PRD.md#18-security-posture), [§5.3](../PRD.md) (audit requirement).
- [docs/security/audit-logging.md](../security/audit-logging.md),
  [docs/security/threat-model.md](../security/threat-model.md).
- [CLAUDE.md](../../CLAUDE.md) (decision routing, the build loop, common
  pitfalls), [.github/CODEOWNERS](../../.github/CODEOWNERS).
- Enforcement: `api/tests/test_transparency_invariants.py`;
  `.github/PULL_REQUEST_TEMPLATE.md` (the contributor pre-flight checklist).
