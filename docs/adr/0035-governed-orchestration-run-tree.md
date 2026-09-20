# ADR 0035 — Governed orchestration on the autonomous executor

**Status:** Accepted (2026-09-20) — committee-ratified at the weekly call.
**Date:** 2026-09-12 · **Updated:** 2026-09-20
**Tracks:** [Issue #563](https://github.com/LegalQuants/lq-ai/issues/563)

## Context

LQ.AI needs parallel agent work that can pause for approval, survive interruption
and retain the application's authority, budget and audit controls. Skills may
also need reusable storage and executable helpers. Confidential documents must
remain protected even when an approved helper is compromised.

The first profile demonstrates planning, approval, delegation, monitoring,
collection and synthesis with sample findings. Substantive research quality and
additional verification are outside that demonstration's scope; existing
governance and honest evidence status remain mandatory.

## Decision

Extend the existing autonomous executor with a governed run tree. Use LangGraph
for continuation, arq for scheduling and LQ-owned Postgres records for governance.
Provide optional persistent skill workspaces and isolated execution of reviewed,
installed Python helpers. Exclude general generated-code execution.

### D1 — One approved research batch, with bounded parallel children

Each manual root belongs to an owner and active project. Permit one immutable
batch of one to four children, one delegation level and no child delegation.
Default to two concurrent children, configurable from one to four. Allow one
active root per user and require explicit deployment-wide capacity limits.
Children have separate contexts and transactions and use closed, pinned profiles.

### D2 — Approval is a durable barrier before child admission

Show the plan, selected resources, skill version, budgets and limits before any
child is admitted. The owner approves that exact revision and authority policy.
Changed scope, budget, policy or executable skill requires renewed approval.
Planning uses a disclosed root allowance. Approval waits release workers and
database transactions; stale, halted or revoked approvals cannot admit work.

### D3 — Separate research data from delegated authority

The model proposes bounded task data. The server supplies ownership, selected
resources, profiles, grants, tiers, budgets and deadlines. Enforce the intersection
of delegated authority, profile grants, phase grants and current policy at every
effect; saved approval cannot override revocation.

All effects use the shared governance path. Apply project/skill inference,
external-egress and anonymization restrictions throughout the tree. Ownership does
not authorize unselected documents. The gateway remains the provider-key holder
and external egress boundary; prompts and tool results cannot grant authority.

### D4 — One execution-state owner behind a narrow adapter

| Component | Responsibility |
|---|---|
| LangGraph with persistent checkpoints | Resume graph steps, interrupt, fan out and join. |
| arq | Schedule separate root and child invocations and durable wakeups. |
| LQ-owned Postgres records | Own approval, current authority, admissions, budgets, effect receipts, results and audit. |

Approval and child waits release the arq invocation. Framework state stays behind
a narrow adapter and cannot restore obsolete permissions. Checkpoints must bound
individual effects within multi-step work. Runtime changes require a reviewed
migration or drained runs.

### D5 — Durable admission, short transactions and explicit uncertain effects

Commit approval validation, admission, budget reservation, dispatch intent and
audit atomically before dispatch. Use short transactions, consistent lock order,
fenced worker ownership and durable step identities. Commit outcomes and their
audit together.

An external call cannot be atomic with Postgres. If its outcome is uncertain
after interruption, retain the reservation and require reconciliation. Do not
automatically repeat it or claim exactly-once external execution. Replaying a
completed effect reuses its receipt.

### D6 — An accounted budget shared by root and children

Reserve the root's planning and completion allowance before funding children.
Atomically enforce settled charges plus outstanding reservations within the
approved root budget. Settle or release each reservation once; uncertain outcomes
retain funds. Refuse unknown paid-provider pricing and expose observed overruns.
This is an accounted-budget ceiling, not a guarantee about the provider's invoice.

### D7 — Halt, ordinary failure and empty success have different outcomes

Ordinary child failure permits successful siblings to finish. Preserve partial,
empty, all-failed and halted outcomes. Halt, revoked authority, exhausted budgets
and deadlines prevent new admissions. At most one already-admitted call per active
child may finish. Halt renders retained work without starting another synthesis
call. Approval and child waits release worker invocations; the root deadline
still applies.

### D8 — Internal child results; root delivery and honest evidence status

Children return bounded results to the root; they do not notify users, publish
KB artifacts or propose memory/precedent changes. Root delivery follows existing
governance. Execution success does not establish citation verification, and a
synthesis must retain its own evidence status. Receipts expose parent and child
progress; audit and telemetry contain metadata rather than raw content.

### D8a — Run working files and explicit parent handoff

Store bounded, revisioned working files in application-owned storage. Children
access their own files and explicitly share immutable revisions with the root;
sharing grants no sibling access. Writes and effect receipts commit together.
Run files survive worker interruption, remain inspectable after halt or opt-out,
and are deleted with their owning session/root/user.

### D8b — Optional persistent skill workspaces

A skill may separately opt into Postgres storage scoped by owner, project or
personal namespace, exact skill identity and storage format version. Use explicit,
bounded read/write/list operations and expected revisions; do not automatically
inject saved work into prompts.

Data survives run/chat deletion and skill removal. Owner inspection, export and
reset remain available when execution is disabled. Hard owner/project deletion
cascades; archival blocks execution. Revalidate current access and preserve
namespace isolation across skill changes. This storage is separate from curated
user memory and executable bundles.

### D8c — Installed bundled helpers; no generated-code execution

Execute only installed Python helpers enabled by exact bundle and immutable
runtime-image identity. Security review covers scripts, supporting code,
dependencies and the image; legal-content review alone is insufficient. Changed
artifacts require renewed review, and revoked approval prevents new calls.
Calls select a declared helper and supply bounded JSON data. Refuse unavailable
configuration or mismatched artifacts.

Run each helper in a fresh container with no network, credentials, application
mounts or engine access, using a non-root user, read-only root and bounded
resources, time and output. Only the trusted broker controls its engine.
Production execution requires a dedicated environment whose engine cannot inspect
or mount LQ application storage or credentials; rootless execution on a shared
host alone is insufficient. Container isolation still depends on the host kernel.

Persistent workspace files are not mounted or imported. Helpers must not evaluate
supplied text, load code from saved work, install packages at runtime or launch
caller-generated programs. Storage and execution are independently optional.

### D8d — Confidentiality must survive compromised helper output

Even a compromised approved helper must receive only explicitly supplied,
authorized data, have no independent access to other matter data, and be unable
to cause disclosure to an unauthorized destination.

Treat documents, helper output and saved results as untrusted data. Preserve
source restrictions through transformations, subsequent inference/tool calls,
child handoff and later workspace reuse. If authority or restrictions cannot be
established, refuse outbound transfer. A network-disabled helper can still induce
an agent to disclose its output; enforce policy at the subsequent call rather
than relying on instructions or output filtering.

Apply the same restrictions to transient job configuration, engine logs,
diagnostics and cleanup failures. The broker, execution platform and LQ policy
enforcement are trusted components requiring separate review.

### D9 — Approval and changing progress are required UI

Provide plan inspection, approval/rejection, concurrent progress, budgets, halt
and retained-result inspection. Only approved profiles can create children.
Capabilities start disabled and require operator enablement. Disabling execution
preserves read/halt access; rollback requires draining or halting retained work.

## Alternatives considered

| Alternative | Benefit | Reason not selected |
|---|---|---|
| Custom Postgres/arq continuation | Complete control over execution state. | Requires LQ to build and maintain graph continuation and joining already supplied by LangGraph. Governance records remain LQ-owned either way. |
| Adopt a complete agent harness | Ready-made delegation, filesystem and execution tools. | Deep Agents, OpenAI Agents SDK, Pi and DeepSeek Harness still require adaptation to LQ's grants, gateway and audit. No demonstrated integration benefit justifies replacing the existing executor. |
| Temporal | Durable workflow and child-lifecycle primitives. | Adds an operational platform beyond the needs of the bounded first profile. |
| Run-only storage | Simpler retention and isolation. | Cannot retain a skill's work across invocations. Keep it for run work, with separate optional persistent storage. |
| General generated-code execution in a sandbox | Agents can invent and debug new calculations. | Expands executable behavior beyond reviewed helpers and the agreed product scope. |
| Reviewed scripts with application-host access | Simpler deployment. | Vetting can miss malicious code or vulnerable dependencies; confidentiality also requires runtime containment. |

LangGraph fits the existing Python executor and the required continuation model.
The [research findings](../research/issue-563-harness-research.md) compare harnesses,
explain the backend experiments and examine execution security. They support this
choice without claiming measured performance or maintenance superiority.

## Consequences

- Reuse existing execution primitives while retaining LQ control of authority
  and data. Approval, reservations, receipts and recovery still need application
  logic; checkpointing alone is insufficient.
- Persistent workspaces improve continuity but add access, retention and
  cross-invocation confidentiality obligations.
- Bundled helpers offer predictable capabilities at the cost of upfront review
  and packaging. New computations require new reviewed helpers.
- Recursive delegation, watch/schedule orchestration, general generated code,
  replay/fork transcripts, SSE and substantive research evaluation remain deferred.

## Ratification and release conditions

This decision amends [ADR 0013 D1](0013-autonomous-layer-design-influences.md),
[ADR 0020 D2/D4/D7](0020-governed-agentic-legal-matter-sessions.md) and
[ADR 0016 P5](0016-transparency-and-governance-invariants.md) only as specified here.
**Ratifier and decision date:** LQAI Committee, 2026-09-20
([minutes](https://github.com/LegalQuants/lq-ai-community/blob/main/meetings/2026-09-20-weekly/notes.md)).
Ratification clears the ADR publication hold; production enablement remains a
separate gate.

Before production adoption, review the runtime migration under
[#524](https://github.com/LegalQuants/lq-ai/issues/524) and the integration evidence
for approval races, competing workers, recovery, budgets, halt, isolation and UI.
Selected-document authorization and project data-policy propagation, including
DE-294, are prerequisites for real matter orchestration.

**Still required before script enablement:** explicit executable security-review
routing and approval evidence; hostile-helper containment and indirect-disclosure
tests across supported calls and persisted reuse; and review of production
executor separation and operational data handling. Existing isolation tests do
not establish the complete confidentiality objective.

## Supporting evidence

The [research note](../research/issue-563-harness-research.md) preserves the findings,
source comparisons and experiment limits, with links to the full assessment. The
[feature PRD](../prds/issue-563-governed-orchestration.md) defines user needs,
requirements, acceptance criteria and release conditions. The
[skill capability summary](../plans/issue-563-skill-capabilities.md) and
[draft operator notes](../deploy/skill-capabilities.md) describe behavior and
operational limits. They are supporting evidence for this accepted decision,
not evidence of shipped capability.
