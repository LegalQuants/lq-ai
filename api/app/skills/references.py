"""Bounded installed-reference snapshots, never persisted as policy or audit data."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from app.skills.capabilities import MAX_FILE_BYTES


def read_reference_snapshot(folder: Path, path: Path) -> str:
    """Read bounded UTF-8 through directory descriptors without following links.

    Holding each directory descriptor prevents parent-directory replacement
    from redirecting this read outside the installed skill.
    """
    relative = path.relative_to(folder)
    if not relative.parts or relative.parts[0] != "references":
        raise ValueError("not an installed reference")
    descriptors: list[int] = []
    try:
        descriptors.append(os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in relative.parts[:-1]:
            descriptors.append(
                os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptors[-1])
            )
        descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=descriptors[-1],
        )
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise ValueError("reference outside bounded text profile")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES or b"\x00" in data:
            raise ValueError("reference outside bounded text profile")
        return data.decode("utf-8")
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
