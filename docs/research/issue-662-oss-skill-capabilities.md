# OSS skills in LQ.AI: capability assessment and adoption buckets

Research for [epic #662](https://github.com/LegalQuants/lq-ai/issues/662), recorded on
4–5 October 2026. The epic is the live delivery and inclusion tracker. This note preserves the
research behind it; bucket placement does not approve a skill for inclusion.

The assessment uses LQ.AI **v0.8.0** at
`c6b1c9bdda8d65ff55e7efd51f949d766c48b129` and the OSS skill snapshot
`fa5a6681dc3cc9a08fa9ed48a5fd213057edafa0`. Later changes on `main` are not retested here.

## Finding

LQ.AI has a useful orchestration and skill-runtime foundation. Supporting an OSS workflow still
requires selecting its inputs and output, adapting its host assumptions, connecting the relevant
capabilities to main chat, and checking the result a user receives.

The [October ordinary-chat baseline](2026-10-04-oss-skills-baseline/README.md) demonstrated installed
skill-body invocation, text/PDF-text input and next-day stored-chat recall with a fresh-chat isolation
control. Of the **14 adapted live probes**, **1 passed, 10 failed their tasks and 3 remained blocked**.
These counts describe one configuration, not a platform-wide capability score or 31-skill verdict.

Workspace storage, bundled helper execution and orchestration were disabled or unconfigured in that
baseline. Their unsuccessful ordinary-chat probes therefore do not establish missing implementations.
The next step is to prove a selected skill's complete path using the components already present.

## Evidence and what it establishes

| Evidence | Established | Limit |
| --- | --- | --- |
| [v0.8.0 release](../releases/v0.8.0.md) and [recorded orchestration demonstration](../uat/adr35-chat/README.md) | A real local model proposed a plan; approval admitted separate Contract QA children; synthesis used their findings. Reload and rejection behavior were recorded. | A fictional agreement and dedicated demonstration path; no general OSS catalog acceptance. The record distinguishes agent-executed checks from human UAT. |
| [Optional storage/helper contract](../deploy/skill-capabilities.md) and [authoring contract](../skill-authoring-guide.md#optional-persistence-and-bundled-helpers) | Implemented, separately enabled workspace and reviewed-helper interfaces exist. | Implementation and controlled acceptance evidence are separate from enabling them for an arbitrary OSS package. |
| [October baseline](2026-10-04-oss-skills-baseline/README.md) and [probe ledger](2026-10-04-oss-skills-baseline/probe-results.json) | Exact submitted prompts, completed replies, failures and outcomes through authenticated ordinary-chat APIs. | Synthetic inputs, local Qwen/GLM models and the recorded settings; no browser acceptance, full Word review or workbook recalculation. |
| [Delayed P5 evidence](2026-10-04-oss-skills-baseline/p5-next-day.json) | Original user/chat/volume retained; fresh client recalled the reference after 24h 08m 34s; empty new chat did not identify the earlier task. | Application replay of saved conversation text. The history includes a same-day recall; this is not 24 hours without an intervening mention or proof of shared memory. |
| [Cowork capability-test PR #26](https://github.com/houfu/lq-plugin-cowork/pull/26) at `b9ed8af9ea205344e1e3f6ff39161926888f25f4` | A comparison source containing 27 probes and stronger criteria in places. | The extra 13 probes and its engine-derived skill verdicts were not run. Cowork results are not LQ.AI results. |

The September demonstration and October baseline used different fixtures and model routes. Neither
should be presented as the other's acceptance run. The larger orchestration work in
[#599](https://github.com/LegalQuants/lq-ai/pull/599) is related foundation work; this research does
not make its entire scope a prerequisite for a first bounded contribution.

## Gaps by capability workstream

Track names follow #662. The proposed increments below are research recommendations; the live epic
and agreed subissues determine scope and ownership.

| Track | Existing foundation or observed behavior | Gap to establish for a selected workflow |
| --- | --- | --- |
| **C1 — Main chat experience** | The recorded demo covers planning, approval, child progress, synthesis and retained runs. | Carry that journey into main chat and verify approval/rejection, progress, retained files/receipts, halt and reopening. Refine the interface for the selected skill's inputs and outputs. |
| **C2 — Skill compatibility and adaptation** | Installed skill-body invocation worked. LQ.AI has its own frontmatter, input and capability contracts. | Pin an OSS package, map its tools/resources and supported mode, and check success, missing-input and failure examples. Loading `SKILL.md` alone is insufficient. |
| **C3 — Skill execution and helpers** | Reviewed Python helpers and a broker contract are implemented; the October runner was unconfigured. | Declare and package one required helper, meet its input/output and dependency contract, and record actual execution and failure evidence. Generated Python text is not execution. |
| **C4 — Chat history and execution evidence** | P5 passed stored-chat replay and a new-chat isolation control. P11 subchecks omitted a skill recorded by the app. | Retrieve selected sessions and relevant execution events with locators, roles, attribution and explicit coverage. Complete P11 with an actual agent-generated file. |
| **C5 — Persistent state** | Versioned, owner/matter/skill-scoped text workspaces exist; they were disabled in the baseline. P2 never created its seed file. | Enable and adapt one agreed store, then demonstrate write, reopen, revision conflict and update. Assess personal, matter and shared companion requirements separately. |
| **C6 — Files and artifacts** | Text-bearing PDFs reached chat. Tested DOCX/XLSX ingestion returned `unsupported_type`; visual PDF content was absent; no requested output files were generated. | Complete one input-to-artifact path, including packaged resources, format validation and user opening/download. Assess available ingestion modes before declaring a whole format absent. |
| **C7 — External sources and connectors** | LQ.AI has gateway-governed connector/research paths. Public web retrieval was unconfigured in this test path; P14 lacked an appropriate tenant/corpus. | Select one source and skill mode, verify retrieval and provenance, and expose partial coverage or failure. A model's promise to browse is not evidence of retrieval. |

The optional storage contract is deliberately narrower than an arbitrary persistent filesystem:
flat UTF-8 names, revision-checked writes, owner/matter/skill/version scope and explicit reads.
Team skill installation does not itself share users' stored files. Likewise, a reviewed bundled
helper receives bounded JSON and a temporary workspace; it does not automatically acquire stored
files, sibling imports, arbitrary package installation or general shell execution. These are
concrete compatibility questions for C2/C3/C5, even during development. See the
[runtime contract](../skill-authoring-guide.md#optional-persistence-and-bundled-helpers).

## Keep three memory questions separate

- **P2: durable skill files.** Can the skill create a file, reopen it in another session, update it,
  and verify that update later? The baseline stopped before the initial write succeeded.
- **P5: task resumption and isolation.** Can the existing task recover a reference while a new task
  does not know it? The delayed API check passed. It does not provide selected cross-session access.
- **P11: current-session evidence.** Can the model accurately account for files, tools and skills
  used in this session? The full setup was blocked and narrower checks were incomplete.

`lq-reflect` needs deliberately selected session evidence and a store for an agreed lesson. P5 alone
does not satisfy either its cross-session retrieval workflow or the shared companion-store contract.

## Skill adoption buckets

The inventory covers **31 distinct skill names** in the
[pinned OSS snapshot](https://github.com/LegalQuants/lq-plugin-oss/tree/fa5a6681dc3cc9a08fa9ed48a5fd213057edafa0/skills).
Names repeated across plugins appear once; an adoption issue must identify the actual package and
mode. The ladder groups the main adaptation burden, not mandatory sequential release gates.

| Bucket | Skills | Capability focus |
| --- | --- | --- |
| **1 — Guided work with supplied material** | `lq-start`, `client-update`, `writing`, `correspondence`, `depositions` | Discover skills, ask questions, read supported supplied material and return grounded drafts/tables. |
| **2 — Connected sources** | `lq-ask`, `lq-connect`, `regulatory` | Retrieve selected sources and retain provenance, coverage and failure information. |
| **3 — Persistent workspaces and preferences** | `new-matter`, `organize-case-docs`, `wiki`, `legalquants`, `lq-mirror`, `lq-apply` | Durable records and updates; distinguish personal, matter and shared companion storage. |
| **4 — Conversation evidence** | `lq-reflect`, `timenarratives` | Selected sessions/events, source locators, speaker roles and attribution. |
| **5 — Structured, editable deliverables** | `legaldesign`, `my-lq-moment`, `closing-checklist`, `document-discovery`, `playbook-builder`, `playbook-review`, `pressuretest` | Packaged resources, helper execution where needed, output validation and usable artifacts. |
| **6 — Detailed document review pipelines** | `definition-check`, `conform`, `cite-check`, `read-redline` | Document structure, bounded review units, evidence/coverage validation and linked findings. |
| **7 — Multi-document operations over time** | `sigpack`, `closing-bible`, `docreview`, `diligence` | Inventories, ledgers, versions, returning files, recovery and collection reconciliation. |

Dependencies cut across the buckets. `conform` consumes current `definition-check` term ledgers;
`playbook-review` needs a playbook conforming to the `playbook-builder` contract. Companion workflows
share onboarding/storage requirements. `my-lq-moment` also needs current-session evidence.
Supplied-material modes may precede connected-source or ongoing matter-management modes, provided
their narrower outcome is documented and verified.

## Bring in a selected skill

For each candidate, document the pinned upstream package, supported inputs, promised result and
required capabilities. Map source instructions to LQ.AI inputs, tools, packaged references/templates,
helper dependencies, persistence scope and output delivery. Preserve attribution and inspectability;
do not silently replace unavailable operations with model claims or change the substantive workflow.

Verify an end-to-end success example and the relevant missing-input, failure and interruption cases.
The [skill contribution process](../../skills/CONTRIBUTING.md) applies when a later PR imports or
changes legal substance. This research note imports no operational skill and provides no attorney
attestation.

The live epic proposes `client-update` as the first bounded workflow, followed by possible
`lq-reflect` and `legaldesign` increments. Those are proposals awaiting maintainer agreement, not
release commitments. **Houfu decides which skills, supported workflows and releases are included.**
The epic tracks capability → integration → release, with skill issues remaining open until their
agreed workflow ships. Shared capabilities can be completed independently.

## Reading and reproducing the baseline

Start with the [baseline report](2026-10-04-oss-skills-baseline/README.md), then its
[evidence guide](2026-10-04-oss-skills-baseline/EVIDENCE.md). The archive includes exact prompts and
responses, failed attempts, runtime/ingestion observations and the delayed P5 receipts. It describes
which records were compacted for publication and how to verify their checksums.

The snapshot preserves the distinction between observed behavior, existing implementations,
disabled configuration, adaptation work and unanswered questions. It does not change the
application, enable optional facilities, or supply acceptance evidence for untested skill modes.
