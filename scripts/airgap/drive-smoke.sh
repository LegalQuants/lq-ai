#!/usr/bin/env bash
# Air-gap functional smoke (DE-032 / DE-233) — drive a REAL user journey
# against the sealed stack: first-run bootstrap -> login -> forced
# password rotation -> create chat -> send a message routed to the local
# Ollama provider -> assert a non-empty assistant response AND that the
# gateway's audit trail (inference_routing_log) recorded the request as
# provider=ollama-local, tier=1, with nothing routed at any cloud tier.
#
# This runs while deny-egress.sh has the compose bridge sealed and
# capture-egress.sh is recording, so a passing run means the journey
# completed with zero packets leaving the deployment.
#
# Model choice: the smoke requests `ollama-local/<model>` via the
# gateway's raw provider/model passthrough (D0, gateway/app/router.py),
# so the SHIPPED gateway.yaml.example is used byte-identical — no CI
# config fork. The default model is a small one (llama3.2:1b) rather
# than the qwen3.5 models the example aliases pin, because CI runners
# are CPU-only and the air-gap property under test (topology, routing,
# tier derivation) is identical for any Ollama-served model: tier
# derives from the provider entry (`ollama-local` -> tier 1), not from
# the model name.
#
# Usage: drive-smoke.sh   (no args; run from anywhere)
#
# Env:
#   AIRGAP_MODEL           Ollama model to route to (default llama3.2:1b;
#                          must have been pulled BEFORE the seal)
#   AIRGAP_API_BASE        api base URL (default http://127.0.0.1:8000)
#   AIRGAP_INFER_TIMEOUT   seconds to wait for the chat response
#                          (default 600 — CPU inference is slow)
#   LQ_AI_FIRST_RUN_ADMIN_EMAIL  bootstrap admin email (default admin@lq.ai)
#   POSTGRES_USER / POSTGRES_DB  for the routing-log assertion
#                          (defaults lq_ai / lq_ai, matching compose)
#
# Requires: docker compose v2, curl, jq, openssl.

set -euo pipefail
cd "$(dirname "$0")/../.."

MODEL="${AIRGAP_MODEL:-llama3.2:1b}"
API_BASE="${AIRGAP_API_BASE:-http://127.0.0.1:8000}"
INFER_TIMEOUT="${AIRGAP_INFER_TIMEOUT:-600}"
ADMIN_EMAIL="${LQ_AI_FIRST_RUN_ADMIN_EMAIL:-admin@lq.ai}"
PG_USER="${POSTGRES_USER:-lq_ai}"
PG_DB="${POSTGRES_DB:-lq_ai}"

PHASE="startup"
on_fail() {
  local rc=$?
  [ "$rc" -eq 0 ] && return 0
  echo "drive-smoke: FAILED during phase: ${PHASE} (exit ${rc})" >&2
  # Container states + recent api/gateway logs are usually enough to
  # tell an auth failure from a routing failure from a dead ollama.
  docker compose ps -a >&2 || true
  docker compose logs --no-color --tail=40 api gateway >&2 || true
}
trap on_fail EXIT

for tool in curl jq openssl; do
  command -v "$tool" >/dev/null || { echo "drive-smoke: missing required tool: $tool" >&2; exit 2; }
done

api() {
  # $1 = method, $2 = path, $3 = json body ('' for none), $4 = extra curl args
  local method="$1" path="$2" body="${3:-}"
  shift 3
  if [ -n "$body" ]; then
    curl -fsS -X "$method" "${API_BASE}${path}" \
      -H 'Content-Type: application/json' "$@" -d "$body"
  else
    curl -fsS -X "$method" "${API_BASE}${path}" "$@"
  fi
}

# ---------------------------------------------------------------------------
PHASE="bootstrap password"
# The api prints the first-run admin password once, at first boot against
# an empty DB ("First-run admin password" is the canonical grep pattern
# per api/app/api/bootstrap.py). The password is the line's last token.
echo "drive-smoke: reading first-run admin password from api logs"
BOOT_PW="$(docker compose logs --no-color api | grep 'First-run admin password' | tail -n 1 | awk '{print $NF}')"
if [ -z "$BOOT_PW" ]; then
  echo "drive-smoke: no bootstrap password found in api logs (was the DB not fresh?)" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
PHASE="login"
echo "drive-smoke: logging in as ${ADMIN_EMAIL}"
LOGIN_JSON="$(api POST /api/v1/auth/login "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${BOOT_PW}\"}")"
TOKEN="$(jq -er '.access_token' <<<"$LOGIN_JSON")"

# The bootstrap admin carries must_change_password=true, and the
# ActiveUser gate 403s every endpoint except change-password until it is
# cleared — rotate, then log in again (rotation revokes all sessions).
if [ "$(jq -r '.user.must_change_password' <<<"$LOGIN_JSON")" = "true" ]; then
  PHASE="forced password rotation"
  echo "drive-smoke: rotating the bootstrap password (forced-change gate)"
  NEW_PW="Airgap-$(openssl rand -hex 12)"  # 12-char policy minimum easily met; hex is JSON-safe
  api POST /api/v1/auth/change-password \
    "{\"current_password\":\"${BOOT_PW}\",\"new_password\":\"${NEW_PW}\"}" \
    -H "Authorization: Bearer ${TOKEN}" >/dev/null
  LOGIN_JSON="$(api POST /api/v1/auth/login "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${NEW_PW}\"}")"
  TOKEN="$(jq -er '.access_token' <<<"$LOGIN_JSON")"
fi

# ---------------------------------------------------------------------------
PHASE="create chat"
echo "drive-smoke: creating a chat"
CHAT_ID="$(api POST /api/v1/chats '{"title":"air-gap smoke"}' \
  -H "Authorization: Bearer ${TOKEN}" | jq -er '.id')"
echo "drive-smoke: chat ${CHAT_ID}"

# ---------------------------------------------------------------------------
PHASE="tier-1 inference"
echo "drive-smoke: sending a message routed to ollama-local/${MODEL} (timeout ${INFER_TIMEOUT}s)"
MSG_JSON="$(api POST "/api/v1/chats/${CHAT_ID}/messages" \
  "{\"content\":\"Reply with the single word OK.\",\"model\":\"ollama-local/${MODEL}\",\"stream\":false}" \
  -H "Authorization: Bearer ${TOKEN}" --max-time "$INFER_TIMEOUT")"

ASSISTANT_CONTENT="$(jq -r '.message.content // empty' <<<"$MSG_JSON")"
ROUTED_PROVIDER="$(jq -r '.routed_provider // empty' <<<"$MSG_JSON")"
ROUTED_TIER="$(jq -r '.routed_inference_tier // empty' <<<"$MSG_JSON")"
echo "drive-smoke: routed_provider=${ROUTED_PROVIDER} routed_inference_tier=${ROUTED_TIER}"
echo "drive-smoke: assistant said: $(head -c 200 <<<"$ASSISTANT_CONTENT")"

PHASE="response assertions"
if [ -z "$ASSISTANT_CONTENT" ]; then
  echo "drive-smoke: FAIL — empty assistant response" >&2
  exit 1
fi
if [ "$ROUTED_PROVIDER" != "ollama-local" ] || [ "$ROUTED_TIER" != "1" ]; then
  echo "drive-smoke: FAIL — expected routed_provider=ollama-local tier=1, got '${ROUTED_PROVIDER}' tier '${ROUTED_TIER}'" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
PHASE="routing-log assertions"
# The gateway writes every routed request to inference_routing_log
# (gateway/app/routing_log.py). Two assertions:
#   1. at least one non-refused row landed at ollama-local / tier 1
#      (our chat turn — the audit trail agrees with the response), and
#   2. ZERO non-refused rows exist at any tier other than 1 — nothing
#      (judge calls, embeddings, retries) was successfully routed to a
#      cloud provider during the sealed run.
psql_scalar() {
  docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -tA -c "$1"
}

echo "drive-smoke: routing-log rows for this run:"
docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -c \
  "SELECT timestamp, requested_model, routed_provider, routed_model, routed_inference_tier, refused, refusal_reason
     FROM inference_routing_log ORDER BY timestamp" || true

TIER1_ROWS="$(psql_scalar "SELECT count(*) FROM inference_routing_log WHERE refused = false AND routed_provider = 'ollama-local' AND routed_inference_tier = 1;")"
NON_TIER1_ROWS="$(psql_scalar "SELECT count(*) FROM inference_routing_log WHERE refused = false AND routed_inference_tier <> 1;")"

if [ "$TIER1_ROWS" -lt 1 ]; then
  echo "drive-smoke: FAIL — no non-refused ollama-local tier-1 row in inference_routing_log" >&2
  exit 1
fi
if [ "$NON_TIER1_ROWS" != "0" ]; then
  echo "drive-smoke: FAIL — ${NON_TIER1_ROWS} non-refused routing-log row(s) at a tier other than 1" >&2
  exit 1
fi

echo "drive-smoke: PASS — login -> chat -> tier-1 response completed; routing log shows ollama-local/tier-1 only"
