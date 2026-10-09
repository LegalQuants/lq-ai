# Evidence guide

This is an archival publication of the 4–5 October 2026 LQ.AI v0.8.0 ordinary-chat baseline for
[#662](https://github.com/LegalQuants/lq-ai/issues/662). It preserves the recorded results, including
failed and incomplete attempts. Publication did not rerun the probes or alter the application.
All timestamps in the evidence are UTC.

## Files

| File | Contents |
| --- | --- |
| [README.md](README.md) | Human-readable configuration, all 14 outcomes, P5 follow-up and limits. |
| [probe-results.json](probe-results.json) | Original live-suite setup, prompts and pass/fail criteria; 32 submitted attempts with exact requests, final responses, errors, timing and evaluator findings. |
| [runtime.json](runtime.json) | Observed service health, image identities, source pins, model digest, ingestion/tool records, runtime settings and selected running-source hash comparisons. |
| [smoke.json](smoke.json) | Initial Qwen and recovery GLM skill-invocation checks, separate from the 14 full probe criteria. |
| [prerequisites.json](prerequisites.json) | Eight fixture upload records, ingestion results and read-only P13 scheduler/preference checks. |
| [receipts.json](receipts.json) | Available application receipts for the initial probes and focused follow-ups. A receipt stream may also retain inference from an earlier timed-out client request. |
| [p5-next-day.json](p5-next-day.json) | Delayed requests/replies, preflight, original and fresh-chat messages, matching inference receipts and evaluator assessment. |
| [sources.json](sources.json) | Primary live-suite capture, supporting PR #26 pin and hashes of the original source captures. PR state is as captured, not a current-status assertion. |
| [manifest.json](manifest.json) | SHA-256 and byte count of each published file in this directory, excluding the manifest itself. |

The ledger uses `not_run` for a full probe that could not be completed. P11 has recorded narrower
attempts even though its full setup was blocked. For streamed requests, HTTP 200 alone is insufficient:
the response must include a completed event before it can establish the requested capability.
No model-generated code was executed by the evaluator to manufacture a successful result.

## Publication transformations

The publication removes duplicate top-level SSE `events` arrays from attempts. Final responses,
including `events_without_completion` error evidence, exact submitted prompts, model metadata,
durations and transport errors are retained. Original attempt hashes accompany the ledger.
The smoke and P5 records use the same compaction. P5's underlying preflight, saved-message and
receipt records are retained in full and grouped into one file.

The original runtime's `removed_projects` field is omitted because previous stack disposal is not
capability evidence. The source manifest identifies captures kept in the original investigation;
its HTML/YAML files are not duplicated here. Original probe criteria are preserved in the ledger.
Private credentials, environment files, Library metadata and the runtime checkout are excluded.
All published conversational inputs and document examples belong to the synthetic test workload.

This archive is sufficient to inspect the recorded requests, replies and scoring. It is not a
turnkey test harness: the binary fixture bytes, installed probe packages and evaluator scripts are
not included. Upload records retain filenames and hashes so a future run can identify matching or
changed inputs. Reconstructed inputs or a different model/configuration require a separately named
run; they must not be appended as though they came from the original fixture.

## Verify the archive

From this directory, using Python's standard library:

```sh
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

for name, expected in json.loads(Path("manifest.json").read_text()).items():
    data = Path(name).read_bytes()
    assert len(data) == expected["bytes"], name
    assert hashlib.sha256(data).hexdigest() == expected["sha256"], name
print("All published files match the manifest.")
PY
```

Hashes check consistency with the published manifest; they are not an independent attestation of
model quality or an execution signature. The original runtime matched four relevant API source files
to the release checkout, not the complete image's build provenance.

## Reproduce the protocol in a separate run

Use a disposable deployment at the recorded release and an explicitly recorded local model route.
Record operator settings, skill pins, fixture bytes/hashes and actual application receipts. The
[release setup](../../releases/v0.8.0.md), [skill authoring contract](../../skill-authoring-guide.md)
and [optional capability notes](../../deploy/skill-capabilities.md) describe the application; the
ledger supplies the exact submitted adaptations. Keep evaluator file generation, upload and
inspection separate from the operations being credited to LQ.AI.

For P5, preserve the same account, original chat and database volume from seeding through resumption.
After at least 24 hours, authenticate a fresh client and reopen that chat. Submit only:

```json
{"content":"What was the reference I gave you?","model":"local","skills":[],"file_ids":[],"stream":true}
```

Compare the completed answer with the independently recorded seed after the response. Do not add
the seed or a copied transcript to the request. Then authenticate a separate fresh client as the
same user, create a chat, verify that its message list is empty and submit:

```json
{"content":"What did I ask you in my previous LQ.AI task?","model":"local","skills":[],"file_ids":[],"stream":true}
```

Retain both persisted replies and their inference receipts. If the original account, chat or volume
is missing, report the blocker; reseeding cannot satisfy the delayed check. A new deliberately seeded
experiment must have its own timing and identity. The recorded pass here includes an earlier same-day
recall and tests API reopening, not browser task-list navigation, crash recovery or exhaustive
cross-user isolation.
