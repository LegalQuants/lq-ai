---
title: Something is wrong
description: Start from what you're seeing, not from a task name — three branches, and the catalog of failures that don't announce themselves.
audience: [operator]
status: draft
sources:
  - docs/HONEST-STATE.md
  - docs/citation-engine.md
  - docs/security/anonymization.md
  - docs/db-schema.md
  - api/app/config.py
  - gateway/app/providers/anthropic.py
  - gateway/app/providers/openai.py
  - gateway/app/providers/ollama.py
  - api/app/clients/gateway.py
  - docker-compose.yml
  - README.md
sidebar:
  order: 26
---

Find your symptom, not a task name:

| You're seeing | Go to |
|---|---|
| `docker compose up` won't come up at all, or a service stays unhealthy | [Day zero](#day-zero--it-wont-start) below |
| It worked before you upgraded; now it doesn't | [After an upgrade](#after-an-upgrade) below |
| It's running, but something feels off — empty answers, missing citations, a redaction you expected didn't happen | [Silent degrade](#silent-degrade) below — start here |
| A specific error message or a known gotcha | [Troubleshooting](troubleshooting.md) — the FAQ index |

## Day zero — it won't start

Confirm Docker has the resources README states — [Hardware sizing](hardware-sizing.md#configuration-2--docker-compose-cloud-provider-keys-a-small-server-or-a-laptop) covers the exact floor and what happens below it. If the compose file itself refuses to interpolate (an error naming a required variable you never intended to set — historically the Slack/Teams bridge variables did this on a default install, fixed as of the checked commit), you're likely on a stale copy of `docker-compose.yml`; re-pull it from the release tag you're installing. Beyond that: [Install with Docker Compose](install-docker-compose.md) and [Troubleshooting](troubleshooting.md) cover the documented gotchas one by one.

## After an upgrade

Go straight to [Upgrade — if it fails halfway](upgrade.md#if-it-fails-halfway). The short version: `api` is the sole migrator, and both workers wait on its health check — a failed migration shows up as `api` unhealthy and the workers never starting, not as a partial, silently-degraded stack.

## Silent degrade

The hardest branch, because nothing here throws an error. Each row below is a control that can fail without telling you — check the column that names what you can actually observe instead.

| What can fail silently | What you'd actually see | What to check |
|---|---|---|
| A citation whose quote spans two retrieved chunks | The marker renders grey as **unverified** — indistinguishable from a citation that was checked and failed. Nothing marks it as "never extracted." | Known limitation, not a bug to report: [`docs/citation-engine.md`](../../citation-engine.md#chunk-boundary-spanning-quotes--silently-drop-today) |
| A source document deleted between retrieval and citation persistence | Same "unverified" rendering as a citation that genuinely failed verification | [`docs/citation-engine.md`](../../citation-engine.md#deleted-source-documents--render-as-unverified-not-system-error) — the spec calls for a distinct state; it isn't built yet |
| A missed entity in the Anonymization Layer | Nothing — the response comes back rehydrated as if the miss never happened | [Anonymization](../trust/anonymization.md) — read this before you rely on it for a matter you can't accept the risk on |
| Embedding failures during ingestion | The file shows `ready`, but knowledge-base search silently degrades to full-text-search only (no vector half) | `documents.ingest_status` (`embed_failed` / `partial`) in [`docs/db-schema.md`](../../db-schema.md#documents); `/api/v1/admin/ingest-health` aggregates it |
| Two 60-second timeout defaults on the inference path | A chat returns an empty answer with no error, or "forgets" an attached document on turn 3 | See below |

:::note[Professional duty]
A silent anonymization miss means client-identifying material may have reached an external provider with no in-app signal, which engages confidentiality (and, where the matter is privileged, privilege) — so the routing decision for a matter you cannot accept that risk on belongs to whoever carries the duty for it, and Tier 1 / local-only routing is the control, not the anonymizer. No jurisdiction's rule is named as universal here.
:::

### Long-document chats going quiet

Three specific defaults, verified against the current source, that can produce a confidently-empty answer with nothing marking it as a failure:

- `DEFAULT_MAX_TOKENS = 4096` on the Anthropic adapter (`gateway/app/providers/anthropic.py`) — a reasoning model can spend the whole budget thinking and emit zero visible characters. The request still reports success.
- `lq_ai_chat_history_token_budget` defaults to `6000` tokens (`api/app/config.py`) — a document attached on turn 1 can be entirely trimmed from history by turn 3, on models with far larger context windows, with nothing in the response saying trimming occurred. Raise it in your deployment's config if your work is long-document-heavy.
- Two 60-second defaults sit on the inference path — `DEFAULT_TIMEOUT_SECONDS = 60.0` in `api/app/clients/gateway.py` (streaming overrides it; non-streaming calls do not) and the same default on the Anthropic and OpenAI adapters (`gateway/app/providers/anthropic.py`, `openai.py`; the Ollama adapter is 120 s). Each is per-request, and `timeout_s` on a provider entry in `gateway.yaml` overrides the adapter one.

These were reported together, with reproduction data, in a community-filed issue on a controlled multi-model benchmark run entirely through the deployed stack; the defaults above are unchanged as of the checked commit. If your practice runs long documents through LQ.AI routinely, budget for raising these rather than assuming the defaults were tuned for your workload — they were tuned for short chat turns.

## Next

- [Troubleshooting](troubleshooting.md)
- [Upgrade](upgrade.md)
- [Rotate a leaked provider key](rotate-a-leaked-key.md)
- [Anonymization](../trust/anonymization.md)
