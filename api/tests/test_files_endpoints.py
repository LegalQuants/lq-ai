"""Integration tests for the C4 file-upload surface.

Covers the full M1-IMPLEMENTATION-ORDER C4 verification:

    Upload a PDF; verify it's in MinIO; download it via API; bytes match.

The MinIO client is mocked with the same in-memory fake from
``test_storage_streaming.py`` so the tests run without a live MinIO.
The DB is the same per-test SAVEPOINT-rolled-back session from
``conftest.py``.

What's tested:

* Auth gate (unauthenticated → 401, must_change_password → 403).
* Per-user isolation: a file owned by user A returns 404 to user B
  on GET, GET /content, and DELETE.
* Round-trip bytes-fidelity: upload a PDF-shaped binary, download via
  ``/content``, byte-compare equal.
* SHA-256 stability: the upload response carries the same hash as the
  one we compute on the client side.
* Size cap: a body larger than the configured limit returns 413 with
  ``code=payload_too_large``.
* Soft-delete: DELETE returns 204; GET returns 404 immediately after;
  a second DELETE also returns 404 (idempotent).
* Validation: non-UUID file_id → 400; missing filename → 400.
* MIME and Content-Disposition: response carries the stored MIME and an
  RFC 6266 Content-Disposition; non-ASCII filenames get an RFC 5987
  ``filename*`` parameter.
* `ingestion_status='pending'` set on insert (read back from DB).
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password
from tests.test_storage_streaming import FakeS3Client


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def fake_s3() -> FakeS3Client:
    return FakeS3Client()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, fake_s3: FakeS3Client) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with a fake S3 client patched in.

    Patches ``app.storage.s3_client`` to yield the in-memory fake. Note:
    we patch in *both* modules where ``s3_client`` is referenced — the
    handlers call through to ``app.storage.stream_upload`` etc., which
    read ``s3_client`` from the module's own namespace.
    """

    @asynccontextmanager
    async def _ctx() -> AsyncIterator[FakeS3Client]:
        yield fake_s3

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    with patch("app.storage.s3_client", _ctx):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"file-{uuid.uuid4().hex[:8]}@example.com",
        display_name="File Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    """A second user in the same DB; used for the per-user isolation test."""

    user = User(
        email=f"file-other-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Other File Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def gated_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"gated-file-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Gated File Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer_for(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


# A small "PDF-shaped" binary blob: a real PDF header + arbitrary bytes.
# Production users upload real PDFs; for the bytes-fidelity test we just
# need a non-trivial binary that won't get coerced into text by any
# layer of the stack.
PDF_PAYLOAD = (
    b"%PDF-1.7\n"
    b"%\xe2\xe3\xcf\xd3\n"  # Binary marker bytes the PDF spec recommends.
    + bytes(range(256)) * 8  # 2 KiB of every byte value.
    + b"%%EOF\n"
)


def _multipart_body(
    *,
    filename: str,
    content_type: str,
    payload: bytes,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the (files, headers) tuple for httpx multipart upload."""

    files = {
        "file": (filename, payload, content_type),
    }
    return files, {}


# ---------------------------------------------------------------------------
# Auth + gate
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_upload_unauthenticated_returns_401(client: AsyncClient) -> None:
    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"x")
    response = await client.post("/api/v1/files", files=files)
    assert response.status_code == 401


@pytest.mark.integration
async def test_upload_with_must_change_password_returns_403(
    client: AsyncClient, gated_user: User
) -> None:
    token = _bearer_for(gated_user)
    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"x")
    response = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "password_change_required"


@pytest.mark.integration
async def test_get_metadata_unauthenticated_returns_401(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/files/{uuid.uuid4()}")
    assert response.status_code == 401


@pytest.mark.integration
async def test_get_content_unauthenticated_returns_401(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/files/{uuid.uuid4()}/content")
    assert response.status_code == 401


@pytest.mark.integration
async def test_delete_unauthenticated_returns_401(client: AsyncClient) -> None:
    response = await client.delete(f"/api/v1/files/{uuid.uuid4()}")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_upload_without_file_part_returns_422(client: AsyncClient, db_user: User) -> None:
    """FastAPI's 422 (pydantic-driven) is fine here — no body, no file.

    422 comes from FastAPI's own form-parsing layer, not our typed
    ``ValidationError``. The C4 brief and OpenAPI sketch declare the
    upload body as required; FastAPI's default behavior matches.
    """

    token = _bearer_for(db_user)
    response = await client.post(
        "/api/v1/files",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_get_metadata_with_invalid_uuid_returns_400(
    client: AsyncClient, db_user: User
) -> None:
    token = _bearer_for(db_user)
    response = await client.get(
        "/api/v1/files/not-a-uuid",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "validation_error"


@pytest.mark.integration
async def test_get_content_with_invalid_uuid_returns_400(
    client: AsyncClient, db_user: User
) -> None:
    token = _bearer_for(db_user)
    response = await client.get(
        "/api/v1/files/not-a-uuid/content",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


@pytest.mark.integration
async def test_delete_with_invalid_uuid_returns_400(client: AsyncClient, db_user: User) -> None:
    token = _bearer_for(db_user)
    response = await client.delete(
        "/api/v1/files/not-a-uuid",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Happy-path round trip — the C4 verification step
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_upload_persists_metadata_and_returns_canonical_shape(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
    fake_s3: FakeS3Client,
) -> None:
    token = _bearer_for(db_user)
    files, _ = _multipart_body(
        filename="contract.pdf",
        content_type="application/pdf",
        payload=PDF_PAYLOAD,
    )
    response = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    # Wire shape mirrors the OpenAPI File schema.
    assert set(body.keys()) >= {
        "id",
        "owner_id",
        "filename",
        "mime_type",
        "size_bytes",
        "hash_sha256",
        "ingestion_status",
        "created_at",
    }
    assert body["filename"] == "contract.pdf"
    assert body["mime_type"] == "application/pdf"
    assert body["size_bytes"] == len(PDF_PAYLOAD)
    assert body["hash_sha256"] == hashlib.sha256(PDF_PAYLOAD).hexdigest()
    assert body["ingestion_status"] == "pending"
    assert body["owner_id"] == str(db_user.id)

    # The bytes landed in MinIO at the canonical key (the bare UUID).
    assert body["id"] in fake_s3.objects
    assert fake_s3.objects[body["id"]] == PDF_PAYLOAD


@pytest.mark.integration
async def test_round_trip_bytes_match_on_download(
    client: AsyncClient, db_user: User, fake_s3: FakeS3Client
) -> None:
    """C4's load-bearing verification: upload → download → bytes match."""

    token = _bearer_for(db_user)
    files, _ = _multipart_body(
        filename="contract.pdf",
        content_type="application/pdf",
        payload=PDF_PAYLOAD,
    )
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upload.status_code == 201
    file_id = upload.json()["id"]

    download = await client.get(
        f"/api/v1/files/{file_id}/content",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert download.status_code == 200
    assert download.content == PDF_PAYLOAD
    assert download.headers["content-type"] == "application/pdf"
    # Content-Disposition is the canonical RFC 6266 attachment form.
    assert download.headers["content-disposition"] == 'attachment; filename="contract.pdf"'
    # Defensive header — clients must not sniff a different MIME.
    assert download.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.integration
async def test_get_metadata_returns_pending_status(client: AsyncClient, db_user: User) -> None:
    token = _bearer_for(db_user)
    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"abc")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    file_id = upload.json()["id"]

    metadata = await client.get(
        f"/api/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert metadata.status_code == 200
    assert metadata.json()["ingestion_status"] == "pending"
    assert metadata.json()["page_count"] is None
    assert metadata.json()["character_count"] is None


# ---------------------------------------------------------------------------
# Per-user isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_other_user_cannot_get_metadata(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    token_a = _bearer_for(db_user)
    token_b = _bearer_for(other_user)

    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token_a}"},
    )
    file_id = upload.json()["id"]

    response = await client.get(
        f"/api/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    # 404, not 403 — the brief calls this out explicitly.
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


@pytest.mark.integration
async def test_other_user_cannot_get_content(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    token_a = _bearer_for(db_user)
    token_b = _bearer_for(other_user)

    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token_a}"},
    )
    file_id = upload.json()["id"]

    response = await client.get(
        f"/api/v1/files/{file_id}/content",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_other_user_cannot_delete(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    token_a = _bearer_for(db_user)
    token_b = _bearer_for(other_user)

    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token_a}"},
    )
    file_id = upload.json()["id"]

    response = await client.delete(
        f"/api/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Soft-delete
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_returns_204_then_get_returns_404(client: AsyncClient, db_user: User) -> None:
    token = _bearer_for(db_user)
    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    file_id = upload.json()["id"]

    deleted = await client.delete(
        f"/api/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 204

    after = await client.get(
        f"/api/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert after.status_code == 404


@pytest.mark.integration
async def test_delete_is_idempotent_on_already_deleted_file(
    client: AsyncClient, db_user: User
) -> None:
    token = _bearer_for(db_user)
    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    file_id = upload.json()["id"]

    first = await client.delete(
        f"/api/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 204

    second = await client.delete(
        f"/api/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Already-deleted file is no longer visible → 404.
    assert second.status_code == 404


@pytest.mark.integration
async def test_soft_delete_preserves_minio_bytes(
    client: AsyncClient, db_user: User, fake_s3: FakeS3Client
) -> None:
    """ADR 0004: soft-delete leaves the MinIO bytes intact."""

    token = _bearer_for(db_user)
    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    file_id = upload.json()["id"]
    assert file_id in fake_s3.objects

    deleted = await client.delete(
        f"/api/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 204

    # Bytes still live in MinIO; D6 / future GC reaps them later.
    assert file_id in fake_s3.objects


# ---------------------------------------------------------------------------
# Size cap
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_upload_oversized_body_returns_413(
    client: AsyncClient, db_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lower the size cap, then push a body that exceeds it."""

    from app.config import get_settings

    # Lower the cap to 1 MB for this test (cache_clear so the new value
    # is picked up by the next get_settings call inside the handler).
    monkeypatch.setenv("LQ_AI_MAX_UPLOAD_SIZE_MB", "1")
    get_settings.cache_clear()
    try:
        token = _bearer_for(db_user)
        # 2 MB body > 1 MB cap.
        oversized = b"X" * (2 * 1024 * 1024)
        files, _ = _multipart_body(
            filename="big.bin",
            content_type="application/octet-stream",
            payload=oversized,
        )
        response = await client.post(
            "/api/v1/files",
            files=files,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 413
        body = response.json()
        assert body["detail"]["code"] == "payload_too_large"
        assert body["detail"]["details"]["limit_bytes"] == 1 * 1024 * 1024
        assert body["detail"]["details"]["received_bytes"] >= 1 * 1024 * 1024
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 404 on unknown id
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_metadata_for_unknown_id_returns_404(client: AsyncClient, db_user: User) -> None:
    token = _bearer_for(db_user)
    response = await client.get(
        f"/api/v1/files/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_get_content_for_unknown_id_returns_404(client: AsyncClient, db_user: User) -> None:
    token = _bearer_for(db_user)
    response = await client.get(
        f"/api/v1/files/{uuid.uuid4()}/content",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_delete_for_unknown_id_returns_404(client: AsyncClient, db_user: User) -> None:
    token = _bearer_for(db_user)
    response = await client.delete(
        f"/api/v1/files/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Headers / Content-Disposition correctness
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_download_sets_filename_star_for_non_ascii(
    client: AsyncClient, db_user: User
) -> None:
    """Non-ASCII filenames produce an RFC 5987 ``filename*`` parameter."""

    token = _bearer_for(db_user)
    # "naïve résumé.pdf" — has accented letters that must be percent-encoded.
    fname = "naïve résumé.pdf"
    files, _ = _multipart_body(filename=fname, content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    file_id = upload.json()["id"]

    download = await client.get(
        f"/api/v1/files/{file_id}/content",
        headers={"Authorization": f"Bearer {token}"},
    )
    cd = download.headers["content-disposition"]
    # ASCII fallback is present (filename="..."), and the RFC 5987 form
    # ``filename*=UTF-8''<percent-encoded>`` is present.
    assert "filename=" in cd
    assert "filename*=UTF-8''" in cd
    # The percent-encoding is correct for the accented letters.
    assert "na%C3%AFve%20r%C3%A9sum%C3%A9.pdf" in cd


# ---------------------------------------------------------------------------
# DB shape sanity
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_inserted_row_has_storage_path_equal_to_id(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """ADR 0004 — storage_path is the bare file UUID."""

    token = _bearer_for(db_user)
    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    file_id = upload.json()["id"]

    row = (
        await db_session.execute(
            text("SELECT storage_path, ingestion_status FROM files WHERE id = :id"),
            {"id": file_id},
        )
    ).one()
    assert row.storage_path == file_id
    assert row.ingestion_status == "pending"


# ---------------------------------------------------------------------------
# M3-A6 Phase 6 prereq: document_id surfacing on the file metadata response
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_metadata_document_id_is_null_when_no_document_row(
    client: AsyncClient, db_user: User
) -> None:
    """Freshly uploaded file: no documents row yet → document_id is null.

    The C5 parse pipeline creates the row asynchronously; the wizard's
    Step 1 polls this endpoint until ``document_id`` flips non-null.
    """

    token = _bearer_for(db_user)
    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    file_id = upload.json()["id"]

    metadata = await client.get(
        f"/api/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert metadata.status_code == 200
    body = metadata.json()
    assert "document_id" in body, "document_id field must be present on the response"
    assert body["document_id"] is None


@pytest.mark.integration
async def test_get_metadata_includes_document_id_when_document_exists(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """Once the C5 pipeline has written a ``documents`` row for the file,
    GET /files/{id} surfaces the document UUID so the Easy Playbook wizard
    (M3-A6 Phase 6) can hand it to ``POST /playbooks/easy``.
    """

    from app.models.document import Document

    token = _bearer_for(db_user)
    files, _ = _multipart_body(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    file_id = upload.json()["id"]

    document = Document(
        id=uuid.uuid4(),
        file_id=uuid.UUID(file_id),
        parser="pymupdf",
        parser_version="test",
        normalized_content="hi",
    )
    db_session.add(document)
    await db_session.flush()

    metadata = await client.get(
        f"/api/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert metadata.status_code == 200
    body = metadata.json()
    assert body["document_id"] == str(document.id)
