"""The skill-runner broker binds loopback unless explicitly opted in.

The broker holds container-engine access. Binding every interface by default
meant a direct or misconfigured run exposed it network-wide, guarded only by its
token (pen-test 2026-09-25, script_runner finding). The Compose overlay opts in
to 0.0.0.0 on its internal-only network via LQ_SCRIPT_BIND_HOST.
"""

from __future__ import annotations

import pytest

TOKEN = "t" * 32


@pytest.mark.unit
def test_make_server_defaults_to_loopback(runner_module) -> None:
    broker = runner_module.Broker({})
    server = runner_module.make_server(broker, TOKEN, port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


@pytest.mark.unit
def test_make_server_honors_explicit_all_interfaces(runner_module) -> None:
    broker = runner_module.Broker({})
    server = runner_module.make_server(broker, TOKEN, "0.0.0.0", 0)
    try:
        assert server.server_address[0] == "0.0.0.0"
    finally:
        server.server_close()


@pytest.mark.unit
def test_serve_passes_bind_host_through(runner_module, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    class _Stop(Exception):
        pass

    def fake_make_server(broker, token, host="127.0.0.1", port=8095):
        seen["host"] = host
        raise _Stop

    monkeypatch.setattr(runner_module, "make_server", fake_make_server)
    broker = runner_module.Broker({})
    with pytest.raises(_Stop):
        runner_module.serve(broker, TOKEN)
    assert seen["host"] == "127.0.0.1"
    with pytest.raises(_Stop):
        runner_module.serve(broker, TOKEN, "0.0.0.0")
    assert seen["host"] == "0.0.0.0"
