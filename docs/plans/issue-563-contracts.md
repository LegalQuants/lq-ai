# Governed plan contracts — W1

Internal implementation of proposed ADR 0035 D1–D3/D6, under
`api/app/autonomous/orchestration/contracts.py`. No API route, database migration
or dispatch path consumes these contracts yet. This is local implementation
evidence, not ratification or a shipped approval feature.

## Input and authority boundary

The model supplies only a `ResearchProposal`: one to four ordered tasks, each
with topic, question, boundaries, output contract and stopping condition. It
cannot select a handler, profile, owner, resources, grants, credentials, budget
or system prompt. The entry parser requires JSON without fences or duplicate
keys, forbids extras at every level, and reports a generic error without input
values. A structurally valid prompt injection remains untrusted task prose.

Implementation bounds are 128 KiB encoded proposal JSON, 256 characters per
topic and 4,096 per other task field. Text is trimmed; blank fields and type
coercion are rejected. The server scope permits up to 128 document IDs and 32
configured source names, with no duplicates. These are internal input bounds;
they do not establish retrieval access, source coverage or adapter operations.

The server constructs `PreparedPlan` from authoritative policy and skill data.
Root and children carry explicit resource scope, phase grants, pinned skill,
minimum inference tier, maximum external-egress tier, privilege classification
and anonymization. Delegation grants are distinct from the root's own phase
grants. Child grants must fit the phase map and delegation envelope; resources
must be a subset of selected root resources. Children cannot weaken tier/data
restrictions, notify, emit KB artifacts or propose memory/precedent changes.
The only child profile key is `research`; resolving the pinned skill's supported
coverage and allowed operations remains server admission work.

## Consent snapshot

The plan binds root/project/owner/plan IDs, revision, original goal, policy
version, all execution scopes, ordered child tasks and dispatch identities,
root/child budgets, root allowance, parallelism, deadline and attempt timeout.
Each planned dispatch ID is unique; it does not represent an admitted child row.

Money uses exact Decimal values, serialized to four decimal places to match
the existing `Numeric(10,4)` session budget. JSON money must be decimal strings;
floats, non-finite/negative values and values requiring rounding are rejected.
Root allowance plus child allocations cannot exceed the total budget. Zero
budget is valid for explicitly free work; determining that providers are free
requires the W4 pricing checks. This snapshot does not perform accounting.

All nested collections are immutable tuples. The approval hash covers every
plan field with sorted JSON keys, sorted resource/grant sets, canonical money
and UTC deadlines. Ordered topics remain ordered. Hash generation revalidates
even objects made through Pydantic's unvalidated `model_copy` API.

`ApprovalBinding.require_matches` checks the owner, complete snapshot binding
and consent/deadline timestamps. It is not a token and cannot prove persistence,
idempotency, current permission, a non-rejected plan, an active run or available
capacity. W3/W4 must check those inside the atomic admission boundary. No callers
may dispatch based solely on an in-memory successful comparison.

## Validation

96 focused tests passed. API mypy passed across 193 source files and Ruff passed.
Tests cover hostile/ambiguous input, immutable round trips, exact budget
limits, consent invalidation, phase and scope restrictions, internal child
delivery, separate delegation grants and free/empty work. Postgres persistence, races and runtime replay are
separate W2/W3 acceptance work.
