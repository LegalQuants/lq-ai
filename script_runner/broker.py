"""Private authenticated broker. Only this trusted process has engine access.

No third-party dependencies, image pulls, host execution or caller-supplied
container configuration. Operator config pins helper bundles to immutable images.
"""

import hmac
import http.client
import json
import logging
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

MAX_BODY = 131072
MAX_REPLY = 524288
DIGEST = re.compile(r"^[0-9a-f]{64}$")
IMAGE = re.compile(r"^(?:sha256:[0-9a-f]{64}|[^\s]+@sha256:[0-9a-f]{64})$")


class EngineConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=15)
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class Broker:
    def __init__(
        self,
        bundles: dict[str, Any],
        socket_path: str = "/var/run/docker.sock",
        instance: str = "lq-skills",
    ) -> None:
        self.bundles, self.socket_path = bundles, socket_path
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", instance):
            raise ValueError("Invalid runner instance name")
        self.instance = instance
        self.slots = threading.BoundedSemaphore(2)
        for key, value in bundles.items():
            if (
                not isinstance(key, str)
                or not isinstance(value, dict)
                or set(value) != {"image", "bundle_digest", "scripts"}
                or not isinstance(value["image"], str)
                or not IMAGE.fullmatch(value["image"])
                or not isinstance(value["bundle_digest"], str)
                or not DIGEST.fullmatch(value["bundle_digest"])
                or not isinstance(value["scripts"], list)
                or not 1 <= len(value["scripts"]) <= 8
                or any(
                    not isinstance(s, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", s)
                    for s in value["scripts"]
                )
            ):
                raise ValueError("Invalid approved bundle configuration")

    def engine(
        self, method: str, path: str, body: Any = None, *, missing_ok: bool = False
    ) -> bytes:
        conn = EngineConnection(self.socket_path)
        try:
            conn.request(
                method,
                "/v1.45" + path,
                body=json.dumps(body) if body is not None else None,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            data = response.read(MAX_REPLY + 1)
            if response.status == 404 and missing_ok:
                return b""
            if len(data) > MAX_REPLY or response.status >= 300:
                raise ValueError("Engine operation failed")
            return data
        finally:
            conn.close()

    def reap_stale(self) -> None:
        """Remove only this broker's expired jobs, including after a restart."""
        query = urlencode(
            {
                "all": "1",
                "filters": json.dumps(
                    {
                        "label": [
                            "lq.skill-job=1",
                            "lq.skill-runner=" + self.instance,
                        ]
                    }
                ),
            }
        )
        containers = json.loads(self.engine("GET", "/containers/json?" + query))
        for container in containers:
            if (
                re.fullmatch(r"[0-9a-f]{64}", container["Id"])
                and container["Created"] < time.time() - 90
            ):
                self.engine("DELETE", f"/containers/{container['Id']}?force=1&v=1", missing_ok=True)

    def run(self, request: Any) -> dict[str, Any]:
        if (
            not isinstance(request, dict)
            or set(request) != {"key", "bundle_digest", "script", "inputs"}
            or not isinstance(request["key"], str)
            or not isinstance(request["inputs"], dict)
        ):
            return {"error": "invalid_request"}
        approved = self.bundles.get(request["key"])
        if (
            approved is None
            or request["bundle_digest"] != approved["bundle_digest"]
            or request["script"] not in approved["scripts"]
        ):
            return {"error": "script_not_enabled"}
        try:
            if (
                len(json.dumps(request["inputs"], ensure_ascii=False, allow_nan=False).encode())
                > 65536
            ):
                return {"error": "invalid_request"}
        except (ValueError, TypeError, RecursionError):
            return {"error": "invalid_request"}
        if not self.slots.acquire(blocking=False):
            return {"error": "runner_busy"}
        name = "lq-skill-job-" + uuid4().hex
        try:
            # An image is selected exclusively from the operator's map. No binds,
            # devices, engine socket, credentials, ports, shared namespaces or
            # caller-selected environment/command are accepted.
            config = {
                "Image": approved["image"],
                "User": "65534:65534",
                "Entrypoint": ["/usr/local/bin/python", "-I", "-B", "/runner/launch.py"],
                "Cmd": [],
                "WorkingDir": "/work",
                "NetworkDisabled": True,
                "Env": [
                    "LQ_SCRIPT_REQUEST=" + json.dumps(request, ensure_ascii=False, allow_nan=False)
                ],
                "Labels": {"lq.skill-job": "1", "lq.skill-runner": self.instance},
                "HostConfig": {
                    "NetworkMode": "none",
                    "ReadonlyRootfs": True,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "Memory": 268435456,
                    "MemorySwap": 268435456,
                    "NanoCpus": 1000000000,
                    "PidsLimit": 32,
                    "Tmpfs": {"/work": "rw,noexec,nosuid,nodev,size=16777216,mode=1777"},
                    "Ulimits": [{"Name": "nofile", "Soft": 64, "Hard": 64}],
                    "LogConfig": {
                        "Type": "json-file",
                        "Config": {"max-size": "1m", "max-file": "1"},
                    },
                },
            }
            created = json.loads(self.engine("POST", "/containers/create?name=" + name, config))
            if created.get("Warnings"):
                # In particular, do not run when the daemon cannot apply a
                # requested resource/isolation control (e.g. rootless cgroups).
                return {"error": "runner_unavailable"}
            self.engine("POST", f"/containers/{name}/start")
            result = json.loads(
                self.engine("POST", f"/containers/{name}/wait?condition=not-running")
            )
            if result.get("StatusCode") != 0:
                return {"error": "script_failed"}
            logs = self.engine("GET", f"/containers/{name}/logs?stdout=1&stderr=0")
            # Docker non-TTY logs contain 8-byte multiplex headers.
            chunks = bytearray()
            while logs:
                if len(logs) < 8:
                    raise ValueError("Invalid execution output")
                size = int.from_bytes(logs[4:8], "big")
                if size > len(logs) - 8:
                    raise ValueError("Invalid execution output")
                chunks.extend(logs[8 : 8 + size])
                logs = logs[8 + size :]
            return json.loads(chunks)
        except (OSError, ValueError, http.client.HTTPException):
            return {"error": "runner_unavailable"}
        finally:
            try:
                # Creation may have succeeded even if its response was lost.
                self.engine("DELETE", f"/containers/{name}?force=1&v=1", missing_ok=True)
            except (OSError, ValueError, http.client.HTTPException):
                raise RuntimeError("Execution cleanup failed") from None
            finally:
                self.slots.release()


def make_server(
    broker: Broker, token: str, host: str = "0.0.0.0", port: int = 8095
) -> ThreadingHTTPServer:
    if len(token) < 32:
        raise ValueError("Runner authentication token must contain at least 32 characters")

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(20)

        def log_message(self, *_args: Any) -> None:
            pass

        def reply(self, status: int, data: dict[str, Any]) -> None:
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self.reply(200 if self.path == "/health" else 404, {"status": "ready"})

        def do_POST(self) -> None:
            if not hmac.compare_digest(
                self.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()
            ):
                self.reply(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.path != "/run" or not 0 < length <= MAX_BODY:
                    self.reply(400, {"error": "invalid_request"})
                    return
                result = broker.run(json.loads(self.rfile.read(length)))
                self.reply(200, result)
            except (ValueError, OSError, RuntimeError, RecursionError):
                self.reply(503, {"error": "runner_unavailable"})

    return ThreadingHTTPServer((host, port), Handler)


def serve(broker: Broker, token: str) -> None:
    server = make_server(broker, token)
    stopped = threading.Event()

    def maintain() -> None:
        while not stopped.is_set():
            try:
                broker.reap_stale()
            except (OSError, ValueError, http.client.HTTPException):
                logging.warning("Runner cleanup unavailable")
            stopped.wait(30)

    threading.Thread(target=maintain, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        stopped.set()
        server.server_close()


if __name__ == "__main__":
    configuration = json.loads(
        Path(os.environ.get("LQ_SCRIPT_BUNDLES", "/config/bundles.json")).read_text()
    )
    serve(
        Broker(configuration, instance=os.environ.get("LQ_SCRIPT_INSTANCE", "lq-skills")),
        os.environ.get("LQ_SCRIPT_TOKEN", ""),
    )
