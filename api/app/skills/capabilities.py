"""Optional, bounded skill capabilities. Declarations never grant execution."""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FileName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$")]
HelperName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
MAX_FILE_BYTES = 65536
MAX_FILES = 32
MAX_WORKSPACE_BYTES = 1048576
MAX_INPUT_BYTES = 65536
MAX_REFERENCE_FILES = 64
REFERENCE_PATH_PATTERN = r"^references(/[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}){1,6}$"
ReferencePath = Annotated[str, Field(pattern=REFERENCE_PATH_PATTERN, max_length=255)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BundledScript(StrictModel):
    name: HelperName
    description: Annotated[str, Field(min_length=1, max_length=500)]


class SkillCapabilities(StrictModel):
    workspace_version: Annotated[int, Field(strict=True, ge=1, le=1000)] | None = None
    scripts: Annotated[tuple[BundledScript, ...], Field(max_length=8)] = ()

    @field_validator("scripts")
    @classmethod
    def unique_helpers(cls, value: tuple[BundledScript, ...]) -> tuple[BundledScript, ...]:
        if len({script.name for script in value}) != len(value):
            raise ValueError("duplicate script")
        return value


class FileRead(StrictModel):
    name: FileName


class ReferenceRead(StrictModel):
    """One of the skill's own ``references/`` files, by its listed path."""

    path: ReferencePath
    offset_bytes: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)] = 0
    max_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_FILE_BYTES)] = MAX_FILE_BYTES


class ReferenceReadResult(StrictModel):
    """An exact UTF-8 byte range; more content requires another explicit call."""

    path: ReferencePath
    content: str
    size_bytes: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
    offset_bytes: Annotated[int, Field(strict=True, ge=0)]
    end_offset_bytes: Annotated[int, Field(strict=True, ge=0)]
    returned_bytes: Annotated[int, Field(strict=True, ge=0, le=MAX_FILE_BYTES)]
    has_more: Annotated[bool, Field(strict=True)]
    next_offset_bytes: Annotated[int, Field(strict=True, ge=0)] | None
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def exact_range(self) -> ReferenceReadResult:
        raw = self.content.encode("utf-8")
        if (
            b"\x00" in raw
            or len(raw) != self.returned_bytes
            or not 0 <= self.offset_bytes <= self.end_offset_bytes <= self.size_bytes
            or self.end_offset_bytes != self.offset_bytes + self.returned_bytes
            or self.has_more != (self.end_offset_bytes < self.size_bytes)
            or self.next_offset_bytes != (self.end_offset_bytes if self.has_more else None)
            or (self.has_more and not self.returned_bytes)
        ):
            raise ValueError("invalid bounded reference range")
        return self


class FileWrite(FileRead):
    expected_revision: UUID | None
    content: str

    @field_validator("content")
    @classmethod
    def bounded_text(cls, value: str) -> str:
        if "\x00" in value or len(value.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("content must be UTF-8 text of at most 64 KiB without NUL")
        return value


class ScriptInput(StrictModel):
    script: HelperName
    inputs: dict[str, Any] = Field(default_factory=dict)

    @field_validator("inputs")
    @classmethod
    def bounded_input(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("script input exceeds 64 KiB")
        return json.loads(encoded)


class EmptyInput(StrictModel):
    pass
