"""Transparency & governance invariants — structural CI gates (ADR 0016).

These tests do not exercise behaviour; they pin the *posture* invariants
that ADR 0016 makes binding, so a future change that quietly violates one
fails CI at collection rather than slipping past review. Each test is
designed to be green on current ``main`` and to trip only on a genuine
violation, with an explicit, documented escape hatch (an allowlist a
contributor must consciously extend) rather than a blunt grep.

Mapped invariants:

* **P1 — one audited egress boundary:** the backend makes no direct
  third-party HTTP calls (``test_backend_makes_no_direct_third_party_egress``).
* **P3 — counts/types, never payloads:** no audit/log model carries a
  raw-content column (``test_audit_models_have_no_raw_payload_columns``).
* **P4 — fail restrictive:** the tier fail-safe is the most-restrictive
  tier (``test_fail_safe_tier_is_most_restrictive``).
* **P5 — atomic audit:** the audit/governance helpers flush, never commit
  (``test_governance_and_audit_helpers_do_not_commit``).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from sqlalchemy import Table

import app
from app.models.audit import AuditLog
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.citation_treatment_signal import CitationTreatmentSignal
from app.models.inference import InferenceRoutingLog
from app.models.tool_call_log import ToolCallLog
from app.models.tool_egress import ToolEgressLog
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
from app.tools.governance import _MAX_TIER

# Root of the importable ``app`` package (``api/app``).
_APP_DIR = Path(app.__file__).resolve().parent


# ─────────────────────────────────────────────────────────────────────────────
# P3 — counts/types, never payloads
# ─────────────────────────────────────────────────────────────────────────────

# Every model whose entire purpose is an audit/log row. If a column name on
# one of these implies it holds raw content, that is a P3 violation.
_AUDIT_MODELS: tuple[type, ...] = (
    ToolCallLog,
    AuditLog,
    ToolEgressLog,
    InferenceRoutingLog,
    CitationLedgerEntry,
    CitationTreatment,
    CitationTreatmentSignal,
    WorkProductFiduciaryGate,
)

# Column names that, by name alone, signal raw-content storage. Matched
# case-insensitively as an exact name, a suffix, or a prefix — chosen so the
# legitimate columns on the audit models today (e.g. ``args_digest``,
# ``details``, ``refusal_reason``, ``user_agent``) do NOT trip.
_DENIED_EXACT: frozenset[str] = frozenset(
    {
        "body",
        "content",
        "payload",
        "plaintext",
        "raw",
        "args",
        "arguments",
        "result",
        "results",
        "response",
        "prompt",
        "completion",
        "message",
        "text",
        "query",
        "input",
        "output",
    }
)
_DENIED_SUFFIX: tuple[str, ...] = (
    "_body",
    "_payload",
    "_content",
    "_plaintext",
    "_text",
    "_raw",
    "_args",
    "_arguments",
    "_result",
    "_results",
    "_response",
    "_prompt",
    "_completion",
    "_message",
)
_DENIED_PREFIX: tuple[str, ...] = ("raw_", "plaintext_")

# Intentional, reviewed exceptions, keyed by (table_name, column_name). Empty
# today: a contributor who genuinely needs a content-bearing column on an audit
# model must add it here in the same PR, which forces the decision into review.
_ALLOWED_CONTENT_COLUMNS: frozenset[tuple[str, str]] = frozenset()


def _implies_raw_content(column_name: str) -> bool:
    name = column_name.lower()
    return name in _DENIED_EXACT or name.endswith(_DENIED_SUFFIX) or name.startswith(_DENIED_PREFIX)


@pytest.mark.unit
def test_audit_models_have_no_raw_payload_columns() -> None:
    """P3: audit/log rows record counts and types, never raw payloads.

    Adding a content-bearing column to an audit model is the most likely
    way to silently turn an auditable surface into a black box, so the
    column names themselves are the tripwire.
    """
    offenders: list[str] = []
    for model in _AUDIT_MODELS:
        table: Table = model.__table__  # type: ignore[attr-defined]
        for column in table.columns:
            if (table.name, column.name) in _ALLOWED_CONTENT_COLUMNS:
                continue
            if _implies_raw_content(column.name):
                offenders.append(f"{table.name}.{column.name}")

    assert not offenders, (
        "Audit/log models must store counts and types only, never raw payloads "
        f"(ADR 0016 P3). Columns whose names imply raw content: {offenders}. "
        "If a column genuinely needs a content-style name, justify it in review "
        "and add it to _ALLOWED_CONTENT_COLUMNS in this file."
    )


# ─────────────────────────────────────────────────────────────────────────────
# P5 — atomic audit: the helpers flush, never commit
# ─────────────────────────────────────────────────────────────────────────────

# Helpers that MUST ride the caller's transaction (flush-not-commit) so an
# audit row and the state change it describes are committed together.
_FLUSH_ONLY_MODULES: tuple[Path, ...] = (
    _APP_DIR / "audit.py",
    _APP_DIR / "tools" / "governance.py",
)


def _calls_commit(source: str) -> bool:
    """True if *source* contains a ``<expr>.commit(...)`` call.

    AST-based so that docstring / comment mentions of ``commit`` (e.g. the
    ``audit.py`` docstring that documents the caller's commit) do not match.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "commit"
        ):
            return True
    return False


@pytest.mark.unit
def test_governance_and_audit_helpers_do_not_commit() -> None:
    """P5: the audit/governance helpers flush, never commit.

    Committing inside a helper would let an audit row land in its own
    transaction, decoupling it from the state change it is supposed to
    describe (the audit-without-state-change / state-change-without-audit
    failure modes ADR 0016 P5 forbids).
    """
    offenders: list[str] = []
    for module_path in _FLUSH_ONLY_MODULES:
        assert module_path.exists(), f"expected helper module missing: {module_path}"
        if _calls_commit(module_path.read_text(encoding="utf-8")):
            offenders.append(str(module_path.relative_to(_APP_DIR.parent)))

    assert not offenders, (
        "Audit/governance helpers must flush, not commit, so audit rows ride "
        f"the caller's transaction (ADR 0016 P5). Offending modules: {offenders}."
    )


# ─────────────────────────────────────────────────────────────────────────────
# P1 — one audited egress boundary
# ─────────────────────────────────────────────────────────────────────────────

# Only this module may construct an outbound HTTP client: it is the backend's
# single door to the gateway, which is itself the only egress boundary (ADR
# 0014). Paths are relative to the ``app`` package root.
_EGRESS_ALLOWLIST: frozenset[str] = frozenset({"clients/gateway.py"})

# Import forms that pull in a general-purpose outbound HTTP client. Targeted at
# import statements (not prose) to avoid false positives on words like
# "requests" in comments.
_HTTP_CLIENT_IMPORTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*import\s+httpx\b", re.MULTILINE),
    re.compile(r"^\s*from\s+httpx\b", re.MULTILINE),
    re.compile(r"^\s*import\s+requests\b", re.MULTILINE),
    re.compile(r"^\s*from\s+requests\b", re.MULTILINE),
    re.compile(r"^\s*import\s+aiohttp\b", re.MULTILINE),
    re.compile(r"^\s*from\s+aiohttp\b", re.MULTILINE),
    re.compile(r"^\s*import\s+urllib\.request\b", re.MULTILINE),
    re.compile(r"^\s*from\s+urllib\.request\b", re.MULTILINE),
)


@pytest.mark.unit
def test_backend_makes_no_direct_third_party_egress() -> None:
    """P1: the backend egresses only through the gateway.

    The backend holds no third-party credentials and makes no third-party
    calls (ADR 0014 D1). The single door is the gateway client; any other
    module importing a general-purpose HTTP client is a new, un-audited
    egress path.
    """
    offenders: list[str] = []
    for path in _APP_DIR.rglob("*.py"):
        rel = path.relative_to(_APP_DIR).as_posix()
        if rel in _EGRESS_ALLOWLIST:
            continue
        source = path.read_text(encoding="utf-8")
        if any(pattern.search(source) for pattern in _HTTP_CLIENT_IMPORTS):
            offenders.append(rel)

    assert not offenders, (
        "All third-party egress must go through the gateway (ADR 0016 P1 / ADR "
        f"0014). Modules importing an outbound HTTP client directly: {offenders}. "
        "Route the call through app.clients.gateway, or — if this is genuinely a "
        "new audited boundary — record the decision and extend _EGRESS_ALLOWLIST."
    )


# ─────────────────────────────────────────────────────────────────────────────
# P4 — fail restrictive
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_fail_safe_tier_is_most_restrictive() -> None:
    """P4: the tier fail-safe is the most-restrictive egress tier.

    ``resolve_provider_tier`` returns ``_MAX_TIER`` when the gateway config
    is absent or a provider is unknown. Egress tiers run 0 (least
    sensitive) … 5 (most restrictive); the fail-safe must be 5 so a missing
    config fails closed, never open.
    """
    most_restrictive_egress_tier = 5
    assert most_restrictive_egress_tier == _MAX_TIER, (
        "The tier fail-safe must be the most-restrictive tier so missing config "
        f"fails closed (ADR 0016 P4); got _MAX_TIER={_MAX_TIER}."
    )
