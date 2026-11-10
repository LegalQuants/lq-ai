"""Real Docker resolver regression using a disposable network and fake DNS."""

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("AIRGAP_DOCKER_TESTS") != "1", reason="opt in to disposable Docker tests"
)

# Test-only dependency; operators may use an already cached Python image.
IMAGE = os.environ.get("AIRGAP_DNS_TEST_IMAGE", "python:3.12-alpine")
SERVER = r"""
import socket, struct, threading
def response(data):
    with open('/tmp/queries', 'a') as f: f.write(data.hex() + '\n')
    end = 12
    while data[end]: end += data[end] + 1
    end += 5
    # Fake authoritative answer; no network forwarding and no public lookups.
    return data[:2] + struct.pack('!HHHHH', 0x8180, 1, 1, 0, 0) + data[12:end] + bytes.fromhex('c00c00010001000000010004c0000201')
def tcp():
    with socket.socket() as sock:
        sock.bind(('0.0.0.0', 53)); sock.listen()
        while True:
            client, _ = sock.accept()
            with client:
                size = struct.unpack('!H', client.recv(2))[0]
                data = b''
                while len(data) < size: data += client.recv(size - len(data))
                answer = response(data)
                client.sendall(struct.pack('!H', len(answer)) + answer)
threading.Thread(target=tcp, daemon=True).start()
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.bind(('0.0.0.0', 53))
    open('/tmp/ready', 'w').close()
    while True:
        data, client = sock.recvfrom(4096)
        sock.sendto(response(data), client)
"""


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Docker with bounded operations against test-owned resources only."""
    return subprocess.run(
        ["docker", *args], text=True, capture_output=True, check=check, timeout=120
    )


def compose(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Run Compose for the unique test project."""
    return subprocess.run(
        ["docker", "compose", *args],
        env=env,
        text=True,
        capture_output=True,
        check=True,
        timeout=120,
    )


def test_external_forwarding_disabled_and_service_dns_preserved(tmp_path: Path) -> None:
    token = uuid.uuid4().hex[:12]
    network, server = f"airgap-dns-test-{token}", f"airgap-dns-server-{token}"
    project = f"airgap-dns-{token}"
    env = dict(os.environ, COMPOSE_PROJECT_NAME=project)
    config = tmp_path / "compose.json"
    override = tmp_path / "dns.yml"
    env["COMPOSE_FILE"] = str(config)
    network_created = False
    compose_created = False
    try:
        docker("network", "create", network)
        network_created = True
        docker(
            "run", "-d", "--name", server, "--network", network, IMAGE, "python", "-u", "-c", SERVER
        )
        for _ in range(50):
            if docker("exec", server, "test", "-f", "/tmp/ready", check=False).returncode == 0:
                break
            time.sleep(0.1)
        else:
            pytest.fail("test DNS server did not start")
        upstream = docker(
            "inspect",
            server,
            "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
        ).stdout.strip()
        config.write_text(
            json.dumps(
                {
                    "services": {
                        "probe": {
                            "image": IMAGE,
                            "dns": [upstream],
                            "command": ["python", "-c", "import time; time.sleep(3600)"],
                        },
                        "postgres": {
                            "image": IMAGE,
                            "command": ["python", "-c", "import time; time.sleep(3600)"],
                        },
                    },
                    "networks": {"default": {"external": True, "name": network}},
                }
            )
        )
        compose_created = True
        compose(env, "up", "-d")
        # Before the fix, the embedded resolver really reaches the external DNS.
        compose(
            env,
            "exec",
            "-T",
            "probe",
            "python",
            "-c",
            "import socket; assert socket.gethostbyname('before-seal.invalid') == '192.0.2.1'",
        )
        before = docker("exec", server, "cat", "/tmp/queries").stdout
        assert before, "unsealed positive control never reached the fake upstream"
        subprocess.run(
            ["bash", str(HARNESS / "seal-dns.sh"), "configure", str(override)],
            env=env,
            check=True,
            capture_output=True,
        )
        env["COMPOSE_FILE"] = os.pathsep.join((str(config), str(override)))
        compose(env, "up", "-d", "--force-recreate")
        subprocess.run(
            ["bash", str(HARNESS / "seal-dns.sh"), "verify"],
            env=env,
            check=True,
            capture_output=True,
        )
        probe = compose(env, "ps", "-q", "probe").stdout.strip()
        # Use the identical UDP/TCP controls shipped in the full CI job.
        subprocess.run(
            ["docker", "exec", "-i", probe, "python", "-"],
            input=(HARNESS / "check-dns.py").read_text(),
            text=True,
            check=True,
            capture_output=True,
            timeout=60,
        )
        assert docker("exec", server, "cat", "/tmp/queries").stdout == before, (
            "sealed lookups reached the upstream DNS"
        )
        # Accidentally recreating one service from the base config must be caught.
        env["COMPOSE_FILE"] = str(config)
        compose(env, "up", "-d", "--force-recreate", "probe")
        env["COMPOSE_FILE"] = os.pathsep.join((str(config), str(override)))
        assert (
            subprocess.run(
                ["bash", str(HARNESS / "seal-dns.sh"), "verify"], env=env, capture_output=True
            ).returncode
            != 0
        )
    finally:
        if compose_created:
            # Only this unique project's containers; no volumes are created/deleted.
            subprocess.run(
                ["docker", "compose", "rm", "-sf"], env=env, capture_output=True, timeout=120
            )
        docker("rm", "-f", server, check=False)
        if network_created:
            docker("network", "rm", network, check=False)
