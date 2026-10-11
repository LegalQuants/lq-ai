#!/usr/bin/env python3
"""Check repo paths and inclusive line ranges in compliance code-cite markers.

Format: ``<!-- code-cite: api/app/example.py:12-34 -->``. Every bullet in
an OWASP structural-controls field must contain at least one marker. This
checks evidence locations, not whether the source substantiates the prose.
Only Python's standard library is required; no application or network calls.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

DEFAULT_DOCUMENT = "docs/compliance/owasp-llm-top10.md"
MARKER = re.compile(r"<!--\s*code-cite:\s*([\w./-]+):(\d+)-(\d+)\s*-->")
MARKER_START = re.compile(r"<!--\s*code-cite\b")
LINK = re.compile(r"\]\(([^\s)]+)\)")


def repository_path(root: Path, path: Path) -> Path:
    """Resolve a path inside the repository, including symlink containment."""
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("path leaves the repository")
    return resolved


def check_document(root: Path, document: str) -> tuple[int, list[str]]:
    """Return the marker count and actionable errors for one document."""
    errors: list[str] = []
    try:
        document_path = repository_path(root, Path(document))
        content = document_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        return 0, [f"{document}: cannot read document: {exc}"]

    markers = list(MARKER.finditer(content))
    if not markers:
        errors.append(f"{document}: no code-cite markers")
    if len(markers) != len(MARKER_START.findall(content)):
        errors.append(f"{document}: malformed code-cite marker (expected path:start-end)")

    line_counts: dict[Path, int] = {}
    for marker in markers:
        doc_line = content.count("\n", 0, marker.start()) + 1
        name, start_text, end_text = marker.groups()
        start, end = int(start_text), int(end_text)
        location = f"{document}:{doc_line}: {name}:{start}-{end}"
        if start < 1 or end < start:
            errors.append(f"{location}: invalid inclusive line range")
            continue
        try:
            target = repository_path(root, Path(name))
            if not target.is_file():
                raise ValueError("target is not a file")
            if target not in line_counts:
                line_counts[target] = len(target.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{location}: {exc}")
            continue
        if end > line_counts[target]:
            errors.append(f"{location}: file has only {line_counts[target]} lines")

    structural = False
    structural_bullets = 0
    for doc_line, line in enumerate(content.splitlines(), 1):
        if line.startswith("## "):
            structural = False
        elif line.startswith("**Structural controls (in code).**"):
            structural = True
        elif line.startswith("**"):
            structural = False
        elif structural and line.startswith("- "):
            structural_bullets += 1
            if MARKER.search(line) is None:
                errors.append(f"{document}:{doc_line}: structural claim has no code-cite")
    if not structural_bullets:
        errors.append(f"{document}: no structural-control bullets checked")

    # Also catch broken local document/config links. Remote sources and
    # fragment-only links need human review; this checker does not fetch them.
    for link in LINK.finditer(content):
        parsed = urlsplit(link.group(1))
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        doc_line = content.count("\n", 0, link.start()) + 1
        try:
            target = repository_path(root, document_path.parent / unquote(parsed.path))
            if not target.exists():
                raise ValueError("target does not exist")
        except (OSError, ValueError) as exc:
            errors.append(f"{document}:{doc_line}: link {link.group(1)}: {exc}")

    return len(markers), errors


def main() -> int:
    """Validate the mapping and exit nonzero on missing or invalid evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("documents", nargs="*", default=[DEFAULT_DOCUMENT])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    count = 0
    errors: list[str] = []
    for document in args.documents:
        checked, failures = check_document(args.root, document)
        count += checked
        errors.extend(failures)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Compliance citations: {count} file/line ranges checked; 0 errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
