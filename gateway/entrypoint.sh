#!/bin/sh
# D0.5 — gateway container entrypoint.
#
# Resolves the question raised by D0.5: with the admin alias-CRUD
# surface enabled, gateway.yaml is now mutable at runtime. We must
# NOT mutate gateway.yaml.example (it's source-controlled and reset
# by `docker compose up --build`), so the runtime file lives in a
# writable mount.
#
# Behavior:
#   - Mount target is a directory (typically /etc/lq-ai/) containing:
#       gateway.yaml.example  (read-only, baked into the image)
#       gateway.yaml          (read-write, created on first boot)
#   - On first boot, if gateway.yaml is absent, copy the example to it.
#   - Always point GATEWAY_CONFIG_PATH at the writable file.
#
# Operators who want immutable config (a hardened deployment that
# refuses runtime edits) mount their own gateway.yaml directly over
# the writable path with `:ro`. The admin write endpoints will
# return 500 with a clean "config not writable" message in that case
# (the file write fails before the in-memory swap).

set -eu

CONFIG_DIR="${LQ_AI_GATEWAY_CONFIG_DIR:-/etc/lq-ai}"
TARGET="${CONFIG_DIR}/gateway.yaml"
# The seed/example lives outside the writable mount point so a named
# volume of CONFIG_DIR doesn't shadow it. Compose mounts the
# repo-root gateway.yaml.example here read-only.
EXAMPLE="${LQ_AI_GATEWAY_EXAMPLE_PATH:-/usr/share/lq-ai/gateway.yaml.example}"

# Privilege drop. The gateway holds plaintext provider keys, so the long-running
# process runs as the unprivileged `lqai` user (uid/gid 10001). The container
# starts as root only so this block can repair ownership of the writable config
# location first: a named volume created by an older, root-running image stays
# root-owned (Docker copies image ownership only into an *empty* volume), and
# admin writes left gateway.yaml as root:root 0600 — unreadable to 10001. We
# chown just the config location (best-effort: read-only and ConfigMap mounts
# are skipped), then re-exec this script as 10001. If the container is started
# as non-root already (e.g. a Kubernetes runAsUser), this block is skipped.
LQ_AI_UID=10001
LQ_AI_GID=10001
if [ "$(id -u)" = "0" ]; then
  if [ -d "${CONFIG_DIR}" ]; then
    chown -R "${LQ_AI_UID}:${LQ_AI_GID}" "${CONFIG_DIR}" 2>/dev/null || true
  fi
  if [ -n "${GATEWAY_CONFIG_PATH:-}" ] && [ -f "${GATEWAY_CONFIG_PATH}" ]; then
    chown "${LQ_AI_UID}:${LQ_AI_GID}" "${GATEWAY_CONFIG_PATH}" 2>/dev/null || true
  fi
  export HOME=/home/lqai
  exec setpriv --reuid="${LQ_AI_UID}" --regid="${LQ_AI_GID}" --clear-groups -- "$0" "$@"
fi

# Honor an explicit override (e.g., a single-file mount) without
# touching anything.
if [ -n "${GATEWAY_CONFIG_PATH:-}" ] && [ "${GATEWAY_CONFIG_PATH}" != "${TARGET}" ]; then
  echo "gateway entrypoint: GATEWAY_CONFIG_PATH=${GATEWAY_CONFIG_PATH} (single-file mode)"
  exec "$@"
fi

if [ ! -d "${CONFIG_DIR}" ]; then
  echo "gateway entrypoint: config directory ${CONFIG_DIR} not present; running with default GATEWAY_CONFIG_PATH"
  exec "$@"
fi

if [ ! -f "${TARGET}" ]; then
  if [ -f "${EXAMPLE}" ]; then
    echo "gateway entrypoint: ${TARGET} not present; seeding from ${EXAMPLE}"
    cp "${EXAMPLE}" "${TARGET}"
  else
    echo "gateway entrypoint: neither ${TARGET} nor ${EXAMPLE} present; falling back to default config path"
    exec "$@"
  fi
fi

export GATEWAY_CONFIG_PATH="${TARGET}"
echo "gateway entrypoint: GATEWAY_CONFIG_PATH=${GATEWAY_CONFIG_PATH}"
exec "$@"
