# Issue 563: durable working files

Owner direction, 14 September 2026: exercise the storage acceptance test without
code execution, then assess whether ADR 0035 needs revision. Continue local work
under the existing publication hold in [the workflow](issue-563-workflow.md).

## Acceptance and implementation choice

A child writes a private working file, survives an interrupted invocation, reads
the stored work, saves findings and explicitly shares its result file. The root
reads that file for synthesis. Prove committed write replay, isolation, stale
revision refusal, halt and deletion against disposable Postgres.

Use application-owned Postgres records for bounded UTF-8 files, with logical
names rather than host paths. Three guarded operations read, write and share.
Authority comes from the approved run/session and tool grants; names and content
cannot select an owner, project, filesystem path or different run. Each session
has at most eight files, 256 KiB total, 64 KiB per file and 32 content revisions
per file. These are fixed upper bounds, not configurable unlimited defaults.

Children read/write their own files. Sharing freezes a file's content and makes
it readable by the parent root; siblings remain isolated. The owner can inspect
all files through the run receipt, including after halt or opt-out. File changes
and completed effect receipts commit in the same transaction, in the established
owner/project/root/account lock order. Shared result references pin the session,
name, revision and digest. Working files are data, never executable instructions.

Storage lasts with its owning session and cascades on session/root/user deletion.
It survives worker restarts and later invocations of that same session. It is not
long-term skill storage available to a new run, and does not read/write user-kept
memory. Code execution and model-directed tool selection are outside this test.

## Separate question: storage across skill invocations

No general skill storage API currently exists. User-kept memory and read-only
packaged skill references serve different purposes. Reuse by a new run needs an
explicit namespace and access contract, including owner/matter boundaries,
skill identity and version compatibility, retention/deletion, concurrent writes,
and what stored material may enter a later prompt. Record this distinction in
the ADR assessment; do not silently turn run files into globally shared memory.

The maintainer selected an **optional persistent skill workspace** as the intended
extension. A skill chooses whether to use it; persistence and loading prior work
are not mandatory steps for every skill invocation. This is a requirement for
future implementation, not a capability established by the run-storage acceptance
test above.

## Script execution assessment

The existing LQ.AI skill loader includes instructions, reference files and
examples; it does not load `scripts/` or register executable helpers. Neither
bundled scripts nor code written during a skill invocation have a built-in runner
in LQ.AI chat, playbooks or autonomous execution. The authoring guide's directory
convention is not an execution capability; the PRD still defers skill scripts.

Chat can call enabled, configured MCP tools, so a separately hosted tool can
execute a script and return its result. The gateway's MCP transport is HTTP; it
does not start a local script process. The older autonomous MCP handler rejects
tools needing confirmation, and the #563 orchestration scope does not currently
allow general MCP calls. The inherited OpenWebUI Python interpreter is separate
from LQ.AI's chat tool loop and message renderer.

This is a code-inspection finding, not a live script-runner acceptance test. It
does not add script execution or connect any execution service. Optional workspace
use and optional script execution remain independent capabilities.

## Evidence

The acceptance test kills a separate Python worker immediately after the notes
write commits, before that graph node can checkpoint. After recovering its dead
claim, a replacement invocation reuses the original effect receipt, reads the
same notes and advances them to revision two. The parent reads each immutable
`findings.json` through the guarded tool and uses those contents for synthesis.
No model, interpreter or filesystem state is carried over from the killed worker.

Focused storage/migration/API-contract run: **16 passed, one skipped** in
**5.04 seconds** (the skip is the existing empty stub-route parametrization).
The storage/API run passed **15 tests** in **11.98 seconds**; its optional real
Redis test was deferred to the full run with disposable Redis configured.
Six browser scenarios and two client tests passed. Svelte reported zero errors
and seven existing warnings in unrelated files; Ruff check/format and mypy
(211 API source files) passed.

Final full API regression: **3,094 passed, one skipped** in **266.83 seconds**,
using four test workers with disposable Postgres and Redis. This includes the
real arq process completing the updated storage flow. The initial full run found
two outdated exact tool-inventory assertions; both were updated to include the
three workspace operations before this passing run. API schema export and route
inventory checks passed. Ruff formatting covered 566 Python files.

The isolated stack build/smoke passed: **eight services healthy, zero restarts**
after a **75-second** soak, plus API/gateway/web probes and docling import. The
stack used the default disabled configuration; enabled execution used only the
disposable queue/database services and the local sample provider.

The implementation also tests atomic file/receipt rollback, forbidden sibling
and other-run reads, private-versus-shared root access, frozen shared files,
stale revisions, Unicode/size/count limits, halt and owner receipt access after
opt-out. Migration 0070 upgrades/downgrades without losing existing runs and
refuses downgrade while work is retained. Deleting a root removes its files.

ADR 0035 **D8a** was added after the interruption acceptance passed. It records
run storage as an explicit architectural capability and leaves reuse by new
skill invocations unimplemented. The technical demonstration remains scripted
with controlled sample responses; this test proves durable tool/storage behavior,
not model-directed tool selection, live research or code execution.
