# P1-B1c — Caselaw FAIL tier via H3 attribution (design)

**Date:** 2026-06-26
**Milestone:** Fiduciary-grade agentic legal work — Phase 1 (WS-B)
**Branch:** `feat/p1b1c-caselaw-fail-attribution`
**Pins:** [ADR 0018](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) D2 (verify external quotes against the materialized opinion text), D3 (the fiduciary-grade gate). Builds on **P1-A1** (caselaw verbatim verification, #218), **P1-B1** (the gate, #225), and **P1-B1b** (the SUPPORTED tier, #229). Lighter, skill-format-coupled cousin of the deferred [DE-279](../../PRD.md#de-279) case-cite resolution.
**Security review:** **required** (citation surface + the gateway egress reused from B1b + the audit/ledger surface; `api/app/citation/**`, `chats.py`). **Do not self-merge** — Kevin/security merges; mirror `origin/main → tucuxi` after.

## Problem

P1-A1 verifies caselaw quotes **verbatim**; P1-B1b adds a **SUPPORTED** tier (paraphrased-but-faithful quotes → `paraphrase_judge` rows). Both are **additive-only**: a caselaw quote that matches no consulted opinion — verbatim *or* by the judge — is still **silently dropped**. So a **fabricated or materially misquoted** caselaw quote leaves no trace, and the gate cannot flag it. This is the last honesty gap in Phase 1: today the fiduciary gate can mark a turn `fiduciary_grade` even though it contains a quote attributed to a real consulted case that the case's own opinion text does not support.

P1-B1c closes that gap: when a blockquote is **confidently attributed** to exactly one consulted opinion and the whole-opinion judge **rejects** it against that opinion, persist a **FAIL** row (`verified=False`). The gate already maps `verified=False → "unverified" → flagged`, and the P1-C1 UI already renders the red flagged badge — so a B1c FAIL row flows end-to-end with **no gate / ledger / UI change**.

## Why FAIL needs attribution (the load-bearing reason it was split from B1b)

B1b's judge pass tries a dropped passage against **every** consulted opinion and accepts if **any** supports it — safe for SUPPORTED (a false *accept* only fails to flag a fabrication; it never flags a good draft). FAIL is the opposite risk: judging a passage against an opinion it was never meant to be checked against, and **rejecting**, would write a wrong FAIL and turn a fiduciary-grade draft `flagged` — **the worst failure mode for a fiduciary tool**. A legitimate **non-caselaw** blockquote (a statute, a KB quote, an emphasis quote) judged against caselaw opinions would reject against all of them → a wrong flag.

So FAIL requires **per-passage → opinion attribution**, which does not exist today: `extract_blockquote_passages` returns a flat `list[str]` with no case association. The signal to attribute on **does** exist but is unparsed: the case-law-research skill ([`skills/case-law-research/SKILL.md`](../../../skills/case-law-research/SKILL.md) §Output) mandates each cited passage render as a markdown blockquote **directly under a `### [Case Name], [Court], [Year] ([Citation])` H3 heading**. The parseable signal is therefore *"the nearest `###` heading above the blockquote."* B1c parses it, matches the case name to one consulted opinion, judges the passage against **that opinion only**, and writes a FAIL row on reject.

## Decisions (maintainer-approved 2026-06-26)

- **Matcher: normalized-exact, single-match only.** Normalize both sides (lowercase, collapse internal whitespace, strip a trailing parenthetical citation and trailing punctuation). Attribute a passage **only** when exactly one consulted cluster's `case_name` normalized-matches the parsed H3 case name. Zero matches, multiple matches, or any near-miss → **no attribution** → the passage stays on the B1b path (drop on reject; never FAIL). The match-gate **is** the false-positive guard. (`ResearchClusterMetadata` stores `case_name`/`court`/`date_filed` but **not** citation, so citation-matching is unavailable; case-name match only.)
- **Can't-judge an attributed passage: flag over-budget as unverified; drop on transient error.** A passage confidently attributed to one consulted opinion, but where the per-turn cost pre-flight is exhausted (deterministic) → write an **unverified FAIL row** ("claims case X, not verified"). A passage where the gateway judge call **errors** (transient) → **drop** (don't flag a good draft on a flaky call).
- **FAIL is strictly additive on top of B1b.** B1c only ever adds FAIL rows for passages that are (a) confidently attributed and (b) judge-rejected or over-budget against the attributed opinion. **Every passage that is *not* confidently attributed behaves exactly as it does on `main` today** (verbatim loop unchanged; unattributed passages take the B1b all-opinions SUPPORTED path and drop on reject). No turn that is `fiduciary_grade` today becomes `flagged` *unless* it contains a quote attributed to a consulted case that that case's opinion does not support — which is precisely the intended behavior.
- **No schema distinction between "judge-rejected" and "over-budget" FAIL.** Both are `verified=False, verification_method=NULL` → ledger `"unverified"` → gate `flagged`. That is the honest framing: a judge reject is *non-support*, not proof of fabrication; both rows are genuinely "not verified." The *why* is captured in **distinct structured log events** for audit (`caselaw_fail_judge_rejected` vs `caselaw_fail_over_budget`). A user-facing severity split is a follow-on **DE** (filed in this PR's §Deferred).
- **Minimal skill-coupled parser now; DE-279 supersedes later.** B1c builds a lightweight parser coupled to the skill's `### Case` convention. The coupling is a **noted risk** (a skill that drops the format silently loses attribution → passages drop, never mis-FAIL — conservative). [DE-279](../../PRD.md#de-279) (Bluebook cite → opinion resolution, a `message_case_citations` table) can later replace the matcher with a format-independent resolver.
- **No migration.** FAIL rows (`verified=False, verification_method=NULL`) already satisfy every `message_caselaw_citations` CHECK — `chk_message_caselaw_citations_verified_has_method` only requires a method when `verified=True`. No gate / ledger / UI / call-site-signature change. Only `ResearchClusterMetadata` gets loaded alongside the existing `ResearchOpinionMetadata`.

## Design

### Component 1 — `attribute_passages` (pure, unit-tested helper, `caselaw.py`)

```python
@dataclass(slots=True)
class AttributedPassage:
    passage: str
    case_name: str | None   # nearest preceding "### " heading's case name, or None

def attribute_passages(answer_text: str) -> list[AttributedPassage]: ...
```

Single pass over `answer_text.splitlines()`, tracking the **most recent `### ` heading** seen. Blockquote-passage assembly is identical to today's `extract_blockquote_passages` (consecutive `>` lines join into one passage; a non-blockquote line ends it). When a passage closes, pair it with the current heading's **case name** — the heading text after stripping the leading `### `, taken **up to the first comma** (the skill format is `### [Case Name], [Court], [Year] ([Citation])`). No preceding `### ` heading → `case_name=None`.

`extract_blockquote_passages` is **kept** (re-expressed as `[a.passage for a in attribute_passages(text)]`) so its existing call sites and tests are untouched.

> **Heading-comma edge case:** a case name itself can contain a comma (rare; e.g. *"In re Marriage of X, Y"*). v1 takes text-before-first-comma — a conservative truncation that, on a comma-containing name, simply *fails to match* the full stored `case_name` → no attribution → drop. It never **mis**-attributes. Note as a parser-fidelity follow-on.

### Component 2 — `match_case_name` (pure, unit-tested helper, `caselaw.py`)

```python
def normalize_case_name(name: str) -> str: ...
def match_case_name(parsed: str, clusters: Sequence[tuple[int, str]]) -> int | None: ...
```

`normalize_case_name`: lowercase; strip a trailing ` (…)` parenthetical (citation); strip trailing punctuation/whitespace; collapse internal whitespace runs to single spaces. `match_case_name`: normalize `parsed` and each cluster's `case_name`; return the `cluster_id` **iff exactly one** cluster normalizes-equal to `parsed`. Zero or ≥2 → `None`. Clusters with a null/empty `case_name` are skipped. Pure and total — no DB, no I/O.

### Component 3 — `caselaw.py` orchestration (attribution-aware judge pass)

`verify_and_persist_caselaw_citations` keeps its signature (the call site already passes `assistant_text` + `tool_sources`). Changes:

1. **Load cluster names.** Alongside the existing `ResearchOpinionMetadata` query, load `ResearchClusterMetadata` for the same `cluster_ids` → build `clusters: list[(cluster_id, case_name)]` and a `cluster_id → opinion text(s)` lookup from the already-loaded `texts`.
2. **Verbatim loop — unchanged.** (Tries all opinions; a verbatim match anywhere = legitimately quoted = SUPPORTED.)
3. **Attribution-aware judge pass** (only when `gateway is not None`). Build `AttributedPassage`s once. **Process attributed passages first, then unattributed** (budget priority — the FAIL-bearing checks get first claim on the per-turn budget). For each still-unverified passage:
   - **Attributed** (`match_case_name` → a cluster `C` that has loaded opinion text):
     - **Cost pre-flight** against `C`'s opinion. If the per-turn budget would be exceeded → write an **unverified FAIL row** for this passage (`verified=False`, `verification_method=NULL`, `opinion_id`/`cluster_id` = `C`'s), log `caselaw_fail_over_budget`, and **continue** (do not spend; later attributed passages also over-budget → each gets its own unverified FAIL row).
     - Else `judge_case_content(passage, C_opinion, gateway, judge_model)`:
       - **accept** → SUPPORTED row (`paraphrase_judge`), exactly as B1b.
       - **reject** → **FAIL row** (`verified=False`, `verification_method=NULL`), log `caselaw_fail_judge_rejected`.
       - If `C` has multiple opinions: judge each until one accepts (SUPPORTED) or all reject (one FAIL row, attributed to `C`'s first opinion).
     - A **transient gateway error** (caught) → **drop** this passage (logged, never fatal). *No FAIL row.*
   - **Unattributed** (`case_name is None`, or no single match, or matched cluster has no loaded opinion text) → the **existing B1b all-opinions path**: judge against each consulted opinion, first accept → SUPPORTED, all reject → **drop**. Never FAIL.
4. `gateway=None` → behaves exactly as today (verbatim-only; deterministic; no egress, no FAIL).

> **Offsets for a FAIL row.** A FAIL passage has no verified span in any opinion. The `message_caselaw_citations` CHECK requires `offset_end > offset_start >= 0`. v1 stores a documented placeholder `source_offset_start=0, source_offset_end=len(passage)` (passage length, always ≥ 1 for a non-empty blockquote — guard empties out before row creation). The trace renders `source_text` (the quote) for display, not the offsets, for caselaw rows. Confirm in the plan (task 1) that C1's trace panel does not key off caselaw offsets.

### Budgeting

Reuses B1b's `CASE_CONTENT_JUDGE_BUDGET_USD` per-turn cap and `estimate_case_content_cost_usd` pre-flight verbatim. The only change is **what happens at the cap for an attributed passage**: B1b stops the whole pass and drops the rest; B1c, for an **attributed** passage, writes an unverified FAIL instead of dropping (decision #2). Unattributed passages at the cap still drop (B1b). Because attributed passages are judged **first**, the budget is spent on FAIL-bearing checks before SUPPORTED-only checks.

## Testing

Unit (pure helpers — the bulk of the value; no DB, no gateway):
- `attribute_passages`: blockquote under a `### Case` H3 → `(passage, "Case Name")`; blockquote with no preceding H3 → `case_name=None`; multi-line wrapped blockquote joins; a `### Case` heading followed by prose then a *later* blockquote still attributes to the nearest preceding H3; comma-in-case-name truncates conservatively; the `## Gaps and caveats` section's non-`###` content never attributes.
- `normalize_case_name` / `match_case_name`: exact match; case/whitespace/trailing-citation-insensitive match; **zero match → None**; **two clusters match → None** (the single-match guard); null `case_name` cluster skipped.

Integration (mocked gateway — **no `-m provider`**; throwaway pgvector, conftest auto-migrates):
- Attributed + judge-**reject** → one FAIL row (`verified=False`, method `NULL`); `assemble_ledger_entries` → `"unverified"`; `compute_and_record_gate` → `flagged`.
- Attributed + judge-**accept** → SUPPORTED row (regression: B1b behavior preserved on the attributed path).
- **Unattributed** (a statute blockquote whose H3 matches no consulted case) + judge would-reject → **drop, no FAIL** (the false-positive guard).
- Attributed + **over-budget** → unverified FAIL row + `caselaw_fail_over_budget` event.
- Attributed + **transient judge error** → drop, no row.
- `gateway=None` → byte-for-byte the pre-B1c verbatim behavior (no FAIL rows).

## Out of scope / Deferred (file as DE-XXX in this PR)

- **DE — FAIL severity split in the trace UI.** Distinguish "judge-rejected (likely fabricated/misquoted)" from "unverified (claims case X, not checked — budget)" in the C1 trace. v1 surfaces both as `"unverified"`/`flagged`; the distinction lives only in structured logs.
- **DE-279** — Bluebook cite → opinion resolution; a format-independent attribution layer that supersedes B1c's skill-coupled `### Case` parser.
- A whitespace/format-tolerant or fuzzy case-name matcher (decision #1 chose normalized-exact-single-match; fuzzy is a later option if drift-misses prove common in practice).

## Pointers

- Strategy: [`docs/proposals/fiduciary-grade-agentic-legal-work.md`](../../proposals/fiduciary-grade-agentic-legal-work.md) (P1-B1c slice)
- Prior slice spec: [`2026-06-25-p1b1b-caselaw-paraphrase-judge-design.md`](2026-06-25-p1b1b-caselaw-paraphrase-judge-design.md) (§"Explicitly out of scope → P1-B1c")
- Reused judge: `api/app/citation/case_content_judge.py`; orchestrator: `api/app/citation/caselaw.py`; FAIL-row model: `api/app/models/message_caselaw_citation.py`; case-name source: `api/app/models/research.py` (`ResearchClusterMetadata`); skill contract: `skills/case-law-research/SKILL.md` §Output; gate/ledger (no change): `api/app/citation/{gate,ledger}.py`.
