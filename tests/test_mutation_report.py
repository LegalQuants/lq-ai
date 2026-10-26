"""Regression checks for empty, interrupted and misleading mutation evidence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.mutation_report import build_report, write_summary


class MutationReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "pyproject.toml"
        self.config.write_text(
            '[tool.mutmut]\nonly_mutate = ["app/example.py"]\n'
            'pytest_add_cli_args_test_selection = ["tests/test_example.py"]\n'
        )
        self.lock = self.root / "uv.lock"
        self.lock.write_text("version = 1\n")
        self.stats = self.root / "stats.json"
        self.test_stats = self.root / "test-stats.json"
        self.test_stats.write_text(json.dumps({"duration_by_test": {"test_example": 0.1}}))
        self.counts = {
            "total": 10,
            "killed": 6,
            "survived": 1,
            "no_tests": 1,
            "skipped": 1,
            "timeout": 1,
            "suspicious": 0,
            "check_was_interrupted_by_user": 0,
            "segfault": 0,
        }

    def report(self, outcome: str = "success") -> dict:
        self.stats.write_text(json.dumps(self.counts))
        return build_report(
            package="gateway",
            stats_path=self.stats,
            test_stats_path=self.test_stats,
            config_path=self.config,
            lock_path=self.lock,
            commit="abc123",
            run_url="https://example.invalid/run/1",
            run_outcome=outcome,
            tool_version="3.6.0",
            duration_seconds="12",
        )

    def test_no_tests_and_timeouts_count_against_score(self) -> None:
        report = self.report()
        self.assertEqual(report["status"], "valid")
        self.assertEqual(report["mutation_score_percent"], 66.67)
        self.assertEqual(report["modules"], ["app/example.py"])
        self.assertEqual(len(report["lock_sha256"]), 64)

    def test_empty_or_all_skipped_is_unavailable(self) -> None:
        for skipped in (0, 10):
            with self.subTest(skipped=skipped):
                self.counts = dict.fromkeys(self.counts, 0)
                self.counts.update(total=skipped, skipped=skipped)
                self.assertEqual(self.report()["status"], "unavailable")

    def test_unchecked_mutants_cannot_be_published(self) -> None:
        self.counts["total"] += 1
        self.assertEqual(self.report()["status"], "unavailable")

    def test_interrupted_or_error_outcomes_cannot_be_published(self) -> None:
        for key in ("check_was_interrupted_by_user", "segfault", "suspicious"):
            with self.subTest(key=key):
                self.counts[key] = 1
                self.counts["survived"] = 0
                report = self.report()
                self.assertEqual(report["status"], "unavailable")
                self.assertIsNone(report["mutation_score_percent"])
                self.counts[key] = 0
                self.counts["survived"] = 1

    def test_missing_test_execution_is_unavailable(self) -> None:
        self.test_stats.write_text('{"duration_by_test": {}}')
        self.assertEqual(self.report()["status"], "unavailable")

    def test_failed_run_never_reuses_a_score(self) -> None:
        self.assertEqual(self.report("failure")["status"], "unavailable")

    def test_missing_export_is_unavailable(self) -> None:
        self.report()
        self.stats.unlink()
        report = build_report(
            package="api",
            stats_path=self.stats,
            test_stats_path=self.test_stats,
            config_path=self.config,
            lock_path=self.lock,
            commit="abc123",
            run_url="",
            run_outcome="success",
            tool_version="3.6.0",
            duration_seconds="",
        )
        self.assertEqual(report["status"], "unavailable")

    def test_invalid_counts_are_rejected(self) -> None:
        for value in (-1, True, "6", 6.5):
            with self.subTest(value=value):
                self.counts["killed"] = value
                self.assertEqual(self.report()["status"], "unavailable")

    def test_unavailable_summary_does_not_print_a_percentage(self) -> None:
        path = self.root / "summary.md"
        write_summary(self.report("failure"), path)
        self.assertNotIn("%", path.read_text())
        self.assertIn("unavailable", path.read_text())


if __name__ == "__main__":
    unittest.main()
