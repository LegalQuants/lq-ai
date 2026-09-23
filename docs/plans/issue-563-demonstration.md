# Orchestration demonstration

The local demonstration lets an owner approve parallel agent work, monitor it and
inspect the combined result. It is available in the unpublished implementation
under **Autonomous sessions → Orchestration demo**, behind an operator setting.
See the [feature PRD](../prds/issue-563-governed-orchestration.md) for requirements
and release status.

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
