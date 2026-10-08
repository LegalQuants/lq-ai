# ADR 0042 — Workspace events, Today View, and read-only email triage

- **Status:** Proposed — draft for contributor review, then maintainer review.
- **Draft date:** 2026-10-08.
- **Scope:** Internal workspace signals first; governed, read-only email signals later.
- **Related roadmap:** PRD DE-201, DE-202, DE-208 and DE-209; existing DE-200 MCP foundation.
- **Tracks:** [Issue #256](https://github.com/LegalQuants/lq-ai/issues/256).
- **ADR number:** 0042 (provisional; maintainers may renumber before merge).

## 1. Summary

Introduce a small internal `WorkspaceEvent` model, build a chronological Today View over it, and
then add optional read-only email ingestion through the existing governed MCP path. Add advisory
email triage only after ingestion, access controls and data-lifecycle handling have been reviewed
and tested.

This is a staged proposal, not permission to implement the entire roadmap. The first PR contains
this ADR only. Each later PR delivers one bounded, testable change and waits for maintainer review
before the next dependent stage proceeds.

## 2. Meeting agreement and review process

The contributor reports that the ADR meeting agreed to proceed slowly through small commits and
incremental, maintainer-reviewed PRs, rather than deliver the work in one large chunk.

This document records that delivery approach. It does **not** claim that every technical detail
below was approved at the meeting, or invent meeting minutes, attendees or an approval date.

The working cycle is:

1. Agree on the next small scope and its acceptance checks.
2. Implement it in focused commits, with the relevant tests and documentation.
3. Submit a small PR explaining the change, evidence, risks and rollback.
4. Address maintainer feedback and amend the proposal where needed.
5. Proceed to the next dependent slice after review and acceptance.

Incremental delivery means small reviewable PRs, not merely many small commits inside one large PR.
Every intermediate merged state must remain usable without the later stages.

## 3. Context and existing foundation

The inspected checkout already has gateway-brokered MCP connectivity, governed tool invocation,
audit infrastructure and autonomous research capabilities. Existing research automation or SMTP
notifications are not equivalent to a mailbox-reading and filing agent.

The PRD describes signal aggregation, basic chronological Today View, email connectors and email
triage as forward-looking work. This proposal narrows that direction into independently reviewable
increments. It does not introduce automatic email filing.

The architectural concern is avoiding separate, incompatible representations for documents, research
findings and future connector signals. Today View should not require the frontend to merge an
expanding set of source-specific endpoints or independently implement permissions, deduplication and
freshness rules.

## 4. Proposed architectural boundary

### 4.1 Establish a minimal workspace-event substrate first

Use `WorkspaceEvent` as the common representation of a chronological workspace signal. It is a
product-facing index of signals, **not** a replacement for the security audit log, a full copy of
source content or a platform-wide event-sourcing rewrite.

The proposed minimum contract covers:

| Concern | Proposed information |
| --- | --- |
| Identity and ownership | Event ID and owning user; optional project association |
| Source | Source kind and stable, scoped source reference |
| Meaning and lifecycle | Event type and defined status |
| Time | Source occurrence time, observation time, creation/update time |
| Provenance | Producing service or connector, relevant source/tool references, freshness and receipt/audit reference where available |
| Protection | Sensitivity classification and applicable access/tier controls |
| Deduplication | Stable digest/key within the owner and source namespace |

Exact column names, status enums and constraints belong in the first implementation PR. Keep source
references scoped to the owner and connector/mailbox where applicable; a provider message ID alone
is not a globally unique identity.

Start with one internal source. Preserve source authorization when producing and displaying events.
Source deletion or access revocation must not leave an event that exposes inaccessible content.
Avoid copying document bodies into event records.

### 4.2 Build Today as a backend projection

Propose an authenticated `/api/v1/today` endpoint that returns a paginated chronological projection
of authorized events. The frontend consumes that contract instead of composing multiple source
endpoints.

The projection includes display text where permitted, source links, status, provenance and
freshness. Define ordering, timezone handling and date-window semantics in the endpoint PR. Use
source occurrence time with a documented observation-time fallback and a stable tie-breaker;
resyncing must not make an old item appear newly received.

Today v1 is chronological, not an AI-ranked priority list. It must distinguish an empty result from
unavailable, stale or failed sources. It must not advertise unimplemented actions.

### 4.3 Keep email access inside the existing MCP trust boundary

The proposed **outbound call path** is:

```text
authenticated, explicit sync request
  → connector sync service
  → governed_tool_invocation and existing authorization/policy checks
  → existing API-to-gateway client
  → gateway MCP adapter
  → operator-configured email MCP server
```

Returned data is validated, minimized and normalized into approved email signals and workspace
events. The email MCP server may integrate with its provider; direct Gmail, Microsoft Graph mailbox,
Exchange or IMAP clients in the core API or web application are outside this proposal.

Reuse the existing operator configuration, tool registry, credential handling, gateway egress
controls and governance path. Do not introduce arbitrary user-supplied MCP destinations or a second
authorization system. The connector must enforce approved read-only tools and scopes; it must not
rely solely on a remote tool's claim that it is read-only. Honor any existing confirmation
requirement.

Begin with explicit, bounded manual sync. No silent direct-provider fallback, automatic mailbox
scanning, attachment downloads or full mailbox mirroring. Scheduling is a later, separately reviewed
increment.

### 4.4 Make triage advisory and suggestions inert

Email triage is a separate, explicit operation over approved, bounded input. It may classify
relevance, explain its reasoning and suggest a next step. Store evidence references, skill/version
information, applicable inference tier and a clear result state such as classified, needs review or
failed.

Email content is untrusted data, never an instruction granting authority. Apply existing sensitivity
and inference-tier controls. Prefer a tool-free classification step; triage must not gain mailbox
mutation capabilities. Any legal-substance skill must satisfy the project's applicable human review
and attestation requirements.

Optional proposed actions are inert records for review or dismissal. A suggestion, approval or UI
interaction must not execute a mailbox change under this ADR.

## 5. Data lifecycle and privacy requirements

- **Minimize retained email data.** No raw message bodies, attachments, subjects, snippets,
  addresses or model-input excerpts may be persisted in new product tables by default. Before
  enabling real ingestion, maintainers must approve a field-level retention contract, including any
  necessary provider references. Additional content retention requires an explicit reviewed
  amendment.
- **Separate product data from telemetry.** Even if a field is approved for product storage, that
  does not authorize placing it in logs, traces, audit payloads, errors or snapshots. Operational
  evidence should use identifiers, counts, outcome codes and carefully scoped hashes, with opaque
  identifiers protected appropriately.
- **Enforce ownership and source permissions.** Reads, sync, triage and suggestions must be isolated
  by user and applicable project/source access. A source link is not an authorization bypass.
- **Handle lifecycle changes.** Define retention, deletion, export, disconnect and credential
  revocation for events, email signals, triage outputs, suggestions, deduplication state and sync
  cursors. Preserve only audit evidence allowed by existing policy, without mailbox content.
- **Make retries safe.** Validate a bounded batch before advancing its cursor. Commit normalized
  records, the cursor and required local audit state consistently. A remote mailbox read cannot be
  part of the database transaction; retries must be idempotent.
- **Fail visibly and safely.** Unavailable credentials, revoked access, invalid responses and policy
  denial must not become successful empty syncs. Preserve accurate last-success/freshness state and
  stop unauthorized access.

Email-specific retention decisions gate real email ingestion, not the earlier internal-only Today
stages.

## 6. Implementation stages and review gates

The stages below are suggested PR boundaries. Maintainers may split them further. No stage
implicitly approves the next one.

| Stage | Bounded change | Evidence required before moving on |
| --- | --- | --- |
| **0 — ADR only** | Submit this document after contributor review; assign its ADR number and link the relevant issue. No runtime changes. | Maintainer review of the boundary, sequence and unresolved prerequisites; amend the ADR to reflect the outcome. |
| **1 — Event foundation** | Add the minimal model, additive migration and persistence/query service. No email or UI; no broad public event API unless justified. | Model, ownership, deduplication and lifecycle tests; migration tested on a disposable database; documented disable/rollback approach. |
| **2 — One internal producer** | Adapt one agreed source, such as a research finding, into events without changing the research agent's behavior. | Source-to-event mapping, retry safety, access/deletion behavior and consistency tests; existing behavior remains intact. |
| **3 — Today backend** | Add `/api/v1/today` over internal events, with pagination, chronological ordering and explicit state/freshness. | Endpoint and authorization tests, empty/error cases, date/order tests, API contract documentation. |
| **4 — Today frontend** | Add the Today page using that endpoint, with source links and honest empty/loading/error/stale states. No ranking or action execution. | UI checks for access, dates, pagination, accessibility and source navigation; verify the browser-to-API flow. |
| **5 — Email contract and governed adapter** | Specify approved read-only MCP tools, normalized response and field-retention contract. Implement against synthetic responses; keep real ingestion disabled. | Policy-denial, tool/scope restriction, credential and malformed-response tests; payload-free telemetry checks; security/maintainer approval. |
| **6 — Bounded email sync** | Enable explicit manual sync through the approved adapter; persist only approved fields, deduplicate and expose accurate sync status. | Retry/cursor consistency, user isolation, stale/error handling, disconnect/revocation, deletion/export and retention tests; controlled read-only integration proof. |
| **7 — Advisory triage** | Add an explicitly invoked, versioned triage skill over approved inputs. No background agent or mailbox actions. | Structured-output validation, uncertainty/failure cases, injection resistance, inference-tier enforcement and applicable human skill review. |
| **8 — Optional inert suggestions** | Surface and optionally persist reviewable next-step suggestions, with dismissal only and no execution path. | Ownership/lifecycle tests and proof that no suggested action invokes mailbox writes or creates tasks. |

For each implementation PR, update the affected specifications and honest capability documentation
alongside the code. Run checks proportionate to that slice; do not claim a feature is shipped from
an ADR, mock or unverified UI alone. Keep feature exposure disabled until its own safety and
lifecycle checks pass, using existing configuration mechanisms where possible.

Prefer disabling a producer/connector and preserving data over destructive schema rollback. Follow
the repository's migration/deployment procedures, including compatible API and worker versions;
never test migrations against a live developer database or delete volumes to reset state.

## 7. Alternatives and consequences

**Lighter alternative:** Compose existing backend sources directly into `/api/v1/today`, without
persisting workspace events. This could reduce the first implementation's schema work and may
suffice for an internal-only view. It would postpone the shared identity, normalization,
deduplication and lifecycle contract until connectors arrive.

**Proposed choice:** Establish a deliberately minimal event substrate first, then prove it with one
internal producer. This adds a migration and lifecycle obligations upfront, but gives Today and
later email signals a shared contract. Avoid speculative abstractions for every future connector.

**Frontend composition:** Not proposed, because it spreads source-merging, permission, pagination
and freshness behavior into the client. The backend projection remains useful even if maintainers
choose the lighter non-persisted alternative.

**Direct provider integrations:** Excluded to preserve the existing gateway/MCP boundary rather than
create a parallel mailbox access path.

## 8. Explicitly outside this ADR

- Sending, archiving, deleting, moving, labeling or forwarding mail, and creating tasks or other
  external records.
- Automatic email filing, autonomous triage, background polling and hourly digests.
- Calendar/task connectors, advanced prioritization and a general workflow-intelligence platform.
- Attachment processing, full-mailbox replication and unrelated agent/orchestration changes.

Any mailbox mutation needs a separate issue, threat model, permission and confirmation design,
lifecycle rules, implementation and maintainer review. User confirmation alone does not bring
mutation into this scope.

## 9. Prerequisites to record during review

Before implementation, record maintainer acceptance or amendment of the event-first boundary and
backend Today projection. Before real email ingestion, record the approved read-only tools/scopes,
ownership model, permitted retained fields, retention/deletion/export behavior and security-review
requirements. Before triage, record approved inputs, inference policy and skill-review requirements.

These are implementation gates, not claims of decisions already made. Capture the outcomes in this
ADR or linked implementation specifications without reopening the agreed incremental delivery
process.

## 10. Repository references and submission

This draft was informed by the local checkout's following documents and existing integration
boundary:

- `docs/PRD.md` — M5–M7 direction and DE-200/201/202/208/209.
- `docs/HONEST-STATE.md` — documented current capabilities and limitations.
- `docs/adr/0014-gateway-egress-boundary-for-tool-providers.md`.
- `docs/adr/0015-governed-tool-calling-model.md`.
- `docs/adr/0016-transparency-and-governance-invariants.md`.
- `docs/adr/0035-governed-orchestration-run-tree.md` — preserve existing orchestration boundaries;
  this proposal does not replace them.
- `api/app/tools/governance.py` and `mcp.yaml.example` — existing governed invocation and
  operator-configured MCP foundation.
- `docs/contribute/coding-agent-onboarding.md` — contribution and verification workflow.

**Submission order:** Contributor reads this attached draft first. After explicit approval to
publish, recheck upstream numbering and contribution requirements, place the single ADR in
`docs/adr/`, and commit/push it to the contributor's fork for a docs-only maintainer-review PR. Do
not bundle implementation changes, self-merge or mark this proposal accepted on the maintainers'
behalf.
