# Issue 563: implementation overview

The local implementation of [#563](https://github.com/LegalQuants/lq-ai/issues/563)
provides governed parallel agents, durable working files and optional skill
storage and helpers. [ADR 0035](../adr/0035-governed-orchestration-run-tree.md)
remains proposed: the code is unpublished and the capabilities are disabled by
default. This PR documents the result for review. The
[research note](../research/issue-563-harness-research.md) explains the evidence
behind the architecture and security choices.

## What is built

| Capability | Available behavior |
|---|---|
| [Orchestration demonstration](issue-563-demonstration.md) | An owner reviews and approves one to four topics, follows parallel child progress, inspects findings and receives a root synthesis. Rejection, halt, empty results and partial failure are visible. |
| Governed execution and recovery | Each child has its own context and bounded authority. Current permissions, budgets and halt govern calls. Interrupted work retains completed results and accounting; calls with uncertain outcomes require reconciliation rather than automatic repetition. |
| [Run working files](issue-563-workspace.md) | Children save private notes across interruptions and explicitly share immutable findings with the root. Owners can inspect files after halt. Files last for the owning run. |
| [Persistent skill workspaces](issue-563-skill-capabilities.md) | Opted-in skills can reuse saved work in later invocations, within an owner/matter/skill namespace. Owners can inspect, export and reset it. |
| [Bundled Python helpers](issue-563-skill-capabilities.md) | Opted-in skills can call declared installed helpers through chat, query-driven background planning and guarded orchestration. Helpers receive selected JSON data and run in isolated, bounded containers. Storage and execution are independent capabilities. |

The demonstration uses controlled sample findings and labels its output
unverified. It demonstrates orchestration, without claiming substantive
legal-research quality. Generated code and arbitrary shell execution are excluded.

## Validation

Local integration checks exercised actual Postgres, arq/Redis, Docker and browser
flows. They cover approval, overlapping children, interruption/recovery, isolation,
budgets, halt, persistent storage and helper execution. API, gateway and web
regressions and isolated stack checks passed. Providers used controlled responses.
These results apply to the unpublished implementation.

## Remaining release work

- **Architecture:** record ADR ratification before publishing the implementation;
  review the shared runtime update under [#524](https://github.com/LegalQuants/lq-ai/issues/524).
- **Helper security:** record executable review and approval for scripts,
  dependencies and images; prove hostile output cannot cause unauthorized
  disclosure through later calls or saved-work reuse; review production executor
  separation and operational data handling. Existing isolation checks do not
  establish that complete confidentiality requirement.
- **Real matter use:** complete selected-document/KB intake and project-policy
  propagation, including DE-294, before enabling real sources and inference.
  Substantive research skills and quality evaluation remain outside this delivery.

[Draft operator guidance](../deploy/skill-capabilities.md) describes configuration
and retention for the proposed skill capabilities. Production enablement remains
a separate decision.
