#!/usr/bin/env bash
# Stack-boot smoke test — the single source of truth for the check that
# .github/workflows/stack-smoke.yml runs in CI (issue #283). Contributors
# run it locally before submitting a change that can break the stack at
# build or boot time: a dependency bump, a Dockerfile or docker-compose.yml
# edit, a new migration.
#
# What it does: builds every default-profile image, boots the full compose
# stack, waits for every healthcheck, probes the api/gateway/web health
# endpoints and the ingest worker's lazily-imported dependencies (docling),
# holds for a soak period, and fails if any container restarted.
#
# What it does NOT do: perform inference or exercise features. No provider
# API keys are required. If no .env exists, a dummy one is written; an
# existing .env is respected.
#
# Requirements: docker compose v2; ~25 GB free disk and 20-30 minutes for
# a cold build (the api image pulls docling/torch). Warm rebuilds are much
# faster. Tunables: SOAK_SECONDS (default 75), WAIT_TIMEOUT (default 900).

set -euo pipefail
cd "$(dirname "$0")/.."

SOAK_SECONDS="${SOAK_SECONDS:-75}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-900}"

# On failure, dump enough context to diagnose without re-running: the
# phase that failed, per-container state (exit code, OOM kill, restart
# count), the last healthcheck probe outputs (the reason a service never
# went healthy lives only here), disk space (the build's known failure
# mode), and recent logs. Full logs go to stack-smoke-logs/ (gitignored;
# uploaded as a CI artifact). In CI the same state is appended to the
# job summary.
LOG_DIR="stack-smoke-logs"
PHASE="startup"

dump_diagnostics() {
  local rc=$?
  [ "$rc" -eq 0 ] && return 0
  # Diagnostics must never die halfway — errexit stays off in here, and
  # a failed mkdir (e.g. disk full, one of the failure modes we report
  # on) must not stop the console dump.
  set +e
  echo
  echo "stack-smoke: FAILED during phase: ${PHASE} (exit ${rc})" >&2
  mkdir -p "$LOG_DIR" 2>/dev/null
  {
    echo "== stack-smoke failed during phase: ${PHASE} (exit ${rc})"
    echo
    echo "== docker compose ps -a"
    docker compose ps -a || true
    echo
    echo "== disk space"
    df -h . || true
    echo
    echo "== container state and last healthcheck probes"
    for id in $(docker compose ps -aq 2>/dev/null); do
      docker inspect --format '{{.Name}} status={{.State.Status}} exit={{.State.ExitCode}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}' "$id" || true
      docker inspect --format '{{if .State.Health}}{{range .State.Health.Log}}  probe exit={{.ExitCode}}: {{printf "%.400s" .Output}}{{"\n"}}{{end}}{{end}}' "$id" || true
    done
  } 2>&1 | tee "$LOG_DIR/state.txt" >&2
  docker compose logs --no-color > "$LOG_DIR/logs.txt" 2>&1 || true
  echo "stack-smoke: last 60 log lines per service follow; full logs in ${LOG_DIR}/" >&2
  docker compose logs --no-color --tail=60 >&2 || true
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
      echo "## Stack smoke failed during phase: \`${PHASE}\`"
      echo
      echo '```'
      cat "$LOG_DIR/state.txt"
      echo '```'
      echo
      echo 'Full compose logs are in the `stack-smoke-logs` workflow artifact.'
    } >> "$GITHUB_STEP_SUMMARY"
  fi
}
trap dump_diagnostics EXIT

if [ ! -f .env ]; then
  echo "stack-smoke: no .env found — writing dummy secrets (boot-only; no provider keys needed)"
  cat > .env <<'EOF'
POSTGRES_PASSWORD=ci-smoke-postgres
MINIO_ROOT_PASSWORD=ci-smoke-minio-password
LQ_AI_GATEWAY_KEY=ci-smoke-gateway-key
JWT_SECRET=ci-smoke-jwt-secret-0123456789abcdef0123456789abcdef
EOF
fi

# api, ingest-worker, and arq-worker share the ./api build context and
# produce byte-identical images. Letting `up --build` build all three
# exports the ~12 GB image three times concurrently, which can exhaust
# disk mid-extraction. Build each distinct image once and tag the worker
# images from the api image — image names are stable because
# docker-compose.yml pins the project name (`name: lq-ai`).
PHASE="build"
echo "stack-smoke: building images"
docker compose build gateway web
docker compose build api
docker tag lq-ai-api:latest lq-ai-ingest-worker:latest
docker tag lq-ai-api:latest lq-ai-arq-worker:latest

# --wait blocks until every default-profile service reports healthy (all
# of them define healthchecks) and fails if any container exits or never
# becomes healthy. --force-recreate starts every container fresh so the
# RestartCount assertion below counts only restarts this run caused —
# named volumes (pgdata, miniodata, model caches) are untouched.
PHASE="boot"
echo "stack-smoke: booting the stack (waiting up to ${WAIT_TIMEOUT}s for healthchecks)"
docker compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" --no-build --force-recreate

PHASE="health probes"
echo "stack-smoke: probing health endpoints from the host"
curl -fsS http://127.0.0.1:8000/health && echo
curl -fsS http://127.0.0.1:8001/health && echo
curl -fsS http://127.0.0.1:3000/health && echo

# The ingest worker defers docling imports into job functions (see
# api/app/workers/document_pipeline.py), so a broken docling survives
# boot. Import it explicitly.
PHASE="lazy-import probes"
echo "stack-smoke: probing lazily-imported dependencies"
docker compose exec -T ingest-worker python -c "from docling.document_converter import DocumentConverter; print('docling import OK')"

# Healthchecks can flicker healthy on a crash-looping service; hold long
# enough for a loop to show up as restarts.
PHASE="soak / restart assertion"
echo "stack-smoke: soaking for ${SOAK_SECONDS}s"
sleep "$SOAK_SECONDS"

failed=0
for id in $(docker compose ps -q); do
  name=$(docker inspect --format '{{.Name}}' "$id")
  restarts=$(docker inspect --format '{{.RestartCount}}' "$id")
  status=$(docker inspect --format '{{.State.Status}}' "$id")
  echo "stack-smoke: ${name} status=${status} restarts=${restarts}"
  if [ "$restarts" != "0" ] || [ "$status" != "running" ]; then
    failed=1
  fi
done

if [ "$failed" != "0" ]; then
  echo "stack-smoke: FAIL — a container restarted or is not running" >&2
  exit 1
fi
echo "stack-smoke: PASS — stack built, booted, and held for ${SOAK_SECONDS}s"
