#!/usr/bin/env bash
set -u
cd /tmp/claude-0/-home-user-lq-ai/a162043a-cd6a-5ef5-afd6-808f8ca801bb/scratchpad
source ./stores.sh
chmod o+x /tmp/claude-0 /tmp/claude-0/-home-user-lq-ai /tmp/claude-0/-home-user-lq-ai/a162043a-cd6a-5ef5-afd6-808f8ca801bb "$SP" "$SP/rustfs-bin"; chmod o+rx "$SP/rustfs-bin/rustfs"
start_as() { RUSTFS_ACCESS_KEY=lq_ai RUSTFS_SECRET_KEY=ci-smoke-minio-password RUSTFS_ADDRESS=127.0.0.1:19000 RUSTFS_CONSOLE_ENABLE=true RUSTFS_CONSOLE_ADDRESS=127.0.0.1:19001 RUSTFS_OBS_LOGGER_LEVEL=warn setpriv --reuid="$1" --regid="$1" --clear-groups nohup "$SP/rustfs-bin/rustfs" server "$2" > "$3" 2>&1 & echo $! > "$SP/rustfs.pid"; }
probe() { for ep in /health /health/live /health/ready /minio/health/live /minio/health/ready /minio/health/cluster; do
  body=$(curl -sS --max-time 3 -o /tmp/claude-0/-home-user-lq-ai/a162043a-cd6a-5ef5-afd6-808f8ca801bb/scratchpad/probe.body -w "%{http_code}" "http://127.0.0.1:19000$ep" 2>/dev/null || echo "---")
  printf "   %-22s %s  %s\n" "$ep" "$body" "$(head -c 110 "$SP/probe.body" 2>/dev/null | tr -d '\n')"; done; }
echo "=== stuck store (uid 10001 on root-owned volume) ==="
rm -rf vol-uid; cp -a vol vol-uid
start_as 10001 ./vol-uid logs/phase7a-stuck.log; curl -sS --retry 12 --retry-delay 1 --retry-connrefused --retry-all-errors --max-time 3 -o /dev/null http://127.0.0.1:19000/health 2>/dev/null; sleep 6
probe; echo "   S3 HeadBucket (signed): $(curl -sS --max-time 3 -o /dev/null -w '%{http_code}' -I http://127.0.0.1:19000/lq-ai-files 2>/dev/null)"
stop_rustfs
echo; echo "=== healthy store (same volume after chown -R 10001:10001) ==="
chown -R 10001:10001 vol-uid
start_as 10001 ./vol-uid logs/phase7b-healthy.log; curl -sS --retry 12 --retry-delay 1 --retry-connrefused --retry-all-errors --max-time 3 -o /dev/null http://127.0.0.1:19000/health 2>/dev/null; sleep 3
probe; echo "   S3 HeadBucket (unsigned): $(curl -sS --max-time 3 -o /dev/null -w '%{http_code}' -I http://127.0.0.1:19000/lq-ai-files 2>/dev/null)"
stop_rustfs; rm -rf vol-uid probe.body
echo; echo "leftover rustfs processes: $(pgrep -x rustfs | wc -l)"
