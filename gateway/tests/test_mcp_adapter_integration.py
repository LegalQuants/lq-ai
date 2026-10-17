"""Real-peer integration tests for MCPToolProviderAdapter (issue #525).

``test_mcp_adapter.py`` drives the adapter with a hand-written fake session, so
a rename of an attribute in the MCP SDK would leave it green. These tests start
a real MCP server (the SDK's own ``FastMCP``, see ``mcp_peer_server.py``) as a
subprocess and drive the adapter through the real client transport.

The SSRF guard stays live. The adapter is configured with the allowlisted
``https://mcp-peer.test/mcp`` and ``validate_egress_target`` runs unpatched;
only its DNS lookup (``egress._resolve_ips``) is stubbed to a public address,
as in the unit tests. The injected session factory then hands the real
``_default_session_factory()`` the peer's loopback URL, so the connect URL is
redirected only after the guard has accepted the configured one.

Every wait is bounded: the adapter times only ``initialize()`` itself, and the
gateway CI job has no timeout of its own.
"""

import json
import socket
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest

from app.config import ToolProviderConfig
from app.providers.tool import egress
from app.providers.tool.base import (
    ToolProviderError,
    ToolProviderHTTPError,
    ToolProviderNetworkError,
    ToolResult,
    ToolSpec,
)
from app.providers.tool.egress import EgressRefused
from app.providers.tool.mcp import MCPToolProviderAdapter, _default_session_factory

PEER_SCRIPT = Path(__file__).with_name("mcp_peer_server.py")
CONFIGURED_URL = "https://mcp-peer.test/mcp"
CONFIGURED_HOST = "mcp-peer.test"
PUBLIC_IP = "93.184.216.34"

START_ATTEMPT_BUDGET_S = 15.0  # per attempt; two attempts at most (bind race only)
READINESS_POLL_S = 0.1
TERMINATE_WAIT_S = 5.0
CALL_DEADLINE_S = 15.0  # every adapter call; the adapter bounds only initialize()

_BIND_ERROR_MARKERS = (
    "address already in use",
    "error while attempting to bind",
    "only one usage of each socket address",
)


@dataclass(frozen=True)
class PeerHandle:
    """A running peer: its loopback MCP endpoint."""

    url: str


@dataclass
class SessionShim:
    """Session factory that records each call, then connects to the real peer.

    The adapter hands it the configured https URL (after the SSRF guard has
    checked it); the shim passes the received headers unchanged to the real
    ``_default_session_factory()`` and points it at the peer.
    """

    peer_url: str
    urls: list[str] = field(default_factory=list)
    headers: list[dict[str, str] | None] = field(default_factory=list)

    @asynccontextmanager
    async def connect(self, url: str, headers: dict[str, str] | None) -> AsyncIterator[Any]:
        self.urls.append(url)
        self.headers.append(headers)
        async with _default_session_factory()(self.peer_url, headers) as session:
            yield session


@dataclass(frozen=True)
class Harness:
    adapter: MCPToolProviderAdapter
    shim: SessionShim


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_log(log_path: Path) -> str:
    return log_path.read_text(encoding="utf-8", errors="replace")


def _stop(proc: subprocess.Popen[bytes]) -> None:
    """terminate -> bounded wait -> kill -> bounded wait."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=TERMINATE_WAIT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=TERMINATE_WAIT_S)


class _PeerStartError(Exception):
    def __init__(self, message: str, *, bind_race: bool) -> None:
        super().__init__(message)
        self.bind_race = bind_race


def _start_peer_once(port: int, log_path: Path) -> subprocess.Popen[bytes]:
    """Start the peer and wait until it answers HTTP; raise _PeerStartError otherwise."""
    url = f"http://127.0.0.1:{port}/mcp"
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            [sys.executable, str(PEER_SCRIPT), str(port)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + START_ATTEMPT_BUDGET_S
        while time.monotonic() < deadline:
            exit_code = proc.poll()
            if exit_code is not None:
                text = _read_log(log_path)
                raise _PeerStartError(
                    f"MCP peer exited with code {exit_code} during start-up. Child log:\n{text}",
                    bind_race=any(marker in text.lower() for marker in _BIND_ERROR_MARKERS),
                )
            try:
                # Any HTTP response counts as ready; TCP accept alone does not.
                httpx.get(url, timeout=1.0, trust_env=False)
                return proc
            except httpx.TransportError:
                time.sleep(READINESS_POLL_S)
        raise _PeerStartError(
            f"MCP peer did not answer HTTP on {url} within {START_ATTEMPT_BUDGET_S}s. "
            f"Child log:\n{_read_log(log_path)}",
            bind_race=False,
        )
    except BaseException:
        _stop(proc)
        raise


@pytest.fixture(scope="module")
def mcp_peer(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PeerHandle]:
    """One real FastMCP peer per module. Sync on purpose: it never touches the
    event loop, and it never goes through the guarded adapter."""
    log_path = tmp_path_factory.mktemp("mcp_peer") / "peer.log"
    proc: subprocess.Popen[bytes] | None = None
    port = 0
    try:
        failure: _PeerStartError | None = None
        for _attempt in (1, 2):
            port = _free_port()
            failure = None
            try:
                proc = _start_peer_once(port, log_path)
                break
            except _PeerStartError as exc:
                failure = exc
                # Only a lost bind race is worth a second port; anything else is a real failure.
                if not exc.bind_race:
                    break
        if proc is None:
            # Raised outside the except block so the message is not repeated by chaining.
            pytest.fail(str(failure), pytrace=False)
        yield PeerHandle(url=f"http://127.0.0.1:{port}/mcp")
    finally:
        if proc is not None:
            _stop(proc)


def _build_harness(
    monkeypatch: pytest.MonkeyPatch,
    peer: PeerHandle,
    *,
    base_url: str = CONFIGURED_URL,
    auth: str = "none",
) -> Harness:
    # Loopback traffic must never go through an environment proxy.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    # Only DNS is stubbed; validate_egress_target itself runs unpatched.
    monkeypatch.setattr(egress, "_resolve_ips", lambda host: [PUBLIC_IP])
    shim = SessionShim(peer_url=peer.url)
    # model_validate: ``auth`` is an extra field of the config model, which mypy's
    # keyword-argument check does not know about.
    config = ToolProviderConfig.model_validate(
        {
            "name": "test-peer",
            "type": "mcp",
            "base_url": base_url,
            "egress_tier": 2,
            "allowlist": {"hosts": [CONFIGURED_HOST]},
            "auth": auth,
        }
    )
    adapter = MCPToolProviderAdapter.from_config(config, session_factory=shim.connect)
    return Harness(adapter=adapter, shim=shim)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, mcp_peer: PeerHandle) -> Harness:
    return _build_harness(monkeypatch, mcp_peer)


async def _list_tools(adapter: MCPToolProviderAdapter) -> dict[str, ToolSpec]:
    with anyio.fail_after(CALL_DEADLINE_S):
        specs = await adapter.list_tools()
    return {spec.name: spec for spec in specs}


async def _invoke(
    adapter: MCPToolProviderAdapter,
    tool: str,
    args: dict[str, Any],
    *,
    user_token: str | None = None,
) -> ToolResult:
    with anyio.fail_after(CALL_DEADLINE_S):
        return await adapter.invoke_tool(tool, args, request_id="req-525", user_token=user_token)


def _flags(spec: ToolSpec) -> tuple[bool, bool, bool]:
    return (spec.read_only, spec.destructive, spec.requires_confirmation)


# --- M1: the peer is real and the adapter reaches it with the guard live ------


@pytest.mark.integration
async def test_peer_is_reachable_through_the_real_transport(harness: Harness) -> None:
    with anyio.fail_after(CALL_DEADLINE_S):
        health = await harness.adapter.health_check()

    assert health.reachable is True
    assert health.error is None
    # The guard saw the configured https URL; only the connect target was redirected.
    assert harness.shim.urls == [CONFIGURED_URL]
    assert harness.shim.headers == [None]


# --- B1-B4: list_tools against the real server --------------------------------


@pytest.mark.integration
async def test_b1_session_initializes_and_lists_the_peers_tools(harness: Harness) -> None:
    tools = await _list_tools(harness.adapter)

    assert set(tools) == {"lookup_clause", "delete_clause", "annotate_clause", "explode"}
    assert harness.shim.urls == [CONFIGURED_URL]


@pytest.mark.integration
async def test_b2_parameters_come_from_the_real_input_schema(harness: Harness) -> None:
    tools = await _list_tools(harness.adapter)

    lookup = tools["lookup_clause"].parameters
    assert lookup != {"type": "object"}  # not the fallback
    assert lookup["type"] == "object"
    assert set(lookup["properties"]) == {"clause_id"}
    assert lookup["properties"]["clause_id"]["type"] == "string"
    assert lookup["required"] == ["clause_id"]
    assert set(tools["annotate_clause"].parameters["properties"]) == {"clause_id", "note"}


@pytest.mark.integration
async def test_b3_read_only_tool_needs_no_confirmation(harness: Harness) -> None:
    tools = await _list_tools(harness.adapter)

    assert _flags(tools["lookup_clause"]) == (True, False, False)


@pytest.mark.integration
async def test_b3_destructive_tool_requires_confirmation(harness: Harness) -> None:
    tools = await _list_tools(harness.adapter)

    assert _flags(tools["delete_clause"]) == (False, True, True)


@pytest.mark.integration
async def test_b4_unannotated_tool_defaults_to_requiring_confirmation(
    harness: Harness,
) -> None:
    tools = await _list_tools(harness.adapter)

    assert _flags(tools["annotate_clause"]) == (False, False, True)


# --- B5-B6: invoke_tool against the real server -------------------------------


@pytest.mark.integration
async def test_b5_succeeding_tool_returns_the_peers_content(harness: Harness) -> None:
    args = {"clause_id": "7.2"}
    result = await _invoke(harness.adapter, "lookup_clause", args)

    assert isinstance(result, ToolResult)
    assert result.provider == "test-peer"
    assert result.tool == "lookup_clause"
    text_blocks = [block for block in result.payload if block["type"] == "text"]
    assert [block["text"] for block in text_blocks] == [
        "Clause 7.2: governed by the laws of Ontario."
    ]
    assert result.bytes_out == len(json.dumps(args).encode("utf-8"))
    assert result.bytes_in == len(json.dumps(result.payload).encode("utf-8"))


@pytest.mark.integration
async def test_b6_failing_tool_raises_a_tool_error_not_a_session_error(
    harness: Harness,
) -> None:
    with pytest.raises(ToolProviderError) as caught:
        await _invoke(harness.adapter, "explode", {"reason": "boom"})

    error = caught.value
    assert error.message == "mcp tool returned an error"
    # A broken session must not be able to satisfy this test.
    assert not isinstance(error, ToolProviderNetworkError | ToolProviderHTTPError)
    content = error.details["content"]
    assert isinstance(content, list)
    texts = [block["text"] for block in content if block["type"] == "text"]
    assert any("peer tool failed on purpose: boom" in text for text in texts)


# --- G1: the SSRF guard is live in this harness --------------------------------


@pytest.mark.integration
async def test_g1_non_allowlisted_url_is_refused_before_any_session(
    monkeypatch: pytest.MonkeyPatch, mcp_peer: PeerHandle
) -> None:
    harness = _build_harness(monkeypatch, mcp_peer, base_url="https://not-allowed.test/mcp")

    with pytest.raises(EgressRefused):
        with anyio.fail_after(CALL_DEADLINE_S):
            await harness.adapter.list_tools()

    assert harness.shim.urls == []
    assert harness.shim.headers == []


# --- G2: a server redirect cannot carry a request off its origin -------------


@dataclass
class _Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


class _SinkHandler(BaseHTTPRequestHandler):
    """Records every request. It stands for a host the operator never allowlisted."""

    received: list[_Recorded]

    def _record(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.received.append(
            _Recorded(
                method=self.command,
                path=self.path,
                headers=dict(self.headers.items()),
                body=self.rfile.read(length),
            )
        )
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_DELETE = _record

    def log_message(self, format: str, *args: Any) -> None:
        pass


class _RedirectHandler(BaseHTTPRequestHandler):
    """Answers every request with a body-preserving 307 to another origin."""

    location: str

    def _redirect(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.send_response(307)
        self.send_header("Location", self.location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_DELETE = _redirect

    def log_message(self, format: str, *args: Any) -> None:
        pass


@contextmanager
def _serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=TERMINATE_WAIT_S)


@dataclass(frozen=True)
class RedirectPair:
    redirector_url: str
    sink_url: str
    received: list[_Recorded]


@pytest.fixture
def cross_origin_redirect() -> Iterator[RedirectPair]:
    """A server that redirects every request to a second origin, and that origin.

    Same host, different port: a different origin for the browser rule the MCP
    SDK and httpx both apply (scheme, host and port).
    """
    received: list[_Recorded] = []
    sink = type("Sink", (_SinkHandler,), {"received": received})
    with _serve(sink) as sink_port:
        sink_url = f"http://127.0.0.1:{sink_port}/mcp"
        redirect = type("Redirect", (_RedirectHandler,), {"location": sink_url})
        with _serve(redirect) as redirect_port:
            yield RedirectPair(
                redirector_url=f"http://127.0.0.1:{redirect_port}/mcp",
                sink_url=sink_url,
                received=received,
            )


@pytest.mark.integration
async def test_g2_cross_origin_redirect_is_not_followed(
    monkeypatch: pytest.MonkeyPatch, cross_origin_redirect: RedirectPair
) -> None:
    """GHSA-5h93-6whr-6q8j: mcp < 1.30.0 followed a server's cross-origin redirect.

    ``validate_egress_target`` checks only the configured URL, so a followed
    redirect sends the request to a host nobody allowlisted. On a 307 that
    request keeps its body: the JSON-RPC message, tool arguments included.
    httpx already drops ``Authorization`` on such a hop, so the body is the
    exposure; the test asserts that nothing at all reaches the second origin.
    """
    harness = _build_harness(
        monkeypatch, PeerHandle(url=cross_origin_redirect.redirector_url), auth="oauth"
    )

    # Broad on purpose: a followed redirect also ends in an error (the second
    # origin is no MCP server), and the assertion that matters must run first.
    with pytest.raises(ToolProviderError) as caught:
        await _invoke(
            harness.adapter,
            "lookup_clause",
            {"clause_id": "matter-confidential-7.2"},
            user_token="user-oauth-token",
        )

    assert cross_origin_redirect.received == []
    # The guard saw the configured URL, and the user's token was offered only there.
    assert harness.shim.urls == [CONFIGURED_URL]
    assert harness.shim.headers == [{"Authorization": "Bearer user-oauth-token"}]
    # The caller is told the server redirected, by status and host only.
    error = caught.value
    assert isinstance(error, ToolProviderHTTPError)
    assert error.upstream_status == 307
    assert cross_origin_redirect.sink_url not in error.message
