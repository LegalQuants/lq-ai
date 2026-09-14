# Research supporting ADR 0035

Findings from 12–14 September 2026 supporting
[ADR 0035](../adr/0035-governed-orchestration-run-tree.md). These explain the
architecture choices; the [implementation overview](../plans/issue-563-workflow.md)
describes the delivered capabilities and remaining release conditions.

## Main finding

LangGraph can supply continuation, approval interrupts and parallel joining while
LQ retains authority, accounting and audit. The research supports this division
of responsibilities. It does not demonstrate that LangGraph is faster or cheaper
to maintain than every alternative.

The existing 0.2.76 runtime already had the necessary
[primitives](https://github.com/langchain-ai/langgraph/blob/0.2.76/libs/langgraph/langgraph/types.py).
The upgrade therefore addresses dependency maintenance and integration, rather
than an absence of orchestration features. arq remains the scheduler, with no
second owner of graph progress. Its
[maintenance-only status](https://github.com/python-arq/arq) also argues for keeping
that integration narrow instead of building a large workflow engine around it.

## Harness comparison

| Reference | Useful finding | Implication for LQ |
|---|---|---|
| [Anthropic multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | A lead delegates independent topics to researchers with separate contexts, then synthesizes their findings. | Use explicit task scope, stopping conditions and artifact references. The account supports the workflow, without establishing legal-research quality. |
| [Open Deep Research](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/src/open_deep_research/deep_researcher.py) | Inspectable supervisor/researcher separation and concurrent batches; the examined path starts research without LQ's durable approval barrier. | Borrow the separation of roles, retain a typed outcome for each topic and add approval before child admission. In-process overlap alone does not prove restart safety. |
| [Deep Agents](https://github.com/langchain-ai/deepagents/blob/178417d0dad063fea0300db68455f4574ef67db3/libs/deepagents/deepagents/middleware/subagents.py) | Packaged delegation and context isolation, with configurable inheritance of tools and state. | Child isolation does not imply reduced authority. LQ must calculate permission intersections and adapt filesystem, memory and model access to its policies. |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python/blob/298b87c72209ae88d1fb22f8361ebb89e876b2dc/examples/research_bot/manager.py) | The research manager combines typed planning, concurrent searches and synthesis. The SDK also offers [approval and resumable run state](https://openai.github.io/openai-agents-python/human_in_the_loop/). | The manager pattern fits a user-facing root with internal children. SDK state does not supply LQ's atomic approval, budget and dispatch records. |
| [Pi extensions](https://github.com/earendil-works/pi/tree/main/packages/coding-agent/examples/extensions/subagent) | Extension-based subagents and blocking tool hooks make it a credible harness reference. | Integration with a TypeScript/process harness is the tradeoff; absent delegation or hooks is not a valid reason to reject it. |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | Provides useful executor and sandbox interfaces for agent tools. | Study its execution boundary independently of the choice of continuation engine. No measured integration benefit justified replacing the existing executor. |
| [Temporal child workflows](https://docs.temporal.io/develop/python/workflows/child-workflows) | Distinguishes child start from completion and makes parent-close behavior explicit. | Adopt those lifecycle questions in the run-tree contract. A separate workflow platform was not justified for the bounded first profile. |

Whole-harness adoption remains a larger change than adding persistence to the
existing executor. Every candidate still needs LQ-specific gateway, selected-data,
approval and audit enforcement. These adoption judgments are engineering
inferences from the inspected interfaces, not conclusions claimed by the projects.

## What the backend experiments established

The [isolated prototype](https://github.com/LegalQuants/lq-ai/tree/4ac3fee64/outputs/issue-563-spike)
used the same application contracts and effect receipts with a LangGraph adapter
and a plain-Python fixed-batch adapter. Its 23 tests passed on LangGraph 1.2.11 and
unchanged on 1.0.10. They exercised approval across process restarts, overlapping
children, empty outcomes, halt, revoked scope, completed and uncertain effects,
and replacement of either adapter by the other.

That establishes a replaceable boundary for **one effect per immutable topic**.
It does not establish portable arbitrary graph state or a code-size advantage:
the small native adapter was not a production Postgres/arq workflow engine.
Both implementations still needed application-owned approval and effect receipts.

Two additional checks resumed 1.2.11 data under 1.0.10. Companion Core/checkpoint
packages stayed unchanged, so this is narrow fixture compatibility. It is not a
general downgrade guarantee or approval of the older runtime's dependency family.
The 1.0.10 fixture's SDK 0.3.15 lacked the
[resource-authorization fix in 0.4.4](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-fvww-7h3r-vfhp);
the affected feature was unused in the experiment.

The [Postgres/LQ-guard probes](https://github.com/LegalQuants/lq-ai/blob/c8fa25c4cda82535bf15ce816f5a28dced614fd8/docs/plans/issue-563-postgres-probe.md)
demonstrated interrupt/resume, overlapping multi-step children and enforcement of
current halt state. They also exposed three consequences of naive integration:

| Observation | Required application control |
|---|---|
| An application commit can survive while its graph checkpoint does not. | Durable effect identities and receipts must suppress repeated dispatch. |
| An interrupted request may have reached a provider without a recorded outcome. | Commit intent and reserve budget before dispatch; preserve uncertainty for reconciliation. |
| Two savers using the same thread can both reach a provider. | Acquire and fence worker ownership; checkpoint storage is not a worker claim. |

Those are findings from diagnostic fixtures, not assertions of defects remaining
in the completed implementation. They explain why checkpointing cannot replace
LQ's governance records. The current capability summaries describe the integrated
recovery behavior.

## Script execution and confidentiality

| Harness reference | Execution approach observed | Lesson for LQ |
|---|---|---|
| [Pi security policy](https://github.com/earendil-works/pi/security) | Commands run within the local user's trust boundary. | Skill packaging does not contain code or provide a sandbox. |
| [Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends) and [sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes) | File-only backends can omit execution; shell/sandbox backends can run general commands. | Storage, execution and network authority are separate choices. A sandbox does not automatically prevent disclosure through permitted access. |
| [DeepSeek sandbox contract](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/sandbox/README.md) | The examined host-process contract restricts filesystem effects and supports permission escalation, without expressing network or credential isolation. | Broader containment needs an appropriate executor; file restrictions alone are insufficient. |
| [OpenAI Agents SDK tools](https://openai.github.io/openai-agents-python/tools/) | Fixed function tools, hosted code interpretation and local/hosted shell are distinct options. | The selected tool and executor determine executable authority; a skill declaration does not impose bundled-only execution. |

For LQ, vetting reduces the likelihood of harmful code, while runtime isolation
limits what a compromised approved helper can access. Restricting network access
still leaves indirect disclosure: helper output could induce a later model or
tool call to send protected data elsewhere. Saved output can carry that risk
into a new skill invocation.

This supports optional storage, exact reviewed bundles and images, isolated
execution, and application enforcement of source restrictions through output and
reuse. The strengthened hostile-output and production-boundary acceptance work
remains pending under ADR D8c/D8d.

## Evidence scope and full assessment

The orchestration comparison uses pinned source revisions where available; the
execution comparison records upstream documentation reviewed on 14 September.
Neither constitutes an independent audit or a performance benchmark. Local
experiments used controlled providers and do not establish research quality.

The [full original research assessment](https://github.com/LegalQuants/lq-ai/blob/4ac3fee64/outputs/issue-563-prior-art.md)
preserves detailed sources, dependency/advisory analysis and prototype limits.
Its provisional recommendations and open gates describe that research snapshot;
the current ADR and implementation overview govern present status.
