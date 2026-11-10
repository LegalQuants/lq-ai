# Headless boot (unsupported)

Headless / API-only use of LQ.AI is **unsupported**: there is no compatibility
promise for third-party API clients. Under [ADR 0031](../adr/0031-headless-api-only-use.md),
the generated OpenAPI export is a CI drift guard for the project's own clients,
not a public compatibility contract. ADR 0025's patch/minor promises do not extend
to third-party clients; their bug reports are answered “unsupported, PRs welcome.”
This page records an observed deployment, not an API quickstart.

## Deployment observed

Tested on October 12–13, 2026, using the then-current `main` (application version v0.9.0) at
[`f36c0c09c9dd`](https://github.com/LegalQuants/lq-ai/commit/f36c0c09c9dd7a6dd930bc8ec4051f52cdd5b21f),
on macOS arm64 with Docker Desktop 4.92.0, Engine 29.8.0 and Compose 5.5.1.
No application source or Compose changes were needed.

There is no headless Compose profile. The services selected from
[docker-compose.yml](../../docker-compose.yml) were `postgres`, `redis`, `rustfs`,
`gateway` and `api`. The isolated project used fresh volumes and a local `.env`
with generated `POSTGRES_PASSWORD`, `JWT_SECRET`, `LQ_AI_GATEWAY_KEY` and
`OBJECT_STORE_SECRET_KEY`. Bind addresses retained their localhost defaults.
To avoid collisions, host-port overrides were `POSTGRES_HOST_PORT=55439`,
`REDIS_HOST_PORT=56389`, `OBJECT_STORE_API_HOST_PORT=59009`,
`OBJECT_STORE_CONSOLE_HOST_PORT=59019`, `API_HOST_PORT=58009` and
`GATEWAY_HOST_PORT=58019`.

These commands were executed from that checkout's root with that configuration:

```sh
docker compose -p lq-ai-headless-690 up -d --build postgres redis rustfs gateway api
docker compose -p lq-ai-headless-690 ps -a --format 'table {{.Service}}\t{{.State}}\t{{.Health}}'
curl --fail --silent --show-error http://127.0.0.1:58009/health
curl --fail --silent --show-error http://127.0.0.1:58009/ready
curl --fail --silent --show-error http://127.0.0.1:58019/health
```

## What worked without `web`

| Observation | Result |
| --- | --- |
| Startup | All five services became healthy; the prerequisite `rustfs-init` exited 0. API migrations and first-run administrator creation completed. |
| Health and readiness | Both health probes returned HTTP 200. API readiness returned HTTP 200 with database, Redis, storage and gateway reporting healthy. |
| Authentication | Unauthenticated project access returned 401; first-run login required password rotation, and project access before rotation returned 403. Rotation and subsequent login succeeded. |
| Backend operations | Skill listing, project creation/readback, and text-file upload/download succeeded. Downloaded bytes matched the upload. |
| HTTP surface | `/openapi.json` returned 200; the API root returned 404. No LQ.AI web application was served. |

## Document ingestion and AI review

The initial text upload remained `pending` without a worker. Ingestion was then
started with the following executed command:

```sh
docker compose -p lq-ai-headless-690 up -d --build ingest-worker
```

A public Harvey Labs [power-purchase-agreement negotiation task](https://github.com/harveyai/harvey-labs/tree/a15650fe74bb20b86f160aaabdad75b87a91b6e8/tasks/contracts/energy/power-purchase-agreement-term-negotiation)
provided 11 source files. All originals uploaded, but ten DOCX, EML and XLSX files
failed ingestion with `unsupported_type`; only the TXT succeeded.
DOCX ingestion has an accepted design in
[ADR 0017](../adr/0017-docx-ingest-via-pandoc.md), with implementation planned
separately. It was not available in the tested deployment. Broader parser and OCR
work is described in
[ADR 0033](../adr/0033-document-pipeline-honesty-and-ocr.md). External
conversion to labeled text allowed all 11 sources to reach `ready`.

With a funded OpenAI key configured in the gateway, `openai-prod/gpt-5` returned
HTTP 200 in 205.26 seconds. Receipts recorded 11 attached and 11 injected files;
a later history read confirmed the assistant answer was saved. The answer
addressed all four requested provisions. Neither `web` nor `arq-worker` ran.
The task's grading criteria were excluded, and no LQ.AI skills were applied.

## Limits of this observation

Readiness did not establish worker availability or job completion. Native Office
and email parsing was not demonstrated; input conversion and Word-output
packaging occurred outside LQ.AI. The generated draft contained formula,
cross-reference and completeness defects: successful inference did not establish
legal-review quality. Embeddings, autonomous runs, bridges, the Word add-in and
existing-volume upgrades were not validated. The RustFS console remained
available on localhost; “headless” here means omitting the LQ.AI `web` service.
