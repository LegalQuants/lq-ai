"""Optional, bounded skill capabilities. Declarations never grant execution."""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

FileName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$")]
HelperName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
MAX_FILE_BYTES = 65536
MAX_FILES = 32
MAX_WORKSPACE_BYTES = 1048576
MAX_INPUT_BYTES = 65536


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
