"""HTTP-level tests for the tabular bulk-op endpoints — DE-304 / ADR 0026.

Covers:

* ``POST /api/v1/tabular/executions/{id}/bulk-ops/preview-cost`` —
  preview math (cold-start default x calls count), Decimal-as-string
  serialization, 400 on bad column, 404 ownership collapse, 409 on
  non-completed executions.
* ``POST /api/v1/tabular/executions/{id}/bulk-ops`` — 202 + row
  persisted at ``pending`` with the confirmed-cost echo, job enqueued,
  and the new row embedded in the execution detail response
  (the ADR 0026 D2 read-side / linkage property).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.tabular import TabularExecution
from app.models.user import User
from app.security import create_access_token, hash_password
from app.tabular import bulk_ops as bulk_ops_module
from app.tabular.bulk_ops import DEFAULT_PER_CALL_USD


@pytest.fixture(autouse=True)
def _fresh_cost_cache() -> None:
    bulk_ops_module.invalidate_cache()


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"bulkop-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token(user.id, user.email, is_admin=user.is_admin)}"
        )
    }


def _rows(n: int) -> list[dict[str, Any]]:
    return [
        {
            "document_id": str(uuid.uuid4()),
            "document_name": f"doc-{i}.pdf",
            "cells": {"Term": {"value": f"{i} years", "confidence": "high"}},
        }
        for i in range(n)
    ]


async def _make_execution(
    db: AsyncSession,
    *,
    user: User,
    status: str = "completed",
    rows: list[dict[str, Any]] | None = None,
) -> TabularExecution:
    execution = TabularExecution(
        user_id=user.id,
        status=status,
        document_ids=[],
        columns=[{"name": "Term", "query": "What is the term?"}],
        results=({"schema_version": "m3-c2-v1", "rows": rows} if rows is not None else None),
    )
    db.add(execution)
    await db.flush()
    return execution


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_preview_redline_math_cold_start(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """3 grid rows → 3 calls at the cold-start default; Decimal fields
    serialize as JSON strings."""

    user = await _make_user(db_session)
    execution = await _make_execution(db_session, user=user, rows=_rows(3))

    resp = await client.post(
        f"/api/v1/tabular/executions/{execution.id}/bulk-ops/preview-cost",
        headers=_bearer(user),
        json={"kind": "redline_rows"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["kind"] == "redline_rows"
    assert payload["calls_count"] == 3
    assert payload["per_call_cost_usd"] == str(DEFAULT_PER_CALL_USD)
    assert payload["estimated_cost_usd"] == str(DEFAULT_PER_CALL_USD * 3)
    # Decimal-as-string invariant.
    assert isinstance(payload["estimated_cost_usd"], str)


@pytest.mark.integration
async def test_preview_summarize_is_one_call(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    execution = await _make_execution(db_session, user=user, rows=_rows(5))

    resp = await client.post(
        f"/api/v1/tabular/executions/{execution.id}/bulk-ops/preview-cost",
        headers=_bearer(user),
        json={"kind": "summarize_column", "column_name": "Term"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["calls_count"] == 1
    assert payload["estimated_cost_usd"] == str(DEFAULT_PER_CALL_USD)


@pytest.mark.integration
async def test_preview_summarize_unknown_column_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The column must belong to the SNAPSHOTTED spec (C-1)."""

    user = await _make_user(db_session)
    execution = await _make_execution(db_session, user=user, rows=_rows(2))

    resp = await client.post(
        f"/api/v1/tabular/executions/{execution.id}/bulk-ops/preview-cost",
        headers=_bearer(user),
        json={"kind": "summarize_column", "column_name": "Nope"},
    )
    assert resp.status_code == 400
    assert "column_name" in resp.json()["detail"]


@pytest.mark.integration
async def test_preview_cross_user_collapses_to_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Missing / cross-user executions collapse into 404 (no leakage)."""

    owner = await _make_user(db_session)
    other = await _make_user(db_session)
    execution = await _make_execution(db_session, user=owner, rows=_rows(1))

    resp = await client.post(
        f"/api/v1/tabular/executions/{execution.id}/bulk-ops/preview-cost",
        headers=_bearer(other),
        json={"kind": "redline_rows"},
    )
    assert resp.status_code == 404

    resp = await client.post(
        f"/api/v1/tabular/executions/{uuid.uuid4()}/bulk-ops/preview-cost",
        headers=_bearer(other),
        json={"kind": "redline_rows"},
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_preview_non_completed_execution_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Bulk-operating a partial grid would mislead — same posture as
    export (ADR 0026 D2)."""

    user = await _make_user(db_session)
    execution = await _make_execution(db_session, user=user, status="running", rows=None)

    resp = await client.post(
        f"/api/v1/tabular/executions/{execution.id}/bulk-ops/preview-cost",
        headers=_bearer(user),
        json={"kind": "redline_rows"},
    )
    assert resp.status_code == 409
    assert "completed" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_bulk_op_202_persists_enqueues_and_links(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """202 + row at ``pending`` with the confirmed-cost echo; the job
    is enqueued; the new op is embedded in the execution detail
    response (linkage / read-side per ADR 0026 D2)."""

    enqueued: list[uuid.UUID] = []

    async def _fake_enqueue(bulk_op_id: uuid.UUID) -> bool:
        enqueued.append(bulk_op_id)
        return True

    monkeypatch.setattr("app.api.tabular.enqueue_tabular_bulk_op_job", _fake_enqueue)

    user = await _make_user(db_session)
    execution = await _make_execution(db_session, user=user, rows=_rows(2))

    resp = await client.post(
        f"/api/v1/tabular/executions/{execution.id}/bulk-ops",
        headers=_bearer(user),
        json={
            "kind": "summarize_column",
            "column_name": "Term",
            "confirmed_cost_usd": "0.01",
        },
    )
    assert resp.status_code == 202, resp.text
    payload = resp.json()
    assert payload["execution_id"] == str(execution.id)
    assert payload["kind"] == "summarize_column"
    assert payload["status"] == "pending"
    assert payload["params"] == {"column_name": "Term"}
    assert payload["confirmed_cost_usd"] == "0.0100"
    assert payload["results"] is None
    assert enqueued == [uuid.UUID(payload["id"])]

    # Read-side: the op is embedded in the detail response.
    detail = await client.get(f"/api/v1/tabular/executions/{execution.id}", headers=_bearer(user))
    assert detail.status_code == 200, detail.text
    ops = detail.json()["bulk_ops"]
    assert [op["id"] for op in ops] == [payload["id"]]
    assert ops[0]["execution_id"] == str(execution.id)


@pytest.mark.integration
async def test_create_bulk_op_empty_grid_400(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed execution with zero grid rows has nothing to
    bulk-operate on — 400, no row created, nothing enqueued."""

    async def _fail_enqueue(bulk_op_id: uuid.UUID) -> bool:  # pragma: no cover
        raise AssertionError("must not enqueue")

    monkeypatch.setattr("app.api.tabular.enqueue_tabular_bulk_op_job", _fail_enqueue)

    user = await _make_user(db_session)
    execution = await _make_execution(db_session, user=user, rows=[])

    resp = await client.post(
        f"/api/v1/tabular/executions/{execution.id}/bulk-ops",
        headers=_bearer(user),
        json={"kind": "redline_rows"},
    )
    assert resp.status_code == 400
    assert "no results grid rows" in resp.json()["detail"]


@pytest.mark.integration
async def test_create_bulk_op_cross_user_404(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await _make_user(db_session)
    other = await _make_user(db_session)
    execution = await _make_execution(db_session, user=owner, rows=_rows(1))

    resp = await client.post(
        f"/api/v1/tabular/executions/{execution.id}/bulk-ops",
        headers=_bearer(other),
        json={"kind": "redline_rows"},
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_create_bulk_op_unknown_kind_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Kinds outside the closed set are a validation error."""

    user = await _make_user(db_session)
    execution = await _make_execution(db_session, user=user, rows=_rows(1))

    resp = await client.post(
        f"/api/v1/tabular/executions/{execution.id}/bulk-ops",
        headers=_bearer(user),
        json={"kind": "translate_rows"},
    )
    assert resp.status_code == 422
