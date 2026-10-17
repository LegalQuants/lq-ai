"""Trusted PID 1 for one installed helper. No caller-supplied code or commands."""

import contextlib
import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path

MAX_OUTPUT = 65536


def main() -> None:
    request = json.loads(os.environ.pop("LQ_SCRIPT_REQUEST"))
    script = request["script"]
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", script):
        raise ValueError("invalid helper")
    root = Path("/bundle")
    files = []
    for path in sorted((root / "scripts").rglob("*")):
        if path.is_symlink():
            raise ValueError("invalid bundle")
        if path.is_file():
            files.append((path.relative_to(root).as_posix(), path.read_text("utf-8")))
    digest = hashlib.sha256(
        json.dumps(files, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != request["bundle_digest"]:
        print(json.dumps({"error": "bundle_changed"}))
        return
    target = root / "scripts" / f"{script}.py"
    if not target.is_file():
        raise ValueError("missing helper")
    # Only reviewed runtime paths enter argv/environment. Work is disposable;
    # no persisted file can become an import or executable on a later call.
    proc = subprocess.Popen(
        ["/usr/local/bin/python", "-I", "-B", str(target)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd="/work",
        env={"PATH": "/usr/local/bin:/usr/bin", "HOME": "/work"},
        start_new_session=True,
    )
    assert proc.stdin and proc.stdout and proc.stderr
    # Use a nonblocking pipe so a helper that never reads stdin cannot
    # stall PID 1 before its timeout starts.
    payload = json.dumps(request["inputs"], ensure_ascii=False, allow_nan=False).encode()
    os.set_blocking(proc.stdin.fileno(), False)
    selector = selectors.DefaultSelector()
    selector.register(proc.stdin, selectors.EVENT_WRITE, "stdin")
    selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
    selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    offset, deadline, error = 0, time.monotonic() + 10, None
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                error = "script_timeout"
                break
            for key, _ in selector.select(timeout=0.1):
                if key.data == "stdin":
                    try:
                        offset += os.write(key.fd, payload[offset : offset + 4096])
                    except BrokenPipeError:
                        offset = len(payload)
                    if offset == len(payload):
                        selector.unregister(key.fileobj)
                        proc.stdin.close()
                    continue
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output[key.data].extend(chunk)
                if sum(map(len, output.values())) > MAX_OUTPUT:
                    error = "output_limit"
                    break
            if error:
                break
        if not error:
            try:
                proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                error = "script_timeout"
    finally:
        # Kill descendants even when the main helper returned successfully.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        selector.close()
    if error:
        print(json.dumps({"error": error}))
    else:
        print(
            json.dumps(
                {
                    "stdout": output["stdout"].decode("utf-8", errors="replace"),
                    "stderr": output["stderr"].decode("utf-8", errors="replace"),
                    "exit_code": proc.returncode,
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"error": "script_failed"}))
