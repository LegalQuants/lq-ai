# Issue 563 — implementation plan for review

**Status: production plan awaiting Houfu's review. Houfu authorized an isolated throwaway integration, now implemented and tested; production coding and application dependency upgrades remain unapproved.**

**Prior-art and prototype revision, 12 September:** the execution backend remains open. The [throwaway integration and findings](issue-563-spike/README.md) demonstrate approval, parallel stub children, process recovery and replacement of LangGraph for a fixed batch. All 23 tests pass. The prototype supports a narrow adapter boundary but does not show that LangGraph reduces total implementation work for this batch or establish production Postgres behavior. Read it alongside the [prior-art assessment](issue-563-prior-art.md).

**Dependency revision:** at Houfu's request, the prototype ran first in an isolated modern environment. Issue 524's application migration remains a separate proposed maintenance milestone. PR 558's 0.6.11 target leaves the typing debt unresolved and excludes newer checkpoint/SDK fixes. Application dependency files remain unchanged; only the disposable prototype has a new manifest and lock.

**LangGraph 1.0 follow-up:** the prototype now uses 1.0.10 instead of 1.2.11. Its unchanged Python code passes all 23 tests and two additional cross-version resume checks. Only LangGraph, prebuilt and SDK versions changed. The required SDK downgrade to 0.3.15 excludes a later resource-auth fix in an unused prototype feature, so functional compatibility does not make this a fully patched production baseline. See the [comparison and limits](issue-563-spike/README.md#L7). The proposed adapter boundary and remaining production gates are unchanged.

**Merged baseline update:** [PR 411](https://github.com/LegalQuants/lq-ai/pull/411) merged on 12 September 2026 as `27c4521de0174a48070484cbaf66b7716432076a`, closing issue 334 / DE-322. Its autonomous write-time playbook/KB visibility checks and archived matter/KB rejection are now available foundations. Retain them when integrating intake and child admission; execution-time scope and revocation checks remain required. Remote `main` was verified at this commit; this local checkout remains at `de73fa4` and has not been pulled or altered for the merge.

Prepared 12 September 2026 for [issue 563](https://github.com/LegalQuants/lq-ai/issues/563). This plan revises the epic around the decisions made in this conversation. Milestones and subissue labels below are local planning labels, not filed GitHub items or allocated ADR/DE numbers.

## 1. Outcome and agreed scope

Build an orchestrator profile on the existing autonomous executor. A research skill proposes topic-specific child runs; the user reviews the plan; approved children run concurrently under inherited governance; the parent collects their terminal outcomes and can assemble a final work product.

**Confirmed by Houfu:**

- Research is the first orchestration example.
- Parallel child runs are required in the first release.
- The user sees and approves the plan before any child runs.
- Use existing enabled legal-research sources and selected matter documents.
- Acceptance proves the orchestrator works. Search relevance, useful authorities, and even a nonempty search response are not acceptance requirements.

Consequently, the main acceptance suite uses a stub planner, controlled search fixtures, and a stub synthesis response. It tests real orchestration, persistence, authorization, concurrency, and UI behavior without requiring live providers. Empty results are valid. This does not establish research quality or expand any research skill's legal coverage.

**Recommended boundaries, still subject to this plan's approval:** one delegation level; at most four child topics per approved plan; default concurrency two, operator-configurable up to four; manual initiation; one approved batch; child runs cannot delegate. Child research loops can follow leads inside their approved topic and source scope. Changing the topic batch, source scope, or budget requires a new plan revision and approval.

The first release remains an autonomous-layer feature. Chat-triggered orchestration, new search providers, recursion, playbook execution as a child, schedules/watches, and research-quality evaluations are separate work.

## 2. What the issue gets right, and what needs changing

Keep the gateway boundary, existing session model, skill registry, shared tool governance, deterministic phase order, and visible receipts. Partially superseding ADR 0013 D1 is necessary. A separate service or imported coding-agent runtime is not justified by this first use case.

| Issue assumption | Finding and proposed correction |
|---|---|
| Sequential-only first release; parallelism deferred | Superseded by Houfu's explicit choice. Atomic reservations, concurrent execution ownership, capacity limits, and cancellation races are required now. |
| Postgres already supplies the execution state machine | It stores lifecycle data, but the analysis loop keeps observations/evidence in memory and the executor normally commits at terminal completion. Durable dispatch, join, and recovery are new work. Move them ahead of orchestration. |
| A fresh child `AsyncSession` solves re-entrancy | Necessary, insufficient. An uncommitted child is invisible to another transaction; external calls must not hold locks on cancellation/budget control rows. Define transaction boundaries and queue recovery explicitly. |
| The existing brake can guarantee the tree never exceeds a dollar cap | Inference currently charges a rolling estimate, not returned provider cost. External tools use configured rates, with zero fallback on lookup failure. Specify an accounted-budget ceiling and label estimates; do not promise an invoice ceiling. |
| Grants can be intersected with the parent's current phase at spawn | That would remove capabilities needed in later child phases. Persist a delegation envelope covering the lifecycle; intersect it with the child's current phase on every invocation. Restrict provider operations and document scope as well as intent names. |
| Tier inheritance is just a floor | Inference minimum tiers and external-tool maximum egress tiers are distinct constraints. The autonomous external path currently passes `max_allowed_tier=None`; inheritance must cover both, including planner/synthesis calls. |
| Typed fields and a digest make the handoff safe | Research needs topic/query text and source content. A string in a typed schema is still untrusted. Separate immutable authority from task data, and validate resource access at execution. A hash alone cannot support synthesis. |
| AND all child gates to determine the tree's fiduciary status | Existing gates have multiple statuses and can be absent. Child gates do not validate new assertions introduced by the parent. Keep run completion, topic coverage, and citation verification separate. |
| H4 requires a replayable/forkable JSONL transcript | Defer it. A second raw-content store introduces retention, access-control, consistency, and replay semantics beyond orchestration. Persist the minimum execution state in Postgres; provide metadata receipts. |
| UI refresh is optional | A concurrent run needs visible changing state. Include bounded polling plus manual refresh in the required UI; SSE can wait. |
| Gateway rate limiting is wholly missing | A process-local tool limiter exists. Its configured limit is currently derived from the maximum provider rate; global/multi-replica coverage is a separate issue. Inspect and bound the actual deployment behavior instead of rebuilding blindly. |
| pi lacks a pre-tool hook and rejects subagents | Current primary documentation shows a blocking `tool_call` hook and a subagent extension example. Reject adoption on integration/runtime/governance cost, not these inaccurate capability claims. |
| Allocate DE-387 onward | DE-387 already names pluggable ingestion; pending PR 564 proposes DE-388–391 for other work. Allocate identifiers only when the documentation change is prepared against current main. |

Evidence: [analysis loop](../api/app/autonomous/nodes.py#L167), [executor transaction handling](../api/app/autonomous/executor.py#L63), [brakes and cost accumulation](../api/app/autonomous/guard.py#L213), [external tier handling](../api/app/autonomous/guard.py#L365), [inference request](../api/app/autonomous/guard.py#L1558), [cost estimator](../api/app/autonomous/cost.py#L50), [gateway limiter configuration](../gateway/app/router.py#L620), and [pi extension documentation](https://raw.githubusercontent.com/earendil-works/pi/refs/heads/main/packages/coding-agent/docs/extensions.md).

## 3. Proposed architecture and decisions for ratification

### A. Durable execution: select the backend before implementation

**Revised draft decision:** retain `api/app/autonomous`, the gateway boundary and existing governance. Select the execution backend only after testing its actual LQ integration. The throwaway comparison establishes that a small adapter can contain LangGraph-specific types and that a fixed batch can recover from application receipts using either runner. It does not establish a LangGraph advantage for multi-step children or justify a custom workflow engine. Keep task contracts and governance outside the adapter; preserve the existing single-session phase behavior.

The authorized prototype initially used LangGraph 1.2.11 and SDK 0.4.4, and now passes unchanged on 1.0.10 and SDK 0.3.15 at Houfu's request. Both configurations retain Core 1.6.3 and checkpoint 4.2.0. This is not a compatibility test of the application's dependency graph. Retire the known runtime migration debt in issue 524 through a separately reviewed maintenance PR before activating durable LangGraph execution in the application, if that backend is selected; review the SDK constraint when choosing the production version. Upstream's published support policy covers 1.x as active LTS and does not list our 0.2 line. [Release policy](https://docs.langchain.com/oss/python/release-policy). See [dependency findings and the migration gate](issue-563-prior-art.md#L114).

The parent plans, persists the plan, and yields for approval. Only the approved revision may admit child work. Each child has an independent LQ session and transaction scope. Compare parallel graph execution with independently queued child jobs; the user requirement for parallel children does not itself select one arq job per child. Approval waits release worker capacity. A coordinator waiting on separately queued children must yield so it cannot exhaust the slots its children need. No database transaction stays open merely to wait for approval or completion.

Select one owner for execution continuation. Under the LangGraph option, a persistent checkpointer owns graph progress; LQ database records own current authority, approval, budget and audit. arq may schedule resumptions but must not drive an independent graph cursor. Under the custom option, LQ's durable continuation records own progress and arq delivers work. Neither option makes provider calls atomic with database writes. Using the same Postgres server for checkpoints and business records does not make their separate transactions atomic.

The current LangGraph pin, 0.2.76, already has `Send`, `Command`, `interrupt` and checkpointer support. This is verified in [version-specific source](https://github.com/langchain-ai/langgraph/blob/0.2.76/libs/langgraph/langgraph/types.py#L181). That corrects the earlier capability assessment; it does not justify retaining an old dependency family when activating persistence. Our executor does not enable a checkpointer. A checkpoint around the five existing phase nodes would still leave the analysis loop's internal calls vulnerable to replay; the selected design must expose meaningful step boundaries. Prefer a small reviewed dependency addition over rebuilding equivalent machinery when it reduces the total integration burden.

If the checkpointed design is selected, add a compatible patched saver and verify strict deserialization, namespace/access boundaries and retention. A previous advisory exclusion based on unused checkpointing must be reconsidered when that feature is enabled. Keep this feature integration separate from the initial dependency migration. arq is in maintenance-only mode, which strengthens the case for a small replaceable queue adapter and weighs against creating a large bespoke workflow engine around it. [arq status](https://github.com/python-arq/arq).

Add explicit scheduling states such as `queued`, `awaiting_approval`, and `waiting_children`, separate from the existing phase and halt concepts. Define valid transitions and terminal outcomes in one contract before altering the status enum, DB CHECK, worker/watchdog predicates, or client union.

Hierarchy fields are `parent_session_id`, `root_session_id`, and `depth`; existing sessions backfill as depth-zero roots with their own root ID. Store stable child order and a unique parent/plan-revision/subtask key. Enforce same-owner/project edges, no cycles, the depth limit, and explicit deletion behavior. A schema-valid foreign key alone does not establish permission to join another user's tree.

Persist approved plan revision/hash, dispatch key, per-step outcome, execution progress, policy version, skill digest, bounded context/evidence references, and execution ownership. Keep task identity and outcomes outside compactable message history. The selected backend owns the progress cursor; do not duplicate it in a competing state machine. Durable data must distinguish a completed step from an invocation whose external outcome is unknown. A worker must refuse stale ownership or replay of a recorded completed step.

Child admission must atomically bind the approved plan, child identity, reservation and audit record before the child can perform an effect. If dispatch crosses a queue boundary, persist a dispatch intention in that transaction and publish only committed work; recover commit-before-enqueue and completion-before-wakeup failures. arq job IDs alone cannot replace durable uniqueness. For checkpointed execution, document and test the equivalent admission/checkpoint failure windows. Approval and dispatch are distinct replay boundaries.

All model-selected effects still enter through `guarded_tool_call`; external tools still use shared governance. Transaction orchestration belongs to the executor. Preflight reservation/audit-intent and terminal outcome/audit must each be atomic with their associated database state. Audit helpers retain flush-only semantics. An external API action cannot be made atomic with a Postgres commit: record uncertain outcomes honestly rather than pretending exactly-once execution.

This requires clarifying the transaction contract associated with ADR 0016 P5. Its local document is still headed **Proposed**, although its invariants are implemented and referenced by accepted ADRs; resolve that documentation status rather than treating it as already ratified.

### B. Authority and handoff contract

**Draft decision:** a child receives a server-created authority envelope and a separately validated research task; neither model text nor child output may alter its authority.

The approved plan contains bounded topic descriptions, selected skill/version, source/provider operation allowlists, selected document IDs, per-child budget, step limits, and deadlines. Each topic specifies its research question, boundaries, output contract and stopping condition. The server supplies ownership, project binding, hierarchy IDs, depth, grants, tier policy, and dispatch keys. Model-supplied authority fields and unknown fields are rejected.

Research text is allowed as bounded **data**, including topic questions and queries. It never supplies a system prompt, role, tool definition, provider credential, or policy override. Child system instructions come from a pinned registry artifact. Parent synthesis reads authorized result/evidence references through a controlled path; a bounded summary remains untrusted even when it has a digest.

For each phase `p`, enforce:

`effective child intents(p) = inherited delegation envelope ∩ child profile grants(p) ∩ PHASE_GRANTS[p] ∩ current operator policy`

Also enforce same owner/project and selected document/source scope. Owning a document is insufficient if it was not selected for this run. Authorization is rechecked when resources are read; snapshotting a grant must not bypass later revocation. The orchestrator's delegation envelope is distinct from its own directly executable intents.

Reuse the visibility rules merged in PR 411 rather than reconstructing a weaker intake path: active KBs and matters are owner-scoped; playbooks must be non-deleted and visible under the existing own/built-in/admin rule. Its `_load_owned_kb`, `_load_owned_project` and `_load_visible_playbook` checks protect schedule/watch/manual write paths. They do not establish a child's approved document subset, delegation limits or current permission after an approval wait. Preserve the admin playbook exception as a resource-visibility rule; it does not authorize a child to widen its delegation envelope. The remaining integration proof must exercise both write-time validation and execution-time revalidation.

Carry the most restrictive applicable inference minimum and external-egress maximum separately. Cover planner, child research, synthesis, and any verification inference. Do not inherit the existing planner's `anonymize=False` default for matter-bearing orchestration traffic without an explicit data-policy decision.

Research children retain deterministic phase completion, but do not emit user notifications, create KB artifacts, or propose memory/precedent changes. They publish internal session outcomes/evidence; the root owns user-facing delivery. The root's orchestrator profile is a technical utility. Any substantive changes to legal-research skills retain the existing attorney-attestation process.

### C. Budget and concurrency contract

**Draft decision:** root and child work consume one accounted budget through atomic reservations; estimates and provider-reported actuals are separate values.

Use Decimal amounts. Reserve capacity for parent planning, synthesis, verification, and notification before allocating child leases. Planning before approval consumes the disclosed root planning allowance; approval is mandatory before child reservations are activated and jobs become runnable.

For the declared accounting model, enforce:

`settled budget charges + outstanding reservations ≤ approved root budget`

An outstanding child lease includes its unused and in-flight allowance. Settling a call converts reservation into a charge; it must not count the same amount twice. Child completion returns only demonstrably unused budget, once. Unknown external outcomes retain a conservative charge/reservation. Record actual reported usage independently; an observed overrun stops further work and is visible, never rewritten to fit the estimate.

Use short root-row locks or equivalent conditional atomic updates with a fixed lock order. Never hold them across provider I/O. Unknown paid-provider pricing refuses admission for this profile; explicitly free configured fixtures/providers are valid. The current estimator alone does not establish a hard provider-invoice ceiling.

Limit total child slots and simultaneous active children separately. Proposed defaults: four slots, concurrency two, one active orchestrated root per user. Deployment-wide admission limits and provider throttling must work across the supported worker topology; an in-process semaphore is insufficient when there are multiple workers. Respect 429 responses with bounded backoff under the same deadline and budget. Keep scheduling decisions in the backend; gateway rate enforcement remains egress policy.

### D. Approval, stop, and partial completion

**Draft decision:** approval authorizes one immutable plan revision, scope, and budget.

Approval records the user, timestamp, plan hash/revision, and policy/skill versions. Duplicate approval is idempotent. Approval of a stale revision is rejected. Halt/rejection/expiry prevents later approval. Policy or skill changes require revalidation; a changed executable plan requires approval again. No automatic fallback from an invalid plan to free-text execution.

Recommended failure policy, **not yet selected by Houfu**: independent ordinary child failures do not cancel siblings. The parent records completed/failed/empty topics and returns a partial outcome when appropriate. A root halt, exhausted root budget, revoked authority, or invalid execution state stops further dispatch. “No search results” is a successful empty result, not a scheduling failure.

Root halt must block new admissions immediately after its transaction commits, including concurrent dispatch. Each active child stops at its next invocation boundary. With parallelism, the bound is **at most one already-admitted call per active child**, not one call for the entire tree. Already-running provider requests may finish. Root halt does not trigger a fresh synthesis model call; available partial state is rendered deterministically.

Admission checks read current root/child control state and execution ownership. They reject terminal, paused or revoked execution as well as `halt_requested`; the current guard's check of only `halt_requested` is insufficient for this lifecycle.

Queued jobs, approval waits, child waits, active work, and abandoned work need distinct watchdog treatment. Use an overall root deadline plus per-attempt deadlines; waiting must not consume the shared 900-second arq job timeout. Lease expiry cannot blindly reissue an uncertain paid call while its former worker may still be active.

Proposed API shape for the design gate: extend `POST /autonomous/run-now` with a validated orchestrator profile, query and selected source/document scope; add `GET /autonomous/sessions/{id}/plan`, `POST /autonomous/sessions/{id}/plan/approve`, `POST /autonomous/sessions/{id}/plan/reject`, and `GET /autonomous/sessions/{id}/tree`. Approval identifies the exact revision/hash and supports idempotent retries. Mutations require the owning authorized user; reads follow the resolved session/evidence policy. Stale/conflicting transitions return a documented conflict response. There is no public arbitrary-child-spawn endpoint: dispatch remains a governed internal intent. Finalize request/response schemas with subissue 02 and update route-count pins with subissue 16.

### E. Results, receipts, and verification

**Draft decision:** receipt composition reports execution truth; evidence verification remains attached to the work product it actually checked.

Children publish a typed terminal result with session/topic IDs, status, error category, optional result/evidence references, and cost totals. An empty result is valid. Bound the context returned to the parent separately from child count and concurrency, retaining authorized references to larger work products. Metadata receipts contain IDs, counts, phases, digests, timing, policy outcomes, and costs. Research text stays in appropriately access-controlled work-product/content storage, outside audit/OTel records. Framework tracing must conform to that same policy.

Show topic coverage and execution completion separately from citation status. Preserve each child's existing gate. If synthesis creates new cited assertions, pass that final work product through the existing ledger/gate machinery. Missing/failed verification is explicitly unverified; a collection of passing children cannot turn an unchecked synthesis green. The orchestrator fixture suite tests these status mappings with fixture verdicts, not legal-quality judgments.

Use ordered child sub-timelines plus the parent's own timeline. Sort by recorded sequence/dispatch order, with stable tie-breakers. Avoid rebuilding a whole tree through one query per event. The tree can join existing `tool_call_log.session_id`; an extra `root_session_id` column in that log is not required for v1.

## 4. Milestones, proposed subissues, and check gates

Each subissue should become a reviewable change with explicit dependencies, schema/doc updates, and focused tests. Split large schema/API/UI items further at preparation time. Security review applies to authorization, budget, cancellation, audit, and gateway changes, not just the original P4.

| Milestone | Proposed subissues | Depends on | Exit gate |
|---|---|---|---|
| **M0 — Compare and ratify the contract** | **01** Review scope and the common fixture acceptance scenario. **02** Prepare an unnumbered draft ADR covering decisions A–E and the prior-art comparison. **03a** Review the completed isolated spike, then validate the candidate against actual LQ guards, Postgres and multi-step child recovery; the stdlib fixture is not a Postgres/arq comparison. **03b** Select one execution-state owner, ratify the ADR, reconcile overlapping PRs and name reviewers; partially supersede ADR 0013 D1, clarify transaction semantics, update DE-294 and fix ADR 0020's bad link. | Isolated spike completed before D0; application integration follows review and its required dependency baseline | **G0a:** Houfu reviews the spike and authorizes the next bounded maintenance/integration work. **G0b:** actual integration evidence supports the selected backend and architectural decisions before full harness implementation. |
| **D0 — Retire the existing runtime debt** | Complete **issue 524 / DE-319** in one separate PR across all three executors: fix typing, upgrade the compatible runtime family, review new/transitive packages and advisory floors, refresh debt/pin documentation, and remove the obsolete Dependabot exception. Preserve runtime behavior; checkpoint activation belongs to the later harness integration. | G0a; source-level design can proceed alongside this milestone | **GD0:** lock and manifest consistent; reviewed dependency diff and advisories; Ruff/mypy clean; compiled-graph tests for all three executors and required API tests pass; container/stack smoke passes. |
| **M1 — Durable, governable runs** | **04** Add hierarchy, policy/skill snapshot, scheduling states and migration/backfill. **05** Integrate durable progress through the selected backend, per-effect records, execution ownership and short transaction boundaries. **06** Implement unique admissions and recovery at the chosen checkpoint/queue boundaries. **07** Add atomic budget reservations, settlement and parent allowance. **08** Add root cancellation and correct watchdog/deadline handling. | M0 / G0b | **G1:** real Postgres race/crash fixtures prove no duplicate child admission, no double budget release, recoverable dispatch, prompt cancellation visibility, and no locks on control rows across I/O. |
| **M2 — Governed profile and handoffs** | **09** Extract the minimum harness interface/closed dispatch registry needed by two profiles; preserve existing single-session behavior. **10** Add strict research-plan/subtask schemas, delegation envelope, resource scoping and both tier constraints. **11** Add visible orchestrator skill artifact, plan persistence and version-bound approval state. | M1 contracts; 09 can follow M0 independently | **G2:** malformed/hostile envelopes fail before dispatch; changed authority/skills invalidate approval; direct handler paths cannot bypass governance; existing autonomous regression tests pass. |
| **M3 — Parallel orchestration** | **12** Dispatch approved topics through the selected execution topology, with independent child sessions and limits per root/user/deployment. **13** Join terminal child outcomes and resume the parent from durable state. **14** Add partial/empty/failure handling, internal child delivery and root-only notification. **15** Propagate inference purpose/run/root correlation, stripping internal metadata before provider requests. | M1 + M2 | **G3:** a root with two blocked stub searches has both children in flight before either is released; parent resume/retry does not respawn them; empty child results do not prevent completion. |
| **M4 — Review and inspect in the UI** | **16** Expose plan read/approve/reject, tree read, and documented status/result contracts. **17** Add research intake with selected documents/sources, explicit plan preview and approve/reject controls. **18** Add tree status, budget breakdown, halt, stable child receipts, bounded polling and manual refresh. **19** Compose evidence/gate metadata and optional final-synthesis ledger integration. | M2 API contracts; runnable flow follows M3 | **G4:** browser scenario proves no child starts before approval, concurrent progress is visible, rejected/stale plans never execute, halt and partial results remain inspectable. |
| **M5 — Release verification** | **20** Run adversarial, race, crash, capacity and compatibility matrix. **21** Update PRD, HONEST-STATE, autonomous guide, DB schema and affected OpenAPI sketches/generated export; provide operator controls and rollback/run-drain instructions. | M3 + M4 | **G5:** all mandatory orchestration checks pass; reviewers approve sensitive paths; feature remains operator-disabled by default until enablement. No live-search relevance gate. |

**Critical path:** isolated prototype (completed) → user review/G0a → required application maintenance/D0 and actual integration proof → ratification/G0b → durable execution/budgets → governed child dispatch → parallel join/recovery → approval/tree UI → release checks. The existing-runtime maintenance is separately reviewable; it does not decide the new harness backend. Moving the general harness abstraction ahead of the durable proof would increase risk. H1–H3 from the epic are reduced to subissue 09; H4 is deferred.

Gateway correlation may be developed alongside dispatch once its contract is pinned. A source/task's IDs must remain internal correlation metadata, never authorization inputs or third-party model fields. Repair unrelated `playbook_executor`/`tabular_extraction` purpose labeling separately unless the same small compatibility change naturally covers it.

The epic's 35–55 engineer-day estimate is not a verified estimate for this revised scope. The earlier draft's 35–60-day allowance is also withdrawn pending backend selection. Parallel execution and durable approval add work; existing runtime primitives may remove substantial custom work. Estimate the selected implementation after G0b, separately identifying reviewer availability.

## 5. Concrete acceptance matrix

These production tests are to be implemented **after plan approval**. The separate throwaway fixture passes 23 tests covering a subset of the behavior below using SQLite and stub controls; it does not satisfy the application integration or release gates.

| Case | Required evidence |
|---|---|
| Approval barrier | Create a root with two planned topics; exercise available scheduling paths; zero child runs/tool calls occur before approval. Approval admits exactly the intended child slots. |
| Genuine parallelism | Hold both stub search calls on independent barriers. Observe both entered before releasing either. Do not rely solely on elapsed-time assertions or two rows marked running. |
| Empty results | Both searches may return empty payloads. Parent joins their terminal states and finishes without fabricated sources or a nonempty-content requirement. |
| Isolation | Each child receives only its approved topic, sources/documents, grants and skill version. A foreign or owned-but-unselected document ID is rejected. No sibling conversation sharing. |
| Approval races | Double click, replayed request, changed plan hash, expired/rejected plan, changed policy, and halt-versus-approve cannot create unauthorized children. |
| Budget races | Concurrent admissions and root synthesis reservations cannot exceed the accounted cap; retries cannot double-charge or double-release; unknown outcomes retain funds; parent retains completion allowance. |
| Dispatch and recovery | Inject failure before/after admission commit, checkpoint writes, enqueue where applicable, child invocation, child completion and parent continuation. Recover without duplicate child records or replay of recorded completed steps. Uncertain external outcomes remain explicit. |
| Cancellation | Use independent DB transactions and actual worker boundaries. Halt while both searches are held; the control request commits without waiting for their completion; neither child begins another call. A waiting/queued child never starts. |
| Failure semantics | Ordinary child failure follows the approved partial-result policy; empty success remains distinct; root halt/budget/authority refusal stops new work; all-failed children never produce a successful research claim. |
| Injection/refusal | Reject unknown target, forbidden intent, wrong field type and extra authority fields. Hostile topic/source/result text changes neither system prompts, sibling plan, source scope, grants, tier policy nor budget. Assert refusal audit metadata without raw payload leakage. |
| Evidence status | Fixture gate statuses demonstrate that absent/failed child or final verification cannot become a green aggregate. No live citation-quality measurement. |
| Capacity | Test more roots than worker slots, multiple workers, deployment limits and provider 429s. Approval waits release job slots; parents waiting on separately queued children cannot consume the capacity needed to run them. Retries are bounded and interactive work remains available. |
| Compatibility | Existing manual single-agent, schedule, watch, receipts and halt scenarios still pass. Migration up/down is checked on a throwaway pgvector Postgres; existing rows backfill as roots. |
| UI | Controlled end-to-end flow: intake → plan preview → approve → two concurrent children → halt or complete → inspect tree. Refresh stops at terminal state and cleans up on navigation. |

Run focused API tests, schema-conformance/route pins, transparency invariants, gateway tests for changed routing fields/policy, Svelte checks, Vitest and the controlled Cypress scenario. Use `uv`, both Ruff format/check, and the repository's mypy settings. Then run the broader required suites once for integration. Migrations use a throwaway `pgvector/pgvector:pg16` database; applying them to a dev stack requires rebuilding api/arq-worker/ingest-worker together.

## 6. Existing work and rollout constraints

- **[PR 411](https://github.com/LegalQuants/lq-ai/pull/411), issue 334 / DE-322 — merged:** write-time playbook/KB visibility and archived matter/KB rejection now form part of the remote baseline. It changes `_spawn_manual_session` from `user_id` to `user: User`; subsequent intake changes must preserve the checks and this calling convention. Recorded API, Gateway, Web and release-image checks passed. This does not complete durable child authorization, matter membership, research intake or the LangGraph migration.
- **[PR 410](https://github.com/LegalQuants/lq-ai/pull/410), issue 332:** still open at the previously reviewed head `961c2c7`; proposes the missing `query` field and matter-intake UI. Latest check: GitHub reports MERGEABLE/CLEAN and API/Gateway/Web pass, but those results date to 25 July. Candidate merge `d20147c` includes #411 and preserves its ownership checks and `user`-based spawn interface, with no check runs on that candidate. The selected-KB execution, cost-input and planner data-handling findings remain: correct them and run fresh checks against the merged baseline before merging and reusing the intake. Issue 332 is the issue it closes, not another PR. See the [merge assessment](issue-563-pr-prerequisite-review.md).
- **[PR 536](https://github.com/LegalQuants/lq-ai/pull/536):** changes matter membership and autonomous access checks. Follow-up review recommends holding it separately for access-revocation, sandbox, deletion and API-contract corrections; it is not a prerequisite for the agreed orchestration pilot, which can initially use existing owner-scoped resources. Inherit authoritative resource visibility through one interface and recheck authority at execution time. If membership lands later, add revocation coverage without granting tree-wide shared access. This sequence remains a recommendation for user review.
- **[Issue 524](https://github.com/LegalQuants/lq-ai/issues/524) and [PR 558](https://github.com/LegalQuants/lq-ai/pull/558):** recommend issue 524 as a separate maintenance milestone before adding durable LangGraph execution to the application, if selected. The authorized isolated spike has already run without upgrading the application. PR 558 targets 0.6.11, fails with 12 typing errors across the three executors, and does not reach pytest. That intermediate version excludes newer checkpoint/SDK fixes through its dependency caps. Prefer a corrected direct 1.x migration; supersede or retarget PR 558 when that replacement is ready. Updating dependencies does not itself authorize checkpointing or select a harness backend. This remains a plan recommendation, not a GitHub mutation.
- **[PR 564](https://github.com/LegalQuants/lq-ai/pull/564):** proposed roadmap/governance changes and ADR/DE number collisions. It also reports ineffective review routing/settings. That report was not independently verified against organization settings in this pass; name actual reviewers and obtain explicit sign-off rather than relying on presumed automation.
- Existing sources expose different operations. CourtListener supports search/read; GovInfo/EDGAR/EUR-Lex must be selected only for operations their enabled adapters actually support. Reusing sources does not imply a universal search interface. The existing `case-law-research` skill is U.S. case-law-specific and cannot silently become a general regulatory skill.
- Expand schema first, deploy compatible workers/UI, then enable orchestration behind an operator control. Disabling it blocks new roots/dispatch and preserves read/halt access to existing runs. Do not downgrade away live trees; drain/halt and retain their evidence before a schema rollback.
- ADR 0016's operator-control principle also needs an actual visible configuration/admin surface for the new feature and limits, not hidden `params` accepted from model output.

## 7. Research and evidence limits

The inspected checkout is `e42f842e860f8930a7f30da2b2a56a2f275fbac0`. GitHub's canonical main was `de73fa4061a0b76c55d9ec61052f5c7816a18606`; the key autonomous, worker, governance, inference-purpose and autonomous UI paths cited here were compared and had no committed diff between those revisions. The checkout contains unrelated staged gateway test changes, which were not modified. Issue 563 had no comments at inspection. Its private Claude planning artifact could not be retrieved, so prior effort estimates and claimed research were independently checked where possible, not treated as evidence.

The initial research below was primarily substrate validation. It did not adequately justify choosing a custom harness coordinator. The [subsequent prior-art assessment](issue-563-prior-art.md) compares Anthropic Research, Open Deep Research, Deep Agents, OpenAI Agents SDK, LangGraph, pi and Temporal, with specific source paths and adoption limits. It changes decision A and adds G0a/G0b before implementation.

Additional primary-source evidence:

- [arq execution and job uniqueness](https://arq-docs.helpmanual.io/#usage): jobs may execute more than once; queue IDs alone are not permanent idempotency. This supports database-owned child admission and recovery.
- [PostgreSQL row locking](https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS): conflicting updates wait for the holding transaction. Combined with the executor's flush/terminal-commit pattern, this identifies a cancellation-visibility risk to reproduce at G1; it is not a claim that a live race test was run here.
- [SQLAlchemy asyncio guidance](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks): concurrent tasks require independently managed sessions. This does not provide dispatch durability by itself.
- [LangGraph functional API](https://docs.langchain.com/oss/python/langgraph/functional-api) and [persistence](https://docs.langchain.com/oss/python/langgraph/persistence): durable execution still requires deliberate treatment of side effects and retries. Subgraphs are not inherently governance bypasses. Select execution-state ownership at G0b; the earlier recommendation to defer this comparison until G1 is withdrawn.
- [pi extensions](https://raw.githubusercontent.com/earendil-works/pi/refs/heads/main/packages/coding-agent/docs/extensions.md) and [pi overview](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md): pre-tool blocking and extension-based subagents exist. Adoption would still require adapting LQ.AI's gateway, grants, persistence and audit.
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness): a Node-based developer preview with an explicit compatibility-change warning. Useful design reference; no demonstrated integration advantage here warrants moving this executor onto it.

## 8. Review decisions

The user choices in section 1 are incorporated. Approval of this draft should additionally settle:

1. One level, four topic slots, default concurrency two, one active root per user, and one approved batch.
2. Review the completed isolated spike and its limits. Keep issue 524 as separately reviewed application maintenance; authorize the next bounded integration proof before selecting the backend and clarifying transaction boundaries at G0b. Production dependency changes and integration coding remain subject to approval.
3. An honestly labeled accounted-budget ceiling; a strict provider-invoice ceiling is a separate metering requirement if desired.
4. The recommended partial-result policy for ordinary child failure; root halt, exhausted budget and revoked authority stop dispatch.
5. Minimal harness extraction and metadata receipts now; raw replay/fork transcripts and general research-quality work deferred.

**Next action: Houfu reviews this revised plan, the prior-art/dependency assessment and the completed isolated prototype.** The throwaway implementation and its LangGraph 1.0 comparison were authorized and completed. Application dependency upgrades and production coding remain subject to approval. The proposed next steps are separately reviewed runtime maintenance, the bounded application integration proof and backend ratification before full harness implementation. File milestones/subissues only when authorized, using available identifiers.
