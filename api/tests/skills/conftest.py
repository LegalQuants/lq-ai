import hashlib
import importlib.util
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def runner_module():
    spec = importlib.util.spec_from_file_location("skill_broker", ROOT / "script_runner/broker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def real_runner(runner_module):
    image = os.environ.get("LQ_TEST_SCRIPT_IMAGE")
    probe = os.environ.get("LQ_TEST_PROBE_IMAGE")
    if not image or not probe:
        pytest.skip(
            "Requires reviewed disposable helper images; see script runner acceptance guide"
        )
    bundles = {}
    for key, folder, runtime, scripts in (
        ("built-in:saved-notes-demo", ROOT / "skills/saved-notes-demo", image, ["summarize_notes"]),
        (
            "test:probe",
            ROOT / "api/tests/fixtures/runner-probe",
            probe,
            ["probe", "stall", "flood"],
        ),
    ):
        files = [
            (p.relative_to(folder).as_posix(), p.read_text())
            for p in sorted((folder / "scripts").rglob("*"))
            if p.is_file()
        ]
        digest = hashlib.sha256(
            json.dumps(files, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        bundles[key] = {"image": runtime, "bundle_digest": digest, "scripts": scripts}
    broker = runner_module.Broker(
        bundles,
        os.environ.get("LQ_TEST_DOCKER_SOCKET", "/var/run/docker.sock"),
        instance="acceptance-563",
    )
    token = "disposable-acceptance-token-563-long-enough"
    server = runner_module.make_server(broker, token, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(
            broker=broker, url=f"http://127.0.0.1:{server.server_port}", token=token
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
