# Issue 563: current policy and the guarded scope boundary

Local implementation, 13 September 2026, under proposed ADR 0035. This does not
ratify PR #567 or enable orchestration. Publication remains held.

## Current authority

`api/app/autonomous/orchestration/policy.py` implements the store's required
current-policy callback. The operator supplies a local immutable `OperatorPolicy`
snapshot; `None` disables execution. No default skill, provider or permissive
fallback is supplied. Its SHA-256 version covers all declared skill pins/profile
grants, enabled source names/types/operations, egress tiers, inference floor and
anonymization requirement. A changed snapshot invalidates existing approval.
Snapshot distribution and refresh across API/worker processes are still an
enablement gate; this callback does not establish distributed revocation by itself.

Each root/child must use a currently enabled skill for its profile, within both
operator and skill grants. The research profile further excludes playbooks,
arbitrary MCP, notifications, KB artifacts, memory and precedent proposals.
Source selections require an enabled configured provider, a registered adapter,
an allowed source type for that skill and a tier within the approved ceiling.
Configured operations must exist in the source registry: for example, EUR-Lex
cannot acquire search support by configuration. An allowed source type is not
proof that arbitrary task prose fits a skill's substantive or jurisdictional
coverage; that remains a plan-builder validation gate.

Skill pins hash the filesystem artifact's name, origin, raw frontmatter, body and
sorted paths/content of all reference/example files. The checker reads the main
artifact again and refuses registry/disk disagreement, missing supporting files,
changed supporting content and supporting-file paths escaping the skill directory.
It does not use the public skill materializer's skip-on-missing behavior. This
pilot path pins filesystem instructions explicitly, without resolving a mutable
slug through user/team chat forks. The execution adapter must consume the pinned
artifact itself; re-fetching a slug through the gateway is not equivalent.

Selected IDs mean `documents.id`, not `files.id`. The callback joins documents,
their owned/non-deleted files and current `project_files` attachments, requiring
every selected document to remain available in the approved project. Share locks
last only through the store's short admission transaction. The store separately
checks current owner opt-in, project archival/ownership/privilege/tier, approval,
deadline and worker fencing.

## Actual tool boundary

`guarded_tool_call` accepts an internal server-resolved `execution_scope`. R5
refreshes the scoped session's halt, status and phase, including an already halted
or terminal session. After the existing R6 phase grant, the boundary narrows the
call to the approved grants; R4 still estimates/checks cost before dispatch.

For document retrieval, the initial scoped implementation accepts only an exact
`file_id` selector. It checks the mapped document against the selected IDs,
current ownership, soft deletion and project attachment in the tool transaction.
The same rows remain share-locked until the local chunk read commits. KB-wide
queries, mixed selectors and unselected owned files are refused. Selected-KB
semantic retrieval is still a later intake/adapter increment.

Inference params inherit the approved minimum tier, privilege and deliberate
anonymization setting even if planner params try to weaken them. The gateway
receives its existing tier-floor and project-privilege fields. Their existing
semantics remain intact: privileged requests cause the gateway to skip rewriting,
even when the explicit anonymization flag is true. No skill slug or internal
root/run IDs are added to provider requests.

Scoped external calls remain refused until the exact provider/operation and
price are bound through the actual dispatch adapter. The legacy external handlers
re-resolve providers and allow unknown pricing to become zero; those paths cannot
yet satisfy ADR 0035. Merely selecting a source in a valid plan does not activate
it. Only scoped document reads, inference and internal findings are implemented.

The optional guard scope narrows calls; it is not proof of durable authorization.
The production adapter must obtain it from the stored plan, perform current-policy
and fenced effect admission, call the guard, and persist the outcome. Ordinary
workers/public routes do not invoke this orchestration path. It remains unsafe to
adopt a concurrently running legacy session or enable dispatch by passing a scope
alone. Existing unscoped callers retain their prior behavior.

## Validation and remaining work

Tests use migrated disposable pgvector/Postgres, a real filesystem skill registry,
the actual store and guard, and stub inference. They cover skill edits/removal,
operator revocation, missing/detached/deleted documents, unsupported operations,
skill source restrictions, unselected-file reads, malformed/broad selectors,
data-policy overrides and R5 ordering/terminal refresh. A combined fixture pauses
an admitted provider call, revokes operator policy, then verifies that its result
can settle while the next effect is refused.

The autonomous regression suite passed **791 tests** in 98.32 seconds. Final
focused checks then passed **35 tests**, including additional policy-limit cases
and the scope-refusal audit regression. Ruff check/format, mypy (197 source files)
and `git diff --check` passed. No live providers, production migrations or feature
flags were used. The disposable database is independent of the user's development
stack.

Next: consume pinned instructions in the execution adapter; bind provider/operation
selection and known pricing; integrate guard admission/settlement without control
locks across provider I/O; provide shared current-policy distribution, worker
capacity/lease lifecycle and wakeup recovery. Production process-death tests and
the LangGraph worker topology remain required before public dispatch.
