"""Independent assertions for the reference range contract."""

import gzip
import hashlib
from pathlib import Path
from typing import Any


def whole_page(path: str, content: str) -> dict[str, Any]:
    size = len(content.encode("utf-8"))
    return {
        "path": path,
        "content": content,
        "size_bytes": size,
        "offset_bytes": 0,
        "end_offset_bytes": size,
        "returned_bytes": size,
        "has_more": False,
        "next_offset_bytes": None,
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
    }


def saif_reference() -> bytes:
    path = (
        Path(__file__).resolve().parents[1] / "fixtures/reference-large/enforcement_actions.json.gz"
    )
    with gzip.open(path, "rb") as stream:
        raw = stream.read(208565)
        assert len(raw) == 208564 and not stream.read(1)
    return raw
