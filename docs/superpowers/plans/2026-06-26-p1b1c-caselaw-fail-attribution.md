# P1-B1c — Caselaw FAIL tier via H3 attribution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flag a fabricated/misquoted caselaw quote by attributing each blockquote to its nearest `### Case` H3 heading, matching that case to one consulted opinion, judging the passage against that opinion only, and persisting a FAIL row on reject — without false-positives on legitimate non-caselaw blockquotes.

**Architecture:** Two new pure helpers in `api/app/citation/caselaw.py` (`attribute_passages`, `match_case_name`/`normalize_case_name`) parse and match the attribution signal. The orchestrator `verify_and_persist_caselaw_citations` gains an attribution-aware judge pass: confidently-attributed passages are judged against their one opinion (reject → FAIL row; over-budget → unverified FAIL row; transient error → drop), while unattributed passages keep B1b's all-opinions SUPPORTED-or-drop behavior exactly. FAIL is strictly additive on top of B1b.

**Tech Stack:** Python 3.12, async SQLAlchemy, FastAPI, pytest/pytest-asyncio. Reuses B1b's `judge_case_content` + per-turn cost budget. No new dependency.

## Global Constraints

- **No migration.** FAIL rows are `verified=False, verification_method=NULL`; they already satisfy every `message_caselaw_citations` CHECK (`chk_message_caselaw_citations_verified_has_method` requires a method only when `verified=True`). Do not add or alter a migration. Next migration number stays `0061` for the next slice.
- **No gate / ledger / UI / call-site-signature change.** `assemble_ledger_entries` already maps `verified=False → "unverified"` (`ledger.py:86`), the gate already maps `"unverified" → flagged`, and the ledger never reads caselaw offsets. Touch only `api/app/citation/caselaw.py` (+ its tests).
- **Additive guarantee.** A passage that is NOT confidently attributed (normalized-exact single-match to one consulted cluster with loaded opinion text) must behave **byte-for-byte as on `main` today**. Verbatim loop unchanged; `gateway=None` path unchanged.
- **Conservative bias.** A false FAIL (flagging a good draft) is worse than a missed FAIL. When in doubt, drop.
- **Offsets for a FAIL row:** `source_offset_start=0, source_offset_end=len(passage)` (passage is non-empty by construction). Documented placeholder; never surfaced (ledger/trace ignore caselaw offsets — confirmed `ledger.py:78-91`).
- **Tests:** host venv + throwaway pgvector (`lqai-test-pg` on `:55432`, conftest auto-migrates). Mocked gateway → **no `-m provider`**. Run `ruff format` AND `ruff check` on touched files before each commit.
- **Commits:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Security-gated** (`api/app/citation/**`): **do not self-merge**; Kevin/security merges; mirror `origin/main → tucuxi` after.

---

### Task 1: `attribute_passages` — pair each blockquote with its nearest `### Case` heading

**Files:**
- Modify: `api/app/citation/caselaw.py` (add `AttributedPassage` dataclass + `attribute_passages`; re-express `extract_blockquote_passages` in terms of it)
- Test: `api/tests/citation/test_caselaw_extraction.py` (extend — existing tests must stay green)

**Interfaces:**
- Consumes: nothing (pure function over `str`).
- Produces:
  ```python
  @dataclass(slots=True)
  class AttributedPassage:
      passage: str
      case_name: str | None
  def attribute_passages(answer_text: str) -> list[AttributedPassage]
  def extract_blockquote_passages(answer_text: str) -> list[str]  # == [a.passage for a in attribute_passages(text)]
  ```

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/citation/test_caselaw_extraction.py`:

```python
from app.citation.caselaw import AttributedPassage, attribute_passages


def test_attributes_blockquote_to_nearest_h3_case() -> None:
    answer = (
        "### Brown v. Board of Education, U.S. Supreme Court, 1954 (347 U.S. 483)\n"
        "\n**Relevant passage:**\n"
        "> Separate educational facilities are inherently unequal.\n"
    )
    assert attribute_passages(answer) == [
        AttributedPassage(
            passage="Separate educational facilities are inherently unequal.",
            case_name="Brown v. Board of Education",
        )
    ]


def test_blockquote_with_no_preceding_h3_has_none_case_name() -> None:
    answer = "> some emphasis quote with no case heading above it\n"
    assert attribute_passages(answer) == [
        AttributedPassage(passage="some emphasis quote with no case heading above it", case_name=None)
    ]


def test_uses_nearest_preceding_h3_when_prose_separates() -> None:
    answer = (
        "### Palsgraf v. Long Island R.R., N.Y., 1928\n"
        "What was retrieved: the opinion discusses proximate cause.\n"
        "How this bears: relevant to foreseeability.\n"
        "> The risk reasonably to be perceived defines the duty to be obeyed.\n"
    )
    result = attribute_passages(answer)
    assert result == [
        AttributedPassage(
            passage="The risk reasonably to be perceived defines the duty to be obeyed.",
            case_name="Palsgraf v. Long Island R.R.",
        )
    ]


def test_case_name_is_text_before_first_comma() -> None:
    # The skill format is "### [Case Name], [Court], [Year] ([Citation])".
    answer = "### Roe v. Wade, U.S., 1973 (410 U.S. 113)\n> a passage\n"
    assert attribute_passages(answer)[0].case_name == "Roe v. Wade"


def test_non_h3_headings_do_not_attribute() -> None:
    # A "## Gaps and caveats" section (level-2) must not attribute its content.
    answer = "## Gaps and caveats\n> not a case passage\n"
    assert attribute_passages(answer) == [
        AttributedPassage(passage="not a case passage", case_name=None)
    ]


def test_later_h3_resets_attribution_for_subsequent_blockquote() -> None:
    answer = (
        "### Case A, Court, 1990\n> passage one\n"
        "### Case B, Court, 1991\n> passage two\n"
    )
    assert attribute_passages(answer) == [
        AttributedPassage(passage="passage one", case_name="Case A"),
        AttributedPassage(passage="passage two", case_name="Case B"),
    ]


def test_extract_blockquote_passages_still_returns_flat_list() -> None:
    answer = "### Case A, Court, 1990\n> alpha\n\nprose\n\n> beta\n"
    assert extract_blockquote_passages(answer) == ["alpha", "beta"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && pytest tests/citation/test_caselaw_extraction.py -v`
Expected: FAIL — `ImportError: cannot import name 'AttributedPassage'`.

- [ ] **Step 3: Implement `AttributedPassage` + `attribute_passages`; re-express `extract_blockquote_passages`**

In `api/app/citation/caselaw.py`, replace the existing `extract_blockquote_passages` function (lines ~39-62) with:

```python
@dataclass(slots=True)
class AttributedPassage:
    """A blockquote passage paired with the case name of its nearest ``### `` heading.

    ``case_name`` is the text of the most recent ``### `` heading above the
    blockquote, taken up to the first comma (the case-law-research skill renders
    headings as ``### [Case Name], [Court], [Year] ([Citation])``). ``None`` when
    no ``### `` heading precedes the blockquote — the attribution false-positive
    guard: an unattributed passage never produces a FAIL row.
    """

    passage: str
    case_name: str | None


def attribute_passages(answer_text: str) -> list[AttributedPassage]:
    """Return each markdown blockquote paired with its nearest ``### `` case heading.

    Consecutive blockquote lines (``> ...``) join into one passage; a
    non-blockquote line ends the current passage. Each closed passage is paired
    with the case name parsed from the most recent ``### `` heading seen so far.
    """
    result: list[AttributedPassage] = []
    current: list[str] = []
    current_case: str | None = None

    def _flush() -> None:
        nonlocal current
        joined = " ".join(p for p in current if p).strip()
        if joined:
            result.append(AttributedPassage(passage=joined, case_name=current_case))
        current = []

    for line in answer_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">"):
            current.append(stripped[1:].strip())
            continue
        if current:
            _flush()
        # Only level-3 (``### ``) headings carry case attribution. ``##``/``#``
        # (and ``####``) do not — guard with an exact "### " prefix that is not
        # also "#### ".
        if stripped.startswith("### ") and not stripped.startswith("#### "):
            heading = stripped[4:].strip()
            current_case = heading.split(",", 1)[0].strip() or None
    if current:
        _flush()
    return result


def extract_blockquote_passages(answer_text: str) -> list[str]:
    """Return the text of each markdown blockquote in ``answer_text`` (flat list).

    Retained for existing callers/tests; equivalent to the passages produced by
    :func:`attribute_passages`.
    """
    return [a.passage for a in attribute_passages(answer_text)]
```

(`dataclass` is already imported at the top of `caselaw.py` — `from dataclasses import dataclass`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && pytest tests/citation/test_caselaw_extraction.py -v`
Expected: PASS (all new + the 5 pre-existing tests).

- [ ] **Step 5: Lint + commit**

```bash
cd api && ruff format app/citation/caselaw.py tests/citation/test_caselaw_extraction.py \
  && ruff check app/citation/caselaw.py tests/citation/test_caselaw_extraction.py
git add api/app/citation/caselaw.py api/tests/citation/test_caselaw_extraction.py
git commit -s -m "feat(citation): attribute caselaw blockquotes to nearest ### Case heading (P1-B1c)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `normalize_case_name` + `match_case_name` — normalized-exact, single-match attribution

**Files:**
- Modify: `api/app/citation/caselaw.py` (add both functions)
- Test: `api/tests/citation/test_caselaw_matching.py` (create)

**Interfaces:**
- Consumes: nothing (pure functions).
- Produces:
  ```python
  def normalize_case_name(name: str) -> str
  def match_case_name(parsed: str, clusters: Sequence[tuple[int, str]]) -> int | None
  ```
  `match_case_name` returns the `cluster_id` iff exactly one cluster's `case_name` normalizes equal to `parsed`; else `None`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/citation/test_caselaw_matching.py`:

```python
from app.citation.caselaw import match_case_name, normalize_case_name


def test_normalize_lowercases_and_collapses_whitespace() -> None:
    assert normalize_case_name("Brown   v.  Board") == "brown v. board"


def test_normalize_strips_trailing_citation_parenthetical() -> None:
    assert normalize_case_name("Roe v. Wade (410 U.S. 113)") == "roe v. wade"


def test_normalize_strips_trailing_punctuation() -> None:
    assert normalize_case_name("Palsgraf v. Long Island R.R.,") == "palsgraf v. long island r.r."


def test_match_returns_cluster_on_single_exact_match() -> None:
    clusters = [(701, "Brown v. Board of Education"), (702, "Roe v. Wade")]
    assert match_case_name("Brown v. Board of Education", clusters) == 701


def test_match_is_case_and_whitespace_insensitive() -> None:
    clusters = [(701, "Brown v. Board of Education")]
    assert match_case_name("brown   v.   board of education", clusters) == 701


def test_match_returns_none_on_zero_matches() -> None:
    clusters = [(701, "Brown v. Board of Education")]
    assert match_case_name("Marbury v. Madison", clusters) is None


def test_match_returns_none_on_two_matches() -> None:
    # Two consulted clusters share a normalized name -> ambiguous -> no attribution.
    clusters = [(701, "Smith v. Jones"), (702, "smith v. jones")]
    assert match_case_name("Smith v. Jones", clusters) is None


def test_match_skips_clusters_with_empty_case_name() -> None:
    clusters = [(701, ""), (702, "Roe v. Wade")]
    assert match_case_name("Roe v. Wade", clusters) == 702
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && pytest tests/citation/test_caselaw_matching.py -v`
Expected: FAIL — `ImportError: cannot import name 'match_case_name'`.

- [ ] **Step 3: Implement both functions**

Add to `api/app/citation/caselaw.py` (after `attribute_passages`). `re` import at top of file if not present (`import re`):

```python
def normalize_case_name(name: str) -> str:
    """Normalize a case name for attribution matching.

    Lowercases, strips a trailing ``(...)`` citation parenthetical, strips
    trailing punctuation/whitespace, and collapses internal whitespace runs to
    single spaces. Conservative: only a normalized-exact match attributes.
    """
    text = name.strip()
    # Drop a trailing parenthetical citation, e.g. "(410 U.S. 113)".
    text = re.sub(r"\s*\([^()]*\)\s*$", "", text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip().rstrip(",.;: ")


def match_case_name(parsed: str, clusters: Sequence[tuple[int, str]]) -> int | None:
    """Return the cluster_id iff exactly one cluster's case_name matches ``parsed``.

    Normalized-exact, single-match only (the false-positive guard). Zero matches,
    two-or-more matches, or clusters with an empty case_name → ``None`` →
    the passage stays on the B1b path (never produces a FAIL row).
    """
    target = normalize_case_name(parsed)
    if not target:
        return None
    matches = [cid for cid, name in clusters if name and normalize_case_name(name) == target]
    return matches[0] if len(matches) == 1 else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && pytest tests/citation/test_caselaw_matching.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd api && ruff format app/citation/caselaw.py tests/citation/test_caselaw_matching.py \
  && ruff check app/citation/caselaw.py tests/citation/test_caselaw_matching.py
git add api/app/citation/caselaw.py api/tests/citation/test_caselaw_matching.py
git commit -s -m "feat(citation): normalized-exact single-match case-name matcher (P1-B1c)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Attribution-aware judge pass — FAIL on reject, unverified-FAIL on over-budget, drop on transient error

**Files:**
- Modify: `api/app/citation/caselaw.py` (`verify_and_persist_caselaw_citations` — load `ResearchClusterMetadata`; replace the B1b judge pass with the attribution-aware pass)
- Test: `api/tests/integration/test_caselaw_fail_attribution.py` (create)

**Interfaces:**
- Consumes: `attribute_passages`, `match_case_name` (Tasks 1-2); `judge_case_content`, `estimate_case_content_cost_usd`, `CASE_CONTENT_JUDGE_BUDGET_USD` (B1b); `ResearchClusterMetadata`, `ResearchOpinionMetadata`.
- Produces: same `verify_and_persist_caselaw_citations` signature (unchanged). New private helper `_judge_attributed_passage`.

- [ ] **Step 1: Write the failing integration tests**

Create `api/tests/integration/test_caselaw_fail_attribution.py`:

```python
"""Integration tests for the caselaw FAIL tier via H3 attribution (P1-B1c).

Invariants:
1. Attributed + judge REJECT -> one FAIL row (verified=False, method NULL)
   -> ledger 'unverified' -> gate 'flagged'.
2. Attributed + judge ACCEPT -> SUPPORTED row (paraphrase_judge) [B1b preserved].
3. UNATTRIBUTED (H3 matches no consulted case) + would-reject -> drop, NO FAIL
   (the false-positive guard).
4. Attributed + over-budget -> unverified FAIL row.
5. Attributed + transient judge error -> drop, no row.

Refs ADR 0018 D2/D3, P1-B1c.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_loop import ToolSourceRecord
from app.citation.caselaw import verify_and_persist_caselaw_citations
from app.citation.gate import compute_and_record_gate
from app.citation.ledger import assemble_ledger_entries
from app.models.chat import Chat, Message
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchClusterMetadata, ResearchOpinionMetadata
from app.models.user import User
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)

pytestmark = pytest.mark.integration

_OPINION_TEXT = (
    "The court considered the duty of good faith. It held that every contract "
    "carries an implied covenant of good faith and fair dealing between parties."
)
# Paraphrase (not verbatim) so the verbatim loop produces nothing.
_PASSAGE = "the court recognized an implied covenant of good faith in all contracts"
_CASE_NAME = "Smith v. Acme Corp."


def _caselaw_source(cluster_id: int) -> ToolSourceRecord:
    return ToolSourceRecord(
        source_kind="caselaw",
        label=_CASE_NAME,
        subtitle=None,
        url=None,
        external_ref=str(cluster_id),
        provider="courtlistener",
        tool="get_cluster",
    )


def _attributed_answer() -> str:
    return f"### {_CASE_NAME}, N.Y., 2001 (1 N.Y. 1)\n\n**Relevant passage:**\n> {_PASSAGE}\n"


def _judge_completion(verdict_json: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-fail-test",
        created=0,
        model="fast",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=verdict_json),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


class _FakeGateway:
    def __init__(self, verdict_json: str) -> None:
        self._verdict = verdict_json
        self.calls = 0

    async def chat_completion(
        self, request: ChatCompletionRequest, *, request_id: str | None = None
    ) -> ChatCompletionResponse:
        self.calls += 1
        return _judge_completion(self._verdict)


class _ErroringGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_completion(
        self, request: ChatCompletionRequest, *, request_id: str | None = None
    ) -> ChatCompletionResponse:
        self.calls += 1
        raise RuntimeError("transient gateway failure")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession):
    user = User(email=f"fail-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="member")
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="fail-chat")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="passage")
    db_session.add(msg)
    await db_session.flush()
    opinion_id, cluster_id = 9001, 901
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=opinion_id,
            cluster_id=cluster_id,
            text_field_used="plain_text",
            storage_path=f"courtlistener/opinions/by-cluster/{cluster_id}/{opinion_id}",
            char_length=len(_OPINION_TEXT),
        )
    )
    db_session.add(
        ResearchClusterMetadata(cluster_id=cluster_id, case_name=_CASE_NAME, court="N.Y.", date_filed="2001-01-01")
    )
    await db_session.flush()
    return msg.id, opinion_id, cluster_id


async def _loader(db: AsyncSession, opinion_id: int) -> str:
    return _OPINION_TEXT


async def _rows(db_session: AsyncSession, message_id: uuid.UUID) -> list[MessageCaselawCitation]:
    return list(
        (
            await db_session.execute(
                select(MessageCaselawCitation).where(MessageCaselawCitation.message_id == message_id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_attributed_reject_writes_fail_row_and_flags(db_session: AsyncSession, seeded) -> None:
    message_id, opinion_id, cluster_id = seeded
    gw = _FakeGateway(json.dumps({"verdict": "no"}))
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=_attributed_answer(),
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 1
    rows = await _rows(db_session, message_id)
    assert len(rows) == 1
    assert rows[0].verified is False
    assert rows[0].verification_method is None
    assert rows[0].opinion_id == opinion_id
    assert rows[0].source_offset_end == len(_PASSAGE)
    await assemble_ledger_entries(db_session, message_id=message_id)
    await compute_and_record_gate(db_session, message_id=message_id)
    gate = (
        await db_session.execute(
            select(WorkProductFiduciaryGate).where(WorkProductFiduciaryGate.message_id == message_id)
        )
    ).scalar_one()
    assert gate.gate_status == "flagged"


@pytest.mark.asyncio
async def test_attributed_accept_writes_supported_row(db_session: AsyncSession, seeded) -> None:
    message_id, _opinion_id, cluster_id = seeded
    gw = _FakeGateway(json.dumps({"verdict": "yes", "confidence": "high"}))
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=_attributed_answer(),
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 1
    rows = await _rows(db_session, message_id)
    assert rows[0].verified is True
    assert rows[0].verification_method == "paraphrase_judge"


@pytest.mark.asyncio
async def test_unattributed_reject_drops_no_fail(db_session: AsyncSession, seeded) -> None:
    message_id, _opinion_id, cluster_id = seeded
    # H3 names a DIFFERENT case than the consulted cluster -> no attribution.
    answer = "### Totally Different Case, N.Y., 1999\n\n**Relevant passage:**\n> " + _PASSAGE + "\n"
    gw = _FakeGateway(json.dumps({"verdict": "no"}))
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=answer,
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 0
    assert await _rows(db_session, message_id) == []


@pytest.mark.asyncio
async def test_attributed_over_budget_writes_unverified_fail(
    db_session: AsyncSession, seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.citation.caselaw as caselaw_mod

    monkeypatch.setattr(caselaw_mod, "CASE_CONTENT_JUDGE_BUDGET_USD", Decimal("0"))
    message_id, opinion_id, cluster_id = seeded
    gw = _FakeGateway(json.dumps({"verdict": "yes", "confidence": "high"}))
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=_attributed_answer(),
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 1
    rows = await _rows(db_session, message_id)
    assert rows[0].verified is False
    assert rows[0].verification_method is None
    assert rows[0].opinion_id == opinion_id
    assert gw.calls == 0  # over-budget -> never judged


@pytest.mark.asyncio
async def test_attributed_transient_error_drops(db_session: AsyncSession, seeded) -> None:
    message_id, _opinion_id, cluster_id = seeded
    gw = _ErroringGateway()
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=_attributed_answer(),
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 0
    assert await _rows(db_session, message_id) == []
    assert gw.calls >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test pytest tests/integration/test_caselaw_fail_attribution.py -v`
Expected: FAIL — `test_attributed_reject_writes_fail_row_and_flags` and `test_attributed_over_budget...` fail (today the reject/over-budget passage drops → `n == 0`, no FAIL row). `ImportError` for `ResearchClusterMetadata` will NOT occur (it exists). The accept/unattributed/transient tests may already pass under B1b — that's fine.

- [ ] **Step 3: Implement the attribution-aware judge pass**

In `api/app/citation/caselaw.py`, add the import for `ResearchClusterMetadata` (the file already imports `ResearchOpinionMetadata` from `app.models.research`):

```python
from app.models.research import ResearchClusterMetadata, ResearchOpinionMetadata
```

Add a `VerificationResult` import for the helper's type if needed — `judge_case_content` returns one; we only inspect `.verified`/`.confidence`. No new import required.

Replace the entire `# --- SUPPORTED judge pass (P1-B1b, additive-only) ---` block (current lines ~218-275, the `if gateway is not None:` block) with the attribution-aware pass below. The verbatim loop above it and the persist block below it are unchanged.

```python
    # --- Attribution-aware judge pass (P1-B1c) ------------------------------
    # Confidently-attributed passages are judged against their one opinion:
    #   reject -> FAIL row; over-budget -> unverified FAIL row; transient error
    #   -> drop. Unattributed passages keep B1b's all-opinions SUPPORTED-or-drop
    #   behavior. FAIL is strictly additive: only attributed passages can FAIL.
    if gateway is not None:
        # Case names for the consulted clusters (for H3 attribution).
        cluster_metas = (
            (
                await db.execute(
                    select(ResearchClusterMetadata).where(
                        ResearchClusterMetadata.cluster_id.in_(cluster_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        clusters: list[tuple[int, str]] = [
            (c.cluster_id, c.case_name) for c in cluster_metas if c.case_name
        ]
        # cluster_id -> [(opinion_id, text)] from the already-loaded opinion texts.
        cluster_texts: dict[int, list[tuple[int, str]]] = {}
        for op, text in texts:
            cluster_texts.setdefault(op.cluster_id, []).append((op.opinion_id, text))

        # Resolve attribution per still-unverified passage; judge attributed
        # passages FIRST so the per-turn budget is spent on FAIL-bearing checks.
        pending = [a for a in attribute_passages(assistant_text) if a.passage not in verbatim_matched]

        def _attributed_cluster(a: AttributedPassage) -> int | None:
            if a.case_name is None:
                return None
            cid = match_case_name(a.case_name, clusters)
            if cid is None or cid not in cluster_texts:
                return None  # no confident match, or named-but-not-fetched
            return cid

        annotated = [(a, _attributed_cluster(a)) for a in pending]
        annotated.sort(key=lambda t: t[1] is None)  # attributed (cid not None) first

        spent: Decimal = Decimal("0")
        for a, cid in annotated:
            if cid is not None:
                spent, row = await _judge_attributed_passage(
                    db,
                    message_id=message_id,
                    passage=a.passage,
                    cluster_id=cid,
                    opinions=cluster_texts[cid],
                    gateway=gateway,
                    judge_model=judge_model,
                    spent=spent,
                )
                if row is not None:
                    rows.append(row)
                continue
            # --- Unattributed: B1b all-opinions SUPPORTED-or-drop ------------
            for op, text in texts:
                est = await estimate_case_content_cost_usd(
                    db, judge_model=judge_model, opinion_text=text
                )
                if spent + est > CASE_CONTENT_JUDGE_BUDGET_USD:
                    break  # budget reached -> drop remaining unattributed work
                spent += est
                try:
                    result = await judge_case_content(
                        passage=a.passage, opinion_text=text, gateway=gateway, judge_model=judge_model
                    )
                except Exception as exc:
                    log.warning("case-content judge error on opinion %s: %r", op.opinion_id, exc)
                    continue
                if not result.verified:
                    continue
                rows.append(
                    MessageCaselawCitation(
                        message_id=message_id,
                        opinion_id=op.opinion_id,
                        cluster_id=op.cluster_id,
                        source_offset_start=0,
                        source_offset_end=len(text),
                        source_text=a.passage,
                        verified=True,
                        verification_method="paraphrase_judge",
                        verification_confidence=result.confidence,
                        partial=True,
                    )
                )
                break
```

Add the private helper above `verify_and_persist_caselaw_citations` (after `locate_passage`):

```python
async def _judge_attributed_passage(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    passage: str,
    cluster_id: int,
    opinions: list[tuple[int, str]],
    gateway: _JudgeGatewayProtocol,
    judge_model: str,
    spent: Decimal,
) -> tuple[Decimal, MessageCaselawCitation | None]:
    """Judge an attributed passage against its cluster's opinion(s) only.

    Returns (updated_spent, row_or_None):
      * accept            -> SUPPORTED row (paraphrase_judge)
      * judge reject      -> FAIL row (verified=False, method NULL)
      * over budget       -> unverified FAIL row (verified=False, method NULL)
      * all transient err -> None (drop; no row)
    """
    saw_reject = False
    first_opinion_id = opinions[0][0]
    for opinion_id, text in opinions:
        est = await estimate_case_content_cost_usd(db, judge_model=judge_model, opinion_text=text)
        if spent + est > CASE_CONTENT_JUDGE_BUDGET_USD:
            log.info(
                "case-content judge: attributed passage over budget; flagging unverified",
                extra={"event": "caselaw_fail_over_budget", "cluster_id": cluster_id},
            )
            return spent, _fail_row(message_id, opinion_id, cluster_id, passage)
        spent += est
        try:
            result = await judge_case_content(
                passage=passage, opinion_text=text, gateway=gateway, judge_model=judge_model
            )
        except Exception as exc:
            log.warning("case-content judge error on opinion %s: %r", opinion_id, exc)
            continue  # transient on this opinion -> try the next
        if result.verified:
            return spent, MessageCaselawCitation(
                message_id=message_id,
                opinion_id=opinion_id,
                cluster_id=cluster_id,
                source_offset_start=0,
                source_offset_end=len(text),
                source_text=passage,
                verified=True,
                verification_method="paraphrase_judge",
                verification_confidence=result.confidence,
                partial=True,
            )
        saw_reject = True  # a real "no" from the judge
    if saw_reject:
        log.info(
            "case-content judge: attributed passage rejected; flagging FAIL",
            extra={"event": "caselaw_fail_judge_rejected", "cluster_id": cluster_id},
        )
        return spent, _fail_row(message_id, first_opinion_id, cluster_id, passage)
    return spent, None  # every opinion errored transiently -> drop


def _fail_row(
    message_id: uuid.UUID, opinion_id: int, cluster_id: int, passage: str
) -> MessageCaselawCitation:
    """Build an unverified caselaw FAIL row (gate -> flagged).

    Offsets are a documented placeholder: a FAIL passage has no verified span in
    the opinion, but the CHECK requires offset_end > offset_start >= 0. The ledger
    and trace never read caselaw offsets (ledger.py:78-91).
    """
    return MessageCaselawCitation(
        message_id=message_id,
        opinion_id=opinion_id,
        cluster_id=cluster_id,
        source_offset_start=0,
        source_offset_end=len(passage),
        source_text=passage,
        verified=False,
        verification_method=None,
        verification_confidence=None,
        partial=False,
    )
```

Also update the module docstring (lines ~8-10) to note B1c writes FAIL rows for attributed passages.

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test pytest tests/integration/test_caselaw_fail_attribution.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the B1b regression suite (additive guarantee)**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test pytest tests/integration/test_caselaw_paraphrase_judge.py tests/integration/test_caselaw_citations.py tests/citation/ tests/test_case_content_judge.py -v`
Expected: PASS — B1b SUPPORTED behavior and verbatim behavior unchanged. (The B1b tests use answers with no `### Case` heading → unattributed → identical behavior.)

- [ ] **Step 6: Lint + commit**

```bash
cd api && ruff format app/citation/caselaw.py tests/integration/test_caselaw_fail_attribution.py \
  && ruff check app/citation/caselaw.py tests/integration/test_caselaw_fail_attribution.py
git add api/app/citation/caselaw.py api/tests/integration/test_caselaw_fail_attribution.py
git commit -s -m "feat(citation): caselaw FAIL tier via H3 attribution (P1-B1c)

Attributed passages judged against their one opinion: reject -> FAIL row,
over-budget -> unverified FAIL, transient error -> drop. Unattributed
passages keep B1b's all-opinions SUPPORTED-or-drop behavior. FAIL is
strictly additive; no migration / gate / ledger / UI change.

Refs ADR 0018 D2/D3. Builds on P1-A1 (#218), P1-B1 (#225), P1-B1b (#229).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: File the deferred FAIL-severity-split DE + run the full api gate

**Files:**
- Modify: `docs/PRD.md` (§9 Deferred Enhancements — add the DE)

**Interfaces:** none (docs + verification).

- [ ] **Step 1: File the DE**

In `docs/PRD.md` §9, add a new DE entry (use the next free DE number — grep `DE-3` to find the highest; B1b/this session referenced up to DE-361, so the next is likely `DE-362` — confirm). Text:

> **DE-XXX — Caselaw FAIL severity split in the trace UI.** P1-B1c surfaces both a judge-rejected caselaw quote (likely fabricated/misquoted) and an over-budget-but-attributed quote (claims case X, not checked) identically as `"unverified"` / `flagged`; the distinction lives only in structured logs (`caselaw_fail_judge_rejected` vs `caselaw_fail_over_budget`). Surface the severity distinction in the C1 trace panel so a reviewer can tell "we checked and it's unsupported" from "we couldn't afford to check." Pairs with DE-279 (format-independent attribution).

- [ ] **Step 2: Run the full api unit + integration suite (collision-guard check)**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test pytest -q`
Expected: PASS, no collection errors. (No new route → `test_endpoints.py`/`test_openapi.py` unchanged; this run confirms nothing collided.)

- [ ] **Step 3: Commit**

```bash
git add docs/PRD.md
git commit -s -m "docs: file DE-XXX (caselaw FAIL severity split in trace UI) (P1-B1c)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final review (after Task 4)

- [ ] **Opus whole-branch review** — dispatch an Opus reviewer over the full branch diff vs `main`. Focus: the additive guarantee (no `fiduciary_grade`→`flagged` regression for unattributed passages), the reject-vs-transient-error distinction in `_judge_attributed_passage` (a real "no" must FAIL; an all-errored passage must drop), budget accounting across attributed→unattributed ordering, and the offset/CHECK placeholder. This pattern has repeatedly caught gate-passing defects.
- [ ] **Push both remotes** — `git push origin feat/p1b1c-caselaw-fail-attribution` and `git push tucuxi feat/p1b1c-caselaw-fail-attribution`.
- [ ] **Open the PR** (origin), attestation N/A (no skill legal substance change). **Security-gated — do NOT self-merge.** Kevin/security merges; then mirror `origin/main → tucuxi main` and confirm `origin == tucuxi`.

## Self-review against the spec

- **Spec coverage:** Component 1 → Task 1; Component 2 → Task 2; Component 3 (orchestration, budget, offsets) → Task 3; "no migration / gate / ledger / UI change" → Global Constraints + Task 3 (no migration touched); decisions #1 (normalized-exact single-match) → Task 2; decision #2 (over-budget→unverified-FAIL, transient→drop) → Task 3 `_judge_attributed_passage` + tests 4-5; FAIL-severity-split DE → Task 4; all 6 spec test cases → Task 3 tests + Task 1/2 unit tests.
- **Placeholder scan:** the only `DE-XXX` is the to-be-numbered DE (Task 4 step 1 says to confirm the number) — acceptable. No TODO/TBD in code.
- **Type consistency:** `AttributedPassage(passage, case_name)`, `attribute_passages -> list[AttributedPassage]`, `match_case_name(parsed, clusters) -> int | None`, `_judge_attributed_passage(...) -> tuple[Decimal, MessageCaselawCitation | None]`, `_fail_row(...) -> MessageCaselawCitation` — used consistently across Tasks 1-3.
