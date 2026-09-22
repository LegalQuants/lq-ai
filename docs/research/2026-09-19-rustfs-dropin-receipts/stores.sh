#!/usr/bin/env bash
# Throwaway helpers for the drop-in rehearsal. Source this file.
# Tracks PIDs in files so nothing needs pkill -f (which matches the shell itself).
set -u
SP=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)  # receipts copy; originally the session scratchpad holding minio-bin, rustfs-bin/, venv/
export LQ_API_DIR=/home/user/lq-ai/api
export S3_ACCESS_KEY=lq_ai S3_SECRET_KEY=ci-smoke-minio-password S3_BUCKET=lq-ai-files S3_REGION=us-east-1
PY=$SP/venv/bin/python

wait_http() { # url
  curl -sS --retry 60 --retry-delay 1 --retry-connrefused --retry-all-errors --max-time 5 -o /dev/null -w "$1 -> %{http_code}\n" "$1"
}

start_minio() { # datadir logfile
  MINIO_ROOT_USER=lq_ai MINIO_ROOT_PASSWORD=ci-smoke-minio-password \
    nohup "$SP/minio-bin" server "$1" --address 127.0.0.1:19100 --console-address 127.0.0.1:19101 > "$2" 2>&1 &
  echo $! > "$SP/minio.pid"
  wait_http http://127.0.0.1:19100/minio/health/live
}

start_rustfs() { # datadir logfile [access secret]
  RUSTFS_ACCESS_KEY="${3:-lq_ai}" RUSTFS_SECRET_KEY="${4:-ci-smoke-minio-password}" \
    RUSTFS_ADDRESS=127.0.0.1:19000 RUSTFS_CONSOLE_ENABLE=true RUSTFS_CONSOLE_ADDRESS=127.0.0.1:19001 \
    RUSTFS_OBS_LOGGER_LEVEL=info \
    nohup "$SP/rustfs-bin/rustfs" server "$1" > "$2" 2>&1 &
  echo $! > "$SP/rustfs.pid"
  wait_http http://127.0.0.1:19000/health
}

stop_pidfile() { # pidfile
  if [ -f "$1" ]; then
    local pid; pid=$(cat "$1")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid"
    fi
    rm -f "$1"
  fi
}
stop_minio() { stop_pidfile "$SP/minio.pid"; }
stop_rustfs() { stop_pidfile "$SP/rustfs.pid"; }

run_rehearsal() { # endpoint manifest mode
  S3_ENDPOINT_URL="$1" MANIFEST="$2" "$PY" "$SP/dropin_rehearsal.py" "$3"
}
