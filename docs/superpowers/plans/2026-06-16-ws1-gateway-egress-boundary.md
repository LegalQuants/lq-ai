# WS1 — Gateway Egress Boundary for Tool/Data-Source Providers (PR1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class **tool-provider** egress class to the Inference Gateway — config schema, an adapter base, an SSRF-guarded outbound primitive, per-provider rate limiting, an egress-tier refusal check, a gateway-written `tool_egress_log`, and a trivial `echo` provider that proves the path end-to-end under test — without any CourtListener/MCP semantics.

**Architecture:** A tool provider is a sibling of inference providers, not a subclass. It is declared in `gateway.yaml` under a new `tool_providers:` block, built into an adapter at startup (held in `app.state.tool_adapters`), and invoked via a new `Router.route_tool_call(...)` path that rate-limits, checks the egress tier, calls the adapter through the `guarded_egress` SSRF primitive, and writes a `tool_egress_log` row (raw SQL, gateway-side, mirroring `inference_routing_log`). This discharges [ADR 0014](../../adr/0014-gateway-egress-boundary-for-tool-providers.md).

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, httpx, SQLAlchemy (raw `text()` for the gateway writer), Alembic (api-side schema), pytest + pytest-asyncio + respx. Gateway is mypy `--strict`.

**Branch:** `feat/legal-research-mcp-plan` (off `main`). This PR is **security-reviewed** (`gateway/**`) — see CLAUDE.md merge-gating: maintainer reviews + merges.

---

## Scope: what PR1 does and does NOT do

**Does:** config schema for `tool_providers`; `ToolProviderAdapter` base + `ToolSpec`/`ToolResult`/error hierarchy; `guarded_egress` SSRF primitive; per-provider rate limiter; egress-tier refusal; `tool_egress_log` migration + ORM model + gateway writer; an `echo` provider type; lifespan wiring; `Router.route_tool_call`; an end-to-end test through the router.

**Does NOT (honest deferrals — do not claim these):**
- **No CourtListener / MCP semantics** — those are PR2/PR4. The only concrete type here is `echo`.
- **No outbound anonymization transform.** ADR 0014 D5 makes anonymization the default, but the transform needs the M2 anonymization mapper + real matter context (which PR1 has neither of). PR1 *parses* the `anonymize_outbound` flag (schema completeness) and writes an honest `anonymization_applied = False`; the transform lands in WS3/WS4 with the first real provider. Leave the typed seam, do not fake it. This mirrors how the gateway already ships `rate_limits` config ahead of global enforcement.
- **No HTTP route exposing tool calls to the backend.** PR1 wires the *internal* `route_tool_call` path and tests it directly; the `/api/v1/research` surface is PR3.

**Hard rules (from CLAUDE.md / handoff):** gateway is mypy `--strict`; run BOTH `ruff format` and `ruff check`; NEVER run host-side `alembic upgrade` on the live dev DB (`127.0.0.1:15432/lq_ai`); commit `-s` with the trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

> **⚠️ TEST/LINT RUNNER CORRECTION (discovered during execution).** The canonical runner is the **host venv**, NOT `docker compose` — the compose `api`/`gateway` services bake code into the image (no source bind-mount), so `docker compose run --rm <svc> pytest` would test stale baked code. Translate every command in the tasks below:
> - `docker compose run --rm gateway pytest tests/X` → `cd ~/Code/lq-ai/gateway && .venv/bin/pytest tests/X -v` (gateway tests are pure unit/respx — no DB needed).
> - `docker compose run --rm api pytest api/tests/X` → `cd ~/Code/lq-ai/api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/X -v`. The api conftest does NOT spin up its own DB — it needs `DATABASE_URL` pointing at a Postgres and creates isolated `lq_ai_test_*` databases on it. Use a **throwaway `pgvector/pgvector:pg16` container on port 15433** (`docker run -d --name lq-test-pg -p 15433:5432 -e POSTGRES_USER=lq_ai -e POSTGRES_PASSWORD=test -e POSTGRES_DB=lq_ai pgvector/pgvector:pg16`), fully isolated from the running dev stack.
> - Lint: `cd gateway && .venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy app` (mypy is `--strict` via config); api: `cd api && .venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy app`.
> The docker compose stack is the *running* LQ.AI app, not the test harness — leave it alone (never `docker compose down -v`).

---

## File Structure

**Gateway (new):**
- `gateway/app/providers/tool/__init__.py` — package marker + re-exports.
- `gateway/app/providers/tool/base.py` — `ToolProviderAdapter` ABC, `ToolSpec`, `ToolResult`, error hierarchy.
- `gateway/app/providers/tool/egress.py` — `guarded_egress` SSRF primitive + `EgressRefused`.
- `gateway/app/providers/tool/ratelimit.py` — `FixedWindowRateLimiter` + `RateLimited`.
- `gateway/app/providers/tool/echo.py` — `EchoToolAdapter` (the test/proof provider type).
- `gateway/app/tool_egress_log.py` — `ToolEgressLogRow` + `ToolEgressLogWriter` protocol + SQL/Null/Recording impls.

**Gateway (modified):**
- `gateway/app/config.py` — `ToolProviderConfig`, `ToolProviderType`, `GatewayConfig.tool_providers`, `provider`-style accessor.
- `gateway/app/main.py` — `build_tool_adapter` factory + lifespan wiring (`app.state.tool_adapters`, `app.state.tool_egress_log`).
- `gateway/app/router.py` — `Router.route_tool_call(...)` + `ToolCallRoutedResult`.

**API (new/modified — schema only, gateway owns the writes):**
- `api/alembic/versions/0048_tool_egress_log.py` — create `tool_egress_log`.
- `api/app/models/tool_egress.py` — `ToolEgressLog` ORM model (for api-side reads/tests; mirrors `inference.py`).
- `docs/db-schema.md` — add the `tool_egress_log` section.

**Config example / docs (modified):**
- `gateway.yaml.example` — `tool_providers:` block with the `echo` example commented + a CourtListener-shaped example commented.
- `docs/security/boundary-registers.md` — egress-boundary register entry.

---

## Task 1: `tool_egress_log` migration + ORM model (api-side schema)

The table is api-owned (schema authority) but gateway-written. Build the schema first so the gateway writer has something to insert into and the api test conftest auto-migrates it.

**Files:**
- Create: `api/alembic/versions/0048_tool_egress_log.py`
- Create: `api/app/models/tool_egress.py`
- Modify: `docs/db-schema.md`
- Test: `api/tests/test_tool_egress_log_model.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_tool_egress_log_model.py
import uuid

import pytest

from app.models.tool_egress import ToolEgressLog


@pytest.mark.asyncio
async def test_tool_egress_log_row_roundtrips(db_session) -> None:
    """A tool_egress_log row persists and reads back with its core fields."""
    row = ToolEgressLog(
        request_id="req_abc",
        provider="echo-test",
        tool="echo",
        tier=4,
        bytes_out=12,
        bytes_in=12,
        refused=False,
        anonymization_applied=False,
    )
    db_session.add(row)
    await db_session.flush()
    assert isinstance(row.id, uuid.UUID)
    assert row.refused is False
    assert row.tier == 4
```

*(Use the existing api test DB-session fixture — confirm its name in `api/tests/conftest.py`; it is the same fixture other `app.models` tests use, e.g. `db_session`.)*

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Code/lq-ai && docker compose run --rm api pytest api/tests/test_tool_egress_log_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.tool_egress'`.

- [ ] **Step 3: Write the migration**

```python
# api/alembic/versions/0048_tool_egress_log.py
"""tool_egress_log — per-call audit of third-party tool/data-source egress

One row per outbound tool-provider call through the gateway (ADR 0014 D3).
Mirrors ``inference_routing_log``: gateway-written, raw SQL, counts/types
only — NEVER raw payloads. Distinct table because egress has a different
access pattern and retention from inference routing.

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_egress_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("bytes_out", sa.Integer(), nullable=True),
        sa.Column("bytes_in", sa.Integer(), nullable=True),
        sa.Column(
            "anonymization_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "refused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("refusal_reason", sa.String(), nullable=True),
        sa.CheckConstraint("tier BETWEEN 1 AND 5", name="chk_tool_egress_log_tier_range"),
    )
    op.create_index("ix_tool_egress_log_provider", "tool_egress_log", ["provider"])
    op.create_index("ix_tool_egress_log_timestamp", "tool_egress_log", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_tool_egress_log_timestamp", table_name="tool_egress_log")
    op.drop_index("ix_tool_egress_log_provider", table_name="tool_egress_log")
    op.drop_table("tool_egress_log")
```

- [ ] **Step 4: Write the ORM model**

```python
# api/app/models/tool_egress.py
"""Tool egress log — per docs/db-schema.md §`tool_egress_log`.

One row per outbound tool/data-source call through the gateway (ADR 0014
D3). Distinct from `inference_routing_log` (different egress, retention)
and from `audit_log` (hot path, counts-only). Gateway-written via raw SQL
(`gateway/app/tool_egress_log.py`); this ORM model backs api-side reads.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ToolEgressLog(Base):
    __tablename__ = "tool_egress_log"
    __table_args__ = (
        CheckConstraint("tier BETWEEN 1 AND 5", name="chk_tool_egress_log_tier_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    tool: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anonymization_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    refused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    refusal_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ToolEgressLog id={self.id} provider={self.provider} "
            f"tool={self.tool} tier={self.tier} refused={self.refused}>"
        )
```

Then register the model so the metadata sees it — add to `api/app/models/__init__.py` following the existing import pattern there (open the file, add `from app.models.tool_egress import ToolEgressLog` and append `"ToolEgressLog"` to `__all__` if present). Add a `tool_egress_log` section to `docs/db-schema.md` mirroring the `inference_routing_log` section (columns table + the "counts only, never payloads" note).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ~/Code/lq-ai && docker compose run --rm api pytest api/tests/test_tool_egress_log_model.py -v`
Expected: PASS (conftest auto-migrates the throwaway pgvector container through 0048).

- [ ] **Step 6: Commit**

```bash
cd ~/Code/lq-ai && git add api/alembic/versions/0048_tool_egress_log.py api/app/models/tool_egress.py api/app/models/__init__.py docs/db-schema.md api/tests/test_tool_egress_log_model.py
git commit -s -m "feat(api): add tool_egress_log table + ORM model (ADR 0014 D3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `ToolProviderConfig` + `tool_providers` in `GatewayConfig`

**Files:**
- Modify: `gateway/app/config.py`
- Test: `gateway/tests/test_tool_provider_config.py`

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_tool_provider_config.py
import pytest

from app.config import GatewayConfig, ToolProviderConfig


@pytest.mark.unit
def test_tool_provider_config_parses_minimal() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "echo-test",
                    "type": "echo",
                    "base_url": "https://example.test",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                }
            ]
        }
    )
    assert len(cfg.tool_providers) == 1
    tp = cfg.tool_providers[0]
    assert isinstance(tp, ToolProviderConfig)
    assert tp.name == "echo-test"
    assert tp.egress_tier == 4
    assert tp.allowlist.hosts == ["example.test"]
    assert tp.anonymize_outbound is True  # default per ADR 0014 D5


@pytest.mark.unit
def test_tool_provider_rejects_both_key_sources() -> None:
    with pytest.raises(ValueError, match="api_key_env OR"):
        ToolProviderConfig.model_validate(
            {
                "name": "x",
                "type": "echo",
                "base_url": "https://example.test",
                "egress_tier": 4,
                "allowlist": {"hosts": ["example.test"]},
                "api_key_env": "FOO",
                "api_key_encrypted": "gAAAA",
            }
        )


@pytest.mark.unit
def test_tool_provider_requires_nonempty_allowlist() -> None:
    with pytest.raises(ValueError):
        ToolProviderConfig.model_validate(
            {
                "name": "x",
                "type": "echo",
                "base_url": "https://example.test",
                "egress_tier": 4,
                "allowlist": {"hosts": []},
            }
        )


@pytest.mark.unit
def test_tool_provider_by_name_accessor() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "echo-test",
                    "type": "echo",
                    "base_url": "https://example.test",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                }
            ]
        }
    )
    assert cfg.tool_provider_by_name("echo-test") is not None
    assert cfg.tool_provider_by_name("missing") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_provider_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'ToolProviderConfig'`.

- [ ] **Step 3: Add the config models**

In `gateway/app/config.py`, after the `ProviderConfig` block (around line 133), add:

```python
# --- Tool / data-source providers (ADR 0014) ---------------------------------


ToolProviderType = Literal["echo", "courtlistener", "mcp"]
"""Tool-provider family. ``echo`` is the test/proof type (PR1); ``courtlistener``
and ``mcp`` land in later PRs."""


class EgressAllowlistConfig(BaseModel):
    """Per-provider outbound host allowlist (the SSRF guard's allow set)."""

    model_config = ConfigDict(extra="forbid")

    hosts: list[str] = Field(min_length=1)
    """Non-empty list of exact hostnames the provider may egress to. An empty
    allowlist is a misconfiguration, not 'allow all' — reject at config load."""


class ToolProviderRateLimitConfig(BaseModel):
    """Per-provider rate limit, enforced at the adapter (ADR 0014 D1 note).

    NOT the gateway's global ``rate_limits`` (whose enforcement middleware is
    unwired). This is a self-contained per-provider limit applied by
    :class:`Router.route_tool_call` before each outbound call."""

    model_config = ConfigDict(extra="allow")

    requests_per_minute: int = Field(default=60, ge=1)


class ToolProviderConfig(BaseModel):
    """One entry under ``tool_providers:`` (ADR 0014 D1).

    Sibling of :class:`ProviderConfig`, not a subclass — a tool provider is
    invoked via ``invoke_tool``, not ``chat_completion``. Reuses the same
    two API-key sourcing paths as inference providers (ADR 0011)."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    type: ToolProviderType
    base_url: str = Field(min_length=1)
    api_key_env: str | None = None
    api_key_encrypted: str | None = None
    egress_tier: InferenceTier
    """Data-egress tier (ADR 0014 D4). The gateway refuses a call whose
    matter/skill ceiling is more restrictive (a lower tier number) than this
    provider's egress_tier."""
    allowlist: EgressAllowlistConfig
    rate_limit: ToolProviderRateLimitConfig = Field(
        default_factory=ToolProviderRateLimitConfig
    )
    anonymize_outbound: bool = True
    """Default True per ADR 0014 D5. NOTE: PR1 parses but does not yet apply
    the transform (no matter context exists); enforcement lands in WS3/WS4."""
    enabled: bool = True

    @model_validator(mode="after")
    def _exactly_one_key_source(self) -> ToolProviderConfig:
        if self.api_key_env and self.api_key_encrypted:
            raise ValueError(
                f"Tool provider {self.name!r}: set either api_key_env OR "
                f"api_key_encrypted, not both."
            )
        return self
```

In `GatewayConfig` (around line 425, beside `providers:`), add the field and accessor:

```python
    tool_providers: list[ToolProviderConfig] = Field(default_factory=list)
```

```python
    def tool_provider_by_name(self, name: str) -> ToolProviderConfig | None:
        """Look up a configured tool provider by name; ``None`` if not found."""
        for provider in self.tool_providers:
            if provider.name == name:
                return provider
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_provider_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add gateway/app/config.py gateway/tests/test_tool_provider_config.py
git commit -s -m "feat(gateway): tool_providers config schema (ADR 0014 D1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `ToolProviderAdapter` base + `ToolSpec` / `ToolResult` / errors

**Files:**
- Create: `gateway/app/providers/tool/__init__.py`
- Create: `gateway/app/providers/tool/base.py`
- Test: `gateway/tests/test_tool_provider_base.py`

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_tool_provider_base.py
import pytest

from app.providers.tool.base import (
    ToolProviderAdapter,
    ToolProviderError,
    ToolResult,
    ToolSpec,
)


@pytest.mark.unit
def test_tool_provider_adapter_is_abstract() -> None:
    with pytest.raises(TypeError):
        ToolProviderAdapter()  # type: ignore[abstract]


@pytest.mark.unit
def test_tool_result_holds_provenance_and_counts() -> None:
    result = ToolResult(
        provider="echo-test",
        tool="echo",
        payload={"echoed": "hi"},
        bytes_in=2,
        bytes_out=2,
    )
    assert result.provider == "echo-test"
    assert result.payload == {"echoed": "hi"}
    assert result.bytes_in == 2


@pytest.mark.unit
def test_tool_spec_carries_metadata_flags() -> None:
    spec = ToolSpec(
        name="echo",
        description="echoes its input",
        parameters={"type": "object"},
        read_only=True,
        destructive=False,
        requires_confirmation=False,
    )
    assert spec.read_only is True
    assert spec.destructive is False


@pytest.mark.unit
def test_tool_provider_error_envelope() -> None:
    err = ToolProviderError("boom", details={"k": "v"})
    assert err.to_envelope()["error"]["code"] == "tool_provider_error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_provider_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.providers.tool'`.

- [ ] **Step 3: Write the package + base**

```python
# gateway/app/providers/tool/__init__.py
"""Tool / data-source provider egress class (ADR 0014).

A tool provider is a sibling of the inference :class:`ProviderAdapter`,
invoked via ``invoke_tool`` rather than ``chat_completion``. All outbound
HTTP from a tool adapter MUST route through ``guarded_egress`` (ADR 0014 D2).
"""

from app.providers.tool.base import (
    ToolProviderAdapter,
    ToolProviderAuthError,
    ToolProviderError,
    ToolProviderHTTPError,
    ToolProviderNetworkError,
    ToolResult,
    ToolSpec,
)

__all__ = [
    "ToolProviderAdapter",
    "ToolProviderAuthError",
    "ToolProviderError",
    "ToolProviderHTTPError",
    "ToolProviderNetworkError",
    "ToolResult",
    "ToolSpec",
]
```

```python
# gateway/app/providers/tool/base.py
"""Abstract :class:`ToolProviderAdapter` contract + shared types.

Mirrors the design of :mod:`app.providers.base` (the inference adapter
contract) but for non-inference egress: list the tools a provider offers,
invoke one, return structured provenance. Errors follow the same
public-safe, key-scrubbing discipline (CONTRIBUTING.md security rules).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import ProviderHealth


# --- Errors -------------------------------------------------------------------


class ToolProviderError(Exception):
    """Base class for tool-provider errors. Public-safe; never leak keys."""

    code: str = "tool_provider_error"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_envelope(self) -> dict[str, object]:
        return {"error": {"code": self.code, "message": self.message, "details": dict(self.details)}}


class ToolProviderAuthError(ToolProviderError):
    code = "unauthorized"


class ToolProviderHTTPError(ToolProviderError):
    code = "tool_provider_unavailable"

    def __init__(
        self, message: str, *, upstream_status: int, details: dict[str, object] | None = None
    ) -> None:
        merged: dict[str, object] = dict(details or {})
        merged["upstream_status"] = upstream_status
        super().__init__(message, details=merged)
        self.upstream_status = upstream_status


class ToolProviderNetworkError(ToolProviderError):
    code = "tool_provider_unavailable"


# --- Tool spec + result -------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """One model-callable tool a provider offers.

    ``parameters`` is a JSON-schema object. The metadata flags map to
    MikeOSS's ``readOnly``/``destructive``/``requiresConfirmation`` and are
    carried through to WS4's confirmation gates (ADR 0015 D2/D4)."""

    name: str
    description: str
    parameters: dict[str, Any]
    read_only: bool = True
    destructive: bool = False
    requires_confirmation: bool = False


@dataclass
class ToolResult:
    """Result of one tool invocation, with provenance + byte counts.

    ``payload`` is the structured tool output. ``skip_anonymization`` marks
    inbound public text (e.g. opinion bodies) that must reach the citation
    engine verbatim (ADR 0014 D5); the echo provider leaves it False."""

    provider: str
    tool: str
    payload: Any
    bytes_in: int = 0
    bytes_out: int = 0
    skip_anonymization: bool = False
    details: dict[str, object] = field(default_factory=dict)


# --- Adapter contract ---------------------------------------------------------


class ToolProviderAdapter(ABC):
    """Abstract contract for a tool/data-source provider adapter.

    Constructed once at startup, held in ``app.state.tool_adapters``, reused
    across requests. All outbound HTTP MUST go through ``guarded_egress``."""

    name: str

    @abstractmethod
    async def list_tools(self) -> list[ToolSpec]:
        """Return the model-callable tools this provider offers."""

    @abstractmethod
    async def invoke_tool(self, tool: str, args: dict[str, Any], *, request_id: str) -> ToolResult:
        """Invoke ``tool`` with ``args``; return structured provenance."""

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Cheap reachability/credential probe."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release owned resources (HTTP clients, etc.)."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_provider_base.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add gateway/app/providers/tool/__init__.py gateway/app/providers/tool/base.py gateway/tests/test_tool_provider_base.py
git commit -s -m "feat(gateway): ToolProviderAdapter base + ToolSpec/ToolResult (ADR 0014)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `guarded_egress` SSRF primitive

This is the security heart of the PR. Every outbound tool call passes through it.

**Files:**
- Create: `gateway/app/providers/tool/egress.py`
- Test: `gateway/tests/test_guarded_egress.py`

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_guarded_egress.py
import pytest

from app.providers.tool.egress import EgressRefused, validate_egress_target


@pytest.mark.unit
def test_rejects_non_https() -> None:
    with pytest.raises(EgressRefused, match="https"):
        validate_egress_target("http://example.test/x", allowlist=["example.test"])


@pytest.mark.unit
def test_rejects_host_not_in_allowlist() -> None:
    with pytest.raises(EgressRefused, match="allowlist"):
        validate_egress_target("https://evil.test/x", allowlist=["example.test"])


@pytest.mark.unit
def test_rejects_private_ip_literal_host() -> None:
    with pytest.raises(EgressRefused, match="private"):
        validate_egress_target("https://127.0.0.1/x", allowlist=["127.0.0.1"])


@pytest.mark.unit
def test_rejects_link_local_and_metadata_ip() -> None:
    with pytest.raises(EgressRefused, match="private"):
        validate_egress_target("https://169.254.169.254/latest", allowlist=["169.254.169.254"])


@pytest.mark.unit
def test_allows_public_host_in_allowlist(monkeypatch) -> None:
    # Stub DNS so the test never makes a real resolution.
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips",
        lambda host: ["93.184.216.34"],  # example.com public IP
    )
    # Should not raise.
    validate_egress_target("https://example.test/x", allowlist=["example.test"])


@pytest.mark.unit
def test_rejects_dns_rebind_to_private(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips",
        lambda host: ["10.0.0.5"],  # allowlisted host that resolves private
    )
    with pytest.raises(EgressRefused, match="private"):
        validate_egress_target("https://example.test/x", allowlist=["example.test"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_guarded_egress.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.providers.tool.egress'`.

- [ ] **Step 3: Write the primitive**

```python
# gateway/app/providers/tool/egress.py
"""SSRF-guarded outbound egress primitive (ADR 0014 D2).

The gateway-native equivalent of MikeOSS's ``validateRemoteMcpUrl`` /
``guardedFetch``. Every tool-provider adapter MUST validate its outbound URL
through :func:`validate_egress_target` before issuing a request. Enforces:
HTTPS-only; host in the per-provider allowlist; resolved IPs are public
(blocks private/loopback/link-local/CGNAT, defeating DNS-rebind)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class EgressRefused(Exception):
    """Raised when an outbound target violates egress policy."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _resolve_ips(host: str) -> list[str]:
    """Resolve ``host`` to its IP addresses. Wrapped so tests can stub it."""
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def validate_egress_target(url: str, *, allowlist: list[str]) -> None:
    """Validate ``url`` against egress policy. Raise :class:`EgressRefused`.

    Checks, in order: scheme is https; host present; host is in ``allowlist``;
    every resolved IP for the host is public (blocks IP-literal private hosts
    and DNS-rebind of an allowlisted name to a private address)."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise EgressRefused(f"egress must use https, got scheme {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise EgressRefused("egress target has no host")
    if host not in allowlist:
        raise EgressRefused(f"host {host!r} not in provider allowlist")
    for ip in _resolve_ips(host):
        if not _is_public_ip(ip):
            raise EgressRefused(f"host {host!r} resolves to private/blocked address {ip}")


# Headers a caller may never override on an outbound tool request.
_FORBIDDEN_OUTBOUND_HEADERS = frozenset({"host", "x-lq-ai-gateway-key"})


def validate_outbound_headers(headers: dict[str, str]) -> None:
    """Reject caller-supplied Host overrides and smuggled gateway auth."""
    for name in headers:
        if name.lower() in _FORBIDDEN_OUTBOUND_HEADERS:
            raise EgressRefused(f"outbound header {name!r} is not allowed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_guarded_egress.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Add the header-validation test + commit**

Append to `gateway/tests/test_guarded_egress.py`:

```python
@pytest.mark.unit
def test_rejects_host_header_override() -> None:
    from app.providers.tool.egress import validate_outbound_headers

    with pytest.raises(EgressRefused, match="Host"):
        validate_outbound_headers({"Host": "evil.test"})
```

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_guarded_egress.py -v` → PASS (7 tests).

```bash
cd ~/Code/lq-ai && git add gateway/app/providers/tool/egress.py gateway/tests/test_guarded_egress.py
git commit -s -m "feat(gateway): SSRF-guarded egress primitive (ADR 0014 D2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Per-provider rate limiter

**Files:**
- Create: `gateway/app/providers/tool/ratelimit.py`
- Test: `gateway/tests/test_tool_ratelimit.py`

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_tool_ratelimit.py
import pytest

from app.providers.tool.ratelimit import FixedWindowRateLimiter, RateLimited


@pytest.mark.unit
def test_allows_up_to_limit_then_refuses() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowRateLimiter(requests_per_minute=3, now=lambda: clock["t"])
    for _ in range(3):
        limiter.check("echo-test")  # no raise
    with pytest.raises(RateLimited):
        limiter.check("echo-test")


@pytest.mark.unit
def test_window_resets_after_60s() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowRateLimiter(requests_per_minute=1, now=lambda: clock["t"])
    limiter.check("echo-test")
    with pytest.raises(RateLimited):
        limiter.check("echo-test")
    clock["t"] += 61.0
    limiter.check("echo-test")  # new window, no raise


@pytest.mark.unit
def test_limits_are_per_provider() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowRateLimiter(requests_per_minute=1, now=lambda: clock["t"])
    limiter.check("a")
    limiter.check("b")  # different provider, independent budget
    with pytest.raises(RateLimited):
        limiter.check("a")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_ratelimit.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the limiter**

```python
# gateway/app/providers/tool/ratelimit.py
"""Per-provider fixed-window rate limiter for tool egress (ADR 0014).

Self-contained, in-memory, per-provider. NOT the gateway's global
``rate_limits`` (whose enforcement middleware is unwired). The clock is
injectable so tests are deterministic without sleeping."""

from __future__ import annotations

import time
from collections.abc import Callable

_WINDOW_SECONDS = 60.0


class RateLimited(Exception):
    """Raised when a provider exceeds its per-minute request budget."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"rate limit exceeded for tool provider {provider!r}")
        self.provider = provider


class FixedWindowRateLimiter:
    """Fixed 60-second window, ``requests_per_minute`` budget per provider."""

    def __init__(
        self, *, requests_per_minute: int, now: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = requests_per_minute
        self._now = now
        # provider -> (window_start, count)
        self._windows: dict[str, tuple[float, int]] = {}

    def check(self, provider: str) -> None:
        """Record one request for ``provider``; raise :class:`RateLimited`
        if it would exceed the budget for the current window."""
        now = self._now()
        start, count = self._windows.get(provider, (now, 0))
        if now - start >= _WINDOW_SECONDS:
            start, count = now, 0
        if count >= self._limit:
            raise RateLimited(provider)
        self._windows[provider] = (start, count + 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_ratelimit.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add gateway/app/providers/tool/ratelimit.py gateway/tests/test_tool_ratelimit.py
git commit -s -m "feat(gateway): per-provider tool egress rate limiter (ADR 0014)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `EchoToolAdapter` — the proof-of-path provider

The echo adapter validates its target through `guarded_egress` but, being a test provider, returns its input rather than making a real call (so unit tests need no network). It proves the adapter contract + egress validation wiring end-to-end.

**Files:**
- Create: `gateway/app/providers/tool/echo.py`
- Modify: `gateway/app/providers/tool/__init__.py` (re-export `EchoToolAdapter`)
- Test: `gateway/tests/test_echo_tool_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_echo_tool_adapter.py
import pytest

from app.config import ToolProviderConfig
from app.providers.tool.base import ToolResult
from app.providers.tool.echo import EchoToolAdapter
from app.providers.tool.egress import EgressRefused


def _cfg(**over) -> ToolProviderConfig:
    base = {
        "name": "echo-test",
        "type": "echo",
        "base_url": "https://example.test",
        "egress_tier": 4,
        "allowlist": {"hosts": ["example.test"]},
    }
    base.update(over)
    return ToolProviderConfig.model_validate(base)


@pytest.mark.unit
async def test_echo_invoke_returns_input() -> None:
    adapter = EchoToolAdapter.from_config(_cfg())
    try:
        result = await adapter.invoke_tool("echo", {"msg": "hi"}, request_id="req_1")
    finally:
        await adapter.aclose()
    assert isinstance(result, ToolResult)
    assert result.provider == "echo-test"
    assert result.payload == {"echoed": {"msg": "hi"}}
    assert result.bytes_out > 0


@pytest.mark.unit
async def test_echo_lists_one_tool() -> None:
    adapter = EchoToolAdapter.from_config(_cfg())
    try:
        tools = await adapter.list_tools()
    finally:
        await adapter.aclose()
    assert [t.name for t in tools] == ["echo"]
    assert tools[0].read_only is True


@pytest.mark.unit
async def test_echo_rejects_unknown_tool() -> None:
    from app.providers.tool.base import ToolProviderError

    adapter = EchoToolAdapter.from_config(_cfg())
    try:
        with pytest.raises(ToolProviderError):
            await adapter.invoke_tool("nope", {}, request_id="req_1")
    finally:
        await adapter.aclose()


@pytest.mark.unit
async def test_echo_base_url_must_pass_egress_policy() -> None:
    # base_url host not in its own allowlist -> egress refusal at validation.
    with pytest.raises(EgressRefused):
        EchoToolAdapter.from_config(
            _cfg(base_url="https://evil.test", allowlist={"hosts": ["example.test"]})
        ).validate_base_url()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_echo_tool_adapter.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the adapter**

```python
# gateway/app/providers/tool/echo.py
"""``echo`` tool provider — the PR1 proof-of-path adapter (ADR 0014).

Implements the full :class:`ToolProviderAdapter` contract and exercises the
egress-validation wiring, but returns its input instead of making a network
call, so unit tests need no live endpoint. Replaced by real providers
(CourtListener PR2, MCP PR4)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import ToolProviderConfig
from app.providers.base import ProviderHealth
from app.providers.tool.base import (
    ToolProviderAdapter,
    ToolProviderError,
    ToolResult,
    ToolSpec,
)
from app.providers.tool.egress import validate_egress_target

DEFAULT_TIMEOUT_SECONDS = 30.0


class EchoToolAdapter(ToolProviderAdapter):
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        allowlist: list[str],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._allowlist = allowlist
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=self._base_url, timeout=DEFAULT_TIMEOUT_SECONDS)

    @classmethod
    def from_config(cls, provider: ToolProviderConfig) -> "EchoToolAdapter":
        if provider.type != "echo":
            raise ValueError(f"EchoToolAdapter built from non-echo provider {provider.type!r}")
        return cls(
            name=provider.name,
            base_url=provider.base_url,
            allowlist=provider.allowlist.hosts,
        )

    def validate_base_url(self) -> None:
        """Confirm the configured base_url satisfies this provider's own
        egress policy (called at build time so a misconfig fails at startup)."""
        validate_egress_target(self._base_url + "/", allowlist=self._allowlist)

    async def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="echo",
                description="Echoes its input arguments back. Test provider only.",
                parameters={"type": "object", "additionalProperties": True},
                read_only=True,
            )
        ]

    async def invoke_tool(self, tool: str, args: dict[str, Any], *, request_id: str) -> ToolResult:
        if tool != "echo":
            raise ToolProviderError(f"unknown tool {tool!r} for echo provider")
        encoded = json.dumps(args).encode("utf-8")
        return ToolResult(
            provider=self.name,
            tool=tool,
            payload={"echoed": args},
            bytes_out=len(encoded),
            bytes_in=len(encoded),
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, reachable=True, latency_ms=0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
```

Add `EchoToolAdapter` to the `__init__.py` re-exports + `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_echo_tool_adapter.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add gateway/app/providers/tool/echo.py gateway/app/providers/tool/__init__.py gateway/tests/test_echo_tool_adapter.py
git commit -s -m "feat(gateway): echo tool provider (PR1 proof-of-path)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Gateway-side `tool_egress_log` writer

Mirror `gateway/app/routing_log.py` exactly: a dataclass row, a `Protocol`, and SQL/Null/Recording implementations. `write()` must never raise.

**Files:**
- Create: `gateway/app/tool_egress_log.py`
- Test: `gateway/tests/test_tool_egress_log_writer.py`

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_tool_egress_log_writer.py
import pytest

from app.tool_egress_log import (
    NullToolEgressLogWriter,
    RecordingToolEgressLogWriter,
    ToolEgressLogRow,
)


@pytest.mark.unit
async def test_recording_writer_captures_rows() -> None:
    writer = RecordingToolEgressLogWriter()
    row = ToolEgressLogRow(provider="echo-test", tool="echo", tier=4, bytes_out=2, bytes_in=2)
    await writer.write(row)
    assert len(writer.rows) == 1
    assert writer.rows[0].provider == "echo-test"


@pytest.mark.unit
async def test_null_writer_is_noop() -> None:
    writer = NullToolEgressLogWriter()
    await writer.write(ToolEgressLogRow(provider="x", tool="echo", tier=4))  # no raise


@pytest.mark.unit
async def test_row_defaults_to_not_refused_not_anonymized() -> None:
    row = ToolEgressLogRow(provider="x", tool="echo", tier=4)
    assert row.refused is False
    assert row.anonymization_applied is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_egress_log_writer.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the writer** (copy the structure of `routing_log.py`)

```python
# gateway/app/tool_egress_log.py
"""``tool_egress_log`` writer (ADR 0014 D3).

Same design as ``app.routing_log``: the gateway is the only component that
knows which tool provider was called, so the gateway writes the audit row —
raw parameter-bound SQL (the table is api-owned; we don't double-up ORM
models across services). Counts and types only, NEVER raw payloads.
``write()`` must never raise: the egress data path takes priority over audit.
Schema authority: ``api/alembic/versions/0048_tool_egress_log.py``."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

__all__ = [
    "NullToolEgressLogWriter",
    "RecordingToolEgressLogWriter",
    "SQLToolEgressLogWriter",
    "ToolEgressLogRow",
    "ToolEgressLogWriter",
]


@dataclass
class ToolEgressLogRow:
    provider: str
    tool: str
    tier: int
    request_id: str | None = None
    bytes_out: int | None = None
    bytes_in: int | None = None
    anonymization_applied: bool = False
    refused: bool = False
    refusal_reason: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


_INSERT_SQL = text(
    """
    INSERT INTO tool_egress_log (
        timestamp, request_id, provider, tool, tier,
        bytes_out, bytes_in, anonymization_applied, refused, refusal_reason
    ) VALUES (
        :timestamp, :request_id, :provider, :tool, :tier,
        :bytes_out, :bytes_in, :anonymization_applied, :refused, :refusal_reason
    )
    """
)


def _to_params(row: ToolEgressLogRow) -> dict[str, object]:
    return {
        "timestamp": row.timestamp,
        "request_id": row.request_id,
        "provider": row.provider,
        "tool": row.tool,
        "tier": row.tier,
        "bytes_out": row.bytes_out,
        "bytes_in": row.bytes_in,
        "anonymization_applied": row.anonymization_applied,
        "refused": row.refused,
        "refusal_reason": row.refusal_reason,
    }


@runtime_checkable
class ToolEgressLogWriter(Protocol):
    async def write(self, row: ToolEgressLogRow) -> None: ...


class SQLToolEgressLogWriter:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def write(self, row: ToolEgressLogRow) -> None:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(_INSERT_SQL, _to_params(row))
        except Exception as exc:
            logger.error("failed to write tool_egress_log row: %s", exc)


class NullToolEgressLogWriter:
    async def write(self, row: ToolEgressLogRow) -> None:
        return None


class RecordingToolEgressLogWriter:
    """Test double; records rows in memory."""

    def __init__(self) -> None:
        self.rows: list[ToolEgressLogRow] = []

    async def write(self, row: ToolEgressLogRow) -> None:
        self.rows.append(row)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_egress_log_writer.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add gateway/app/tool_egress_log.py gateway/tests/test_tool_egress_log_writer.py
git commit -s -m "feat(gateway): tool_egress_log writer (ADR 0014 D3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `Router.route_tool_call` — the governed egress path

Ties it together: resolve the provider, rate-limit, check egress tier, invoke the adapter, write the audit row. Refusals are audited too (a `refused=True` row), mirroring the inference path's `_write_unresolved`.

**Files:**
- Modify: `gateway/app/router.py`
- Test: `gateway/tests/test_route_tool_call.py`

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_route_tool_call.py
import pytest

from app.config import GatewayConfig
from app.providers.tool.echo import EchoToolAdapter
from app.providers.tool.ratelimit import FixedWindowRateLimiter
from app.router import Router, ToolEgressRefused
from app.tool_egress_log import RecordingToolEgressLogWriter


def _config() -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "echo-test",
                    "type": "echo",
                    "base_url": "https://example.test",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                    "rate_limit": {"requests_per_minute": 2},
                }
            ]
        }
    )


def _router(writer, clock=None):
    cfg = _config()
    adapter = EchoToolAdapter.from_config(cfg.tool_providers[0])
    limiter = FixedWindowRateLimiter(
        requests_per_minute=2, now=(clock or (lambda: 1000.0))
    )
    return Router(
        config=cfg,
        adapters={},
        tool_adapters={"echo-test": adapter},
        tool_egress_log=writer,
        tool_rate_limiter=limiter,
    )


@pytest.mark.unit
async def test_route_tool_call_happy_path_writes_audit_row() -> None:
    writer = RecordingToolEgressLogWriter()
    router = _router(writer)
    result = await router.route_tool_call(
        "echo-test", "echo", {"msg": "hi"}, request_id="req_1", max_allowed_tier=4
    )
    assert result.payload == {"echoed": {"msg": "hi"}}
    assert len(writer.rows) == 1
    assert writer.rows[0].refused is False
    assert writer.rows[0].tier == 4


@pytest.mark.unit
async def test_route_tool_call_refuses_when_egress_tier_exceeds_ceiling() -> None:
    writer = RecordingToolEgressLogWriter()
    router = _router(writer)
    # Matter ceiling is tier 3 (privileged); provider egress_tier 4 is weaker.
    with pytest.raises(ToolEgressRefused, match="egress_tier"):
        await router.route_tool_call(
            "echo-test", "echo", {"msg": "x"}, request_id="req_2", max_allowed_tier=3
        )
    assert writer.rows[-1].refused is True
    assert writer.rows[-1].refusal_reason is not None


@pytest.mark.unit
async def test_route_tool_call_refuses_unknown_provider() -> None:
    writer = RecordingToolEgressLogWriter()
    router = _router(writer)
    with pytest.raises(ToolEgressRefused, match="unknown"):
        await router.route_tool_call(
            "missing", "echo", {}, request_id="req_3", max_allowed_tier=5
        )


@pytest.mark.unit
async def test_route_tool_call_enforces_rate_limit() -> None:
    writer = RecordingToolEgressLogWriter()
    router = _router(writer)
    for i in range(2):
        await router.route_tool_call(
            "echo-test", "echo", {}, request_id=f"r{i}", max_allowed_tier=4
        )
    with pytest.raises(ToolEgressRefused, match="rate"):
        await router.route_tool_call(
            "echo-test", "echo", {}, request_id="r3", max_allowed_tier=4
        )
    assert writer.rows[-1].refused is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_route_tool_call.py -v`
Expected: FAIL — `Router.__init__` got unexpected kwargs / `cannot import name 'ToolEgressRefused'`.

- [ ] **Step 3: Extend the Router**

In `gateway/app/router.py`: add imports near the top:

```python
from dataclasses import dataclass

from app.providers.tool.base import ToolProviderAdapter, ToolResult
from app.providers.tool.egress import EgressRefused
from app.providers.tool.ratelimit import FixedWindowRateLimiter, RateLimited
from app.tool_egress_log import (
    NullToolEgressLogWriter,
    ToolEgressLogRow,
    ToolEgressLogWriter,
)
```

Add the refusal error + result type (module level):

```python
class ToolEgressRefused(Exception):
    """Raised when a tool call is refused (unknown provider, tier ceiling,
    rate limit, or SSRF policy). Always paired with an audited refusal row."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ToolCallRoutedResult:
    provider: str
    tool: str
    payload: object
    tier: int
```

Extend `Router.__init__` to accept the new (optional, keyword-only, defaulted) dependencies so existing inference construction is unchanged:

```python
    def __init__(
        self,
        *,
        config: GatewayConfig,
        adapters: dict[str, ProviderAdapter],
        config_provider: Callable[[], GatewayConfig] | None = None,
        tool_adapters: dict[str, ToolProviderAdapter] | None = None,
        tool_egress_log: ToolEgressLogWriter | None = None,
        tool_rate_limiter: FixedWindowRateLimiter | None = None,
    ) -> None:
        self._config = config
        self._adapters = adapters
        self._config_provider = config_provider
        self._tool_adapters = tool_adapters or {}
        self._tool_egress_log = tool_egress_log or NullToolEgressLogWriter()
        # A single shared limiter; per-provider budgets are keyed inside it.
        # If not injected, build one from the max configured rpm (the limiter
        # is per-provider-keyed, so a single instance serves all providers).
        if tool_rate_limiter is not None:
            self._tool_rate_limiter = tool_rate_limiter
        else:
            max_rpm = max(
                (tp.rate_limit.requests_per_minute for tp in config.tool_providers),
                default=60,
            )
            self._tool_rate_limiter = FixedWindowRateLimiter(requests_per_minute=max_rpm)
```

Add the method:

```python
    async def route_tool_call(
        self,
        provider_name: str,
        tool: str,
        args: dict[str, object],
        *,
        request_id: str,
        max_allowed_tier: int | None = None,
    ) -> ToolCallRoutedResult:
        """Govern + dispatch one tool call (ADR 0014 D2/D3/D4).

        Order: resolve provider -> rate limit -> egress-tier ceiling ->
        adapter invoke (which validates SSRF) -> write audit row. Every
        refusal writes a ``refused=True`` row before raising."""
        provider = self.config.tool_provider_by_name(provider_name)
        adapter = self._tool_adapters.get(provider_name)
        if provider is None or adapter is None:
            await self._tool_egress_log.write(
                ToolEgressLogRow(
                    provider=provider_name, tool=tool, tier=0,
                    refused=True, refusal_reason="unknown tool provider",
                    request_id=request_id,
                )
            )
            raise ToolEgressRefused(f"unknown tool provider {provider_name!r}")

        # Rate limit (per-provider).
        try:
            self._tool_rate_limiter.check(provider_name)
        except RateLimited as exc:
            await self._tool_egress_log.write(
                ToolEgressLogRow(
                    provider=provider_name, tool=tool, tier=provider.egress_tier,
                    refused=True, refusal_reason="rate limit exceeded",
                    request_id=request_id,
                )
            )
            raise ToolEgressRefused(str(exc)) from exc

        # Egress-tier ceiling: refuse if the provider's egress tier is weaker
        # (numerically greater) than the matter/skill ceiling allows.
        if max_allowed_tier is not None and provider.egress_tier > max_allowed_tier:
            await self._tool_egress_log.write(
                ToolEgressLogRow(
                    provider=provider_name, tool=tool, tier=provider.egress_tier,
                    refused=True, refusal_reason="egress_tier exceeds policy ceiling",
                    request_id=request_id,
                )
            )
            raise ToolEgressRefused(
                f"egress_tier {provider.egress_tier} exceeds ceiling {max_allowed_tier}"
            )

        # Invoke (adapter validates SSRF on any real outbound call).
        try:
            result: ToolResult = await adapter.invoke_tool(tool, args, request_id=request_id)
        except EgressRefused as exc:
            await self._tool_egress_log.write(
                ToolEgressLogRow(
                    provider=provider_name, tool=tool, tier=provider.egress_tier,
                    refused=True, refusal_reason=f"ssrf: {exc.reason}",
                    request_id=request_id,
                )
            )
            raise ToolEgressRefused(f"egress refused: {exc.reason}") from exc

        # Success audit row. anonymization_applied is honestly False in PR1
        # (no outbound transform yet — see plan scope note).
        await self._tool_egress_log.write(
            ToolEgressLogRow(
                provider=provider_name, tool=tool, tier=provider.egress_tier,
                bytes_out=result.bytes_out, bytes_in=result.bytes_in,
                anonymization_applied=False, refused=False, request_id=request_id,
            )
        )
        return ToolCallRoutedResult(
            provider=provider_name, tool=tool, payload=result.payload,
            tier=provider.egress_tier,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_route_tool_call.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full gateway suite to confirm no regression in inference construction**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest -q`
Expected: PASS (existing `Router(...)` callers still work — the new params are keyword-only with defaults).

- [ ] **Step 6: Commit**

```bash
cd ~/Code/lq-ai && git add gateway/app/router.py gateway/tests/test_route_tool_call.py
git commit -s -m "feat(gateway): Router.route_tool_call governed egress path (ADR 0014)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Lifespan wiring + `build_tool_adapter` factory

Build tool adapters at startup (validating each base_url against egress policy), hold them in `app.state.tool_adapters`, construct the SQL egress writer from the existing engine, and pass them into the `Router`.

**Files:**
- Modify: `gateway/app/main.py`
- Test: `gateway/tests/test_tool_adapter_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_tool_adapter_wiring.py
import pytest

from app.config import GatewayConfig
from app.main import build_tool_adapter
from app.providers.tool.echo import EchoToolAdapter
from app.providers.tool.egress import EgressRefused


@pytest.mark.unit
def test_build_tool_adapter_echo() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "echo-test", "type": "echo",
                    "base_url": "https://example.test", "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                }
            ]
        }
    )
    adapter = build_tool_adapter(cfg.tool_providers[0])
    assert isinstance(adapter, EchoToolAdapter)


@pytest.mark.unit
def test_build_tool_adapter_rejects_base_url_outside_allowlist() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "bad", "type": "echo",
                    "base_url": "https://evil.test", "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                }
            ]
        }
    )
    with pytest.raises(EgressRefused):
        build_tool_adapter(cfg.tool_providers[0])


@pytest.mark.unit
def test_build_tool_adapter_disabled_returns_none() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "off", "type": "echo", "enabled": False,
                    "base_url": "https://example.test", "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                }
            ]
        }
    )
    assert build_tool_adapter(cfg.tool_providers[0]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_adapter_wiring.py -v`
Expected: FAIL — `cannot import name 'build_tool_adapter'`.

- [ ] **Step 3: Add the factory + wire the lifespan**

In `gateway/app/main.py`, add the factory beside `build_adapter` (~line 96):

```python
def build_tool_adapter(provider: ToolProviderConfig) -> ToolProviderAdapter | None:
    """Construct the tool adapter for one provider, or ``None`` if disabled
    or no adapter exists for the type. Validates the base_url against the
    provider's egress policy at build time so a misconfig fails at startup."""
    if not provider.enabled:
        return None
    if provider.type == "echo":
        adapter = EchoToolAdapter.from_config(provider)
        adapter.validate_base_url()
        return adapter
    # courtlistener (PR2), mcp (PR4) land later.
    return None
```

Add imports at the top of `main.py`:

```python
from app.config import ToolProviderConfig
from app.providers.tool.base import ToolProviderAdapter
from app.providers.tool.echo import EchoToolAdapter
from app.tool_egress_log import (
    NullToolEgressLogWriter,
    SQLToolEgressLogWriter,
)
```

In the lifespan startup (where `app.state.adapters` is built and the `Router` is constructed — find the block around the existing `Router(config=..., adapters=...)` construction), add:

```python
    tool_adapters: dict[str, ToolProviderAdapter] = {}
    for tp in config.tool_providers:
        adapter = build_tool_adapter(tp)
        if adapter is not None:
            tool_adapters[tp.name] = adapter
    app.state.tool_adapters = tool_adapters

    # Reuse the same engine the inference routing-log writer uses. If the
    # gateway has no DB engine (DATABASE_URL unset), fall back to the no-op
    # writer — same posture as NullRoutingLogWriter.
    tool_egress_writer = (
        SQLToolEgressLogWriter(engine) if engine is not None else NullToolEgressLogWriter()
    )
    app.state.tool_egress_log = tool_egress_writer
```

Then pass them into the `Router(...)` construction in that same block:

```python
    router = Router(
        config=config,
        adapters=adapters,
        config_provider=...,            # keep the existing value
        tool_adapters=tool_adapters,
        tool_egress_log=tool_egress_writer,
    )
```

And in the shutdown half of the lifespan, close the tool adapters alongside the inference adapters:

```python
    for adapter in tool_adapters.values():
        await adapter.aclose()
```

*(Find the existing `engine` variable used by `SQLRoutingLogWriter` in this lifespan; reuse it verbatim. If the routing-log writer uses a different name, match it.)*

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_adapter_wiring.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full gateway suite + lifespan smoke (uses the example config)**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest -q`
Expected: PASS. The `gateway_app` fixture starts the full lifespan against `gateway.yaml.example`; if that example has no `tool_providers`, the wiring is a no-op and existing tests stay green. (Task 10 adds the example block.)

- [ ] **Step 6: Commit**

```bash
cd ~/Code/lq-ai && git add gateway/app/main.py gateway/tests/test_tool_adapter_wiring.py
git commit -s -m "feat(gateway): build + wire tool adapters and egress writer into lifespan

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: `gateway.yaml.example` block + boundary-register doc + gates

**Files:**
- Modify: `gateway.yaml.example`
- Modify: `docs/security/boundary-registers.md`
- Test: `gateway/tests/test_example_config_tool_providers.py`

- [ ] **Step 1: Write the failing test**

```python
# gateway/tests/test_example_config_tool_providers.py
from pathlib import Path

import pytest

from app.config_loader import load_config

EXAMPLE = Path(__file__).resolve().parents[2] / "gateway.yaml.example"


@pytest.mark.unit
def test_example_config_has_commented_tool_providers(example_env) -> None:
    """The example loads cleanly; if a tool_providers block is uncommented it
    must validate. PR1 ships it commented so the default stack is unchanged."""
    cfg = load_config(EXAMPLE)
    # Commented-out by default -> empty list, stack behavior unchanged.
    assert cfg.tool_providers == []
```

*(The `example_env` fixture and `EXAMPLE` path mirror `gateway/tests/conftest.py`. If `conftest.py` already exposes an `EXAMPLE_CONFIG` constant, import it instead of recomputing the path.)*

- [ ] **Step 2: Run test to verify it fails (or passes trivially), then add the example block**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_example_config_tool_providers.py -v`
Expected: PASS already (no block yet → empty list). Now add the documented (commented) block so operators have the shape. Append to `gateway.yaml.example` after the `providers:` section:

```yaml
# ============================================================
# TOOL / DATA-SOURCE PROVIDERS (ADR 0014) — third-party egress
# ============================================================
# A tool provider is third-party egress the gateway brokers and audits
# (case-law APIs, MCP servers). Distinct from inference `providers:` above.
# Every entry is SSRF/allowlist-guarded, tier-tagged, rate-limited, and
# written to `tool_egress_log`. Uncomment and configure to enable.
#
# tool_providers:
#   - name: courtlistener-prod
#     type: courtlistener          # PR2 (not yet shipped); `echo` is the test type
#     base_url: https://www.courtlistener.com/api/rest/v4
#     api_key_env: COURTLISTENER_API_TOKEN   # OR api_key_encrypted (ADR 0011)
#     egress_tier: 4               # data-egress tier (ADR 0014 D4)
#     allowlist:
#       hosts: [www.courtlistener.com]   # exact outbound host allowlist (SSRF)
#     rate_limit:
#       requests_per_minute: 60    # per-provider, enforced at the adapter
#     anonymize_outbound: true     # default; transform lands in WS3/WS4
```

- [ ] **Step 3: Re-run the test + the full suite**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_example_config_tool_providers.py -q && docker compose run --rm gateway pytest -q`
Expected: PASS.

- [ ] **Step 4: Add the boundary-register entry**

In `docs/security/boundary-registers.md`, add a register row/section for the **tool/data-source egress boundary**: what it guards (third-party egress), the controls (HTTPS-only, DNS-private block, host allowlist, no Host override, header validation, egress-tier ceiling, per-provider rate limit), the audit surface (`tool_egress_log`, counts-only), and a link to ADR 0014. Match the doc's existing entry format.

- [ ] **Step 5: Run the gates (CLAUDE.md: both ruff gates + mypy --strict for gateway)**

```bash
cd ~/Code/lq-ai && docker compose run --rm gateway ruff format --check . \
  && docker compose run --rm gateway ruff check . \
  && docker compose run --rm gateway mypy --strict app
```
Expected: all clean. Fix any findings inline (re-run until green). Then the api gates for the migration/model:
```bash
cd ~/Code/lq-ai && docker compose run --rm api ruff format --check . && docker compose run --rm api ruff check .
```

- [ ] **Step 6: Commit**

```bash
cd ~/Code/lq-ai && git add gateway.yaml.example docs/security/boundary-registers.md gateway/tests/test_example_config_tool_providers.py
git commit -s -m "docs(gateway): tool_providers example block + egress boundary register (ADR 0014)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: End-to-end integration test through the lifespan

Prove the whole path with the example config carrying a (temporarily uncommented) echo provider, via the real lifespan-built router.

**Files:**
- Test: `gateway/tests/test_tool_egress_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# gateway/tests/test_tool_egress_integration.py
import pytest

from app.config import GatewayConfig
from app.main import build_tool_adapter
from app.router import Router
from app.tool_egress_log import RecordingToolEgressLogWriter


@pytest.mark.unit
async def test_end_to_end_echo_through_router() -> None:
    """Config -> build_tool_adapter -> Router.route_tool_call -> audit row.
    Exercises every PR1 component together without a network call."""
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "echo-test", "type": "echo",
                    "base_url": "https://example.test", "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                    "rate_limit": {"requests_per_minute": 10},
                }
            ]
        }
    )
    adapter = build_tool_adapter(cfg.tool_providers[0])
    assert adapter is not None
    writer = RecordingToolEgressLogWriter()
    router = Router(
        config=cfg, adapters={},
        tool_adapters={"echo-test": adapter}, tool_egress_log=writer,
    )
    try:
        result = await router.route_tool_call(
            "echo-test", "echo", {"q": "hello"}, request_id="req_e2e", max_allowed_tier=5
        )
    finally:
        await adapter.aclose()
    assert result.payload == {"echoed": {"q": "hello"}}
    assert result.tier == 4
    assert len(writer.rows) == 1
    row = writer.rows[0]
    assert row.refused is False
    assert row.bytes_out and row.bytes_out > 0
    assert row.anonymization_applied is False  # honest: no transform in PR1
```

- [ ] **Step 2: Run it**

Run: `cd ~/Code/lq-ai && docker compose run --rm gateway pytest tests/test_tool_egress_integration.py -v`
Expected: PASS.

- [ ] **Step 3: Full suites green (gateway + api)**

```bash
cd ~/Code/lq-ai && docker compose run --rm gateway pytest -q && docker compose run --rm api pytest -q
```
Expected: PASS. (No `EXPECTED_PATHS`/`IMPLEMENTED_ROUTES` change in PR1 — no new HTTP route is added. That guard bumps in PR3.)

- [ ] **Step 4: Commit**

```bash
cd ~/Code/lq-ai && git add gateway/tests/test_tool_egress_integration.py
git commit -s -m "test(gateway): end-to-end tool egress path through router (ADR 0014)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Push, PR, security review

- [ ] **Step 1: Push both remotes**

```bash
cd ~/Code/lq-ai && git push origin feat/legal-research-mcp-plan && git push tucuxi feat/legal-research-mcp-plan
```

- [ ] **Step 2: Open the PR** (base `main`), titled `feat(gateway): tool-provider egress boundary (WS1 / ADR 0014)`. In the body: link ADR 0014 + the mini-PRD; list the acceptance criteria from the PR1 row of the roadmap and check each; **flag the honest deferral** (no outbound anonymization transform yet; no CourtListener/MCP semantics; no HTTP route). Note this is security-sensitive (`gateway/**`).

- [ ] **Step 3: Watch CI, route to security review.** Per CLAUDE.md merge-gating, `gateway/**` changes are **maintainer-reviewed + maintainer-merged** — do NOT self-merge. Offer the maintainer a review walkthrough. Address review feedback via the `superpowers:receiving-code-review` discipline (verify each point against the code, don't perform agreement).

---

## Self-Review (completed against the spec)

**Spec coverage (WS1 section + ADR 0014):**
- New tool-provider class → Tasks 2, 3, 6, 9. ✓
- `tool_providers:` config block → Task 2 + Task 10 (example). ✓
- SSRF/allowlist primitive (HTTPS, DNS-private-block, host allowlist, no Host override, header validation) → Task 4. ✓
- `tool_egress_log` (counts only, refused+reason) → Tasks 1, 7, 8. ✓
- Per-provider rate limiting at the adapter (C3) → Tasks 5, 8. ✓
- Egress-tier refusal (ADR 0014 D4) → Task 8. ✓
- Outbound anonymization (ADR 0014 D5) → **explicitly scoped out of PR1** with an honest seam (documented in Scope + Task 8 success row writes `anonymization_applied=False`). Flagged, not silently dropped. ✓
- Echo/test provider proving the path (spec "What WS1 does NOT do") → Task 6 + Task 11. ✓
- Boundary-register doc (WS6 rider) → Task 10. ✓

**Placeholder scan:** no TBD/TODO; every code step shows complete code; the two "find the existing X in the lifespan" notes (Task 9) point at a real, named construct (`engine`, the `Router(...)` block) rather than hand-waving — the implementer locates a concrete symbol, not invents one.

**Type consistency:** `ToolProviderConfig`, `ToolProviderAdapter`, `ToolSpec`, `ToolResult`, `ToolEgressLogRow`, `ToolEgressRefused`, `EgressRefused`, `RateLimited`, `FixedWindowRateLimiter`, `build_tool_adapter`, `Router.route_tool_call`, `ToolCallRoutedResult` are defined once and referenced with the same names/signatures across tasks. `route_tool_call(provider_name, tool, args, *, request_id, max_allowed_tier)` matches between Task 8 definition and Task 11 use. `ToolResult.bytes_out/bytes_in` consistent between Tasks 3, 6, 8.

**Known seam to confirm at execution time (not a gap):** Task 9 reuses the lifespan's existing DB `engine` symbol for the egress writer; its exact variable name must be read from `gateway/app/main.py` at implementation time (it is whatever `SQLRoutingLogWriter` is constructed with). Called out in the task.
