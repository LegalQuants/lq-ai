"""Stream-validated installed reference snapshots and bounded UTF-8 ranges."""

from __future__ import annotations

import codecs
import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from app.skills.capabilities import MAX_FILE_BYTES, ReferenceReadResult


class ReferenceRangeError(ValueError):
    """A valid reference was requested at an unavailable UTF-8 byte boundary."""


def bounded_utf8(data: bytes) -> str:
    """Never split a codepoint at the end or reinterpret a continuation offset."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.reason == "unexpected end of data" and exc.end == len(data):
            if exc.start:
                return data[: exc.start].decode("utf-8")
            raise ReferenceRangeError("max_bytes must fit the next UTF-8 character") from None
        raise ReferenceRangeError("offset_bytes must be a UTF-8 character boundary") from None


@dataclass(frozen=True)
class ReferenceSnapshot:
    size_bytes: int
    sha256: str
    content: str = field(repr=False, compare=False)
    offset_bytes: int = field(default=0, repr=False, compare=False)

    def page(self, path: str, max_bytes: int = MAX_FILE_BYTES) -> dict[str, object]:
        content = bounded_utf8(self.content.encode("utf-8")[:max_bytes])
        returned = len(content.encode("utf-8"))
        end = self.offset_bytes + returned
        more = end < self.size_bytes
        return ReferenceReadResult(
            path=path,
            content=content,
            size_bytes=self.size_bytes,
            offset_bytes=self.offset_bytes,
            end_offset_bytes=end,
            returned_bytes=returned,
            has_more=more,
            next_offset_bytes=end if more else None,
            sha256=self.sha256,
        ).model_dump()


def read_reference_snapshot(
    folder: Path,
    path: Path,
    *,
    offset_bytes: int = 0,
    max_bytes: int = MAX_FILE_BYTES,
    expected: ReferenceSnapshot | None = None,
) -> ReferenceSnapshot:
    """Hash/validate the entire file in bounded buffers, retaining only one range.

    No-follow directory descriptors prevent parent replacement from redirecting
    the read. A later page is returned only from bytes whose full-file hash still
    matches the bound snapshot. Memory does not grow with the installed file.
    """
    relative = path.relative_to(folder)
    if not relative.parts or relative.parts[0] != "references" or ".." in relative.parts:
        raise ValueError("not an installed reference")
    descriptors: list[int] = []
    try:
        descriptors.append(os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in relative.parts[:-1]:
            descriptors.append(
                os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptors[-1])
            )
        descriptor = os.open(
            relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptors[-1]
        )
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("reference is not a regular file")
        if offset_bytes > info.st_size:
            raise ReferenceRangeError("offset_bytes exceeds the file size")
        decoder = codecs.getincrementaldecoder("utf-8")()
        digest = hashlib.sha256()
        captured = bytearray()
        position = 0
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            while position < info.st_size:
                chunk = stream.read(min(MAX_FILE_BYTES, info.st_size - position))
                if not chunk:
                    raise ValueError("reference changed during read")
                if b"\x00" in chunk:
                    raise ValueError("reference contains NUL")
                decoder.decode(chunk, final=False)
                digest.update(chunk)
                start = max(offset_bytes - position, 0)
                stop = min(offset_bytes + max_bytes - position, len(chunk))
                if start < stop:
                    captured.extend(chunk[start:stop])
                position += len(chunk)
            decoder.decode(b"", final=True)
            if stream.read(1):
                raise ValueError("reference grew during read")
        after = os.fstat(descriptor)
        if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("reference changed during read")
        sha256 = digest.hexdigest()
        if expected and (expected.size_bytes != position or expected.sha256 != sha256):
            raise ValueError("reference changed since binding")
        return ReferenceSnapshot(position, sha256, bounded_utf8(bytes(captured)), offset_bytes)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
