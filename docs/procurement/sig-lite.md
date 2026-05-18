# SIG Lite — Privileged-Matter Handling (M2-D3 starter scope)

> **Scope of this file**: a **focused starter** covering only the SIG Lite questions whose answers depend on the privileged-project handling implemented in M2-B3 / verified in M2-D3. The **full Procurement-Readiness Pack** (every SIG Lite domain, plus CAIQ, plus cover letter) is **out of scope here** and tracked as [DE-086](../PRD.md#de-086--procurement-readiness-pack); this file is the starter for that work.
>
> Operators reviewing this file for their own procurement cycle should treat it as a complement to (not a substitute for) the full SIG Lite questionnaire. Items not covered here either don't bear on privileged-matter handling or belong to a SIG Lite domain DE-086 will fill in.

---

## How to read this file

Each question below follows the format established in [`docs/procurement/README.md`](README.md):

- **Question** — text from the SIG Lite questionnaire (paraphrased where the source uses domain-specific shorthand).
- **Project response** — the answer applicable to a standard LQ.AI deployment with privileged matters configured per the recommended posture.
- **`[OPERATOR-CONFIGURABLE]`** — where the answer depends on operator-specific deployment choices.
- **References** — relevant PRD sections, security artifacts, and code-side enforcement points.

---

## Data Protection & Privacy Domain (D — selected questions)

### D.1.3 — How is sensitive data classified, and what controls apply to each classification?

**Project response.** LQ.AI provides a two-tier classification mechanism at the application layer:

1. **Non-privileged matters** — the default. Anonymization Layer (PRD §4.7) pseudonymizes user/assistant chat content before transmission to the configured inference provider; retrieved source documents remain un-pseudonymized so the model can reason against intact source text (per [Decision M2-1](anonymization.md#what-gets-pseudonymized)). The pre-anonymization step covers the standard Presidio entity set (PERSON, ORGANIZATION, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION) plus two custom legal recognizers (CaseNumberRecognizer, MatterNumberRecognizer per M2-B2). The post-anonymization step rehydrates pseudonyms back to originals in the model's response before it reaches the user.

2. **Privileged matters** — explicit operator/user designation via the `Project.privileged` flag (`docs/db-schema.md` → `projects` table). Anonymization is **disabled** for chats inside privileged projects (per [Decision A — privileged-skip](anonymization.md#privileged-chats--why-we-skip-m2-b3--m2-d3)): the content reaches the provider verbatim because rewriting privileged work product risks corrupting it and may complicate later assertion of privilege over the artifact. Privileged projects pair with `minimum_inference_tier` (DB CHECK constraint enforces non-NULL when `privileged=true`) so the operator can require local-only (Tier 1) routing for the most sensitive matters.

The control set differs by classification:

| Control | Non-privileged | Privileged (Tier 1 local) | Privileged (Tier 2+ ZDR) |
|---|---|---|---|
| Pre-transmission pseudonymization | Yes | N/A (no transmission) | No |
| Tier-floor enforcement (gateway) | Optional per project | Tier 1 required | Tier 2+ allowed per project setting |
| Audit `privilege_marked` | `false` | `true` | `true` |
| Audit `privilege_basis` | NULL | `project:<name>` | `project:<name>` |
| Provider sees raw entity names | No (pseudonymized) | N/A (local) | Yes |

**References:** [`docs/security/anonymization.md` §What gets pseudonymized](anonymization.md#what-gets-pseudonymized); [`docs/security/anonymization.md` §Privileged chats](anonymization.md#privileged-chats--why-we-skip-m2-b3--m2-d3); PRD §1.5.2 (Inference Tiers), PRD §4.7 (Anonymization Layer).

**Honest validation posture for non-privileged classification.** The pseudonymization control described above runs on every non-privileged chat. Its **mechanism** (pre-substitute, transmit, post-rehydrate; per-request mapper, never persisted) is exercised end-to-end by integration tests including the round-trip correctness suite. Its **recognizer accuracy on legal-document corpus** is empirically unmeasured — Presidio's published metrics target general English (news, social media), not legal prose. Procurement reviewers evaluating residual-risk should read [`docs/security/anonymization.md` §"What's validated vs what's unvalidated"](anonymization.md#whats-validated-vs-whats-unvalidated) for the explicit "where to trust and where to be careful" framing, including the explicit "route to Tier 1 (local Ollama) if the unvalidated risk is unacceptable" guidance. Empirical validation on a curated legal-document corpus is welcomed as a community contribution per [PRD §9 / DE-282](../PRD.md#de-282--anonymization-layer-empirical-validation-on-legal-document-corpus).

---

### D.2.7 — Are any controls applied to data classified as attorney work-product or covered by attorney-client privilege?

**Project response.** Yes. The application provides a first-class **privileged-project** designation that:

1. **Bypasses pseudonymization end-to-end.** The pre-anonymization middleware short-circuits when the incoming request carries `lq_ai_privileged=true` (`gateway/app/anonymization/middleware.py`); the response-path rehydrator is a no-op because nothing was substituted on the request path. The content reaches the inference provider exactly as the user composed it.

2. **Audit-logs the privilege designation as a first-class column.** Every state-changing action on a privileged-project resource writes an `audit_log` row with `privilege_marked=true` and `privilege_basis="project:<project name>"`. The column is indexed and queryable; operators querying for "every action against privileged-matter content over date range X" use `SELECT * FROM audit_log WHERE privilege_marked = true AND timestamp BETWEEN ...`. The CHECK constraint `chk_audit_log_privileged_with_basis` enforces that `privilege_marked=true` rows always have a non-NULL `privilege_basis`.

3. **Honors a per-project tier-floor.** Privileged projects must declare a `minimum_inference_tier` (DB CHECK constraint `chk_projects_privileged_implies_tier`). The gateway's tier-floor logic (PRD §4.4) refuses any routing weaker than the declared tier with HTTP 403 `tier_below_minimum`. The recommended configuration for privileged matters is `minimum_inference_tier=1` (local Ollama only) so the content never leaves the operator's deployment.

4. **Preserves Citation Engine functionality.** Citation verification operates on the chat content directly; no special-casing for privileged projects. A privileged-matter chat with attached source documents produces verified citations exactly as a non-privileged chat does.

**`[OPERATOR-CONFIGURABLE]`** — The operator decides which projects are privileged and which tier floor applies per project. The default posture for new projects is non-privileged + no tier floor; operators set the privileged flag and tier floor when creating or updating the project (`POST /api/v1/projects`, `PATCH /api/v1/projects/{id}`).

**`[OPERATOR-CONFIGURABLE]`** — For privileged matters routed at Tier 2 (enterprise ZDR upstream) rather than Tier 1 (local), the operator's procurement agreement / DPA / BAA with that provider is the binding contractual control covering the unsubstituted content. The application surfaces what tier was used per request via `inference_routing_log.routed_inference_tier`; the contractual control is the operator's responsibility to negotiate and maintain with the upstream.

**References:** [`docs/security/anonymization.md` §Privileged chats](anonymization.md#privileged-chats--why-we-skip-m2-b3--m2-d3); PRD §3.11 (Projects), PRD §4.4 (Tier-Floor Enforcement), PRD §5.3 (Audit Log); `api/app/audit.py::_resolve_project_privilege`; `gateway/app/anonymization/middleware.py` skip conditions.

---

## Audit & Logging Domain (L — selected questions)

### L.2.5 — Are administrative actions on customer data logged in a tamper-evident manner?

**Project response.** Yes, with the following posture:

- **Append-only at the application layer.** The `audit_log` table has no UPDATE or DELETE paths exposed through the API; every state-changing action writes one row at the time of the action. The audit-log writer (`api/app/audit.py::audit_action`) is the only authorized writer; the row is added to the request's outer transaction so the audit row commits atomically with the underlying state change (no audit row without a state change; no state change without an audit row).

- **First-class privilege + tier columns.** The privilege fields (`privilege_marked`, `privilege_basis`) and the routing fields (`routed_inference_tier`, `routed_provider`) are first-class columns rather than JSONB so audit queries can filter on them efficiently. The CHECK constraint `chk_audit_log_privileged_with_basis` prevents writing `privilege_marked=true` without a `privilege_basis`.

- **Request correlation.** Each row carries a `request_id` (the X-Request-ID header value) so audit-log entries cross-reference to gateway `inference_routing_log` rows and application logs.

**`[OPERATOR-CONFIGURABLE]`** — Tamper-evidence at the **DB level** (e.g., row-level signatures, append-only Postgres extensions, periodic snapshot hashes) is the operator's responsibility per their deployment posture. The application does not implement cryptographic tamper-evidence on `audit_log` rows in v0.2; operators with that requirement typically address it via Postgres-level controls (immutable schemas, role-restricted writes, WAL archiving with integrity checking).

**`[OPERATOR-CONFIGURABLE]`** — Retention policy for `audit_log` is operator-controlled. The application writes rows indefinitely; operators with retention-period requirements run a periodic `DELETE FROM audit_log WHERE timestamp < ...` job sized to their policy.

**References:** [`docs/db-schema.md` `audit_log` table](../db-schema.md#audit_log); PRD §5.3 (Audit Log).

---

### L.3.2 — Can administrators surface every action taken on a customer's data within a defined time window?

**Project response.** Yes, via the `GET /admin/audit-log` endpoint (admin-gated). Query parameters include `user_id`, `resource_type`, `resource_id`, `action`, `privilege_marked`, `routed_inference_tier`, `from_timestamp`, `to_timestamp`. The response is paginated (default 100 rows; max 500) so large windows can be walked with cursor-style pagination.

For privileged-matter compliance evidence specifically: `GET /admin/audit-log?privilege_marked=true&from_timestamp=...&to_timestamp=...` returns every audited action against privileged-project resources in the window. Cross-reference to the gateway's `inference_routing_log` table (joined on `request_id`) yields the full pipeline view including which provider/model handled each request and whether anonymization fired.

**References:** [`api/app/api/admin.py` audit-log endpoint]; PRD §5.3 (Audit Log).

---

## Out of scope for this file

The full SIG Lite questionnaire covers 18 domains spanning data protection, access controls, network security, vulnerability management, incident response, business continuity, supplier management, and more. This starter file covers only the questions whose responses materially differ depending on the privileged-project handling.

For the full procurement-readiness pack — pre-filled responses across every SIG Lite domain plus CAIQ Lite plus a cover letter template — see [DE-086](../PRD.md#de-086--procurement-readiness-pack). Community contributions to that work are explicitly welcomed; see [`docs/procurement/README.md` §Contributing](README.md#contributing) for the contribution path.
