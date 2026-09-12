# Issue 563 — prior art and revised harness recommendation

**Research date: 12 September 2026. Research and production-design proposal, supplemented by the authorized isolated prototype and LangGraph 1.0 comparison described below. Application implementation remains subject to review.**

The earlier plan examined our repository carefully but did not adequately compare existing harnesses before choosing custom continuation machinery. That choice is reopened. The subsequent [authorized throwaway integration](issue-563-spike/README.md) demonstrates a replaceable execution adapter using LangGraph and plain Python for one fixed research batch. It supports keeping LQ's contracts, authority, budgets, audit and gateway access independent of the framework; it does not yet establish which production coordinator is simpler. **The prototype ran before the application upgrade, in its own maintained dependency environment, as Houfu requested.** Section 6's issue-524 migration remains a separate application maintenance recommendation. The presence of primitives in 0.2.76 is a capability finding, not a recommendation to retain that version.

## 1. Closest prior art

### Anthropic's multi-agent research system: closest product workflow

Anthropic describes a lead researcher assigning independent topics to parallel researchers with separate contexts, then synthesizing their findings. Its engineering account emphasizes clear task boundaries, effort limits, persistent progress, and returning references to substantial artifacts. Its lead can commission further research after reviewing results. This is a production account, not a downloadable implementation of the entire system. [Engineering article, June 2025](https://www.anthropic.com/engineering/multi-agent-research-system).

**Design consequence for LQ:** specify each child by its question, scope, permitted sources, output contract and stopping condition. Keep child observations separate; let the root retrieve authorized evidence by reference. Our first release can deliberately use one approved batch. Further batches would need another approval. The article supports the workflow choice; it does not establish research quality for our legal sources or determine our worker architecture.

### LangChain Open Deep Research: closest inspectable research implementation

The inspected implementation separates clarification, a research brief, a supervisor, researcher loops, research compression and final reporting. `supervisor_tools` limits a batch of `ConductResearch` calls and invokes researcher subgraphs with `asyncio.gather`. Researchers receive topic-specific messages; their compressed reports return to the supervisor. The shown path does not contain a user-approval barrier before delegation. Its broad exception handling can end the supervisor research phase. [Pinned implementation](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/deep_researcher.py#L291).

**Design consequence for LQ:** reuse this separation of responsibilities. Keep a typed outcome for every approved topic, including failures and empty results, instead of collapsing all outcomes into report text. In-process concurrency in this example does not by itself prove restart-safe scheduling. Our orchestration tests should exercise the real control flow with stub researchers; useful search output remains outside acceptance.

### Deep Agents: closest packaged harness

Deep Agents provides a tool loop with context management, skills, delegation and approval support on LangGraph. This makes it a much more relevant comparison than evaluating only coding CLIs. [Overview](https://docs.langchain.com/oss/python/deepagents/overview).

The inspected `SubAgentMiddleware` distinguishes isolated task messages from conversation forks. Tools can inherit from the parent, and explicitly supplied filesystem permissions replace the parent's rules. Other permitted state fields can also cross the boundary. These are configurable library semantics, not proof that a child is less privileged. [Pinned middleware](https://github.com/langchain-ai/deepagents/blob/178417d0dad063fea0300db68455f4574ef67db3/libs/deepagents/deepagents/middleware/subagents.py#L66).

Its asynchronous delegation interface separates starting, inspecting, updating and cancelling a task. Task metadata lives outside the message history so compaction cannot erase task identities. That interface requires an Agent Protocol server; co-deployment is supported, so it does not necessarily require a separate service or hosted platform. [Async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents).

**Design consequence for LQ:** borrow isolated child contexts and a durable task registry. Persist authority separately, and compute permission intersections in LQ. Progress polling belongs in deterministic backend/UI code for our batch workflow. We do not need the model to repeatedly call a status tool. Approval must cover the whole immutable batch before its first child starts; per-child tool approval alone does not establish that invariant.

**Adoption assessment:** worth studying, but importing the whole harness is not yet my preferred route. The inspected source identifies version 0.7.13 and requires LangChain >=1.4.0, LangChain Core >=1.6.2, and additional model integrations. This is a broader dependency change than enabling primitives in our existing LangGraph executor. [Pinned dependency manifest](https://github.com/langchain-ai/deepagents/blob/178417d0dad063fea0300db68455f4574ef67db3/libs/deepagents/pyproject.toml). Its filesystem, memory and model integration surfaces would need a separate fit assessment against our gateway and selected-document rules.

### OpenAI Agents SDK: compact manager and approval interfaces

The SDK explicitly distinguishes a manager invoking agents as tools from a handoff that transfers conversational control. The manager pattern fits our user-facing root and internal researchers. [Agents and manager pattern](https://openai.github.io/openai-agents-python/agents/).

Its `research_bot` example is particularly concrete: `_plan_searches` produces a typed search plan, `_perform_searches` launches concurrent tasks and collects completions, and `_write_report` synthesizes. The example immediately starts searches after planning; caught search exceptions become `None`. It does not demonstrate our durable approval or crash-recovery contract. [Pinned research manager](https://github.com/openai/openai-agents-python/blob/298b87c72209ae88d1fb22f8361ebb89e876b2dc/examples/research_bot/manager.py#L37).

The SDK supports approval on an agent-as-tool invocation, propagates nested interruptions to the outer run, and can serialize `RunState`. Its documentation recommends recording agent/SDK versions alongside long-lived paused state. [Human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/).

**Design consequence for LQ:** use an explicit manager contract, a persisted pending decision, and version-aware resume. SDK state persistence is useful machinery; it does not itself prove that our approval record, budget reservation, child creation and dispatch are transactionally consistent.

There are two concrete integration checks. Agent-level input/output guardrails do not run before every action; tool guardrails have their own coverage limits. LQ's enforcement must wrap each applicable invocation, including inference. [Guardrail boundaries](https://openai.github.io/openai-agents-python/guardrails/). Tracing can capture model/tool inputs and outputs, with sensitive-data capture enabled by default; an adapter would need deliberate trace configuration and an approved export path. [Tracing](https://openai.github.io/openai-agents-python/tracing/).

**Adoption assessment:** a credible alternative if we later replace the inner loop, but it introduces another execution abstraction beside LangGraph. For this feature, its manager, typed-result and approval interfaces are more immediately useful than adopting the entire SDK.

## 2. Runtime and smaller-harness references

### LangGraph deserves a real comparison before we build its equivalent

Our lockfile pins **0.2.76**. That version already contains `Send`, `Command`, `interrupt` and checkpointer integration. `interrupt` resumes by re-entering its node, making replay boundaries consequential. These capabilities are verified in version-specific source, not inferred from current documentation. [0.2.76 source](https://github.com/langchain-ai/langgraph/blob/0.2.76/libs/langgraph/langgraph/types.py#L181).

Our executor currently calls `graph.compile()` without a checkpointer, and its analysis loop keeps progress inside one phase node. This is an integration gap, not evidence that LangGraph lacks the needed primitives. [Local executor](../api/app/autonomous/executor.py#L232), [local state contract](../api/app/autonomous/state.py#L13).

Current LangGraph documentation describes parallel workers with their own input state and combined outputs. [Orchestrator-worker example](https://docs.langchain.com/oss/python/langgraph/workflows-agents#creating-workers-in-langgraph). Checkpointers persist execution progress and successful task writes within a partly failed parallel step. [Checkpoint documentation](https://docs.langchain.com/oss/python/langgraph/checkpointers). A Postgres-backed saver is available; library checkpointing does not inherently require another database service. [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence). Exact saver/runtime compatibility and failure behavior still require validation at the versions we choose.

**Revised recommendation:** evaluate LangGraph as the owner of graph continuation and parallel joining. Keep LQ's database records authoritative for identity, approval, current permissions, budget reservations and audit. A checkpoint may reference those records; it must not restore stale authority over newer policy. The same Postgres server does not make separate checkpoint and business-data writes atomic.

Enabling a checkpoint only around the existing five phases would still replay work inside a failed analysis phase. We need deliberate step boundaries for model/tool effects. An interrupt can re-execute preceding code, so approval and dispatch should be separate boundaries with idempotent admissions. [Interrupt replay rules](https://docs.langchain.com/oss/python/langgraph/interrupts#side-effects-called-before-interrupt-must-be-idempotent).

`Send` is also not a distributed queue: distinguish concurrent child execution inside one invocation from independently scheduled child runs. Either topology must give children their own LQ sessions and database transaction scopes. If children are separate jobs, a waiting coordinator must yield rather than occupy the worker capacity those children need. arq can schedule resumptions, but it should not independently own a second graph cursor.

### pi and DeepSeek Harness: useful narrower lessons

The issue's statement that pi has no pre-tool hook is incorrect: extensions can intercept and block tool calls. [Extension documentation](https://raw.githubusercontent.com/earendil-works/pi/refs/heads/main/packages/coding-agent/docs/extensions.md). Its subagent example includes separate task-count/concurrency limits, bounded returned output, cancellation signals and per-child progress. [Subagent example](https://raw.githubusercontent.com/earendil-works/pi/refs/heads/main/packages/coding-agent/examples/extensions/subagent/index.ts).

**Design consequence for LQ:** expose a small harness interface with separate limits for topic count, active children and returned context. Treat UI progress as structured events. Adopting pi would still require adapting a TypeScript/process-based runtime to our Python executor and governance model; lack of delegation is not a valid rejection reason.

DeepSeek Harness is plugin-oriented and currently identifies itself as a Node-based developer preview with compatibility-breaking changes expected. [Repository](https://github.com/deepseek-ai/deepseek-harness). It supports considering a small extension boundary, but I have not established an adoption advantage over the Python candidates. This pass checked its overview, not all of its plugin internals.

### Temporal: a reference for lifecycle semantics, rather than our first adoption candidate

Temporal distinguishes child-start acknowledgement from child completion and makes parent-close behavior explicit. [Python child workflows](https://docs.temporal.io/develop/python/workflows/child-workflows).

**Design consequence for LQ:** define what happens to every child when the root fails, expires, is cancelled or completes. Our records must distinguish planned, admitted, started and terminal work. Borrow these failure cases for acceptance testing. Adopting Temporal would expand this issue into a workflow-platform decision; no evidence from this pilot yet warrants that expansion.

## 3. What changes in the plan

| Earlier position | Revised position |
|---|---|
| Build the Postgres/arq continuation machinery first | Compare it with LangGraph checkpoint/interrupt/fan-out support before selecting the execution backend. |
| The old LangGraph pin justifies deferring these features | The primitives exist in 0.2.76. Assess compatibility and maintenance separately from capability. |
| Zero new dependencies | Prefer a small, reviewed dependency addition if it removes more custom lifecycle code than it introduces. This is a recommendation for review, not authorization to change dependencies. |
| One arq job per child is already decided | Independent child sessions and authority are required; scheduling topology is an implementation decision to validate. |
| A generic harness extraction is a prerequisite | Extract only the interfaces needed for the research profile and existing single-run behavior. |
| Recovery might be revisited after building it | Decide execution-state ownership before production implementation. Do not build parallel state machines and reconcile them later. |

This separates three responsibilities: **the skill defines the research task; the runtime manages progress and waiting; LQ decides what may run and what it may access or spend.** A library can implement the second responsibility without taking over the third.

The user requirements remain: parallel topic children in v1, approval before any child runs, enabled legal sources and selected documents, and orchestration acceptance independent of search-result quality. The recommended partial-failure policy is still awaiting the user's decision.

## 4. Comparison gate and authorized throwaway result

Houfu subsequently authorized a small throwaway integration before the application upgrade. The [completed spike](issue-563-spike/README.md) compares maintained LangGraph with a patched SQLite saver against a stdlib fixed-batch runner using the same application contracts and receipts. It passes 23 tests, including hard process crashes and backend replacement. This validates an adapter boundary; it is not the originally proposed Postgres/arq production comparison. Application source and dependency files remain unchanged.

The subsequent requested 1.0 comparison pins LangGraph 1.0.10 and passes the same 23 tests without Python changes, plus two resume checks using data created under 1.2.11. Its prebuilt and SDK packages also downgrade; SDK 0.3.15 excludes the 0.4.4 resource-auth fix discussed below. That feature is unused in the local fixture. The [version comparison](issue-563-spike/README.md#L7) distinguishes functional equivalence here from production dependency selection.

The remaining integration gate should compare the selected candidate with the actual LQ guard, Postgres and worker topology, including a multi-step child. Keep the application runtime migration separately reviewed. Do not build two production implementations or interpret the existing LangGraph dependency as deciding this new harness's design.

Both candidates must satisfy the same checks:

1. A two-topic plan persists and survives process restart before approval. No child model or search call occurs before approval. Duplicate approval does not admit duplicate children; a stale plan cannot run.
2. Two controlled child tasks overlap in execution, each with its own session and approved scope. Empty output is a successful outcome. The fixture needs no live research provider.
3. A recorded child completion survives coordinator restart and is not repeated. A call whose external result is unknown remains distinguishable from a recorded completion; do not claim exactly-once provider execution.
4. Root cancellation prevents new admissions and is checked before subsequent calls. Ordinary failure, expiry and root closure produce explicit child outcomes. Test the chosen partial-failure policy.
5. Root budget reservations remain atomic across children. Child messages, restored checkpoints and returned state cannot modify authority or replace current access checks.
6. Approval waits release worker capacity. A topology using separate queued children cannot deadlock when coordinator capacity is full. Document the scope of concurrency limits across workers.
7. Restart after a deployment either uses a compatible recorded execution version or refuses a resume explicitly. Audit/trace output stays within LQ's existing data policy.

The decision record should compare custom code retained, new dependencies, transaction boundaries, recovery ownership, worker behavior, retention and effects on the three existing LangGraph executors. Prefer LangGraph if it removes substantial continuation code while preserving these controls. Prefer the custom coordinator only if the evidence shows a simpler integration. Do not replace this gate with a successful two-call `asyncio.gather` demo.

PR 558 currently proposes **0.2.76 → 0.6.11**, not 1.x. The dependency assessment below recommends a direct 1.x migration under issue 524 instead of using that intermediate target. [PR 558](https://github.com/LegalQuants/lq-ai/pull/558).

## 5. Evidence limits

The prior-art comparison itself was primary-source research and source inspection. The later authorized [throwaway experiment](issue-563-spike/README.md) adds dependency resolution, execution and crash evidence for its own isolated configuration only. It does not benchmark the frameworks or prove application compatibility. Fixed source revisions inspected through GitHub were Open Deep Research `1b7d2e80`, Deep Agents `178417d0`, OpenAI Agents Python `298b87c7`, and LangGraph tag `0.2.76`. Current documentation may describe newer capabilities; it is not a compatibility guarantee for our pinned stack. Adoption judgments and proposed LQ boundaries are engineering inferences, not claims made by those projects.

## 6. Dependency upgrades and technical debt

**Recommendation: complete the existing [issue 524 / DE-319](https://github.com/LegalQuants/lq-ai/issues/524) migration to a maintained LangGraph 1.x baseline before adding durable orchestration.** This is useful maintenance even if we ultimately choose the custom coordinator: three existing features already depend on LangGraph. Keep that migration reviewable separately from checkpoint integration and harness behavior. No dependency files have been changed in this planning pass.

### Why the upgrade earns its place

Upstream designates LangGraph 1.x as active LTS; its published legacy support table does not include our 0.2 line. Deep Agents remains pre-1.0 and has a different stability promise. This supports moving the existing runtime forward without automatically adopting the larger harness. [Release policy](https://docs.langchain.com/oss/python/release-policy).

Our repeated upgrade failures are concrete debt. PR 558's recorded API job passes Ruff, then reports **12 `add_node` typing errors across the playbook, tabular and autonomous executors**. It stops before pytest. The failure is evidence of an unresolved type-integration problem; it does not prove a runtime regression or prove runtime compatibility. [CI job](https://github.com/LegalQuants/lq-ai/actions/runs/33166158461/job/98831953256). Our Dependabot configuration already singles out this package because of repeated failed upgrades. [Local configuration](../.github/dependabot.yml#L19).

There is also a timing advantage: the three executors currently have no persistent LangGraph checkpoints. Migrating before we introduce durable runs avoids adding a legacy checkpoint-format migration to the work. That is an inference about our integration cost, not a claim that the current upgrade is risk-free.

### Why I would skip PR 558's intermediate target

The PR changes only the manifest and lock, leaves the old hold comment, retains checkpoint 2.1.2 and moves the SDK to 0.2.15. Its manifest widens to `>=0.2.76,<0.7`, so it does not establish a modern minimum. It encounters the same typing problem we already need to solve for issue 524.

More decisively, LangGraph **0.6.11 requires checkpoint <4 and SDK <0.3**. Those caps exclude newer fixes discussed below. LangGraph **1.2.11** allows checkpoint 4.x and SDK 0.4.x, while requiring LangChain Core 1.x and adding the prebuilt package. [0.6.11 manifest](https://github.com/langchain-ai/langgraph/blob/0.6.11/libs/langgraph/pyproject.toml), [1.2.11 manifest](https://github.com/langchain-ai/langgraph/blob/1.2.11/libs/langgraph/pyproject.toml).

A corrected direct 1.x migration is therefore preferable to paying the integration cost for 0.6.11 and then upgrading again. Recommend superseding or retargeting PR 558 when the replacement is ready; no GitHub action has been taken.

### Review the package family and the features we will activate

| Package | Current lock | Candidate for the migration/integration |
|---|---|---|
| LangGraph | 0.2.76 | 1.2.11, the current published stable release observed; recheck at implementation. |
| LangChain Core | 0.3.86 | Compatible patched 1.x; PyPI currently reports 1.6.3. Review release age and resolved dependencies before selecting. |
| Checkpoint base | 2.1.2 | 4.2.0 is currently published. Require at least the applicable patched minimum, rather than trusting LangGraph's lower bound. |
| LangGraph SDK | 0.1.74 | 0.4.4, currently published and containing the recent custom-auth fix. |
| Postgres saver | Not installed | Consider 3.1.2 only if the checkpointed design is selected; review its psycopg 3 and pool dependencies. |

Published package records: [LangGraph](https://pypi.org/project/langgraph/1.2.11/), [Core](https://pypi.org/project/langchain-core/1.6.3/), [checkpoint](https://pypi.org/project/langgraph-checkpoint/4.2.0/), [SDK](https://pypi.org/project/langgraph-sdk/0.4.4/), [Postgres saver](https://pypi.org/project/langgraph-checkpoint-postgres/3.1.2/). These are candidates, not the output of a tested dependency resolution.

The checkpoint JSON deserialization advisory is patched in checkpoint **4.1.1**. It concerns loading tampered persisted checkpoints and requires unauthorized access to stored checkpoint bytes; it does not demonstrate a current remotely exploitable LQ path. Nevertheless, enabling persistent resume changes the relevance of an advisory previously excluded because we had no checkpointer. [Advisory](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-fjqc-hq36-qh5p).

The msgpack hardening also needs configuration: use strict deserialization with a supported allowlist mechanism, and verify that the selected saver actually applies it. Merely installing a newer version does not establish strict mode. [Advisory and configuration](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-g48c-2wqr-h844).

SDK **0.4.4** fixes resource-decorator action scoping. Our inspected code does not use those decorators, so this is a dependency hygiene consideration rather than evidence of an existing LQ authorization bypass. [SDK advisory](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-fvww-7h3r-vfhp). The Postgres package's **3.1.1** namespace fix concerns store search/list operations; distinguish that surface from checkpoint save/load during review. [Store advisory](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-47pj-3jcm-6whg).

LangGraph 1.2.11's declared minimums still admit checkpoint 4.1.0 and SDK 0.4.2. Use reviewed minimum-version constraints where needed and a frozen lock containing the actual approved versions. Do not treat `langgraph>=1,<2` alone as a sufficient patch policy.

One stale concern can be narrowed: issue 524 reports a websockets downgrade in an earlier proposed lock. Published SDK 0.4.4 metadata now allows `websockets>=14,<17`, which permits our existing 16.1.1. That SDK no longer forces the reported downgrade; the full resolver result still needs review. [Published SDK metadata](https://pypi.org/pypi/langgraph-sdk/0.4.4/json).

### Maintenance milestone and exit gate

After user approval, use a dedicated issue-524 PR to fix the three executors' typing, upgrade and lock the runtime family, refresh the debt entry and pin comments, and remove the obsolete pre-1.0 Dependabot exception. Preserve existing executor behavior; add checkpointing in the later harness change. Avoid blanket type ignores and unreviewed changes to unrelated packages.

The exit gate is: reviewed dependency additions/removals/downgrades and current advisories; lock consistency; Ruff and mypy clean; the existing compiled-graph tests for all three executors plus the required API suite passing; and container/stack smoke checks. The three focused test files currently contain 29 tests. Existing CI and images already install from the committed frozen lock. No dependency installation or runtime verification was performed here.

### Avoid replacing one kind of debt with another

arq explicitly reports maintenance-only status. [Repository](https://github.com/python-arq/arq). Retaining it as a small queue adapter may be reasonable; building a large new workflow engine tightly around it deserves stronger justification. Record ownership of enqueue/retry/cancellation integration and keep run state independent of queue internals. This finding does not by itself justify a queue replacement in issue 563.

For this project, assess debt by support coverage, reachable features, recurring upgrade work and custom code retained—not package age alone. The isolated prototype ran before the application migration at Houfu's request. Retiring the existing LangGraph integration debt remains separately useful; choose the new harness backend on actual integration evidence. Existing weekly update groups, release cooldown and frozen builds provide the maintenance mechanism; restore LangGraph to that mechanism once its exception is resolved.
