"""Reviewed acceptance probe; this file is never a production skill helper."""

import json
import os
import socket
from pathlib import Path

json.load(__import__("sys").stdin)
marker = Path("/work/marker")
fresh = not marker.exists()
marker.write_text("disposable")
try:
    Path("/bundle/scripts/changed.py").write_text("changed")
    readonly = False
except OSError:
    readonly = True
try:
    socket.create_connection(("198.51.100.1", 443), timeout=0.2).close()
    network = True
except OSError:
    network = False
status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
limits = {
    name: (Path("/sys/fs/cgroup") / name).read_text().strip()
    for name in ("memory.max", "memory.swap.max", "pids.max", "cpu.max")
}
print(
    json.dumps(
        {
            "uid": os.getuid(),
            "fresh": fresh,
            "readonly": readonly,
            "network": network,
            "caps": status["CapEff"].strip(),
            "no_new_privs": status["NoNewPrivs"].strip(),
            "engine_socket": Path("/var/run/docker.sock").exists(),
            "application": Path("/app").exists(),
            "env_keys": sorted(os.environ),
            "limits": limits,
        }
    )
)
