"""Regression tests for invalid, missing and escaping compliance citations."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check-compliance-citations.py"
SPEC = importlib.util.spec_from_file_location("compliance_citations", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class ComplianceCitationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "source.py").write_text("first\nsecond\nthird\n", encoding="utf-8")

    def write_document(self, claim: str, extra: str = "") -> None:
        (self.root / "mapping.md").write_text(
            "## LLM01:2025 — Prompt Injection\n\n"
            "**Structural controls (in code).**\n\n"
            f"- {claim}\n\n"
            "**Residual risk.** Human review remains required.\n" + extra,
            encoding="utf-8",
        )

    def test_accepts_inclusive_first_and_last_lines(self) -> None:
        self.write_document("Evidence <!-- code-cite: source.py:1-3 -->")
        self.assertEqual(CHECKER.check_document(self.root, "mapping.md"), (1, []))

    def test_rejects_missing_file_directory_and_invalid_ranges(self) -> None:
        (self.root / "directory").mkdir()
        for marker in (
            "missing.py:1-1",
            "directory:1-1",
            "source.py:0-1",
            "source.py:3-2",
            "source.py:1-4",
        ):
            with self.subTest(marker=marker):
                self.write_document(f"Evidence <!-- code-cite: {marker} -->")
                self.assertTrue(CHECKER.check_document(self.root, "mapping.md")[1])

    def test_rejects_escaping_paths_and_symlinks(self) -> None:
        (self.root / "escape.py").symlink_to(self.root.parent / "outside.py")
        for name in ("../outside.py", "/outside.py", "escape.py"):
            with self.subTest(name=name):
                self.write_document(f"Evidence <!-- code-cite: {name}:1-1 -->")
                self.assertTrue(CHECKER.check_document(self.root, "mapping.md")[1])

    def test_rejects_missing_and_malformed_markers(self) -> None:
        for claim in ("No evidence", "Bad <!-- code-cite: source.py:one-three -->"):
            with self.subTest(claim=claim):
                self.write_document(claim)
                self.assertTrue(CHECKER.check_document(self.root, "mapping.md")[1])

    def test_requires_evidence_on_each_structural_bullet(self) -> None:
        self.write_document("Evidence <!-- code-cite: source.py:1-1 -->\n- Missing")
        errors = CHECKER.check_document(self.root, "mapping.md")[1]
        self.assertTrue(any("structural claim has no code-cite" in error for error in errors))

    def test_requires_structural_fields(self) -> None:
        (self.root / "mapping.md").write_text("<!-- code-cite: source.py:1-1 -->", encoding="utf-8")
        self.assertTrue(CHECKER.check_document(self.root, "mapping.md")[1])

    def test_checks_local_links_without_fetching_remote_links(self) -> None:
        self.write_document(
            "Evidence <!-- code-cite: source.py:1-1 -->",
            "[valid](source.py#L1) [external](https://example.com/missing) [section](#scope)",
        )
        self.assertEqual(CHECKER.check_document(self.root, "mapping.md")[1], [])
        self.write_document("Evidence <!-- code-cite: source.py:1-1 -->", "[broken](missing.md)")
        self.assertTrue(CHECKER.check_document(self.root, "mapping.md")[1])

    def test_cli_fails_when_a_cited_file_is_removed(self) -> None:
        self.write_document("Evidence <!-- code-cite: source.py:1-3 -->")
        command = [sys.executable, str(SCRIPT), "--root", str(self.root), "mapping.md"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.root / "source.py").unlink()
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("target is not a file", result.stderr)


if __name__ == "__main__":
    unittest.main()
