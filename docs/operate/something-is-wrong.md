# Something is wrong

Find your symptom, not a task name:

| You're seeing | Go to |
|---|---|
| `docker compose up` won't come up at all, or a service stays unhealthy | [Day zero](#day-zero--it-wont-start) below |
| It worked before you upgraded; now it doesn't | [After an upgrade](#after-an-upgrade) below |
| It's running, but something feels off — empty answers, missing citations, a redaction you expected didn't happen | [Silent degrade](#silent-degrade) below — start here |
| A specific error message or a known gotcha | [Troubleshooting](troubleshooting.md) — the FAQ index |

## Day zero — it won't start

Confirm Docker has the resources README states — [Hardware sizing](hardware-sizing.md#configuration-2--docker-compose-cloud-provider-keys-a-small-server-or-a-laptop) covers the exact floor and what happens below it. If the compose file itself refuses to interpolate (an error naming a required variable you never intended to set — historically the Slack/Teams bridge variables did this on a default install, fixed as of the checked commit), you're likely on a stale copy of `docker-compose.yml`; re-pull it from the release tag you're installing. Beyond that: [Install with Docker Compose](../../README.md) and [Troubleshooting](troubleshooting.md) cover the documented gotchas one by one.

## After an upgrade

Go straight to [Upgrade — if it fails halfway](upgrade.md#if-it-fails-halfway). The short version: `api` is the sole migrator, and both workers wait on its health check — a failed migration shows up as `api` unhealthy and the workers never starting, not as a partial, silently-degraded stack. If the upgrade in question is the `v0.8.0` bundled-store migration, check the [MinIO to RustFS migration runbook](../runbooks/minio-to-rustfs.md)'s own verification and rollback sections first — its failure modes are more specific than the general upgrade runbook's.

## Silent degrade

The hardest branch, because nothing here throws an error. Each row below is a control that can fail without telling you — check the column that names what you can actually observe instead.

| What can fail silently | What you'd actually see | What to check |
|---|---|---|
| A citation whose quote spans two retrieved chunks | The marker renders grey as **unverified** — indistinguishable from a citation that was checked and failed. Nothing marks it as "never extracted." | Known limitation, not a bug to report: [`docs/citation-engine.md`](../citation-engine.md#chunk-boundary-spanning-quotes--silently-drop-today) |
| A source document deleted between retrieval and citation persistence | Same "unverified" rendering as a citation that genuinely failed verification | [`docs/citation-engine.md`](../citation-engine.md#deleted-source-documents--render-as-unverified-not-system-error) — the spec calls for a distinct state; it isn't built yet |
| A missed entity in the Anonymization Layer | Nothing — the response comes back rehydrated as if the miss never happened | [Anonymization](../security/anonymization.md) — read this before you rely on it for a matter you can't accept the risk on |
| Embedding failures during ingestion | The file shows `ready`, but knowledge-base search silently degrades to full-text-search only (no vector half) | `documents.ingest_status` (`embed_failed` / `partial`) in [`docs/db-schema.md`](../db-schema.md#documents); `/api/v1/admin/ingest-health` aggregates it |
| Generous per-request timeouts and a large max-output-tokens default on the inference path | A chat returns an empty answer with no error, or "forgets" an attached document on turn 3 | See below |

> [!NOTE]
> **Professional duty** — A silent anonymization miss means client-identifying material may have reached an external provider with no in-app signal, which engages confidentiality (and, where the matter is privileged, privilege) — so the routing decision for a matter you cannot accept that risk on belongs to whoever carries the duty for it, and Tier 1 / local-only routing is the control, not the anonymizer. No jurisdiction's rule is named as universal here.

### Long-document chats going quiet

Specific defaults, verified against the current source, that can still produce a confidently-empty answer with nothing marking it as a failure — the exact numbers have moved since this page was first drafted, so read this section rather than an older cached copy:

- `DEFAULT_MAX_TOKENS = 16384` on the Anthropic adapter (`gateway/app/providers/anthropic.py`, raised from an earlier `4096`) — a reasoning model can still spend the whole budget thinking and emit zero visible characters, even at the larger ceiling. The request still reports success.
- `lq_ai_chat_history_token_budget` (`api/app/config.py`) defaults to `64_000` tokens, raised from `6_000` after issue #503, in which a ~47,000-token case file attached on turn 1 was silently gone by turn 2 on models with 200k–1M context windows, with nothing in the response saying trimming had occurred. The raise is a ceiling, not the fix: attached-document blocks still count against the chat-history budget, and not counting them (**DE-391**, `docs/PRD.md` §9) is the category fix that remains open.
- The per-request timeout defaults on the inference path are now generous rather than tight: `DEFAULT_TIMEOUT_SECONDS = 60.0` in `api/app/clients/gateway.py` (streaming overrides it; non-streaming calls do not) is unchanged, but the Anthropic and OpenAI gateway adapters (`gateway/app/providers/anthropic.py`, `openai.py`) and the Ollama adapter (`gateway/app/providers/ollama.py`) now all default to `DEFAULT_TIMEOUT_SECONDS = 600.0`, up from the `60.0` / `120.0` this page previously reported. A slow response is therefore now much less likely to be the cause of an empty answer than it once was — check the max-tokens and history-budget defaults above first. Each timeout is per-request, and `timeout_s` on a provider entry in `gateway.yaml` overrides the adapter default.

The history-budget raise and the timeout raises landed separately, in response to reported cases; check the values your own deployment runs (a fork or an older release may not carry them) rather than assuming every install matches the defaults above. If your practice runs long documents through LQ.AI routinely, DE-391 — not counting attached documents against the history budget at all — is the fix to watch for; the raised ceilings above are a mitigation, not that fix.
