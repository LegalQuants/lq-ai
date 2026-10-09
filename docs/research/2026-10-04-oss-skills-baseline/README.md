# LQ.AI v0.8.0 ordinary-chat capability baseline

Recorded 4 October 2026; updated 5 October 2026 with the delayed P5 result. All recorded times are
UTC.

Research evidence for [epic #662](https://github.com/LegalQuants/lq-ai/issues/662). Read the
[capability assessment](../issue-662-oss-skill-capabilities.md) for the implementation and adoption
context.

## What this establishes

The run used a fresh disposable LQ.AI v0.8.0 stack. Its nine running services passed health checks
at observation time. This is a historical record, not a live service-status report.

**Local chat and installed skill-body invocation work.** A packaged skill returned its expected
fixed token, and LQ.AI recorded the applied skill and local model. Plain text and text-bearing PDFs
also entered the chat context. These checks do not establish companion-file access, script
execution, or readiness of all 31 OSS skills.

The adapted live 14-probe suite now has **1 full pass, 0 partial results, 10 failed tasks, and 3
blocked full probes**. P5 is the completed pass. The successful chat/skill smoke checks sit outside
those 14 full pass criteria. A failed task is scoped to the tested chat path and configuration; it
is not automatically an absent feature throughout LQ.AI.

**The baseline remains open.** The feasible immediate follow-ups and delayed P5 continuation are
complete. The prerequisites for the remaining blocked probes are still outstanding.

## Configuration and model changes

The first model was local **Qwen `qwen3.8:27b-mlx`**. It completed the initial smoke and several
probes, then requests began timing out. Even a short streaming diagnostic failed at the API's
60-second timeout. The cause of that stall is unresolved.

The gateway was restarted and switched to the already-installed local **GLM
`glm-4.7-flash:latest`**, which became the default for the remainder of this run. Streaming skill
invocation succeeded. Some GLM requests also timed out, so streaming and model replacement did not
eliminate the problem. Shorter focused follow-ups then produced completed results for PDF
inspection, packaged-image access, workbook creation and session recall. No model was credited with
capabilities merely because its model listing advertised them.

All inference remained local, with no cloud fallback. Application code and security/network access
were not changed. Skill workspaces remain disabled, no bundled-script runner is configured,
orchestration chat remains disabled, and the test user's autonomous-mode preference is false. The
last two settings are separate controls.

## Per-probe findings

### P1 — Bundled Python script: failed in this configuration

The real packaged probe skill loaded, but no environment fingerprint was produced. No script runner
is configured and no script execution was recorded. This is an unavailable execution path for this
chat; it does not mean the API container lacks Python.

### P2 — Durable file across sessions: failed at the initial step

The model did not create `probe-ledger.json`. Workspaces are disabled. There is therefore no seeded
file for the later-day read, increment and third-session verification. Do not confuse this with P5's
stored conversation history.

### P3 — Word tracked changes: failed

The synthetic two-page tracked DOCX and its accepted-copy control uploaded successfully. Both failed
ingestion with `unsupported_type`; neither supplied document content to the model. Exact changes,
authors and the comment were not recovered. This is a verified input-path limitation, preceding
model interpretation.

### P4 — Visual PDF inspection: failed after a completed follow-up

Earlier attempts timed out. The focused GLM retry completed but reported no visible markup on page 2
and could not inspect page 3. The fixture has strike-through/underline on page 2 and a scanned
signature page at page 3. Runtime evidence shows PyMuPDF-extracted text was supplied to chat, with
the raster page and visual markup absent. Thus the tested input path does not provide the
information needed for this visual task.

### P5 — Resumed task and fresh-task isolation: passed in the adapted API test

On **5 October 2026 at 00:51:59 UTC**, a fresh authenticated client reopened **Capability baseline —
P5-initial**, **24 hours 8 minutes 34 seconds** after the original seed. The only submitted prompt
was **What was the reference I gave you?** LQ.AI completed its response at **00:52:21 UTC**: **The
reference provided was ALDERNEY-7.** The expected value was checked by the evaluator after the
response; it was not added to the request, an attachment, or a skill.

A separate fresh client authenticated as the same user, created a new chat, and verified that it
contained no messages. At **00:52:21 UTC**, it asked **What did I ask you in my previous LQ.AI
task?** The completed response at **00:52:41 UTC** was:

> I don't have access to the history of previous conversations or tasks outside of the current session. If you have a question you'd like to ask now, please let me know, and I'll do my best to help!

Both requests used `local` → `host-ollama` / `glm-4.7-flash:latest`, with no fallback, skills or
file attachments. Both returned HTTP 200 and a completed streaming event. The persisted messages and
matching inference receipts confirm the actual replies and model. The original baseline user, seeded
chat, and database volume were preserved. No service restart, configuration change, permission
change, restoration or reseeding was performed during this check.

**Limits:** this establishes next-day application replay of the stored chat and one successful
fresh-chat isolation control. The stored history includes a same-day recall response, so it is not a
test of 24 hours since the most recent mention. Initial seeding used Qwen; same-day and delayed
resumption used GLM. It does not prove provider-private memory, cross-task memory, durable files,
complete event-history access, crash recovery or exhaustive isolation. Reopening was through the
authenticated chat API; task-list UI navigation was not exercised.

### P6 — Web search and official quotation: failed

No official page was retrieved or quoted. Qwen said it could not fetch the page but also named tools
without evidence that they existed. No actual retrieval was recorded. Public web search was not
configured for this test path; this result does not establish whether other LQ.AI research
integrations could be configured.

### P7 — Packaged companions: failed

**P7a:** The original OSS legaldesign package was installed. GLM returned inline HTML and claimed a
template name, without a verified read of the real companion or a downloadable artifact.

**P7b:** Initial attempts timed out. A completed focused retry explicitly reported inability to read
the packaged HTML/PNG or create a download. The actual template and image were present in the
installed synthetic package. Model-generated substitute HTML does not prove access to those files.

### P8 — Assemble selected PDF pages: failed

Both source PDFs were ingested and attached. GLM completed a reply saying it could not generate
downloadable files. No assembled PDF was created, so page order and retained content could not be
verified.

### P9 — Workbook with formula and round trip: failed after a completed follow-up

Earlier attempts timed out. The focused retry returned unexecuted Python code rather than an XLSX
file, despite being asked for a real workbook. A separate supplied XLSX was rejected during
ingestion as `unsupported_type`. No generated workbook exists for the second-session append and
formula-recalculation checks. Printed code was not executed by the evaluator to manufacture a pass.

### P10 — Real Word tracked-change output: failed

GLM returned unexecuted Python code and claimed a document was saved. No file was created. The
printed code also does not encode actual Word tracked revisions. This combines an unmet artifact
requirement with an unreliable model claim about execution.

### P11 — Current-session files, tools and skills: full probe blocked; subchecks incomplete

The full setup needs an actually generated file in the conversation, which the earlier file-creation
attempt did not produce. Two narrower checks correctly quoted `Copper lanterns shimmer beside the
quiet quay.` and reported no created files. Both omitted `harness-probe` from the skill history
recorded by the application. The focused answer claimed to read execution metadata without a
demonstrated retrieval. The inspected history loader supplies message roles and text, not the
complete receipt stream. These subchecks do not establish complete session introspection.

### P12 — Read a public page and explain its provenance: failed

Qwen promised to fetch the page but returned no heading, quotation, retrieval route or session-file
status. No tool execution supported that promise. This is a failed response, not evidence of
successful browsing.

### P13 — Scheduled skill over an existing workbook: blocked

Read-only schedule listing succeeds and is empty. The test user's `autonomous_enabled` preference is
false; the mutation routes require that opt-in. The writable workbook/output path is also
unestablished. Completing this probe would require changing the current access setting and
establishing the file workflow. No schedule was created and no access setting was changed. A manual
run or evaluator timer would not prove scheduled execution.

### P14 — Enterprise people search: not run

The original probe requires Cowork Enterprise Search and real internal source material. The
authorized test environment is synthetic and local. A fabricated organizational corpus would be a
separately labeled adaptation, not a pass for this original test.

## Separate the conclusions

### Directly supported by application evidence

- Installed skill bodies can be applied and their use recorded.
- DOCX and XLSX bytes can be stored, but this ingestion path rejects them as unsupported types.
- The tested PDF chat path supplied extracted text and omitted the visual evidence required by P4.
- No target tool calls or generated output files were recorded. The file inventory remains the eight uploaded synthetic fixtures.
- Runtime settings disable workspace access and leave script execution unconfigured; optional implementations must be assessed separately before proposing new code.
- Conversation text recall works within the stored chat more than 24 hours after seeding, and the delayed fresh-chat control did not know the prior task. Complete skill/tool-event recall was not demonstrated.

### Model behavior and infrastructure limits

- Qwen's later stall and the 60-second timeouts are inference/transport findings, not missing-capability verdicts by themselves.
- GLM also had timeouts; focused completed replies resolved P4, P7b and P9 beyond those earlier inconclusive attempts.
- Claimed tools, claimed template use, and claims of saved files were not trusted without matching execution and artifact records.
- The local Ollama embedding route returned HTTP 501; vector search was not established by this run.

## What remains and when to check it

**Completed now under the existing authorization:** focused P4, P7b and P9 attempts; the clearer P11
subcheck; the final-model fresh-chat isolation control; and read-only scheduler/prerequisite checks.
These used the same local route and synthetic inputs. Focused P4/P9 used ordinary chat without the
optional, lengthy harness skill body; this prompt adaptation is retained in the evidence.

**Delayed P5 completed on 5 October 2026, 00:51:59–00:52:41 UTC.** The resumption and isolation
outcomes are recorded above. No wider probe campaign was run.

- Original chat: `fd6faabf-ec21-4d77-a3e8-df661b0cfc78`; seed time: **4 October 2026, 00:43:25 UTC**.
- Fresh isolation chat: `68363da0-dd20-4ac1-aeaf-04930299cbc5`.
- Same baseline user: `da3d0896-4d5b-42f9-affb-b70a1579c659`.
- Original volume: `lq-ai-capability-baseline_pgdata`, created **4 October 2026, 00:38:45 UTC**, verified mounted on the existing PostgreSQL service.
- GLM model digest: `d1a8a26252f18b34301218d22abd2620a65b85ba4b78987842eb157e01321222`. The gateway configuration hash matched the recorded baseline; workspaces and orchestration remained disabled, no script runner was configured, and autonomous mode remained false.
- Resumed reply ID: `805a0070-4711-4d64-9397-9fe5ed8e5b7e`; matching GLM inference receipt: **00:52:20.922247 UTC**.
- Isolation reply ID: `31c0227a-e862-4dbb-b649-7afc12d02872`; matching GLM inference receipt: **00:52:41.461768 UTC**.

The exact requests, completed responses, saved messages, receipts, state checks and evaluator
assessment are in [p5-next-day.json](p5-next-day.json). The [evidence guide](EVIDENCE.md) explains
the publication format and [manifest](manifest.json). No further check was scheduled automatically.

**Full P11** requires an actual generated file in the chat, rather than an evaluator upload
relabeled as agent output. **P13** requires autonomous opt-in plus a working prior-file/output path.
**P14** requires an appropriate authorized tenant and real corpus. Those prerequisites cannot be
supplied while retaining the current no-access-expansion boundary. Browser rendering, Word's review
pane and workbook recalculation also remain unverified.

## Relationship to #662

The evidence supports discussing three separate areas: a supported configuration for OSS skill
runtime and package access; richer document input/output paths; and truthful, model-accessible
execution/session evidence. Preserve the distinction between durable files, same-chat replay,
new-chat isolation and event-history access.

These findings support [epic #662](https://github.com/LegalQuants/lq-ai/issues/662). The epic owns
current scope, contributor participation and maintainer inclusion decisions. This report supplies
research evidence; the larger orchestration effort remains related foundation work.

## Sources and reproducibility

- Primary criteria: the [live 14-probe suite](https://houfu.github.io/lq-plugin-cowork/probes.html) and [testing guide](https://houfu.github.io/lq-plugin-cowork/testing.html).
- [Cowork PR #26](https://github.com/houfu/lq-plugin-cowork/pull/26) was captured at `b9ed8af9ea205344e1e3f6ff39161926888f25f4`. It contains 27 probes and stronger criteria in places. Its extra 13 probes and official 31-skill verdict calculation were not run or claimed here.
- Original OSS skill pin: `fa5a6681dc3cc9a08fa9ed48a5fd213057edafa0`.
- LQ.AI release source: v0.8.0, `c6b1c9bdda8d65ff55e7efd51f949d766c48b129`. Four relevant API files matched the running image byte-for-byte; this is not full build-provenance attestation.
- Separate larger effort: [LQ.AI PR #599](https://github.com/LegalQuants/lq-ai/pull/599).

The [published evidence archive](EVIDENCE.md) retains exact submitted requests, final replies,
timeouts, model routing, receipts, ingestion errors, runtime settings and checksums. Duplicate
streaming deltas are omitted as documented. Evaluator-side fixture generation, inspection and upload
were never credited as LQ.AI capabilities. Credentials and runtime environment files are excluded.
