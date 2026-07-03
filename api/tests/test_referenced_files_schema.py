"""referenced-files schema surface referenced_file_ids (pure Pydantic, no DB)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.chats import (
    MESSAGE_REFERENCED_FILES_MAX_LEN,
    MessageCreateRequest,
    MessagePostResponse,
    MessageResponse,
)


def _minimal_message_response() -> MessageResponse:
    """Construct MessageResponse with exactly its required fields."""
    return MessageResponse(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        chat_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        role="assistant",
        content="test",
        created_at=datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC),
    )


@pytest.mark.unit
class TestReferencedFileIds:
    def test_referenced_file_ids_defaults_empty(self) -> None:
        req = MessageCreateRequest(content="hi")
        assert req.referenced_file_ids == []

    def test_referenced_file_ids_accepts_list(self) -> None:
        ids = ["11111111-1111-1111-1111-111111111111"]
        req = MessageCreateRequest(content="hi", referenced_file_ids=ids)
        assert req.referenced_file_ids == ids

    def test_referenced_file_ids_over_cap_rejected(self) -> None:
        ids = ["11111111-1111-1111-1111-111111111111"] * (MESSAGE_REFERENCED_FILES_MAX_LEN + 1)
        with pytest.raises(ValidationError):
            MessageCreateRequest(content="hi", referenced_file_ids=ids)

    def test_applied_referenced_file_ids_defaults_empty(self) -> None:
        resp = MessagePostResponse(message=_minimal_message_response())
        assert resp.applied_referenced_file_ids == []
