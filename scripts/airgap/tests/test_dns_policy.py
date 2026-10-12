"""Regress DNS configuration, acceptance captures and bridge rule ordering."""

import json
import os
import shutil
import socket
import struct
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]


@pytest.fixture
def tools(tmp_path: Path) -> dict[str, str]:
    """Stub Docker metadata and sudo; run the actual scripts and packet parser."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['network', 'inspect']:\n"
        " print('fc00:30::/64\\n172.30.0.0/16' if '.IPAM.Config' in args[-1] else 'abc123456789abcdef')\n"
        "elif 'config' in args: print(os.environ['TEST_COMPOSE'])\n"
        "elif 'ps' in args: print(os.environ.get('TEST_IDS', 'fixture-container'))\n"
        "elif args[0] == 'inspect': print(os.environ['TEST_INSPECT'])\n"
        "else: sys.exit(2)\n"
    )
    docker.chmod(0o755)
    sudo = bindir / "sudo"
    sudo.write_text('#!/bin/sh\nexec "$@"\n')
    sudo.chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}")
    env["TEST_COMPOSE"] = json.dumps({"services": {"api": {}, "init": {}, "future-service": {}}})
    env["TEST_INSPECT"] = json.dumps(
        [{"HostConfig": {"Dns": ["127.0.0.1"], "NetworkMode": "fixture_default"}}]
    )
    env["AIRGAP_ARTIFACT_DIR"] = str(tmp_path)
    return env


def run(script: str, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run a harness entry point as a subprocess."""
    return subprocess.run(
        ["bash", str(HARNESS / script), *args], env=env, text=True, capture_output=True
    )


def test_override_covers_init_and_future_services(tmp_path: Path, tools: dict[str, str]) -> None:
    output = tmp_path / "override.yml"
    result = run("seal-dns.sh", "configure", str(output), env=tools)
    assert result.returncode == 0, result.stderr
    policy = output.read_text()
    for name in ("api", "init", "future-service"):
        assert f'  "{name}":\n    dns: !override [127.0.0.1]' in policy


@pytest.mark.parametrize("mode", ["host", "container:other", "service:other"])
def test_shared_namespace_rejected(tmp_path: Path, tools: dict[str, str], mode: str) -> None:
    tools["TEST_COMPOSE"] = json.dumps({"services": {"api": {"network_mode": mode}}})
    assert (
        run("seal-dns.sh", "configure", str(tmp_path / "override.yml"), env=tools).returncode != 0
    )


def sealed_config(tools: dict[str, str]) -> None:
    """Install a merged policy configuration in the Docker stub."""
    tools["TEST_COMPOSE"] = json.dumps({"services": {"api": {"dns": ["127.0.0.1"]}}})


def test_actual_container_policy_verified(tools: dict[str, str]) -> None:
    sealed_config(tools)
    assert run("seal-dns.sh", "verify", env=tools).returncode == 0


@pytest.mark.parametrize("dns", [[], ["8.8.8.8"], ["127.0.0.1", "8.8.8.8"]])
def test_unsealed_container_rejected(tools: dict[str, str], dns: list[str]) -> None:
    sealed_config(tools)
    tools["TEST_INSPECT"] = json.dumps(
        [{"HostConfig": {"Dns": dns, "NetworkMode": "fixture_default"}}]
    )
    result = run("seal-dns.sh", "verify", env=tools)
    assert result.returncode != 0
    assert "without DNS isolation" in result.stderr


def test_missing_init_container_rejected(tools: dict[str, str]) -> None:
    sealed_config(tools)
    tools["TEST_IDS"] = ""
    assert run("seal-dns.sh", "verify", env=tools).returncode != 0


def test_omitted_override_rejected(tools: dict[str, str]) -> None:
    assert run("seal-dns.sh", "verify", env=tools).returncode != 0


def packet(
    destination: str, transport: str = "udp", port: int = 53, *, reply: bool = False
) -> bytes:
    """Build an Ethernet IPv4/IPv6 packet for real tcpdump filter evaluation."""
    ipv6 = ":" in destination
    family = socket.AF_INET6 if ipv6 else socket.AF_INET
    source = "fc00:30::2" if ipv6 else "172.30.0.2"
    if reply:
        source, destination = destination, source
    src, dst = socket.inet_pton(family, source), socket.inet_pton(family, destination)
    if transport == "udp":
        payload = struct.pack("!HHHH", 45000, port, 20, 0) + b"\x00" * 12
        protocol = 17
    else:
        payload = struct.pack("!HHIIBBHHH", 45000, port, 0, 0, 0x50, 2, 8192, 0, 0)
        protocol = 6
    if ipv6:
        header = struct.pack("!IHBB16s16s", 6 << 28, len(payload), protocol, 64, src, dst)
    else:
        header = struct.pack(
            "!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), 0, 0, 64, protocol, 0, src, dst
        )
    return b"\x00" * 12 + struct.pack("!H", 0x86DD if ipv6 else 0x800) + header + payload


def pcap(path: Path, packets: list[bytes]) -> None:
    """Write a classic Ethernet pcap without packet-generation dependencies."""
    data = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for frame in packets:
        data += struct.pack("<IIII", 1, 0, len(frame), len(frame)) + frame
    path.write_bytes(data)


@pytest.mark.parametrize(
    "destination", ["1.1.1.1", "10.200.0.53", "2606:4700:4700::1111", "fd00:dead::53"]
)
@pytest.mark.parametrize("transport", ["udp", "tcp"])
def test_dns_without_replies_fails(
    tmp_path: Path, tools: dict[str, str], destination: str, transport: str
) -> None:
    assert shutil.which("tcpdump"), "tcpdump required for capture regression tests"
    pcap(tmp_path / "sealed.pcap", [packet(destination, transport)])
    result = run("capture-egress.sh", "assert-clean", "sealed", env=tools)
    assert result.returncode != 0
    assert "DNS attempt(s) outside" in result.stderr
    assert (tmp_path / "sealed.dns-attempts.txt").exists()
    assert run("capture-egress.sh", "assert-dns-attempts", "sealed", env=tools).returncode == 0


def test_internal_dns_is_allowed(tmp_path: Path, tools: dict[str, str]) -> None:
    pcap(tmp_path / "sealed.pcap", [packet("172.30.0.53"), packet("fc00:30::53")])
    assert run("capture-egress.sh", "assert-clean", "sealed", env=tools).returncode == 0


def test_other_blocked_attempts_remain_inventory_only(
    tmp_path: Path, tools: dict[str, str]
) -> None:
    pcap(tmp_path / "sealed.pcap", [packet("1.1.1.1", "tcp", 443)])
    assert run("capture-egress.sh", "assert-clean", "sealed", env=tools).returncode == 0
    assert (tmp_path / "sealed.attempts.txt").exists()


def test_public_reply_still_fails(tmp_path: Path, tools: dict[str, str]) -> None:
    pcap(tmp_path / "sealed.pcap", [packet("1.1.1.1", "tcp", 443, reply=True)])
    assert run("capture-egress.sh", "assert-clean", "sealed", env=tools).returncode != 0


def test_empty_control_and_missing_capture_fail(tmp_path: Path, tools: dict[str, str]) -> None:
    pcap(tmp_path / "empty.pcap", [])
    assert run("capture-egress.sh", "assert-dns-attempts", "empty", env=tools).returncode != 0
    assert run("capture-egress.sh", "assert-clean", "missing", env=tools).returncode != 0


def test_bridge_dns_rules_precede_private_allowlist(tmp_path: Path, tools: dict[str, str]) -> None:
    bindir = Path(tools["PATH"].split(os.pathsep)[0])
    for name in ("iptables", "ip6tables"):
        binary = bindir / name
        binary.write_text(
            "#!/bin/sh\n"
            'printf "%s %s\\n" "$(basename "$0")" "$*" >> "$TEST_RULE_LOG"\n'
            'case "$1" in -C) exit 1 ;; esac\n'
        )
        binary.chmod(0o755)
    ip = bindir / "ip"
    ip.write_text("#!/bin/sh\nexit 0\n")
    ip.chmod(0o755)
    log = tmp_path / "rules.txt"
    tools["TEST_RULE_LOG"] = str(log)
    result = run("deny-egress.sh", "seal", env=tools)
    assert result.returncode == 0, result.stderr
    rules = log.read_text()
    assert rules.index("-d 172.30.0.0/16 -p udp --dport 53 -j RETURN") < rules.index(
        "-p udp --dport 53 -j DROP"
    )
    assert rules.index("-p tcp --dport 53 -j DROP") < rules.index("-d 10.0.0.0/8 -j RETURN")
    assert "ip6tables -I DOCKER-USER 1 -i br-abc123456789 -j LQ-AIRGAP" in rules
    assert "ip6tables -I DOCKER-USER 1 -j LQ-AIRGAP" not in rules
    assert run("deny-egress.sh", "unseal", env=tools).returncode == 0
    assert "ip6tables -D DOCKER-USER -i br-abc123456789 -j LQ-AIRGAP" in log.read_text()


def test_missing_ipv6_chain_fails_closed(tmp_path: Path, tools: dict[str, str]) -> None:
    bindir = Path(tools["PATH"].split(os.pathsep)[0])
    for name in ("iptables", "ip"):
        binary = bindir / name
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
    binary = bindir / "ip6tables"
    binary.write_text("#!/bin/sh\nexit 1\n")
    binary.chmod(0o755)
    result = run("deny-egress.sh", "seal", env=tools)
    assert result.returncode != 0
    assert "cannot seal an IPv6 network" in result.stderr
