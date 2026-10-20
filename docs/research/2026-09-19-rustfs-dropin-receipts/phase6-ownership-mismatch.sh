#!/usr/bin/env bash
set -u
cd /tmp/claude-0/-home-user-lq-ai/a162043a-cd6a-5ef5-afd6-808f8ca801bb/scratchpad
source ./stores.sh
start_as() { # uid datadir logfile
  RUSTFS_ACCESS_KEY=lq_ai RUSTFS_SECRET_KEY=ci-smoke-minio-password RUSTFS_ADDRESS=127.0.0.1:19000 \
  RUSTFS_CONSOLE_ENABLE=true RUSTFS_CONSOLE_ADDRESS=127.0.0.1:19001 RUSTFS_OBS_LOGGER_LEVEL=info \
  setpriv --reuid="$1" --regid="$1" --clear-groups nohup "$SP/rustfs-bin/rustfs" server "$2" > "$3" 2>&1 &
  echo $! > "$SP/rustfs.pid"
}
health() { curl -sS --retry 12 --retry-delay 1 --retry-connrefused --retry-all-errors --max-time 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:19000/health 2>/dev/null || echo "none"; }
logscan() { python3 - "$1" <<'PY'
import json, sys
n = 0
for line in open(sys.argv[1]):
    try: d = json.loads(line)
    except Exception:
        s = line.strip()
        if s and any(w in s for w in ("ermission", "denied", "rror", "panic")): print("RAW  |", s[:170]); n += 1
        continue
    msg = d.get("message", ""); err = str(d.get("error", "")); blob = msg + err
    if d.get("level") == "ERROR" or any(w in blob for w in ("ermission", "denied", "EACCES", "read-only", "unwritable")):
        print(d.get("level"), "|", msg[:95], "|", err[:80]); n += 1
    if n >= 10: break
print(f"({n} matching lines shown)")
PY
}

echo "=== 6a: RustFS as uid 10001 on the ROOT-OWNED MinIO volume (the container's situation without a helper) ==="
rm -rf vol-uid; cp -a vol vol-uid; cp manifest.json manifest-p6.json
ls -ld vol-uid vol-uid/lq-ai-files vol-uid/.minio.sys | awk '{print "   ", $1, $3":"$4, $NF}'
start_as 10001 ./vol-uid logs/phase6a-uid10001-rootowned.log
echo "health: $(health)"
if kill -0 "$(cat rustfs.pid)" 2>/dev/null; then echo "process: running as uid $(ps -o uid= -p "$(cat rustfs.pid)" | tr -d ' ')"; else echo "process: EXITED (rc unknown)"; fi
echo "--- log scan ---"; logscan logs/phase6a-uid10001-rootowned.log
echo "--- READ through the api module ---"; run_rehearsal http://127.0.0.1:19000 manifest-p6.json verify 2>&1 | tail -3
echo "--- WRITE through the api module (mutate) ---"; run_rehearsal http://127.0.0.1:19000 manifest-p6.json mutate 2>&1 | grep -E "mutated|Error|error|InternalError|Traceback" | head -4
stop_rustfs
echo "--- on disk after 6a ---"; ls -a vol-uid | tr '\n' ' '; echo; ls -ld vol-uid/.rustfs.sys 2>/dev/null | awk '{print "    .rustfs.sys", $1, $3":"$4}'

echo; echo "=== 6b: same volume after chown -R 10001:10001 (what the helper service does), RustFS as uid 10001 ==="
chown -R 10001:10001 vol-uid; cp manifest.json manifest-p6.json
start_as 10001 ./vol-uid logs/phase6b-uid10001-chowned.log
echo "health: $(health)"
echo "--- log scan ---"; logscan logs/phase6b-uid10001-chowned.log
echo "--- READ ---"; run_rehearsal http://127.0.0.1:19000 manifest-p6.json verify 2>&1 | tail -2
echo "--- WRITE then READ ---"; run_rehearsal http://127.0.0.1:19000 manifest-p6.json mutate 2>&1 | grep -E "mutated|rror" | head -2; run_rehearsal http://127.0.0.1:19000 manifest-p6.json verify 2>&1 | tail -1
stop_rustfs
rm -rf vol-uid manifest-p6.json
echo; echo "leftover rustfs processes: $(pgrep -x rustfs | wc -l)"
