# PR6d — Case-law-research skill + C5 tool-usage (declare & surface) + honesty pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `case-law-research` skill, make a skill's declared `tool_usage` load-bearing-but-non-gating (parse → check against configured connectors → surface), and run the milestone's final D6 honesty pass (file DE-350, fix a dangling DE reference, reconcile the narrative).

**Architecture:** `tool_usage` is parsed into the existing skill frontmatter schema and echoed through `SkillSummary` → `Skill` detail. A new resolver compares it against the operator's configured connectors (gateway CourtListener capability ∪ configured MCP servers) and the skill-detail endpoint surfaces `unavailable_tool_usage` (never gating; `null` when undeterminable). The skill is filesystem content. The honesty pass is docs.

**Tech Stack:** Python (FastAPI, Pydantic v2), TypeScript/SvelteKit (Svelte 4, Vitest), Markdown skill content.

## Global Constraints

- **Branch:** `feat/pr6d-case-law-skill` off `main` (`13a5f9e`), already created; the spec is committed on it. Push `origin` + `tucuxi`. `origin/main` PROTECTED — PR + GitHub merge; sync tucuxi after. **Create the branch BEFORE committing anything; never commit on local `main`** (a prior PR's spec committed on main diverged from the squash and forced a tucuxi force-push — don't repeat it).
- **C5 = declare + surface, NEVER gating.** The skill always loads/lists/runs. `unavailable_tool_usage` is informational. Availability-resolution failure degrades to `null` (request still 200) — never 500, never empty-means-missing.
- **`tool_usage` vocabulary = connector identifiers** (`["courtlistener"]`; extensible to MCP server names), matched case-insensitively against configured connectors.
- **No migration, no schema/DB change** — `tool_usage` is frontmatter; `unavailable_tool_usage` is computed.
- **The case-law skill is PROCEDURAL** — asserts method, not legal positions. If a reviewer finds substantive legal assertions in the skill body, STOP and escalate to the CLAUDE.md attestation path (do not self-merge).
- **Not security-gated** (skill content + `api/app/skills/**` + `api/app/api/skills.py` + `web/` + docs; no `gateway/**`, no `docs/security/**`, no auth/crypto/audit). → self-merge after CI green.
- **No DE-341 stub retirement** here (→ 6e). No `web/backend/open_webui/**` edits.
- **Tests:** api via host venv from `api/`: `cd ~/Code/lq-ai/api && .venv/bin/pytest tests/<file> -q` (DB tests need `DATABASE_URL="postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai"` — the `lq-test-pg` throwaway container; conftest auto-migrates). Web: `cd ~/Code/lq-ai/web && npx vitest run <file>` + `npm run check:lq-ai`. Run BOTH `ruff format api/` and `ruff check api/`; `cd api && .venv/bin/mypy app/...`.
- **No `@testing-library/svelte`** — test pure helpers via the `<script context="module">` pattern (RefusalMessageBubble / ToolGatePrompt precedent).
- **Commit (every commit):** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Stage explicitly — never `git add -A` (untracked `docs/` scratch must not be staged).

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `api/app/skills/schema.py` | Modify | `LQAIFrontmatter.tool_usage`; `SkillSummary.tool_usage`; `Skill.unavailable_tool_usage`; `derive_summary` populates `tool_usage`. |
| `api/app/skills/connectors.py` | Create | `resolve_available_connectors()` (async; gateway caps ∪ mcp servers; `None` on error) + pure `unavailable_tool_usage(declared, available)`. |
| `api/app/api/skills.py` | Modify | Compute + attach `unavailable_tool_usage` in the built-in branch of `_resolve_full_skill_payload`. |
| `docs/api/backend-openapi.yaml` | Modify | Add `tool_usage` + `unavailable_tool_usage` to the `Skill` response schema (no new path). |
| `skills/case-law-research/SKILL.md`, `skills/case-law-research/examples/*.md` | Create | The procedural skill + one worked example. |
| `web/src/lib/lq-ai/types.ts` | Modify | `SkillSummary.tool_usage`, `Skill.unavailable_tool_usage`. |
| `web/src/routes/lq-ai/skills/[id]/+page.svelte` (+ a small helper module) | Modify/Create | "Uses: …" + non-blocking "not configured" note (3 states). |
| `docs/PRD.md`, the 6c spec doc, `web/static/learn/playgrounds/governed-tool-flow.html`, `web/src/routes/lq-ai/learn/how/+page.svelte`, `README.md`, `docs/skill-authoring-guide.md` | Modify | Honesty pass. |

---

## Task 1: `tool_usage` in the frontmatter schema + summary

**Files:**
- Modify: `api/app/skills/schema.py` (`LQAIFrontmatter` ~line 151 after `trigger_examples`; `SkillSummary` ~line 218 after `output_format`; `Skill` ~line 247; `derive_summary` ~line 389)
- Test: `api/tests/test_skills_tool_usage.py` (new)

**Interfaces:**
- Produces (consumed by Tasks 2–3, 5): `LQAIFrontmatter.tool_usage: list[str] | None`; `SkillSummary.tool_usage: list[str] | None`; `Skill.unavailable_tool_usage: list[str] | None`.

**Gate:** pytest — frontmatter parses `tool_usage`; `derive_summary` copies it; absent → `None`.

- [ ] **Step 1: Write the failing test** (`api/tests/test_skills_tool_usage.py`):
```python
from app.skills.schema import LQAIFrontmatter, SkillFrontmatter, derive_summary


def test_frontmatter_parses_tool_usage():
    fm = LQAIFrontmatter.model_validate({"tool_usage": ["courtlistener"]})
    assert fm.tool_usage == ["courtlistener"]


def test_frontmatter_tool_usage_absent_is_none():
    assert LQAIFrontmatter.model_validate({}).tool_usage is None


def test_derive_summary_carries_tool_usage():
    front = SkillFrontmatter.model_validate(
        {"name": "x", "description": "d", "lq_ai": {"tool_usage": ["courtlistener"]}}
    )
    summary = derive_summary("x", front)
    assert summary.tool_usage == ["courtlistener"]
```

- [ ] **Step 2: Run; expect FAIL** (`AttributeError`/validation — field missing).
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_skills_tool_usage.py -q
```

- [ ] **Step 3: Add the field to `LQAIFrontmatter`** (after `trigger_examples`, ~line 151):
```python
    tool_usage: list[str] | None = Field(
        default=None,
        description="C5 (PR6d) — connector identifiers this skill calls "
        "(e.g. ['courtlistener'], extensible to MCP server names). Parsed and "
        "SURFACED against the operator's configured connectors; never enforced "
        "(a skill with an unconfigured connector still loads and runs).",
    )
```

- [ ] **Step 4: Add `tool_usage` to `SkillSummary`** (after `output_format`, ~line 218):
```python
    tool_usage: list[str] | None = None
```
and have `derive_summary` populate it (in the `return SkillSummary(...)` call, ~line 389, add):
```python
        tool_usage=lq.tool_usage,
```

- [ ] **Step 5: Add `unavailable_tool_usage` to the `Skill` detail model** (~line 247, alongside `id`):
```python
    unavailable_tool_usage: list[str] | None = None
    """C5 (PR6d) — declared connectors NOT configured in this deployment.
    ``[]`` = all available; non-empty = the gaps; ``None`` = could not be
    determined (gateway unreachable). Computed at skill-detail time; never
    gates the skill. Default ``None`` so ``materialise()`` (which doesn't set
    it) leaves it for the endpoint to fill."""
```

- [ ] **Step 6: Run; expect PASS.**
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_skills_tool_usage.py -q
```

- [ ] **Step 7: ruff + mypy + commit.**
```bash
cd ~/Code/lq-ai && ruff format api/ && ruff check api/ && (cd api && .venv/bin/mypy app/skills/schema.py)
git add api/app/skills/schema.py api/tests/test_skills_tool_usage.py
git commit -s -m "feat(api): parse + surface skill tool_usage frontmatter (C5, PR6d)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: connector-availability resolver

**Files:**
- Create: `api/app/skills/connectors.py`
- Test: extend `api/tests/test_skills_tool_usage.py`

**Interfaces:**
- Consumes: `app.research.service.get_capabilities()` → `{"enabled": bool, "providers": [...]}`; `app.mcp.service.list_servers()` → `list[{"name","type","auth"}]`.
- Produces (consumed by Task 3):
  - `async def resolve_available_connectors(*, request_id: str | None = None) -> set[str] | None`
  - `def unavailable_tool_usage(declared: list[str] | None, available: set[str] | None) -> list[str] | None`

**Gate:** pytest — resolver builds the union; returns `None` on error; the pure function's three-state table.

- [ ] **Step 1: Write failing tests** (append to `api/tests/test_skills_tool_usage.py`):
```python
import pytest
from unittest.mock import AsyncMock, patch
from app.skills.connectors import resolve_available_connectors, unavailable_tool_usage


def test_unavailable_pure_function():
    assert unavailable_tool_usage(None, {"courtlistener"}) == []
    assert unavailable_tool_usage([], {"courtlistener"}) == []
    assert unavailable_tool_usage(["courtlistener"], None) is None        # undeterminable
    assert unavailable_tool_usage(["courtlistener"], {"courtlistener"}) == []
    assert unavailable_tool_usage(["courtlistener"], set()) == ["courtlistener"]
    assert unavailable_tool_usage(["CourtListener"], {"courtlistener"}) == []  # case-insensitive


@pytest.mark.asyncio
async def test_resolve_available_unions_caselaw_and_mcp():
    with patch("app.skills.connectors.get_capabilities", new=AsyncMock(return_value={"enabled": True, "providers": [{}]})), \
         patch("app.skills.connectors.list_servers", new=AsyncMock(return_value=[{"name": "files", "type": "mcp", "auth": "none"}])):
        got = await resolve_available_connectors()
    assert got == {"courtlistener", "files"}


@pytest.mark.asyncio
async def test_resolve_available_none_on_error():
    with patch("app.skills.connectors.get_capabilities", new=AsyncMock(side_effect=RuntimeError("gw down"))), \
         patch("app.skills.connectors.list_servers", new=AsyncMock(return_value=[])):
        assert await resolve_available_connectors() is None


@pytest.mark.asyncio
async def test_resolve_available_caselaw_disabled_excludes_courtlistener():
    with patch("app.skills.connectors.get_capabilities", new=AsyncMock(return_value={"enabled": False, "providers": []})), \
         patch("app.skills.connectors.list_servers", new=AsyncMock(return_value=[])):
        assert await resolve_available_connectors() == set()
```

- [ ] **Step 2: Run; expect FAIL** (module missing).
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_skills_tool_usage.py -k "unavailable or resolve" -q
```

- [ ] **Step 3: Implement `api/app/skills/connectors.py`:**
```python
"""C5 (PR6d) — resolve which connectors a deployment has configured, so the
skill-detail endpoint can SURFACE (never enforce) a skill's declared
``tool_usage`` against reality."""

from __future__ import annotations

import logging

from app.mcp.service import list_servers
from app.research.service import get_capabilities

log = logging.getLogger(__name__)

_COURTLISTENER = "courtlistener"


async def resolve_available_connectors(*, request_id: str | None = None) -> set[str] | None:
    """The connector identifiers the operator has wired: CourtListener (when the
    gateway advertises it) ∪ configured MCP server names. Returns ``None`` when
    availability can't be determined (gateway unreachable) — the caller treats
    ``None`` as 'unknown', NOT 'all missing'."""
    try:
        caps = await get_capabilities(request_id=request_id)
        servers = await list_servers(request_id=request_id)
    except Exception as exc:  # noqa: BLE001 — degrade to 'unknown', never 500 the skill view
        log.warning("resolve_available_connectors: capability probe failed: %r", exc)
        return None
    available: set[str] = set()
    if isinstance(caps, dict) and caps.get("enabled"):
        available.add(_COURTLISTENER)
    for s in servers or []:
        name = s.get("name") if isinstance(s, dict) else None
        if isinstance(name, str) and name:
            available.add(name.lower())
    return available


def unavailable_tool_usage(
    declared: list[str] | None, available: set[str] | None
) -> list[str] | None:
    """Declared connectors not in ``available``. ``[]`` when nothing declared;
    ``None`` when availability is undeterminable; case-insensitive match."""
    if not declared:
        return []
    if available is None:
        return None
    avail_lower = {a.lower() for a in available}
    return [d for d in declared if d.lower() not in avail_lower]
```

- [ ] **Step 4: Run; expect PASS.**
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_skills_tool_usage.py -k "unavailable or resolve" -q
```

- [ ] **Step 5: ruff + mypy + commit.**
```bash
cd ~/Code/lq-ai && ruff format api/ && ruff check api/ && (cd api && .venv/bin/mypy app/skills/connectors.py)
git add api/app/skills/connectors.py api/tests/test_skills_tool_usage.py
git commit -s -m "feat(api): connector-availability resolver for C5 tool_usage (PR6d)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: surface `unavailable_tool_usage` on skill-detail

**Files:**
- Modify: `api/app/api/skills.py` (`_resolve_full_skill_payload`, the built-in branch ~lines 605-619)
- Modify: `docs/api/backend-openapi.yaml` (the `Skill` schema — add the two fields; **no new path**)
- Test: `api/tests/test_skill_endpoints.py` (extend — verified module). It installs a registry from `FIXTURES_DIR` (`client` fixture, line ~82: `MutableSkillRegistry(load_registry(FIXTURES_DIR))`), auth via `_bearer(db_user)` → `headers={"Authorization": f"Bearer {token}"}`, `@pytest.mark.integration`. **Decouple from Task 4:** add a fixture skill under `FIXTURES_DIR` (mirror the existing `alpha-test-skill` SKILL.md) carrying `lq_ai.tool_usage: [courtlistener]`, and assert against THAT — do not depend on the real `case-law-research` skill.

**Interfaces:**
- Consumes: Task 2 `resolve_available_connectors`, `unavailable_tool_usage`; Task 1 `Skill.unavailable_tool_usage` / `SkillSummary.tool_usage`.
- Produces: skill-detail JSON gains `tool_usage` (echoed) + `unavailable_tool_usage` (computed `[]`/list/`null`).

**Gate:** pytest — detail of a skill with `tool_usage` returns both fields; a skill without it omits/`null`s; resolver failure degrades to `null` and still 200.

- [ ] **Step 1: Add a `tool_usage` fixture skill + write the failing test.** In `api/tests/test_skill_endpoints.py`'s `FIXTURES_DIR` (find its value at the top of the module — a path under `api/tests/`), add a fixture skill `delta-tooluser/SKILL.md` mirroring the existing `alpha-test-skill` fixture, with `lq_ai.tool_usage: [courtlistener]`. Then add the test (mirror the module's `client` + `_bearer(db_user)` + `@pytest.mark.integration` pattern):
```python
@pytest.mark.integration
async def test_skill_detail_surfaces_tool_usage(client: AsyncClient, db_user: User) -> None:
    token = _bearer(db_user)
    h = {"Authorization": f"Bearer {token}"}

    with patch("app.api.skills.resolve_available_connectors", new=AsyncMock(return_value={"courtlistener"})):
        resp = await client.get("/api/v1/skills/delta-tooluser", headers=h)
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool_usage"] == ["courtlistener"]
    assert body["unavailable_tool_usage"] == []

    with patch("app.api.skills.resolve_available_connectors", new=AsyncMock(return_value=set())):
        resp2 = await client.get("/api/v1/skills/delta-tooluser", headers=h)
    assert resp2.json()["unavailable_tool_usage"] == ["courtlistener"]

    with patch("app.api.skills.resolve_available_connectors", new=AsyncMock(return_value=None)):
        resp3 = await client.get("/api/v1/skills/delta-tooluser", headers=h)
    assert resp3.status_code == 200
    assert resp3.json()["unavailable_tool_usage"] is None
```
This is endpoint-level wiring under test — fully decoupled from Task 4's real skill via the synthetic `FIXTURES_DIR` skill. (`patch` + `AsyncMock` are imported in this module already, or add `from unittest.mock import AsyncMock, patch`.)

- [ ] **Step 2: Run; expect FAIL** (fields absent / 200-without-fields).

- [ ] **Step 3: Wire the endpoint.** In `api/app/api/skills.py` `_resolve_full_skill_payload`, the built-in branch (after `skill = registry.get_skill(...)`, before the dict comprehension ~line 614) — import the resolver at top (`from app.skills.connectors import resolve_available_connectors, unavailable_tool_usage`) and compute:
```python
    available = await resolve_available_connectors(
        request_id=request.headers.get("x-request-id")
    )
    skill.unavailable_tool_usage = unavailable_tool_usage(skill.tool_usage, available)

    raw = skill.model_dump()
    # Keep unavailable_tool_usage even when None/[] (it's a meaningful verdict),
    # but otherwise preserve the existing None/empty-tags filtering.
    return {
        k: v
        for k, v in raw.items()
        if k in {"tool_usage", "unavailable_tool_usage"}
        or (v is not None and not (isinstance(v, list) and len(v) == 0 and k in {"tags"}))
    }
```
Note: the existing comprehension drops `None`/empty; we must NOT drop `unavailable_tool_usage` when it is `null` or `[]` (both are real verdicts), nor `tool_usage`. The `k in {...}` clause whitelists them through. (User/team shadow branches — `_skill_from_user_skill` — are unchanged: DB-backed skills carry no `tool_usage` today; they return without the fields, which the web treats as "no declaration.")

- [ ] **Step 4: OpenAPI.** In `docs/api/backend-openapi.yaml`, add to the `Skill` schema's properties:
```yaml
        tool_usage:
          type: array
          items: {type: string}
          nullable: true
          description: Connector identifiers the skill declares it uses (C5).
        unavailable_tool_usage:
          type: array
          items: {type: string}
          nullable: true
          description: Declared connectors not configured in this deployment; null when undeterminable. Informational, never gating.
```
No path was added → the `EXPECTED_PATHS`/count guards in `test_openapi.py` are unchanged. Still run `test_openapi.py` to confirm conformance.

- [ ] **Step 5: Run; expect PASS** (endpoint + openapi).
```bash
cd ~/Code/lq-ai/api && DATABASE_URL="postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai" .venv/bin/pytest tests/test_skills_tool_usage.py tests/test_openapi.py -q
# plus the skills-endpoint module you extended
```

- [ ] **Step 6: ruff + mypy + commit** (`git add api/app/api/skills.py docs/api/backend-openapi.yaml <skills-endpoint-test>`).

---

## Task 4: the `case-law-research` skill

**Files:**
- Create: `skills/case-law-research/SKILL.md`
- Create: `skills/case-law-research/examples/research-trail.md`
- Reference (mirror frontmatter shape): `skills/nda-review/SKILL.md`
- Test: `api/tests/test_skill_loader.py` (it builds a registry from the real `skills/` dir). **No pinned built-in skill-count assertion exists** (verified at write time — the endpoint list test uses a `>=` superset and runs against `FIXTURES_DIR`, not the real corpus), so adding the skill won't break an existing count. Just add a focused registration assertion.

**Interfaces:**
- Produces: a built-in skill `case-law-research` the loader registers with `lq_ai.tool_usage: [courtlistener]`.

**Gate:** the loader registers it (no WARNING/skip); any pinned skill-count test is updated; review confirms the body is procedural.

- [ ] **Step 1: Write the failing registration test.** In `api/tests/test_skill_loader.py` (read it first for how it builds a registry from the real `skills/` dir — likely `load_registry(<repo skills path>)`), add:
```python
def test_case_law_research_skill_registered():
    registry = load_registry(<the real skills dir constant this module uses>)
    names = {s.name for s in registry.list_summaries()}
    assert "case-law-research" in names
    detail = registry.get_skill("case-law-research")
    assert detail is not None
    assert detail.tool_usage == ["courtlistener"]
```
Reuse the module's existing `load_registry` import + the real-skills-dir path constant it already references (do not hard-code a new path).

- [ ] **Step 2: Run; expect FAIL** (skill not present).

- [ ] **Step 3: Write `skills/case-law-research/SKILL.md`.** Mirror `skills/nda-review/SKILL.md`'s frontmatter shape. Frontmatter:
```yaml
---
name: case-law-research
description: Use when the user asks to find, read, or cite U.S. case law on a question — locating controlling or persuasive decisions via CourtListener, reading the opinion text, and grounding any statement in what the source actually says.
lq_ai:
  title: Case-Law Research
  version: 1.0.0
  author: LegalQuants
  tags: [research, case-law, litigation, citations, courtlistener]
  jurisdiction: us
  tool_usage: [courtlistener]
  trigger_examples:
    - "find case law on the duty of good faith in NY"
    - "what does the Ninth Circuit say about trade-secret misappropriation"
    - "pull the leading Supreme Court cases on personal jurisdiction"
    - "is there controlling authority for fee-shifting here"
    - "read the opinion in that case and tell me the holding"
  inputs:
    required:
      - name: question
        type: text
        description: The legal question or issue to research.
    optional:
      - name: jurisdiction
        type: text
        description: Court(s)/jurisdiction to focus on (e.g., "9th Circuit", "New York", "SCOTUS"). Defaults to a broad U.S. search.
  output_format: report
  use_organization_profile: true
---
```
- [ ] **Step 4: Write the SKILL.md body — PROCEDURAL methodology only** (the review gate). Cover, as method (not legal conclusions):
  - The tool chain: `search_case_law` (find candidate clusters) → `get_cluster` (case metadata/opinions) → `read_opinion` / `find_in_case` (read/locate text). Note these run through the governed gateway and are tier-gated + audited.
  - Grounding discipline: cite only what the tools returned; quote/locate the supporting passage; the "Sources consulted" panel (PR6c) shows the user the provenance trail.
  - Honesty: report what was searched and what was NOT found; do not assert a holding not present in retrieved text; flag when authority is thin or jurisdiction-mismatched.
  - Scope limits (state explicitly): U.S. case law via CourtListener only; coverage gaps exist; this is research assistance, **not** a citator — it does not validate that a case is still good law (no Shepardizing/KeyCite). Recommend the user validate before relying.
  - Output: a structured report — issue, the authorities found (with citations the provenance panel backs), what each supports, and explicit gaps/caveats.
  Keep every statement methodological. Do NOT encode substantive legal rules or jurisdiction-specific holdings.

- [ ] **Step 5: Write `skills/case-law-research/examples/research-trail.md`** — one worked example: a sample question → the sequence of tool calls → a short cited answer with the gaps/caveats section. Illustrative, procedural.

- [ ] **Step 6: Run; expect PASS** (skill registers; count test green).
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/ -k "skill" -q 2>&1 | tail -8
```
Confirm no loader WARNING/skip for `case-law-research`.

- [ ] **Step 7: Commit** (`git add skills/case-law-research/ <count-test-if-changed>`).

---

## Task 5: web — types + skill-detail surfacing

**Files:**
- Modify: `web/src/lib/lq-ai/types.ts` (`SkillSummary` ~line 445; `Skill` ~line 474)
- Modify: `web/src/routes/lq-ai/skills/[id]/+page.svelte` (the skill-detail render)
- Create: `web/src/lib/lq-ai/skills/toolUsageNote.ts` (pure helper) + test `web/src/lib/lq-ai/__tests__/toolUsageNote.test.ts`

**Interfaces:**
- Consumes: the Task 3 API fields.
- Produces: `toolUsageNote(toolUsage, unavailable): { uses: string[]; warning: string | null }` driving the UI.

**Gate:** Vitest on the pure helper (3 states); svelte-check clean.

- [ ] **Step 1: Add the web types.** `SkillSummary` (~line 445) gains `tool_usage?: string[] | null;`; `Skill` (~line 474) gains `unavailable_tool_usage?: string[] | null;`.

- [ ] **Step 2: Write the failing helper test** (`__tests__/toolUsageNote.test.ts`):
```ts
import { describe, it, expect } from 'vitest';
import { toolUsageNote } from '../skills/toolUsageNote';

describe('toolUsageNote', () => {
  it('no declaration → no uses, no warning', () => {
    expect(toolUsageNote(null, null)).toEqual({ uses: [], warning: null });
  });
  it('declared + all available → uses listed, no warning', () => {
    expect(toolUsageNote(['courtlistener'], [])).toEqual({ uses: ['courtlistener'], warning: null });
  });
  it('declared + missing → warning names the gap', () => {
    const r = toolUsageNote(['courtlistener'], ['courtlistener']);
    expect(r.uses).toEqual(['courtlistener']);
    expect(r.warning).toContain('courtlistener');
    expect(r.warning).toContain('not configured');
  });
  it('undeterminable (null unavailable) → uses listed, no warning', () => {
    expect(toolUsageNote(['courtlistener'], null)).toEqual({ uses: ['courtlistener'], warning: null });
  });
});
```

- [ ] **Step 3: Run; expect FAIL** (module missing). `cd ~/Code/lq-ai/web && npx vitest run src/lib/lq-ai/__tests__/toolUsageNote.test.ts`

- [ ] **Step 4: Implement `web/src/lib/lq-ai/skills/toolUsageNote.ts`:**
```ts
/** C5 (PR6d) — derive the non-gating skill-detail tool-usage note. */
export interface ToolUsageNote {
	uses: string[];
	warning: string | null;
}

export function toolUsageNote(
	toolUsage: string[] | null | undefined,
	unavailable: string[] | null | undefined
): ToolUsageNote {
	const uses = toolUsage ?? [];
	// `unavailable` null/undefined = undeterminable → no verdict; [] = all available.
	const missing = Array.isArray(unavailable) ? unavailable : [];
	const warning =
		missing.length > 0
			? `${missing.join(', ')} ${missing.length === 1 ? "isn't" : "aren't"} configured in this deployment — ask your operator to enable ${missing.length === 1 ? 'it' : 'them'}.`
			: null;
	return { uses, warning };
}
```

- [ ] **Step 5: Run; expect PASS.**

- [ ] **Step 6: Render in the skill-detail page** (`web/src/routes/lq-ai/skills/[id]/+page.svelte`). Where the page renders skill metadata (find where `jurisdiction`/`output_format`/tags render), add, when `note.uses.length > 0`:
```svelte
<script lang="ts">
  // ... existing imports
  import { toolUsageNote } from '$lib/lq-ai/skills/toolUsageNote';
  // where `skill` is the loaded Skill detail object:
  $: usageNote = toolUsageNote(skill?.tool_usage, skill?.unavailable_tool_usage);
</script>

{#if usageNote.uses.length > 0}
  <div class="lq-tool-usage" data-testid="skill-tool-usage">
    <span class="lq-tool-usage-label">Uses:</span> {usageNote.uses.join(', ')}
    {#if usageNote.warning}
      <p class="lq-tool-usage-warning" data-testid="skill-tool-usage-warning">⚠ {usageNote.warning}</p>
    {/if}
  </div>
{/if}
```
Match the page's existing class/style conventions (reuse a metadata-row style; the warning a muted amber note — mirror `RefusalMessageBubble`'s amber if a token exists). Nothing is disabled.

- [ ] **Step 7: svelte-check clean; commit** (`git add web/src/lib/lq-ai/types.ts web/src/lib/lq-ai/skills/toolUsageNote.ts web/src/lib/lq-ai/__tests__/toolUsageNote.test.ts web/src/routes/lq-ai/skills/[id]/+page.svelte`).

---

## Task 6: D6 honesty pass — DE-350, dangling ref, narrative, authoring guide

**Files:**
- Modify: `docs/PRD.md` (§9 after DE-349; §3.6 verify), `docs/superpowers/specs/2026-06-20-pr6c-external-source-citations-design.md`, `web/static/learn/playgrounds/governed-tool-flow.html`, `web/src/routes/lq-ai/learn/how/+page.svelte`, `README.md`, `docs/skill-authoring-guide.md`

**Gate:** DE-350 filed; no `DE-360` remains; no user-facing surface still promises the case-law skill as "coming"; authoring guide documents `tool_usage`; grep gates clean.

- [ ] **Step 1: File DE-350** in `docs/PRD.md` §9, immediately after the `DE-349` entry (match the `#### DE-NNN — title` + body format of its neighbors):
```markdown
#### DE-350 — Generic-MCP-result provenance (`source_kind='mcp'` on `message_tool_sources`)

PR6c shipped retrieval-provenance for **case-law** tool results only (`source_kind='caselaw'`, from `search_case_law`/`get_cluster`). Extend `message_tool_sources` capture to generic MCP connector results (`source_kind='mcp'`) so a tool call to any operator-wired MCP server surfaces in the "Sources consulted" panel with a per-server label/url convention. Needs a label/url extraction strategy per MCP result shape (no structured cluster metadata to lean on).
```

- [ ] **Step 2: Fix the dangling `DE-360` reference.** `grep -rn "DE-360" docs/` → in `docs/superpowers/specs/2026-06-20-pr6c-external-source-citations-design.md` repoint every `DE-360` to `DE-350`. Re-grep to confirm zero `DE-360` remain repo-wide:
```bash
cd ~/Code/lq-ai && grep -rn "DE-360" . --include=*.md || echo "(clean — no DE-360)"
```

- [ ] **Step 3: Reconcile the three narrative surfaces** — drop the forward-looking "coming next" (the case-law skill is now shipped; the remaining DE-341 stub retirement is internal cleanup, not a user-facing promise):
  - `web/static/learn/playgrounds/governed-tool-flow.html` — the `Availability` block: move/keep "the case-law research skill" within "available today"; **remove** the `<div class="next">…Coming…</div>` forward promise (or replace with a plain "This milestone's capabilities are shipped." line). Read the current block first (the 6c honesty pass left "Coming next: the case-law research skill and retirement of the legacy OpenWebUI MCP stub").
  - `web/src/routes/lq-ai/learn/how/+page.svelte` §17 — same: fold the skill into "Available today," drop the "Coming next" clause.
  - `README.md` legal-research paragraph — drop the trailing "Coming next: …" sentence; the availability sentence ends at the shipped set.

- [ ] **Step 4: Document `tool_usage` in `docs/skill-authoring-guide.md`** — add it to the frontmatter field reference with the honest framing: a list of connector identifiers the skill uses; **parsed and surfaced** on the skill-detail page against the operator's configured connectors; **not enforced** — a skill whose connector isn't configured still loads and runs, and the operator sees a non-blocking note. (Mirror how `minimum_inference_tier` is documented as declared-not-enforced.)

- [ ] **Step 5: Verify-don't-redo sweep.** Confirm (fix only genuine drift): ADR `0014`/`0015` `Status:` is `Accepted`; the boundary-register tool-provider egress entry reads SHIPPED; `message_tool_sources` is documented in `docs/db-schema.md` (6c); PRD §3.6 research-capability language reads as shipped (tighten residual "will/coming"). Note in the report what you checked and what (if anything) you changed.

- [ ] **Step 6: Grep gates.**
```bash
cd ~/Code/lq-ai && grep -rn "DE-360" . --include=*.md || echo "(no DE-360)"
grep -rn "coming next\|Coming next\|next release\|Coming in the next" web/static/learn/playgrounds/governed-tool-flow.html web/src/routes/lq-ai/learn/how/+page.svelte README.md || echo "(no forward promises in the three surfaces)"
```
The second grep should return nothing in those three files (the forward promises are gone). Any hit elsewhere is out of scope.

- [ ] **Step 7: svelte-check clean (the how/+page.svelte edit); commit** (`git add` the six files).

---

## Task 7: Verification + ship

**Files:** none (verification + ship).

- [ ] **Step 1: Full backend gate.**
```bash
cd ~/Code/lq-ai && ruff format api/ && ruff check api/
cd ~/Code/lq-ai/api && .venv/bin/mypy app/skills app/api/skills.py
DATABASE_URL="postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai" .venv/bin/pytest tests/test_skills_tool_usage.py tests/test_openapi.py -q && DATABASE_URL="postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai" .venv/bin/pytest tests/ -k "skill" -q 2>&1 | tail -6
```
Expected: ruff/mypy clean; tool_usage + endpoint + skill-registration tests green.

- [ ] **Step 2: Full web gate.**
```bash
cd ~/Code/lq-ai/web && npx vitest run src/lib/lq-ai/__tests__/toolUsageNote.test.ts && npm run check:lq-ai 2>&1 | tail -3
```
Expected: Vitest green; svelte-check 0 errors.

- [ ] **Step 3: Build + visual check.** Rebuild `web` (pre-built bundle):
```bash
cd ~/Code/lq-ai && docker compose up -d --build web 2>&1 | tail -5
```
Open the `case-law-research` skill-detail page; confirm "Uses: CourtListener" renders, and — with CourtListener unconfigured — the non-blocking "⚠ … isn't configured …" note appears (the skill still loads). A headless static render of the note (3 states) is an acceptable substitute screenshot. Capture for the PR.

- [ ] **Step 4: Procedural-framing + final review.** Dispatch an independent review of the branch diff with two foci: (a) **the skill body asserts method, not substantive legal positions** (if it does → escalate to attestation, do NOT self-merge); (b) the C5 wiring never gates and degrades to `null` correctly. Apply material findings.

- [ ] **Step 5: Push both remotes + open the PR.**
```bash
cd ~/Code/lq-ai && git push -u origin feat/pr6d-case-law-skill && git push -u tucuxi feat/pr6d-case-law-skill
gh pr create --repo LegalQuants/lq-ai --base main --head feat/pr6d-case-law-skill \
  --title "PR6d/WS5: case-law-research skill + C5 tool-usage (declare & surface) + milestone honesty pass" \
  --body-file <(printf '%s\n' "<PR body: the procedural case-law-research skill; C5 = tool_usage parsed + checked against configured connectors + surfaced non-gating (null when undeterminable); the skill-detail Uses/warning note; the honesty pass (DE-350 filed, DE-360 dangling ref fixed, the three surfaces no longer promise the skill as coming, authoring guide documents tool_usage as surfaced-not-enforced); not security-gated; DE-341 stub retirement split to 6e; screenshots>")
```
Frontend + skill content + api skills code → **self-merge after CI green** (unless the review escalated the skill to attestation). After merge, sync tucuxi main. After 6d: **6e** (DE-341 stub retirement), then the release gate.

---

## Self-Review (run before dispatching execution)

**Spec coverage:** C5 parse (§Component 2 / Parse) → Task 1 ✓. Resolver + pure unavailable (§Check) → Task 2 ✓. Skill-detail surfacing + OpenAPI, non-gating + null-degrade (§Surface) → Task 3 ✓. The procedural skill + worked example + `tool_usage` frontmatter (§Component 1) → Task 4 ✓. Web types + UI note 3 states (§UI) → Task 5 ✓. Honesty pass: DE-350 + DE-360 fix + 3 surfaces + authoring guide + verify sweep (§Component 3) → Task 6 ✓. Non-goals respected: no migration, no gating, no DE-341, no generic-MCP build, no tier enforcement. Self-merge + attestation-escalation posture → Task 7 Step 4.

**Placeholder scan:** deterministic backend code (schema field, resolver, endpoint wiring, OpenAPI) is verbatim. The skill SKILL.md body is a concrete content brief (the body is authored prose — the plan specifies its required sections + the procedural constraint, which is the right altitude for prose, not code). The web UI snippet names the file to mirror + exact data-testids; the helper is verbatim. PR body is a ship-time fill-in. One conditional flagged honestly: Task 3's endpoint test may need Task 4's skill present (or a throwaway fixture) — called out in Task 3 Step 1.

**Type/signature consistency:** `tool_usage: list[str] | None` identical across `LQAIFrontmatter`, `SkillSummary`, `derive_summary`, web `SkillSummary`. `unavailable_tool_usage: list[str] | None` identical across `Skill` (model), the endpoint, web `Skill`. `resolve_available_connectors(*, request_id=None) -> set[str] | None` + `unavailable_tool_usage(declared, available) -> list[str] | None` consistent Tasks 2↔3. `toolUsageNote(toolUsage, unavailable) -> {uses, warning}` consistent Tasks 5 (def) ↔ 5 (render). No new API path → no `EXPECTED_PATHS`/count-guard change (stated in Task 3 Step 4).

**Execution note:** Tasks 1–3 + 5 are clean subagent-driven TDD (pytest/Vitest red/green). Task 4 is content with a registration gate + a procedural-framing review (the load-bearing human/agent check for self-merge). Task 6 is docs with grep gates. Anchors verified against the tree at write time (`main`=`13a5f9e`): `schema.py` (LQAIFrontmatter 82-169, SkillSummary 190-218, Skill 230-251, derive_summary 366-402), `api/skills.py` `_resolve_full_skill_payload` 581-619, `research/service.get_capabilities` (→ `{enabled, providers}`), `mcp/service.list_servers` (→ `[{name,type,auth}]`), web types `SkillSummary` 445, `Skill` 474, skill-detail route `web/src/routes/lq-ai/skills/[id]/+page.svelte`. The executor re-greps the skills-endpoint test module + any pinned skill-count test before Tasks 3–4 (named "find it" in those tasks).
```
