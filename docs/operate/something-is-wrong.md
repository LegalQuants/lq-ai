# Something isn't working

Find the step that failed, then check its settings and logs. The sections below cover common setup, access and document problems. For a specific error message or a known gotcha not covered here, check [Troubleshooting](troubleshooting.md) — the FAQ index.

## During setup

Docker Compose refuses to start if a required secret is empty — it reports `error while interpolating services...: required variable ... is missing a value` and names the variable. This historically caught people on the Slack/Teams bridge variables on a default install; that's fixed as of the checked commit, so if you still hit it, you're likely on a stale copy of `docker-compose.yml` — re-pull it from the release tag you're installing. If Docker won't come up at all rather than complaining about one variable, confirm it has the resources the README states first — [Hardware sizing](hardware-sizing.md#configuration-2--docker-compose-cloud-provider-keys-a-small-server-or-a-laptop) covers the floor and what happens below it. Beyond that, [Install with Docker Compose](../../README.md) and [Troubleshooting](troubleshooting.md) cover the documented gotchas one by one.

If the first-run password is missing from the logs, an admin account may already exist — see [If you can't sign in](#if-you-cant-sign-in) below for how to reset it.

If the AI can't answer, check that a provider is enabled with a key set, and that the model alias your chat is using actually resolves to one of them (`providers:` and `model_aliases:` in `gateway.yaml`). The chat UI surfaces this as "no model configured" / "no provider · default"; add a key via `.env` or **Admin/Configure → Provider keys**.

## If you can't sign in

Reset the admin password without touching any data:

```bash
docker compose exec api python -m app.cli reset-admin-password
```

This prints a new password and forces a change on next login (`must_change_password=true`), and works the same on a fresh install or an established deployment (`api/app/cli.py`). Avoid `docker compose down -v` as a recovery step: it destroys **all** local data, not just the admin account, and should never be used on an established deployment.

## If a document gets stuck

Check `files.ingestion_status` (`pending` / `processing` / `ready` / `failed`) and the `ingest-worker` logs; a `failed` row's `ingestion_error` names a specific code (`unsupported_type`, `unsupported_content`, `parse_failed`, `decode_error`, `ingestion_timeout`) — see [Troubleshooting](troubleshooting.md) for what each one means.

Text extraction, embedding preparation and answering questions are separate steps that can fail independently — a `ready` file can still be missing its search data; see [A ready file can still be missing search data](#a-ready-file-can-still-be-missing-search-data) below. Uploading a plain-text or Markdown file doesn't download or exercise the models used to process PDFs at all — that path skips the Docling thread/timeout machinery entirely and reads the decoded bytes directly (`api/app/pipeline/ingest.py`), so it won't reproduce, or rule out, a PDF-specific stall.

## After an upgrade

Go straight to [Upgrade — if it fails halfway](upgrade.md#if-it-fails-halfway) for the runbook. The short version: check the image versions (`docker compose images`) and the migration revision (`docker compose exec api alembic current`), then read the `api` logs before retrying anything. Keep `api` and both workers (`arq-worker`, `ingest-worker`) on the same build — `api` is the sole schema migrator, and both workers wait on its health check, so a failed migration shows up as `api` unhealthy and the workers never starting at all, not as a partial, silently-degraded stack. A healthy website can coexist with failed background processing, so when a task looks stuck, inspect the service that actually handles it rather than assuming the whole stack is down.

If the upgrade in question is the `v0.8.0` bundled-store migration, use the dedicated [MinIO to RustFS migration runbook](../runbooks/minio-to-rustfs.md) instead — its verification and rollback sections are more specific than the general upgrade runbook's.

## Silent degrade

These don't throw an error. Each item below names what you'd actually notice instead of an error, and what to check. The defaults named below are current as of the checked commit; check the values your own deployment actually runs before troubleshooting against them — a fork or an older release may not carry the same numbers.

### When answers stop arriving

Distinguish a slow model, a failed streamed response and a whole-answer request timing out — they call for different fixes. The provider adapters (Anthropic, OpenAI, Ollama) wait up to `DEFAULT_TIMEOUT_SECONDS = 600.0`s for the provider (`gateway/app/providers/anthropic.py`, `openai.py`, `ollama.py`); `timeout_s` on a provider entry in `gateway.yaml` overrides it. The api's own client to the gateway waits only `DEFAULT_TIMEOUT_SECONDS = 60.0`s (`api/app/clients/gateway.py`) — the constant's docstring says streaming overrides this, but `chat_completion_stream` actually reuses the same client and inherits the same 60 s. In practice that clock resets on every chunk the gateway forwards on the streaming path (the call site is `api/app/api/chats.py:3662`), so an actively-streaming turn can legitimately run well past 60 s without a `504`. The non-streaming path (called from `chats.py:3345` and `:3994`) has no such reprieve: any generation over 60 s does fail there with a `504` (`GatewayTimeout`). A confidently-empty answer with no error at all is unlikely to be a timeout — check the output-budget point below first, since a timeout surfaces as an explicit `504`, not as silence.

A reasoning model can also spend its whole output budget thinking and emit zero visible characters, with the request still reporting success. That budget defaults to `DEFAULT_MAX_TOKENS = 16384` on the Anthropic adapter (`gateway/app/providers/anthropic.py`), raised from an earlier `4096` — a larger ceiling makes this less likely, not impossible. Long documents also affect processing and these limits, so check the timestamps, the model actually chosen, and the error (if any) on that specific request before assuming you need to raise a timeout.

### If citations or privacy checks look wrong

Read the source passage yourself, and keep the failed example (with made-up data where possible) rather than just describing it. A displayed citation and a privacy-tier badge do not by themselves establish that the underlying check was accurate or complete — each has a known gap. Unlike those two, whether anonymization ran isn't shown in the chat itself at all: that's visible only via the audit log's `anonymization_applied` field (`gateway/app/api/inference.py`; `inference_routing_log.anonymization_applied`), and even that only records that the middleware fired, not that anything was actually caught:

- A citation whose quote spans two retrieved chunks renders grey as **unverified**, indistinguishable from a citation that was checked and genuinely failed — known limitation, not a bug to report: [`docs/citation-engine.md`](../citation-engine.md#chunk-boundary-spanning-quotes--silently-drop-today)
- A source document deleted between retrieval and citation persistence renders the same "unverified" way — the spec calls for a distinct state; it isn't built yet: [`docs/citation-engine.md`](../citation-engine.md#deleted-source-documents--render-as-unverified-not-system-error)
- A missed entity in the Anonymization Layer shows nothing at all — the response comes back rehydrated as if the miss never happened. Read [Anonymization](../security/anonymization.md) before you rely on it for a matter you can't accept that risk on.

> [!NOTE]
> **Professional duty** — A silent anonymization miss means client-identifying material may have reached an external provider with no in-app signal, which engages confidentiality (and, where the matter is privileged, privilege) — so the routing decision for a matter you cannot accept that risk on belongs to whoever carries the duty for it, and Tier 1 / local-only routing is the control, not the anonymizer. No jurisdiction's rule is named as universal here.

### A ready file can still be missing search data

`files.ingestion_status = ready` means text was extracted and stored — it says nothing about search. `documents.ingest_status` separately reports embedding preparation: `embed_failed` or `partial` mean some or all of the search vectors are missing, so keyword search can still return results while the meaning-based half is degraded ([`docs/db-schema.md`](../db-schema.md#documents)). An administrator can check `GET /api/v1/admin/ingest-health` (`api/app/api/admin.py`) for a summary across both fields, then the `ingest-worker` logs for the affected file.

### Why an older attachment can disappear from the conversation

The api replays the most recent prior turns that fit both caps at once — `lq_ai_chat_history_max_messages` (default `20`) and `lq_ai_chat_history_token_budget` (default `64_000` tokens) — oldest dropped first, and attached-document blocks count toward that token budget like any other message (`api/app/config.py`). A model's larger context window does not override these app-level limits. The budget was raised from `6_000` after issue #503, where a ~47,000-token case file attached on turn 1 was silently gone by turn 2 on models with 200k–1M context windows, with nothing in the response saying trimming had occurred — but the raise is a ceiling, not the fix: not counting attached-document blocks against the chat-history budget at all is the category fix that remains open (**DE-391**, [`docs/PRD.md` §9](../PRD.md#9-deferred-enhancements-and-identified-future-work)).

Both settings are read from the `api` container's environment as `LQ_AI_CHAT_HISTORY_TOKEN_BUDGET` and `LQ_AI_CHAT_HISTORY_MAX_MESSAGES` — `.env.example` lists them, but the shipped `docker-compose.yml` does not forward either into the `api` service's `environment:` block, so setting them in `.env` alone changes nothing. Add them to that block and recreate the container. `0` on either setting disables history replay entirely.
