# Optional skill storage and bundled helpers

Local #563 implementation, awaiting the existing ADR/publication gates. Both
capabilities are disabled by default. Enabling storage does not enable scripts.

**Draft operator notes:** this documentation PR publishes the design and local
evidence, not migration 0071, the runner, images or the deployment overlay. The
commands below describe the separate unpublished implementation and cannot enable
these capabilities on this branch. Production script enablement additionally
requires the pending [ADR D8c/D8d confidentiality gates](../adr/0035-governed-orchestration-run-tree.md#d8d--confidentiality-must-survive-compromised-helper-output).

## Persistent workspaces

Apply migration **0071** through the normal deployment migration process and
rebuild the API, arq worker and ingest worker together. Never apply host migrations
to a running development database. Set `LQ_AI_SKILL_WORKSPACES_ENABLED=true` on the
API and arq worker when ready. Only skills declaring
`lq_ai.capabilities.workspace_version` receive list/read/write tools.

Storage uses the application Postgres database and its backup/access controls.
It is scoped to the owner, matter (or personal namespace for projectless chat),
exact skill identity and declared storage format. Files survive chat/run deletion.
They are deleted by owner reset or hard deletion of the owning matter/account.
Archiving a matter blocks tool access but preserves owner inspection/export/reset.
Deleting or disabling a skill preserves saved data so the owner can recover it.
`/lq-ai/skills/workspaces` provides inspection and reset; account export includes
`skill_workspaces.json`. Backups retain their existing operator retention policy.

Each workspace allows 32 named UTF-8 files, 64 KiB per file and 1 MiB total.
Names have no paths. Writes require the current revision UUID; `null` creates a
new file. Conflicts require a fresh read and deliberate revision. Each write gets
a fresh UUID, including after reset. Workspace versions isolate incompatible data;
there is no implicit migration between versions. Minor skill edits can retain the
same workspace version. Work is loaded only through an explicit read call.

## Review and enable a bundled helper

Production execution requires a dedicated environment separated from LQ application
storage and credentials. Its engine must not be able to inspect or mount that
storage; rootless execution on a shared application host alone is insufficient.
The broker has privileged control of its selected engine; keep it away from
application credentials and public ingress. Review this deployment boundary and
operational input/output handling before enablement. Container controls reduce access and resource use; they do not
replace review of bundled code or provide a VM security boundary. Docker's
[engine security guidance](https://docs.docker.com/engine/security/) describes
the daemon trust boundary.
The acceptance probes use cgroup v2. The engine must support the requested
resource limits; container-creation warnings cause refusal before execution.

1. Review the skill's declared `scripts/<name>.py` files and supporting files.
   Helpers must treat JSON inputs as data: no `eval`, generated imports, shell
   interpretation or loading code from the writable temporary directory. Remove
   secrets from the bundle. The initial runtime supports Python with its standard
   library; reviewed dependencies may be installed in a custom image at build time.
2. Build the immutable image on the selected execution engine. From repository root:

   ```sh
   docker build -f script_runner/Dockerfile.bundle \
     --build-arg SKILL_DIR=skills/saved-notes-demo -t lq-saved-notes:review .
   docker image inspect --format '{{.Id}}' lq-saved-notes:review
   ```

3. Use that image ID (or an immutable registry digest) to produce a reviewable map:

   ```sh
   cd api
   .venv/bin/python -m app.skills.bundle_manifest saved-notes-demo \
     --skills-dir ../skills --image sha256:<reviewed-image-id> > /absolute/path/bundles.json
   ```

   The map records the skill identity, hash of all installed script files,
   allowed helper names and immutable image. Merge entries to enable more skills.
   The broker never pulls images. Install the same reviewed images on its engine.
   Changing source requires rebuilding, reviewing and updating this map; mismatch
   refuses execution. Changing a pinned orchestration skill also requires a new
   approved plan. Script source is visible in the skill's Source tab.
4. Generate a separate random authentication token of at least 32 characters.
   Configure `LQ_AI_SKILL_SCRIPT_RUNNER_TOKEN`, `LQ_SKILL_ENGINE_SOCKET` and the
   absolute `LQ_SKILL_BUNDLES_FILE`. Use a unique stable
   `LQ_SKILL_RUNNER_INSTANCE` for each broker sharing an engine.
   Set `LQ_SKILL_ENGINE_GID` to the socket's group ID as seen in the container
   (default 0). The broker runs as uid 65534 with that supplementary group;
   make the manifest readable to it. Do not make the engine socket world-writable.
5. The optional overlay connects only the API, arq worker and broker to an internal
   network, with no broker host port:

   ```sh
   docker compose -f docker-compose.yml -f deploy/compose.skill-runner.yml \
     up -d --build api arq-worker ingest-worker skill-runner
   ```

   For another private deployment, set `LQ_AI_SKILL_SCRIPT_RUNNER_URL` and the
   same token on the API/worker. Use TLS when crossing hosts. Keep the broker on
   an operator-controlled private endpoint; do not route `/run` through public ingress.

## Execution contract and operational limits

The request selects an enabled installed helper and supplies a JSON object of at
most 64 KiB. There is no source-code, shell command, executable path, interpreter,
image, mount or environment parameter. Generated-code execution is unsupported.
DB/inline skills can declare storage but cannot install executable scripts.

Every job runs as uid/gid 65534 in a new container: no network, read-only root,
no added capabilities, no-new-privileges, one CPU, 256 MiB memory with no additional
swap, 32 processes, 64 open files and a 16 MiB `/work` tmpfs. Docker's default
seccomp profile remains active. The trusted launcher enforces a 10-second helper
deadline and 64 KiB combined stdout/stderr. It executes Python with `-I -B`; imports
from the current directory, user site and `PYTHONPATH` are disabled. Scripts using
sibling imports must be packaged as reviewed installed dependencies in the image.
The only child environment is PATH/HOME (Python may add locale metadata).

The launcher verifies the bundle hash again, reads bounded JSON from stdin and
captures stdout, stderr and exit status. Workspace files are not mounted: a skill
explicitly reads selected text, sends it as input, and optionally saves selected
output through a separate workspace tool. `/work` is discarded between calls.

The broker accepts two concurrent jobs and refuses excess work. API calls time
out after 45 seconds. Jobs are forcibly removed after every request, including
an uncertain create response. A 30-second sweep removes jobs older than 90 seconds
belonging to that broker instance after an interruption/restart. Engine failure
can delay cleanup; restore the broker/engine and inspect only containers labelled
`lq.skill-job=1` and `lq.skill-runner=<instance>`. Inputs exist transiently in job
configuration and outputs in bounded engine logs until deletion; broker HTTP logs
omit request bodies and authentication. No API/worker container gets engine access.

Chat exposes tools for attached skills. The query-driven background planner and
the guarded orchestration adapter use the same service; orchestration additionally
requires exact grants, pinned skill approval, worker claims and durable effects.
Single-inference playbook, tabular and query-less watch paths do not acquire a new
agent loop merely because a skill includes a script. The existing orchestration
demonstration does not automatically grant these optional tools.

To disable calls, unset the runner URL/token on API/worker and stop the broker.
Keep it available until current jobs finish or let its cleanup sweep drain them.
Disabling persistence retains owner inspection/export/reset. Migration downgrade
refuses retained workspace rows: export and intentionally clear them first.

## Acceptance

CI builds the sample image and the separate reviewed `runner-probe` test image,
then runs `api/tests/skills` and the guarded orchestration capability tests against
real Postgres and Docker. Only inference responses and provider discovery are
controlled samples. The probes check authentication, changed bundle refusal,
fresh temporary storage, isolation, timeout, output bounds and cleanup. They are
never installed as production skill helpers.

For local reproduction, use a disposable pgvector Postgres container and the
fixture strategy in `api/tests/conftest.py`. Build both images as the CI step does,
then set `DATABASE_URL`, `LQ_TEST_SCRIPT_IMAGE`, `LQ_TEST_PROBE_IMAGE` and optionally
`LQ_TEST_DOCKER_SOCKET` before running the same tests. Image values must be immutable
IDs/digests. No provider keys or application credentials are needed.
