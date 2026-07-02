#!/usr/bin/env python3
"""Resolve markdown links in the given files against the repo tree.

Checks two link shapes and asserts the referenced repo path exists:
  1. relative markdown links:      [text](docs/foo.md)  or  [text](../adr/0018-x.md)
  2. GitHub blob links on main:    https://github.com/LegalQuants/lq-ai/blob/main/<path>
Anchors (#...) and pure-external URLs (http[s] not to our blob) are ignored.
Exit 1 (and print) if any link dangles.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # docs/audits/ -> repo root
BLOB = "https://github.com/LegalQuants/lq-ai/blob/main/"
LINK_RE = re.compile(r"\]\(([^)]+)\)")


def resolve(target: str, doc: Path) -> Path | None:
    target = target.split("#", 1)[0].strip()
    if not target:
        return None
    if target.startswith(BLOB):
        return REPO / target[len(BLOB):]
    if target.startswith(("http://", "https://", "mailto:")):
        return None  # external, not our concern
    return (doc.parent / target).resolve()


def main(files: list[str]) -> int:
    dangling: list[str] = []
    for f in files:
        doc = Path(f).resolve()
        for m in LINK_RE.finditer(doc.read_text(encoding="utf-8")):
            path = resolve(m.group(1), doc)
            if path is not None and not path.exists():
                dangling.append(f"{f}: {m.group(1)} -> {path}")
    for d in dangling:
        print("DANGLING:", d)
    print(f"{'FAIL' if dangling else 'OK'}: {len(dangling)} dangling link(s)")
    return 1 if dangling else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
