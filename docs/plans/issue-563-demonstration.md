# Orchestration demonstration

The demonstration lets an owner approve parallel agent work, monitor it and
inspect the combined result. The implementation adds this flow
under **Autonomous sessions → Orchestration demo**, behind an operator setting.
See the [feature PRD](../prds/issue-563-governed-orchestration.md) for requirements
and release status.

After migration 0067, an operator can set `LQ_AI_ORCHESTRATION_DEMO_ENABLED=true`
in the development or release Compose environment and restart the API and arq
worker. Both services receive the flag and a shared child-capacity limit of two
unless `LQ_AI_ORCHESTRATION_DEPLOYMENT_CHILDREN` overrides it. The flag enables
only this sample workflow; live providers, persistent skill workspaces and
bundled helpers remain separate capabilities.
Drain or halt active demo runs before switching the flag off. With the flag off,
the worker schedules no orchestration recovery or execution; owner read and halt
access remains available. Switching the flag off does not itself halt or expire
retained runs. A queued or running root can remain active until its owner halts it
or recovery runs after re-enablement; the one-active-root-per-owner rule still
applies. Plans have a one-hour deadline. If that deadline passes while the flag
is off, recovery on re-enablement expires the run or marks unresolved effects
for reconciliation rather than resuming it.

## User-visible behavior

- Select an owned active project and one to four topics. Review the plan, scope
  and budget, then approve or reject that exact revision before children run.
- Follow separate child sessions as they progress concurrently. Inspect their
  findings and receipts; only the root delivers the final synthesis.
- Halt further work and retain available results. Ordinary child failure preserves
  successful siblings; empty, partial and failed outcomes remain distinguishable.
- Inspect private notes and explicitly shared findings in the run receipt.
  [Working files](issue-563-workspace.md) survive interrupted execution.

LangGraph maintains continuation, arq schedules work, and LQ retains approval,
authority, accounting and audit. Waiting releases workers; recovery reuses
completed effects and preserves uncertain calls for reconciliation.

## Demonstration scope

Topic labels form the plan without an LLM call. Child responses and synthesis use
a deterministic sample provider through the actual guarded execution path.
Results remain labelled as a demonstration and unverified. This does not establish
model planning, citation quality or live research integration.

Local checks exercised the complete queue/database flow, concurrent children,
restart, approval, halt and partial/empty outcomes. Controlled browser checks
covered plan review, changing progress and result inspection. Real-matter
selected-document/KB integration, live providers and production enablement remain
pending.
