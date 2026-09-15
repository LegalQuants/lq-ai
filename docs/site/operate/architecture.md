---
title: Architecture
description: How the services fit together, what ships at each milestone, and where a customer's data can leave the deployment.
audience: [operator, evaluator]
status: draft
sources:
  - docs/architecture.md
  - docs/HONEST-STATE.md
sidebar:
  order: 20
---

The diagram and walkthrough below are the visual companion to the PRD — useful whether you're deciding what to run where, sizing the deployment, or reviewing it before sign-off. Solid borders and edges are what ships in the v1 release path; dashed ones are forward-looking and explicitly not committed for delivery.

<!-- include: docs/architecture.md -->

## What this means when you're deciding where to run it

Three things in the diagram above are worth reading as deployment decisions rather than as labels alone:

**Storage never leaves your environment, by construction.** Postgres, Redis, and MinIO/S3 all sit inside the "Storage (operator's environment)" box regardless of which LLM provider you route to — there is no LegalQuants-side service that holds a copy of your chats, files, or audit log. The only edge that crosses into infrastructure you don't control is the one from the Inference Gateway to whichever provider you've configured, and that edge is annotated with the routed tier on every call.

**One box holds every privileged key.** The Inference Gateway is drawn as a single subgraph for a reason: every service that needs to call a model — chat, playbooks, tabular review, the autonomous layer, document ingestion's embedding step — routes through it rather than calling a provider directly. If you're reviewing this for a security sign-off, that single box is what you scope the review around; the [trust centre](../trust/index.md) is where the rest of that review lives.

**The `Mn` tags tell you what's actually running, not what's designed.** Today View and the Signal Aggregation Service are drawn with dashed borders — forward-looking M5+ elements, explicitly not committed for delivery. The MCP-Client Subsystem is drawn solid and tagged *M2 slot*: the architectural slot is committed in the v1 path even though no connectors ship until M5+ (`docs/architecture.md`, Legend and §"What sits where, and why"). Read the milestone breakdown in the include above, or [`docs/HONEST-STATE.md`](../../HONEST-STATE.md), before assuming a labelled box is a shipped one.

## Next

- [Trust centre](../trust/index.md)
- [Logs and monitoring](logs-and-monitoring.md)
- [Published gaps](../trust/published-gaps.md)
