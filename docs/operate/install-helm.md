# Install on Kubernetes with Helm

The repository includes a Helm chart for Kubernetes, but it does not yet include everything in
the Docker Compose setup. The chart lives at `deploy/helm/lq-ai/` — it isn't published to a Helm
repository, so you install from a clone rather than `helm repo add`.
[`docs/HONEST-STATE.md`](../HONEST-STATE.md) §9 marks it **drafted**: it deploys the chat surface
end to end, but read on before you commit to it for anything more.

## Add the missing workers

Per [`deploy/helm/lq-ai/NOTES.txt`](../../deploy/helm/lq-ai/NOTES.txt), the chart installs
Postgres (`pgvector/pgvector:pg16`), Redis, RustFS (the bundled S3-compatible object store,
[ADR 0036](../adr/0036-bundled-object-store-rustfs.md)), the Inference Gateway, the FastAPI
backend, and the web client — each as its own Deployment or StatefulSet, with a ClusterIP Service
and, optionally, an Ingress in front of `web`. It does **not** install the two background workers
Compose runs: `ingest-worker` and `arq-worker`. Plan how those workers will run before you rely on
this chart for anything beyond chat.

> [!CAUTION]
> **Silent failure** — The chart has no Deployment for the `ingest-worker` or `arq-worker`
> background workers — only `deployment-{api,gateway,web}.yaml` exist under
> `deploy/helm/lq-ai/templates/`. Document ingestion (the pipeline that turns an uploaded file
> into `ready`) and every queued background job — Easy Playbook, Tabular Review generation,
> autonomous sessions — depend on those two workers, and this chart does not deploy them
> ([`docs/PRD.md`](../PRD.md), DE-327). Chat against already-ingested content works; a file upload
> will sit in `processing` indefinitely with nothing consuming its job, and nothing in the chart's
> own output says so — every Pod the chart *does* define reports healthy, because the missing ones
> were never scheduled. Watch for this in the file's own status in the LQ.AI UI, or compare
> `kubectl get pods` against the component list above.

The same gap means there's no migration-ordering mechanism for a future worker deployment either
— no `LQ_AI_SKIP_MIGRATIONS` wiring for a worker Pod (DE-327 again); the pre-upgrade migration Job
described under "Upgrading a chart that previously installed MinIO" below is a separate, narrower
mechanism for the object-store swap specifically, not a general worker-migration story.

## Check the provider settings

A provider entry needs `type`, `base_url`, and `tier` — none has a default
(`gateway/app/config.py`). `deploy/helm/lq-ai/values-example.yaml`'s own sample uses `adapter:`
instead of `type:` and omits `base_url` and `tier` entirely, so copying it as written fails config
validation and the gateway container never comes up; the Pod's own logs are where that surfaces,
not `helm install`'s output. `gateway.config` becomes the whole `gateway.yaml` the gateway loads,
validated against that same file at startup. Every alias the backend asks for must also map to a
configured provider — `smart` is the chat default (`api/app/api/chats.py`) — so start from a copy
of [`gateway.yaml.example`](../../gateway.yaml.example) rather than a fragment like the one below:

```yaml
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

## Allow for your workload

The chart supplies starting values for memory and processing resources, one entry per component
in `values.yaml`:

| Component | Requests | Limits |
|---|---|---|
| gateway | `200m` / `256Mi` | `1000m` / `1Gi` |
| api | `200m` / `256Mi` | `1000m` / `2Gi` |
| web | `100m` / `256Mi` | `500m` / `1Gi` |

The storage services get a `PersistentVolumeClaim` sized by `postgres.storage` (default `20Gi`),
`redis.storage` (default `5Gi`), and `objectStore.storage` (falls back to the deprecated
`minio.storage`, default `50Gi`, when left blank). Treat these as starting points, not sizing
advice — adjust them after testing with representative documents and numbers of users.

## Prepare the cluster

You need a cluster with dynamic storage provisioning (or a `storageClass` you set per component in
`values.yaml`), `kubectl`, and Helm 3. Configure ingress and certificates yourself for the address
your users will visit — TLS is your ingress controller's job; `ingress.tls` passes through to
whatever you configure (cert-manager, a wildcard certificate), and the chart issues nothing itself
(see "Chart details that need deployment work" below for what its own Ingress does and doesn't
do). Do not put real credentials into a values file you intend to commit to source control: the
chart reads four secrets by reference rather than taking them inline — see "Match the secret names
and keys" below for the exact names and keys, and create them before you install.

## Pin the image version

`values.yaml` leaves `image.tag` empty so it falls back to `.Chart.AppVersion` — and `Chart.yaml`
pins that to `0.1.0`. `values-example.yaml` hardcodes `image.tag: "v0.1.0"` too. Neither matches a
real released image: the api and gateway in this checked commit report `0.7.1`
(`api/app/__init__.py`, `gateway/app/__init__.py`), and published image tags follow the project's
release versioning ([ADR 0025](../adr/0025-release-versioning-and-pipeline-ordering.md)), not the
chart version. Set `image.tag` to an actual `vX.Y.Z` release yourself — copying
`values-example.yaml` as-is will try to pull an image that was never published, and the Pods will
sit in `ImagePullBackOff` with no clearer signal than that.

```yaml
image:
  tag: "vX.Y.Z"   # a real release tag, not the chart's own version
```

## Check more than healthy pods

After you install (see "Install with reviewed values" below), check more than whether the Pods
report `Running`. [`deploy/helm/lq-ai/NOTES.txt`](../../deploy/helm/lq-ai/NOTES.txt) documents the
first-run admin password retrieval, the `web` port-forward, and the `cosign verify` command for
the image tag you set — but that file lives at the chart root, not under
`deploy/helm/lq-ai/templates/`, so Helm does not print it automatically after `helm install` or
`helm upgrade` the way a chart's `templates/NOTES.txt` would; read the file directly rather than
waiting for its contents to appear in your terminal. The `cosign verify` command it gives checks a
keyless-OIDC signature against this repository's GitHub Actions identity — see
[`docs/security/releases/README.md`](../security/releases/README.md) if you sign with an
operator-controlled key instead.

The missing `ingest-worker` and `arq-worker` (see the caution above) mean healthy chart-managed
Pods alone don't establish working uploads or queued background jobs.

The resource defaults above exist, but this chart doesn't establish high availability, scaling, or
production hardening on its own: it ships no `NetworkPolicy`, no `PodDisruptionBudget`, and no
autoscaling — `replicaCount` in `values.yaml` is a fixed number per component, and scaling beyond
one replica of `api` is untested against the chart's assumption that a single Pod runs its own
migrations on boot.

## Match the secret names and keys

The chart reads four secrets by reference rather than taking them inline — create them first, in
the same namespace as the release:

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

`values-example.yaml` is the source for this list and for the matching
`postgres.passwordSecretRef` / `objectStore.rootPasswordSecretRef` / `gateway.authSecretRef` /
`gateway.providerKeys` entries in `values.yaml`. The bundled object store moved from MinIO to
RustFS ([ADR 0036](../adr/0036-bundled-object-store-rustfs.md)); the chart still carries a
deprecated `minio.*` values block for backward compatibility, and if
`objectStore.rootPasswordSecretRef` is left blank it falls back to `minio.rootPasswordSecretRef`
(`lq-ai-minio` / `password`) — but `objectStore.*` is what current installs should set, and per
ADR 0036 the compatibility keys are supported through at least v0.10.0 and the rest of the 0.x
series. Provider credentials use the separate `gateway.providerKeys` mapping shown above —
structurally different from the other three (an open-ended name→secretRef mapping, rather than a
single fixed `*SecretRef` field), even though `lq-ai-provider-keys` is itself one of the four
secrets created above. Change any of these references in your values file if your secret store
uses different names.

## Chart details that need deployment work

Beyond the missing workers, the wiring between the Pods the chart *does* define has gaps of its
own, and none of them fail loudly:

- The api template sets `GATEWAY_URL`, but the api reads `LQ_AI_GATEWAY_URL`
  (`api/app/config.py`; `docker-compose.yml` and `.env.example` both set that name) — so the api
  falls back to its own default (`http://localhost:8001`) and never reaches the gateway Service.
- The gateway template sets only `LQ_AI_GATEWAY_KEY` and the provider keys. Its skill fetch
  defaults to `http://api:8000` (`gateway/app/clients/backend.py`), not the chart's `<release>-api`
  Service name, so `LQ_AI_API_URL` needs setting; without `DATABASE_URL` it logs a warning and
  persists no `inference_routing_log` rows (`gateway/app/main.py`); without
  `LQ_AI_GATEWAY_MASTER_KEY` the runtime provider-keys API stays unavailable.
- `gateway.yaml` is mounted from the ConfigMap read-only, so this is also the hardened-deployment
  case `gateway/entrypoint.sh` documents on purpose: the admin alias/key write endpoints fail
  cleanly rather than silently, because the file write itself fails before any in-memory swap. If
  you want in-app config edits, you need a writable mount instead of the rendered ConfigMap.
- The Ingress sends every path to `web` (`templates/ingress.yaml`). Published web images call the
  LQ.AI backend at `/lq/api/v1/*` (`.github/workflows/release.yml`); the release stack's own
  reverse proxy (`proxy/Caddyfile`) strips that `/lq` prefix and forwards to the api, and the chart
  has no equivalent rule, so those calls reach `web` instead. Wire the browser's API address to
  the api Service yourself, and check that the `web` image you deploy was built for that address.

Installing the chart as-is is not a complete substitute for the tested Docker Compose route.

## Inspect the chart before installing

Edit `my-values.yaml` first: choose a real image tag, supply the correct provider schema, set the
secret references, and resolve the missing-worker and API-routing gaps above as far as you plan
to. Then check that the rendered YAML is at least well-formed:

```bash
helm lint ./deploy/helm/lq-ai -f my-values.yaml
helm template lq-ai ./deploy/helm/lq-ai -f my-values.yaml > rendered.yaml
# Review the rendered resources before installing.
```

`helm lint` and `helm template` don't catch any of the gaps described above — they only prove the
rendered YAML is well-formed, not that these contracts hold.

## Install with reviewed values

With the secrets created and `my-values.yaml` pointing at a real image tag and a corrected
provider schema:

```bash
helm install lq-ai ./deploy/helm/lq-ai -f my-values.yaml
kubectl get pods
kubectl get services
```

## Upgrading a chart that previously installed MinIO

The bundled object store moved from MinIO to RustFS in
[ADR 0036](../adr/0036-bundled-object-store-rustfs.md). If you installed this chart before that
change, `NOTES.txt` documents upgrade guidance for every `helm upgrade` — read it directly, per
the note under "Check more than healthy pods" above: the old api Deployment never actually read
the `MINIO_*` variables the old chart set, so the MinIO PersistentVolumeClaim it left behind should
be empty — confirm that before deleting it, and treat RustFS as a fresh store. A dedicated, opt-in
Helm hook (`migrations.enabled: true` in `values.yaml`, per
[ADR 0037](../adr/0037-deployment-migrations-framework.md)) runs a pre-upgrade Job that migrates an
existing object-store claim in place instead, for operators who deliberately wired data into that
claim; it stays `false` by default because most existing Helm installs were never wired to their
bundled MinIO in the first place. If your claim does hold real objects, stop and follow
[`docs/releases/v0.8.0.md`](../releases/v0.8.0.md) instead of deleting anything.

## Next

- [Reverse proxy and TLS](reverse-proxy-tls.md) — a non-Kubernetes way to add TLS.
- [Architecture](../architecture.md) — where these services sit relative to each other.
