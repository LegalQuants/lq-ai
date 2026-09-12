# ADR 0035 — Governed orchestration on the autonomous executor

**Status:** Proposed — open for comment; not ratified and not a shipped capability.
**Date:** 2026-09-12
**Owner:** Issue #563 maintainers; ratifying and security reviewers to be recorded below.
**Tracks:** [Issue #563](https://github.com/LegalQuants/lq-ai/issues/563).
**Proposed amendments:** ADR 0013 D1 (one level of delegation), ADR 0020 D2/D4/D7
(orchestrator lifecycle, tree budgets and internal child delivery), and ADR 0016 P5
(explicit transaction boundaries around external effects). Existing single-session
behavior and the gateway boundary remain the baseline until implementation lands.

## Context

A lawyer should be able to describe a matter, select documents and enabled research
sources, review a proposed topic plan, and approve parallel research children. The
root collects each child's outcome and produces an inspectable result. Research is
the first example of an orchestration profile, not a replacement for existing
single-session, watch or scheduled execution.

The original epic proposed sequential children, approval only above a threshold,
custom Postgres/arq continuation, and a replayable JSONL transcript. Subsequent
requirements and research changed that proposal. Parallel children and approval
before **any child runs** are required in the first release. The runtime choice is
still open. A successful orchestration test may return no research results; it
must prove control flow, persistence and governance rather than legal quality.

The code baseline for this draft is main at
[`27c4521`](https://github.com/LegalQuants/lq-ai/commit/27c4521de0174a48070484cbaf66b7716432076a),
including PR #411's resource-visibility checks. The existing executor has a
five-phase LangGraph without a checkpointer. Its analysis node contains multiple
model/tool calls; adding checkpoints only between phases would not make those
individual effects recoverable. See [executor](../../api/app/autonomous/executor.py),
[analysis](../../api/app/autonomous/nodes.py), [guard](../../api/app/autonomous/guard.py)
and [state](../../api/app/autonomous/state.py).

This proposal builds on [ADR 0013](0013-autonomous-layer-design-influences.md),
[ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md),
[ADR 0015](0015-governed-tool-calling-model.md),
[ADR 0016](0016-transparency-and-governance-invariants.md),
[ADR 0018](0018-citation-ledger-and-fiduciary-grade-output.md) and
[ADR 0020](0020-governed-agentic-legal-matter-sessions.md).
ADR 0013 and ADR 0016 currently retain **Proposed** headers even though deployed
code implements their invariants. This draft does not silently accept either
document wholesale; ratification must record the precise amendments adopted here.

## Research and evidence

The [saved assessment](https://github.com/LegalQuants/lq-ai/blob/4ac3fee64/outputs/issue-563-prior-art.md)
and [prototype report and sources](https://github.com/LegalQuants/lq-ai/tree/4ac3fee64/outputs/issue-563-spike)
are the dated evidence behind this draft. They are research artifacts, not
application code or an accepted architecture.

| Reference | Finding and consequence for this proposal |
|---|---|
| [Anthropic research system](https://www.anthropic.com/engineering/multi-agent-research-system) | A lead assigns isolated research topics and synthesizes results. Adopt explicit questions, boundaries and artifact references; the account does not determine LQ worker topology or prove legal-research quality. |
| [Open Deep Research](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/deep_researcher.py) | Inspectable supervisor/researcher separation and parallel batches. Retain a typed outcome per topic and add durable user approval; concurrent calls alone do not establish restart safety. |
| [Deep Agents](https://github.com/langchain-ai/deepagents/blob/178417d0dad063fea0300db68455f4574ef67db3/libs/deepagents/deepagents/middleware/subagents.py) | Packaged delegation and context isolation are relevant prior art. Its configurable tool/state inheritance requires explicit adaptation to LQ's grants, selected documents and gateway; whole-harness adoption is not justified by the current experiment. |
| [OpenAI Agents SDK research example](https://github.com/openai/openai-agents-python/blob/298b87c72209ae88d1fb22f8361ebb89e876b2dc/examples/research_bot/manager.py) | Typed planning, concurrent searches and synthesis are useful patterns. The example does not supply LQ's durable approval, budget or audit transaction. Adding a second agent SDK has no demonstrated integration benefit here. |
| [LangGraph 0.2.76 primitives](https://github.com/langchain-ai/langgraph/blob/0.2.76/libs/langgraph/langgraph/types.py) | The existing version already has interrupt, command and fan-out primitives. Capability is not the reason to upgrade. Integration, replay boundaries and dependency maintenance are separate decisions. |
| [pi extension example](https://github.com/earendil-works/pi/tree/main/packages/coding-agent/examples/extensions/subagent) | The epic's categorical rejection was inaccurate: pi supports blocking tool hooks and extension-based subagents. Its TypeScript/process integration cost, rather than absent delegation, is the relevant objection. |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) and [Temporal child workflows](https://docs.temporal.io/develop/python/workflows/child-workflows) | Useful extension/lifecycle references. No demonstrated benefit warrants adding their runtime or operational platform to this pilot. |

The isolated experiment used the same application contracts and effect receipts
with a LangGraph adapter and a stdlib fixed-batch adapter. **23 tests passed** on
LangGraph 1.2.11 and, unchanged, on 1.0.10. Tests included approval across process
restarts, barrier-proven overlap, empty output, halt, revoked scope, completed and
uncertain effect recovery, and replacing either adapter with the other. Two
additional one-off checks resumed 1.2.11 data under 1.0.10. These are recorded
results from the linked experiment, not new production tests run for this ADR.

This demonstrates a narrow replaceable boundary for **one effect per immutable
topic**. It does not prove arbitrary checkpoint portability, multi-step child
recovery, Postgres transaction behavior, worker ownership, queue delivery,
deployment-wide limits, real LQ authorization, dollar accounting or gateway
integration. The 24-line native adapter is not a production Postgres/arq engine;
its size cannot establish that a custom runtime is cheaper. LangGraph also did
not remove the need for application-owned approval and effect receipts.

The 1.0.10 experiment retained Core 1.6.3, checkpoint 4.2.0 and SQLite saver 3.1.1;
it was not a test of the original 1.0 dependency family. Its SDK 0.3.15 excludes
the [resource-decorator authorization fix in SDK 0.4.4](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-fvww-7h3r-vfhp).
That feature is unused in the fixture. Passing the fixture is neither a production
dependency approval nor evidence that the application has an exploitable path.

## Proposed decisions

### D1 — One approved research batch, with bounded parallel children

Keep the orchestrator in `api/app/autonomous` as a profile of the existing
executor. Each researcher is an ordinary LQ autonomous session with its own
context, ownership and transaction scope. The model may propose bounded topics;
it cannot create arbitrary agents, tools, system prompts or privileges.

The proposed first-release defaults are:

| Boundary | Proposal |
|---|---|
| Initiation | Manual, with a nonempty query and an owned, active project |
| Delegation | One level; children cannot delegate |
| Plan | One immutable approved batch; one to four topic slots |
| Parallelism | Two active children by default; operator-configurable from one to four |
| User capacity | One active orchestrated root per user, including approval/child waits |
| Deployment capacity | Explicit operator-configured shared admission limits; no implicit unlimited fallback |
| Inputs | Selected matter documents and operations actually supported by enabled source adapters |
| Subsequent work | A changed batch, scope or budget requires a new revision and approval |

Source enablement does not imply a universal search interface. Skill selection
must respect the skill's declared coverage; the U.S. `case-law-research` skill
does not become a general regulatory skill through delegation. Ship the root
instructions as a visible, versioned `skills/orchestrator-harness/SKILL.md`.
Substantive research-skill changes retain the attorney-attestation process.

### D2 — Approval is a durable barrier before child admission

Planning may consume a disclosed root planning allowance. Persist and show the
plan, topic scopes, selected sources/documents, skill version, budgets and limits
before asking for approval. No child session is admitted, no child lease is
activated and no child tool runs until an authorized owner approves that exact
revision. Approval is not a model decision or a cost-threshold exception.

Bind approval to the root and project, revision/hash, approving user, time,
authority-policy version and skill digest. Repeated approval is idempotent;
stale, rejected, expired or halted plans cannot start. Revalidate current policy
and resource visibility after the wait. A changed executable plan needs approval
again. Invalid planning output fails without falling back to free-text execution.

Approval waits release worker capacity and database transactions. Use explicit
lifecycle states such as `awaiting_approval`, `queued` and `waiting_children`,
distinct from the existing phase and halt fields. Define the full transition
table before changing status enums, DB constraints, watchdogs or client types.

### D3 — Separate research data from delegated authority

Use a strict model-authored task schema for bounded topic text, question,
boundaries, output contract and stopping condition. Treat all such text, source
content and child summaries as untrusted data. Parse JSON structurally; reject
unknown fields, malformed/oversize input, unknown targets and forbidden intents.
Typed strings, envelope markers and hashes do not make prose trustworthy.

The server constructs the authority envelope: owner/project and tree IDs,
approved scope, pinned skill, phase grants, tier restrictions, budget, deadlines
and dispatch identity. Only a closed registry may select a child profile.
System instructions come from the pinned skill artifact. A model must not supply
authority fields, handler names, provider credentials or prompt overrides.

For phase `p`, enforce:

```text
child intents(p) = inherited delegation envelope
                   ∩ child profile grants(p)
                   ∩ PHASE_GRANTS[p]
                   ∩ current operator policy
```

The root's ability to delegate is distinct from its own directly executable
intents. Do not intersect a child's complete lifecycle with only the parent's
current analysis grants. Enforce owner/project and selected document/source
scope before dispatch and each resource read. Ownership alone does not authorize
an owned-but-unselected document. Saved grants never override later revocation.

Resolve and enforce both the minimum inference tier and maximum external-egress
tier under their existing semantics; these are different constraints. Apply
authoritative project/skill restrictions and deliberate anonymization to root
planning, research, synthesis and verification. Mandatory project selection in
intake does not, by itself, propagate those restrictions through execution.

Every model/tool effect uses `guarded_tool_call` and the shared governance
substrate, retaining R5 → R6 → R4. Framework helpers and direct handler paths
cannot bypass it. The gateway remains the only provider-key holder and external
egress; internal run/root correlation IDs are stripped before provider requests.

### D4 — One execution-state owner behind a narrow adapter

Keep task contracts, approval, current authority, budgets, results and audit in
LQ-owned records. Framework types must remain inside the execution adapter. The
adapter resumes work by stable run identity and returns structured progress;
checkpoints must not restore obsolete permissions over current LQ policy.

**Backend selection is unresolved.** Evaluate maintained LangGraph first against
the actual LQ integration, with a native continuation design as the comparator.
Ratification must choose exactly one production continuation owner and topology:

| Candidate | Owns progress | Responsibilities that remain in LQ |
|---|---|---|
| LangGraph with persistent checkpointing | Graph step continuation, interrupt/resume and join | Approval, authority, admissions, effect receipts, budgets and audit; arq may schedule resumptions, not a competing graph cursor |
| LQ Postgres continuation with arq | Application step records and durable continuation; arq delivers work | The same controls, plus explicit implementation and maintenance of scheduling/join/recovery |

Prefer the candidate that reduces total supported continuation work while
passing the same acceptance scenarios. Do not ship both as configurable runtime
alternatives. Graph fan-out is not itself a distributed queue; whether children
run within a coordinator invocation or as separate jobs remains part of this
comparison. Separate jobs must not depend on a waiting parent occupying the
worker slots they need. Bound capacity across workers, not only in one semaphore.

Persist step/effect identities outside compactable conversation history. Define
meaningful recovery boundaries inside the multi-step analysis loop. LangGraph
[interrupts replay their node](https://docs.langchain.com/oss/python/langgraph/interrupts),
so approval and dispatch need separate, idempotent boundaries. Validate the
selected saver and [persistence behavior](https://docs.langchain.com/oss/python/langgraph/persistence)
at the locked versions, including serialization restrictions and trace settings.
Changing runtime or graph versions requires a tested migration or draining runs;
the fixed-batch swap test does not authorize arbitrary live checkpoint conversion.

### D5 — Durable admission, short transactions and explicit uncertain effects

Add parent/root/depth and stable child order, with a unique
parent/plan-revision/subtask identity. Existing sessions backfill as roots. Enforce
same-owner/project edges, no cycles, depth limits and explicit deletion/retention
behavior. Foreign keys alone do not establish permission to join a tree.

Atomically commit approval validation, child identity, budget reservation and
admission audit before making the child runnable. If a queue boundary is used,
persist dispatch intent in that transaction and recover commit-before-enqueue
and completion-before-wakeup failures. Queue job IDs are not durable admission
uniqueness. Checkpointed execution needs equivalent failure-window coverage.

Use independently managed child DB sessions, short control-row transactions,
consistent lock ordering and fenced execution ownership. Never hold control-row
locks across model/provider I/O, user approval or child completion waits.
Stale workers cannot admit another call or overwrite a newer execution owner.

For ADR 0016 P5, preserve flush-only audit/governance helpers. The executor owns
two distinct atomic boundaries: admission/reservation with audit intent, and
recorded outcome/settlement with outcome audit. A provider call between them
cannot be atomic with a Postgres commit. A crash after a possible external effect
but before recording it produces an explicit **uncertain** outcome and retained
reservation. Do not automatically repeat it or report exactly-once provider
execution. Lease expiry alone is not proof that an old provider request stopped.

### D6 — An accounted budget shared by root and children

Use Decimal amounts and retain the root's planning, synthesis, verification and
delivery allowance before allocating child leases. Under the declared accounting
model, enforce atomically:

```text
settled budget charges + outstanding reservations ≤ approved root budget
```

A child lease includes its unused and in-flight allowance. Settlement converts
reservation into charge without double counting. Return demonstrably unused
funds once; uncertain outcomes retain conservative funds. Record provider actuals
separately from estimates. An observed overrun remains visible and stops further
work; never rewrite usage to fit the cap. Unknown paid-provider pricing refuses
admission for this profile; explicitly free configured providers/fixtures are valid.

Label this an **accounted-budget ceiling**, not a guaranteed provider-invoice cap.
Strict invoice guarantees require separately verified pricing and metering. Tests
must cover concurrent admission, retries, double settlement/release and preserving
enough parent allowance to finish an ordinarily partial run.

### D7 — Halt, ordinary failure and empty success have different outcomes

An independent child's ordinary failure does not cancel successful siblings.
Join typed outcomes for every approved topic and report partial coverage. Empty
search output is successful empty work; all-failed children cannot produce a
successful research claim. This partial-result behavior is proposed for ratification.

Root halt, exhausted root budget, revoked authority or invalid execution state
stops further dispatch. Once halt commits, no new call is admitted. At most one
already-admitted call per active child may finish; this is not one call for the
entire tree. Halt does not start a fresh synthesis model call. Render available
partial state deterministically and keep receipts inspectable.

Use root and per-attempt deadlines, bounded retry/backoff and distinct watchdog
treatment for queued, approval-waiting, child-waiting, active and abandoned work.
Approval/child waits must not consume the shared 900-second arq invocation timeout.

### D8 — Internal child results; root delivery and honest evidence status

Children preserve deterministic phase completion, including ethics review, but
their delivery is internal. They return typed session/topic outcome and bounded
authorized evidence references. They do not notify users, write KB artifacts or
propose memory/precedent changes. The root owns user-facing delivery under the
existing output governance and curation rules.

Keep execution completion, topic coverage and citation verification distinct.
Retain each child's gate verdict, including absent/failed/unverified states. A
parent's new cited assertions require their own existing ledger/gate evaluation;
passing child gates cannot make an unchecked synthesis green. Test aggregation
with fixture verdicts, without requiring relevant or nonempty live search results.

Receipts show the parent's events and ordered child sub-timelines, with stable
dispatch/sequence tie-breakers and links to existing child receipts. Join
`tool_call_log.session_id`; no extra root column is required there for v1. Keep
research text in access-controlled content/work-product storage. Audit, OTel and
framework traces contain only approved metadata, not raw goals or results.
Defer a second replay/fork JSONL content store.

### D9 — Approval and changing progress are required UI

Reuse the matter-intake entry point and existing receipts. Extend run-now with
an explicit orchestrator profile and selected document/source scope; plan read,
approve/reject and tree-read contracts are required. Approval identifies the
revision/hash and documents stale/conflicting transitions. There is no arbitrary
public child-spawn API. Final schemas, path counts and generated OpenAPI must
land together with the corresponding implementation.

The required browser flow is intake → plan preview → approve/reject → concurrent
child progress → halt or completion → tree inspection. Include budget breakdown,
bounded polling that stops on terminal state/navigation, and manual refresh. SSE
and expanded session-list trees can wait. Expose feature enablement and limits
on an operator configuration/admin surface; orchestration starts disabled.

## Dependencies and implementation sequence

| Work | Relationship to #563 |
|---|---|
| [PR #411](https://github.com/LegalQuants/lq-ai/pull/411) | Merged foundation: preserve write-time project/KB/playbook visibility and archived-resource rejection. Add current per-child approved-scope checks after approval waits. |
| [PR #410](https://github.com/LegalQuants/lq-ai/pull/410) / issue #332 | Reuse intake after its review and checks pass. The current review requires a project for query intake, correct numeric inputs, loading/error handling and matching contracts/tests. Its [KB comment](https://github.com/LegalQuants/lq-ai/pull/410#discussion_r3996565271) explicitly defers retrieval to separate work. Correct manual selected-KB execution and complete project data-policy propagation before exercising real matter orchestration. |
| [Issue #524 / DE-319](https://github.com/LegalQuants/lq-ai/issues/524) | Separately review the maintained runtime migration across all three executors before activating durable LangGraph in the application, if selected. Review the actual dependency diff, advisory floors and serializer configuration; fixture compatibility does not approve the application lock. |
| [PR #558](https://github.com/LegalQuants/lq-ai/pull/558) | The 0.6.11 proposal does not complete the 1.x migration. The saved review records 12 typing errors before pytest; prefer a corrected direct migration under #524. |
| [PR #536](https://github.com/LegalQuants/lq-ai/pull/536) | Separate membership work; not a prerequisite for the owner-scoped pilot. Use one current-access interface so later membership/revocation integrates without tree-wide access grants. |
| [PR #564](https://github.com/LegalQuants/lq-ai/pull/564) | Coordinate ADR/DE identifiers and actual review assignments. Its broader governance proposal need not merge before this one. Do not assume automatic review routing is working. |

The authorized workflow is **this documentation PR first**, then a separate
local implementation branch. Implementation commits must not be pushed or opened
as a code PR until this ADR is ratified. Local integration experiments may supply
evidence back to the proposed ADR; local coding does not constitute ratification.
The runtime maintenance remains a distinct reviewable change from harness behavior.

Prepare contracts and the bounded integration experiment first. Use its evidence
to finish D4 and the ratification record below. Continue with durable admissions,
budgets and halt; governed child dispatch and recovery; root synthesis/evidence;
approval/tree API and UI; then release verification. Extract only the harness
interface and closed registry required by these profiles. Do not do a general
loop rewrite as a prerequisite. The epic's earlier 35–55 engineer-day estimate
does not estimate this revised design; estimate after backend selection.

## Acceptance gates

The production fixture suite must exercise actual LQ governance, separate
transactions and the selected worker topology. The SQLite experiment satisfies
none of the production integration gates by itself.

| Gate | Required evidence |
|---|---|
| Approval and races | Zero children/effects before approval; duplicate/stale/expired/rejected approval and halt-versus-approve cannot admit unauthorized work. |
| Parallelism and empty output | Two stub searches both enter independent barriers before either is released; both may return empty, and the root joins without fabricated evidence. |
| Isolation and handoff | Foreign and owned-but-unselected resources refuse; stale policy/skill versions invalidate authority; hostile input/output cannot change sibling scope, prompts, grants, tiers or budget. |
| Recovery | Inject faults around admission commit, enqueue/checkpoint, invocation, effect receipt and parent continuation; no duplicate child or completed-step replay; uncertain external outcomes remain explicit. Include multi-step children and competing coordinators. |
| Budget | Real Postgres concurrent reservations cannot exceed the accounted cap; settlement/retry cannot double charge/release; unknown outcomes retain funds. |
| Cancellation and capacity | Halt commits while providers are blocked; no next call starts. Approval and parent waits release worker capacity; multiple workers respect root/user/deployment limits and bounded 429 backoff. |
| Evidence and delivery | Ordinary partial, empty, all-failed and halted results stay distinct; missing/failed child or final verification never becomes a green aggregate; only the root delivers to users. |
| Compatibility and UI | Existing manual/schedule/watch/receipt/halt behavior passes; controlled browser flow proves approval, concurrent progress and inspection; migration up/down and root backfill pass on throwaway pgvector Postgres. |

Run focused and required API tests, Ruff format/check and mypy; compiled graphs
for all three executors when the shared runtime changes; relevant gateway and
transparency tests; Svelte checks, Vitest and controlled Cypress for the UI.
Dependency/container changes require the stack smoke gate. Never use the live
dev database for migration testing. Documentation, schema and API changes accompany
their implementation, and completion claims cite actual results.

Expand schema before deploying compatible API/workers/UI. Enabling is an explicit
operator action after review. Disabling prevents new roots/dispatch and preserves
read/halt access to existing trees. Drain or halt live trees and retain evidence
before any rollback that removes their schema/runtime support.

## Ratification record — must be completed before the code branch is published

- [ ] Accept D1 limits, parallel first release and one approved batch.
- [ ] Accept D2/D3 version-bound approval and delegated authority contract.
- [ ] Select **one** D4 continuation owner and worker topology; link actual LQ /
      Postgres / multi-step integration results and the reviewed runtime baseline.
- [ ] Accept D5's external-effect uncertainty and audit transaction clarification.
- [ ] Accept D6's accounted-budget meaning and D7's partial/halt semantics.
- [ ] Accept internal child delivery, evidence-status separation, required UI and deferrals.
- [ ] Record the exact amendments to ADR 0013 D1, ADR 0020 D2/D4/D7 and ADR 0016 P5;
      make DE-294 a prerequisite for shipping #563 without labeling it implemented.
- [ ] Record ratifier names, dated decision/minutes or review links, and security
      reviewers for authority, audit, budget, cancellation and gateway changes.

**Selected backend/topology:** pending integration evidence and ratification.
**Decision date and ratifiers:** pending.
**Implementation publication:** held until the above decision is recorded.

## Consequences and deferred scope

The existing governance and receipt substrate remains useful, but concurrency
requires new durable admission, accounting and transaction work. A runtime library
can reduce continuation work without taking ownership of LQ authority. Conversely,
a small fixture is insufficient justification for building a custom workflow engine.

Recursive delegation, watch/schedule orchestration, additional unapproved batches,
real playbook execution as a child type, general harness extraction, raw replay/fork
transcripts, SSE and research-quality evaluation are outside this first release.
The preserved research plan lists these deferrals; allocate any additional DE IDs
against the current register rather than reusing the epic's colliding DE-387 onward.
This ADR does not add them to the shipped capability list or close issue #563.
