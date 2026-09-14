# Optional skill persistence and bundled scripts

Owner direction, 14 September 2026: implement optional persistent skill
workspaces and bundled script execution. Generated code execution is excluded.
Continue locally under the publication hold in [the workflow](issue-563-workflow.md).

## Implementation contract

- Skills opt in independently to persistence and named Python helpers. An absent
  declaration preserves existing behavior. Reading stored work is an explicit
  tool operation, not automatic prompt injection.
- Persistent files belong to the authenticated owner, project (or personal
  namespace for projectless chat), resolved skill identity and declared workspace
  format version. A new invocation in that scope
  can reopen them. Run deletion does not delete them; project/user deletion and
  an explicit owner reset do. User/team skill identities must not alias built-ins.
- Files use bounded UTF-8 content, logical names and expected revisions. No host
  paths. Database changes and their local audit/receipt commit together.
- Script calls select a declared helper and pass bounded JSON data. There is no
  source-code, command-line, interpreter, image or executable-path request field.
  Scripts and supporting code are read-only installed artifacts; their contents
  are pinned. DB/inline skill text cannot create executable helpers.
- Operators enable exact script bundle versions and immutable runtime images.
  Each execution uses a disposable container with no network, credentials, host
  mounts or container-engine access, a read-only root, non-root user, dropped
  capabilities, bounded resources and a hard timeout. A separate trusted broker
  owns container creation; the API and job containers never receive its engine
  socket. Missing configuration refuses execution; there is no host fallback.
- A script consumes JSON input and returns bounded output. Workspace operations
  remain separate explicit tools: scripts receive selected data, and the caller
  can save selected output if that skill also opted in to persistence. Scripts
  cannot directly access the database or another skill's files.
- Common tools serve interactive chat and background skill calls. Orchestration
  adds its existing exact approval, tool grants, worker fence and effect receipts.
  Completion never means a result is legally verified.
- Bundled scripts remain reviewed code: a script that interprets supplied text as
  code defeats this contract and must not be enabled. Isolation still applies to
  bundled code. Third-party packages are installed into the reviewed image at build
  time; runtime installation and arbitrary generated programs are unsupported.

## Work packages and acceptance

1. **Contracts and persistent store:** optional declarations, independent storage
   migration, owner inspection/reset, bounded revisioned tools. Prove two separate
   invocations reuse data, isolation and conflicting writes, deletion and opt-out.
2. **Bundled runner:** pin declared scripts, implement authenticated broker and
   disposable jobs, ship a harmless technical helper. Prove real script output,
   unavailable/mismatched bundle refusal, timeout, output bounds and container
   isolation. Inputs that resemble commands remain data.
3. **Application integration:** make tools available only for attached/current
   skills; connect chat and guarded background execution. Prove both through their
   actual application paths, including orchestration halt/replay checks.
4. **Reviewable handoff:** update ADR, PRD, schemas, authoring/deployment guidance,
   workflow and evidence. Run appropriate integration/regression checks and save
   signed-off local commits. Do not publish or enable the user's running stack.

## Completion and review — 14 September 2026

All four work packages are complete locally. Migration 0071, the common skill
service, owner inspection/reset/export, chat tool loop, background planner,
guarded orchestration adapter, private broker, sample helper and optional
deployment overlay are implemented. ADR 0035 D8b/D8c, PRD, database schema,
OpenAPI sketch/export and authoring/deployment guidance describe the final scope.

The sample skill only demonstrates storing notes and counting lines/words. No
generated-code execution or substantive research skill was added. Both capability
switches retain disabled defaults. The existing orchestration demonstration does
not acquire these grants automatically; the explicit acceptance policy exercises
root and child calls. Single-inference playbook/tabular/query-less watch paths
retain their current execution model. See [supported paths and operator setup](../deploy/skill-capabilities.md).

Spec-compliance and code review checked namespace isolation, current identity
resolution, transactional writes, expected-revision conflicts, bounded input/output,
immutable bundle selection, engine separation and no arbitrary command/source
parameters. Review fixes included fresh revision UUIDs after reset, complete
ephemeral planner observations, cleanup after uncertain container creation,
restart cleanup, daemon-warning refusal and accurate nonzero-exit outcomes.
The private broker connection is documented in the transparency invariant;
third-party requests remain gateway-only. CI includes real helper acceptance,
and the runner/service paths are assigned security reviewers in CODEOWNERS.
Bundled script files under `/skills/` still need an explicit security-review
assignment alongside the existing maintainer/attorney routing.

### Subsequent confidentiality requirements — pending

The later 14 September security discussion adds
[ADR D8d](../adr/0035-governed-orchestration-run-tree.md#d8d--confidentiality-must-survive-compromised-helper-output).
The completed increment below does not establish that a hostile helper result
cannot induce unauthorized disclosure through subsequent model/tool calls or
persisted reuse. Executable review routing/evidence, those application-flow tests
and production executor/log-handling separation remain pending before script
enablement. See [the follow-up workflow](issue-563-workflow.md#skill-confidentiality-follow-up--14-september-2026).

### Evidence

| Check | Result |
|---|---|
| Final focused capability acceptance, real disposable Postgres + Docker | **34 passed** in 40.80s. Includes independent invocations, concurrent creation, owner/matter/format/skill isolation, team revocation, total quota, export/reset/deletion, migration refusal, streaming/non-streaming chat, background planner, root/child replay, rollback and halt during helper execution. |
| API regression suite | **3,120 passed, 8 skipped** in 223.76s; a disposable Redis instance exercised real arq wakeups. Docker-gated tests skipped here were run separately in the final focused acceptance above. The final nonzero-exit follow-up is covered there. |
| Contracts and transparency follow-up | **9 passed**; generated OpenAPI matches the application and the private-broker exception is explicit. |
| Ruff and format | Both pass across API, operational scripts and script runner. |
| Mypy | **221 source files** pass, including the broker/launcher. |
| Scoped Svelte check | **0 errors**; 7 existing warnings. |
| Web unit suite | **770 tests / 85 files passed**. |
| Browser acceptance | **3 passed**: saved-text inspection/reset with autonomy off; read/reset failures preserve state; helper source displays as escaped text. |
| Default stack smoke | Eight services built/started with dummy credentials under isolated `lq-ai-563-skills-smoke`; API/gateway/web and lazy Docling probes pass; **45-second soak, all healthy, zero restarts**. |
| Containerized broker | Non-root broker with dropped capabilities, read-only root and socket group ran the authenticated sample: **two lines, three words**. Optional Compose overlay validates with a private internal network, no public broker port and no API/worker engine mount. |

Docker acceptance checks the actual job uid, capabilities, no-new-privileges,
read-only bundle, unavailable network/application files/socket, fresh temporary
space, and cgroup CPU/memory/swap/process limits. It also covers authentication,
undeclared or changed bundles, input resembling source code remaining data,
ten-second timeout, output overflow and container cleanup. The reviewed probe
image is test-only. Local execution used Docker Desktop/Linux on arm64; the CI
job reproduces the suite on its Linux runner. No live model/provider was called.

Test images used for the final acceptance:

- Sample: `sha256:bb454651ee92518dd3e00dada7177b18bf46e823d6c8f4c83847a40efcd77f3a`.
- Probe: `sha256:1d703d458558907e7a81ff9ace1b325ef96d37f1500c43237a8df3faf61ab7ce`.
- Broker: `sha256:7bd8da60eec5bc4abcd2b64eb31b667adf12aaa2906f9036814b2f497f3fd253`.

Publication, ADR ratification and operator enablement remain external gates.
The subsequent confidentiality requirements above add implementation and
deployment evidence gates; the earlier passing tests do not satisfy them.
Bundled code still needs review; containers are not a VM security boundary.
Account/project backups retain their existing policy, and engine failure can
delay disposal until recovery. These limits are recorded in the deployment guide.
