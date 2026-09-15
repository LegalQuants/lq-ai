---
title: Install with Helm
description: Deploy the core LQ.AI services to Kubernetes with the in-repo chart, and what it doesn't yet run for you.
audience: [operator]
status: draft
sources:
  - deploy/helm/lq-ai/Chart.yaml
  - deploy/helm/lq-ai/values.yaml
  - deploy/helm/lq-ai/values-example.yaml
  - deploy/helm/lq-ai/NOTES.txt
  - docs/PRD.md
  - docs/HONEST-STATE.md
  - api/app/__init__.py
  - gateway/app/__init__.py
sidebar:
  order: 12
---

The chart lives at `deploy/helm/lq-ai/` in this repository — it isn't published to a Helm repository, so you install from a clone rather than `helm repo add`. `docs/HONEST-STATE.md` §9 marks it **drafted**: it deploys the chat surface end to end, but read "What the chart doesn't run" below before you commit to it for anything more.

## What it installs

Per `deploy/helm/lq-ai/NOTES.txt`: Postgres (`pgvector/pgvector:pg16`), Redis, MinIO, the Inference Gateway, the FastAPI backend, and the web client — each as its own Deployment or StatefulSet, with a ClusterIP Service and, optionally, an Ingress in front of `web`. Resource requests and limits are set per component in `values.yaml` (for example the gateway defaults to `200m`/`256Mi` requesting up to `1000m`/`1Gi`); the storage services get a `PersistentVolumeClaim` sized by `postgres.storage`, `redis.storage`, and `minio.storage`.

## Before you install

You need a cluster, `kubectl`, and Helm 3. The chart reads four secrets by reference rather than taking them inline — create them first:

```bash
kubectl create secret generic lq-ai-postgres \
  --from-literal=password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
kubectl create secret generic lq-ai-minio \
  --from-literal=password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
kubectl create secret generic lq-ai-auth \
  --from-literal=jwt-secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --from-literal=gateway-key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
kubectl create secret generic lq-ai-provider-keys \
  --from-literal=anthropic="sk-ant-..." \
  --from-literal=openai="sk-..."
```

(`deploy/helm/lq-ai/values-example.yaml` is the source for this list and for the matching `passwordSecretRef` / `authSecretRef` / `providerKeys` entries in `values.yaml`.)

## Set the image tag explicitly

`values.yaml` leaves `image.tag` empty so it falls back to `.Chart.AppVersion` — and `Chart.yaml` pins that to `0.1.0`. `values-example.yaml` hardcodes `image.tag: "v0.1.0"` too. Neither matches a real released image: the api and gateway in this checked commit report `0.7.0` (`api/app/__init__.py`, `gateway/app/__init__.py`), and published image tags follow the project's release versioning ([ADR 0025](../../adr/0025-release-versioning-and-pipeline-ordering.md)), not the chart version. Set `image.tag` to an actual `vX.Y.Z` release yourself — copying `values-example.yaml` as-is will try to pull an image that was never published, and the Pods will sit in `ImagePullBackOff` with no clearer signal than that.

```yaml
image:
  tag: "vX.Y.Z"   # a real release tag, not the chart's own version
gateway:
  config: |
    providers:
      - name: anthropic-prod
        adapter: anthropic
        api_key_env: ANTHROPIC_API_KEY
        models: [claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5]
  providerKeys:
    ANTHROPIC_API_KEY: { secretName: lq-ai-provider-keys, key: anthropic }
```

## Install and verify

```bash
helm install lq-ai ./deploy/helm/lq-ai -f my-values.yaml
```

`NOTES.txt` prints on success: how to retrieve the first-run admin password from the api Pod's logs, how to port-forward to `web`, and the `cosign verify` command for the image you pulled — run it against the tag you actually set above, not the chart's default.

## What the chart doesn't run

:::caution[Silent failure]
The chart has no Deployment for the `ingest-worker` or `arq-worker` background workers — only `deployment-{api,gateway,web}.yaml` exist under `deploy/helm/lq-ai/templates/`. Document ingestion (the pipeline that turns an uploaded file into `ready`) and every queued background job — Easy Playbook, Tabular Review generation, autonomous sessions — depend on those two workers, and this chart does not deploy them (`docs/PRD.md`, DE-327). Chat against already-ingested content works; a file upload will sit in `processing` indefinitely with nothing consuming its job, and nothing in the chart's own output says so — every Pod the chart *does* define reports healthy, because the missing ones were never scheduled. Watch for this in the file's own status in the LQ.AI UI, or compare `kubectl get pods` against the component list above.
:::

The same gap means there's no migration-ordering mechanism for a future worker deployment either — no migration `Job`, no `LQ_AI_SKIP_MIGRATIONS` wiring (DE-327 again). The chart also ships no `NetworkPolicy`, no `PodDisruptionBudget`, and no autoscaling: `replicaCount` in `values.yaml` is a fixed number per component, and scaling beyond one replica of the `api` is untested against the chart's assumption that a single Pod runs its own migrations on boot. TLS is your ingress controller's job — `ingress.tls` passes through to whatever you configure (cert-manager, a wildcard certificate); the chart issues nothing itself.

## Next

- [Reverse proxy and TLS](reverse-proxy-tls.md) — a non-Kubernetes way to add TLS.
- [Architecture](architecture.md) — where these services sit relative to each other.
- [Backup and restore](backup-and-restore.md) — the chart's PersistentVolumeClaims are what you're backing up.
