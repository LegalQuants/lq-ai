"""Large references remain discoverable; each explicit call returns one bound range."""

import hashlib
from pathlib import Path

import pytest

from app.errors import ToolNotGranted
from app.skills.binding import SkillBinding, bind_record
from app.skills.capabilities import ReferenceRead
from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry
from app.skills.tools import SkillTools
from tests.skills.reference_helpers import saif_reference


def installed(tmp_path: Path, raw: bytes) -> tuple[Path, Path, MutableSkillRegistry, SkillBinding]:
    folder = tmp_path / "large-demo"
    (folder / "references").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: large-demo\ndescription: Synthetic range fixture\n---\nRead on request.\n"
    )
    path = folder / "references/enforcement_actions.json"
    path.write_bytes(raw)
    holder = MutableSkillRegistry(load_registry(tmp_path))
    record = holder.current().get("large-demo")
    assert record is not None
    return folder, path, holder, bind_record(record)


@pytest.mark.parametrize("size", [0, 65535, 65536, 65537, 208564])
def test_files_remain_discoverable_and_ranges_cover_exact_bytes(tmp_path: Path, size: int) -> None:
    raw = saif_reference() if size == 208564 else b"x" * size
    _folder, _path, holder, binding = installed(tmp_path, raw)
    detail = holder.current().get_skill("large-demo")
    assert detail is not None
    assert [(f.path, f.size_bytes) for f in detail.on_demand_files] == [
        ("references/enforcement_actions.json", size)
    ]
    assert len(binding.reference_snapshots[0][1].content.encode()) <= 65536
    service = SkillTools(holder)
    cursor = 0
    pieces = []
    calls = 0
    while True:
        page = service.read_reference(
            binding, ReferenceRead(path="references/enforcement_actions.json", offset_bytes=cursor)
        )
        calls += 1
        piece = page["content"].encode()
        assert page["size_bytes"] == size
        assert page["sha256"] == hashlib.sha256(raw).hexdigest()
        assert page["offset_bytes"] == cursor
        assert page["returned_bytes"] == len(piece) <= 65536
        cursor += len(piece)
        assert page["end_offset_bytes"] == cursor
        pieces.append(piece)
        assert page["has_more"] is (cursor < size)
        if not page["has_more"]:
            assert page["next_offset_bytes"] is None
            break
        assert page["next_offset_bytes"] == cursor
    assert b"".join(pieces) == raw
    assert calls == max(1, (size + 65535) // 65536)
    if size == 208564:
        assert [len(piece) for piece in pieces] == [65536, 65536, 65536, 11956]


def test_utf8_boundaries_and_invalid_offsets_are_explicit(tmp_path: Path) -> None:
    raw = ("a" * 65535 + "🚀" + "é" * 200).encode()
    _, _, holder, binding = installed(tmp_path, raw)
    service = SkillTools(holder)
    first = service.read_reference(binding, ReferenceRead(path=binding.reference_paths[0]))
    assert first["returned_bytes"] == first["next_offset_bytes"] == 65535
    second = service.read_reference(
        binding, ReferenceRead(path=binding.reference_paths[0], offset_bytes=65535)
    )
    assert second["content"].startswith("🚀") and not second["has_more"]
    for offset in (65536, len(raw) + 1):
        refused = service.read_reference(
            binding, ReferenceRead(path=binding.reference_paths[0], offset_bytes=offset)
        )
        assert refused["error"] == "invalid_range"
    too_small = service.read_reference(
        binding, ReferenceRead(path=binding.reference_paths[0], offset_bytes=65535, max_bytes=1)
    )
    assert too_small["error"] == "invalid_range"
    end = service.read_reference(
        binding, ReferenceRead(path=binding.reference_paths[0], offset_bytes=len(raw))
    )
    assert end["returned_bytes"] == 0 and end["has_more"] is False


@pytest.mark.parametrize("change", ["replace", "remove", "symlink"])
def test_later_page_refuses_changed_or_redirected_file(tmp_path: Path, change: str) -> None:
    _, path, holder, binding = installed(tmp_path, saif_reference())
    service = SkillTools(holder)
    first = service.read_reference(binding, ReferenceRead(path=binding.reference_paths[0]))
    if change == "replace":
        raw = bytearray(saif_reference())
        raw[-1] = ord(" ") if raw[-1] != ord(" ") else ord("x")
        path.write_bytes(raw)
    elif change == "remove":
        path.unlink()
    else:
        outside = tmp_path / "outside.json"
        outside.write_bytes(saif_reference())
        path.unlink()
        path.symlink_to(outside)
    with pytest.raises(ToolNotGranted):
        service.read_reference(
            binding,
            ReferenceRead(path=binding.reference_paths[0], offset_bytes=first["next_offset_bytes"]),
        )


def test_invalid_utf8_or_nul_beyond_first_range_is_not_admitted(tmp_path: Path) -> None:
    for tail in (b"\xff", b"\x00"):
        root = tmp_path / tail.hex()
        root.mkdir()
        _folder, path, _holder, _ = installed(root, b"x" * 70000)
        path.write_bytes(b"x" * 70000 + tail)
        record = load_registry(root).get("large-demo")
        assert record is not None and not record.on_demand_paths


@pytest.mark.parametrize(
    "params",
    [
        {"offset_bytes": -1},
        {"offset_bytes": True},
        {"max_bytes": 0},
        {"max_bytes": 65537},
        {"max_bytes": True},
    ],
)
def test_range_arguments_are_strict_and_bounded(params: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ReferenceRead.model_validate({"path": "references/guide.md", **params})
