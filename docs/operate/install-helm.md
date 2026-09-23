# Install with Helm

The chart lives at `deploy/helm/lq-ai/` in this repository — it isn't published to a
Helm repository, so you install from a clone rather than `helm repo add`.
[`docs/HONEST-STATE.md`](../HONEST-STATE.md) §9 marks it **drafted**: it deploys the
chat surface end to end, but read "What the chart doesn't run" below before you
commit to it for anything more.

## What it installs

Per [`deploy/helm/lq-ai/NOTES.txt`](../../deploy/helm/lq-ai/NOTES.txt): Postgres
(`pgvector/pgvector:pg16`), Redis, RustFS (the bundled S3-compatible object store,
[ADR 0036](../adr/0036-bundled-object-store-rustfs.md)), the Inference Gateway, the
FastAPI backend, and the web client — each as its own Deployment or StatefulSet,
with a ClusterIP Service and, optionally, an Ingress in front of `web`. Resource
requests and limits are set per component in `values.yaml` (for example the gateway
defaults to `200m`/`256Mi` requesting up to `1000m`/`1Gi`); the storage services get a
`PersistentVolumeClaim` sized by `postgres.storage`, `redis.storage`, and
`objectStore.storage`.

## Before you install

You need a cluster, `kubectl`, and Helm 3. The chart reads four secrets by reference
rather than taking them inline — create them first:

```bash
kubectl create secret generic lq-ai-postgres \
  --from-literal=password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
kubectl create secret generic lq-ai-object-store \
  --from-literal=password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
kubectl create secret generic lq-ai-auth \
  --from-literal=jwt-secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --from-literal=gateway-key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
kubectl create secret generic lq-ai-provider-keys \
  --from-literal=anthropic="sk-ant-..." \
  --from-literal=openai="sk-..."
```

(`deploy/helm/lq-ai/values-example.yaml` is the source for this list and for the
matching `rootPasswordSecretRef` / `authSecretRef` / `providerKeys` entries in
`values.yaml`. The chart also carries a deprecated `minio.*` values block for
backward compatibility with older values files — `objectStore.*` is what current
installs should set; per ADR 0036 the compatibility keys are supported through at
least v0.10.0.)

## Set the image tag explicitly

`values.yaml` leaves `image.tag` empty so it falls back to `.Chart.AppVersion` — and
`Chart.yaml` pins that to `0.1.0`. `values-example.yaml` hardcodes `image.tag:
"v0.1.0"` too. Neither matches a real released image: the api and gateway in this
checked commit report `0.7.1` (`api/app/__init__.py`, `gateway/app/__init__.py`), and
published image tags follow the project's release versioning
([ADR 0025](../adr/0025-release-versioning-and-pipeline-ordering.md)), not the chart
version. Set `image.tag` to an actual `vX.Y.Z` release yourself — copying
`values-example.yaml` as-is will try to pull an image that was never published, and
the Pods will sit in `ImagePullBackOff` with no clearer signal than that.

```yaml
image:
  tag: "vX.Y.Z"   # a real release tag, not the chart's own version
gateway:
  config: |
    providers:
      - name: anthropic-prod
        type: anthropic
        base_url: https://api.anthropic.com
        api_key_env: ANTHROPIC_API_KEY
        tier: 4       # standard commercial account; 3 under a zero-data-retention agreement
        models: [claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5]
    model_aliases:
      smart:
        primary: { provider: anthropic-prod, model: claude-sonnet-4-6 }
  providerKeys:
    ANTHROPIC_API_KEY: { secretName: lq-ai-provider-keys, key: anthropic }
```

`gateway.config` becomes the whole `gateway.yaml` the gateway loads, validated
against `gateway/app/config.py` at startup. Every provider entry needs `type`,
`base_url`, and `tier` — none has a default. `values-example.yaml`'s own sample uses
`adapter:` instead of `type:` and omits `base_url` and `tier` entirely, so copying it
as written fails config validation and the gateway container never comes up; the
Pod's own logs are where that surfaces, not `helm install`'s output. Every alias the
backend asks for must also map to a configured provider — `smart` is the chat
default (`api/app/api/chats.py`) — so start from a copy of
[`gateway.yaml.example`](../../gateway.yaml.example) rather than a fragment like the
one above.

## Install and verify

```bash
helm install lq-ai ./deploy/helm/lq-ai -f my-values.yaml
```

`NOTES.txt` prints on success: the exact `cosign verify` command for the image tag
you set (keyless OIDC against this repository's GitHub Actions identity — see
[`docs/security/releases/README.md`](../security/releases/README.md) if you sign with an
operator-controlled key instead), how to retrieve the first-run admin password from
the api Pod's logs, and how to port-forward to `web`.

## Upgrading a chart that previously installed MinIO

The bundled object store moved from MinIO to RustFS in
[ADR 0036](../adr/0036-bundled-object-store-rustfs.md). If you installed this chart
before that change, `NOTES.txt` prints upgrade guidance on every `helm upgrade`: the
old api Deployment never actually read the `MINIO_*` variables the old chart set, so
the MinIO PersistentVolumeClaim it left behind should be empty — confirm that before
deleting it, and treat RustFS as a fresh store. A dedicated, opt-in Helm hook
(`migrations.enabled: true` in `values.yaml`, per [ADR 0037](../adr/0037-deployment-migrations-framework.md))
runs a pre-upgrade Job that migrates an existing object-store claim in place instead,
for operators who deliberately wired data into that claim; it stays `false` by
default because most existing Helm installs were never wired to their bundled MinIO
in the first place. If your claim does hold real objects, stop and follow
[`docs/releases/v0.8.0.md`](../releases/v0.8.0.md) instead of deleting anything.

## What the chart doesn't run

> [!CAUTION]
> **Silent failure** — The chart has no Deployment for the `ingest-worker` or
> `arq-worker` background workers — only `deployment-{api,gateway,web}.yaml` exist
> under `deploy/helm/lq-ai/templates/`. Document ingestion (the pipeline that turns
> an uploaded file into `ready`) and every queued background job — Easy Playbook,
> Tabular Review generation, autonomous sessions — depend on those two workers, and
> this chart does not deploy them ([`docs/PRD.md`](../PRD.md), DE-327). Chat against
> already-ingested content works; a file upload will sit in `processing` indefinitely
> with nothing consuming its job, and nothing in the chart's own output says so —
> every Pod the chart *does* define reports healthy, because the missing ones were
> never scheduled. Watch for this in the file's own status in the LQ.AI UI, or
> compare `kubectl get pods` against the component list above.

The wiring between the Pods the chart *does* define has its own gaps, and none of
them fail loudly:

- The api template sets `GATEWAY_URL`, but the api reads `LQ_AI_GATEWAY_URL`
  (`api/app/config.py`; `docker-compose.yml` and `.env.example` both set that name)
  — so the api falls back to its own default (`http://localhost:8001`) and never
  reaches the gateway Service.
- The gateway template sets only `LQ_AI_GATEWAY_KEY` and the provider keys. Its
  skill fetch defaults to `http://api:8000` (`gateway/app/clients/backend.py`), not
  the chart's `<release>-api` Service, so `LQ_AI_API_URL` needs setting; without
  `DATABASE_URL` it logs a warning and persists no `inference_routing_log` rows
  (`gateway/app/main.py`); without `LQ_AI_GATEWAY_MASTER_KEY` the runtime
  provider-keys API stays unavailable.
- `gateway.yaml` is mounted from the ConfigMap read-only, so this is also the
  hardened-deployment case `gateway/entrypoint.sh` documents on purpose: the admin
  alias/key write endpoints fail cleanly rather than silently, because the file
  write itself fails before any in-memory swap. If you want in-app config edits, you
  need a writable mount instead of the rendered ConfigMap.
- The Ingress sends every path to `web` (`templates/ingress.yaml`). Published web
  images call the LQ.AI backend at `/lq/api/v1/*`
  (`.github/workflows/release.yml`); the release stack's own reverse proxy
  (`proxy/Caddyfile`) strips that `/lq` prefix and forwards to the api, and the
  chart has no equivalent rule, so those calls reach `web` instead.

`helm lint` and `helm template` don't catch any of this — they only prove the
rendered YAML is well-formed, not that these contracts hold:

```bash
helm lint ./deploy/helm/lq-ai -f my-values.yaml
helm template lq-ai ./deploy/helm/lq-ai -f my-values.yaml > rendered.yaml
# Review the rendered resources before installing.
```

The same worker gap means there's no migration-ordering mechanism for a future worker
deployment either — no `LQ_AI_SKIP_MIGRATIONS` wiring for a worker Pod (DE-327
again); the pre-upgrade migration Job described above is a separate, narrower
mechanism for the object-store swap specifically, not a general worker-migration
story. The chart also ships no `NetworkPolicy`, no `PodDisruptionBudget`, and no
autoscaling: `replicaCount` in `values.yaml` is a fixed number per component, and
scaling beyond one replica of the `api` is untested against the chart's assumption
that a single Pod runs its own migrations on boot. TLS is your ingress controller's
job — `ingress.tls` passes through to whatever you configure (cert-manager, a
wildcard certificate); the chart issues nothing itself.

## Next

- [Reverse proxy and TLS](reverse-proxy-tls.md) — a non-Kubernetes way to add TLS.
- [Architecture](../architecture.md) — where these services sit relative to each other.
