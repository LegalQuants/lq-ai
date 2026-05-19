"""Easy Playbook generation pipeline — M3-A6.

Sub-package for the auto-generation pipeline that turns a corpus of
5-20 prior agreements into a drafted playbook. Phases:

* Phase 3 (this commit) — :mod:`.extractor`: per-document clause
  extraction via the ``playbook-easy-extract`` skill.
* Phase 4 — clustering + draft assembly (not yet landed).
* Phase 5 — orchestration + ARQ worker + endpoints (not yet landed).

Per-stage outputs are deliberately structural (no quality judgments);
the user-attorney evaluates the final assembled playbook, not any
intermediate. See PRD §3.7 + the M3-A6 prep doc at
``docs/superpowers/plans/2026-05-19-m3-a6-easy-playbook-wizard.md``.
"""

from app.playbooks.easy.extractor import (
    ExtractedClause,
    ExtractedClauseSourceOffsets,
    extract_clauses_from_document,
)

__all__ = [
    "ExtractedClause",
    "ExtractedClauseSourceOffsets",
    "extract_clauses_from_document",
]
