# M3-A4 Playbook Execution UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a SvelteKit UI in `web/` that lets operators run the M3-A1/A2/A3 Playbook engine against a document, preview the cost, and read structured per-position results with citations — verified by a Cypress E2E covering the full happy path.

**Architecture:** New `/lq-ai/playbooks/` list route + `/lq-ai/playbook-executions/[id]/` result route, both reading from the existing `POST /api/v1/playbooks/{id}/execute` + `GET /api/v1/playbook-executions/{id}` endpoints (PR #49). Adds two thin GET endpoints (`GET /api/v1/playbooks` + `GET /api/v1/playbooks/{id}`) so the list view has something to enumerate. Result view uses a dense-row + expand-to-reveal layout (per §5.4 design decision) with severity/outcome pills derived from existing `--lq-{accent|warn|error}` design tokens. Cost preview is client-side math against a static per-model rate table (§5.2). A reusable disclaimer banner component ships on both views (§5.3, Decision F).

**Tech Stack:** Backend: FastAPI / SQLAlchemy async / Pydantic v2. Frontend: SvelteKit 2 / TypeScript / Tailwind v4 + project `--lq-*` design tokens. Tests: pytest (api/), vitest (web/), Cypress (web/cypress/e2e/).

**Source branch:** `m3-a4-playbook-execution-ui` off `origin/m3-development` (currently at `eb59f5c`).

---

## Decisions locked at planning time

These are the answers to the §5 design questions from the handoff. The plan assumes them as constraints, not as TBDs:

| Question | Decision |
|---|---|
| §5.1 — CRUD scope | **GET-only.** `GET /playbooks` (list) + `GET /playbooks/{id}` (detail). POST/PATCH/DELETE defer to M3-A6 alongside the Easy Playbook wizard. |
| §5.2 — Cost preview math | **Client-side.** Static per-model rate table at `web/src/lib/lq-ai/playbookCost.ts` (sourced from public Anthropic/OpenAI pricing pages); n_positions × estimated tokens × $/token. Informational only, doesn't gate execution. |
| §5.3 — Disclaimer banner | **Ships in M3-A4.** New `PlaybookDisclaimerBanner.svelte`; rendered on both list + result views. CONTRIBUTING.md / PRD §1.3 refresh still defer to M3-close docs batch. |
| §5.4 — Card layout | **Dense rows + expand-to-reveal.** Table-style rows with severity pill, issue title, outcome pill, citation count + chevron toggle; expand reveals standard + actual + redline + citation chunk IDs. |

---

## Deferred from scope (record in PR body)

These come up while building this UI but explicitly stay out of M3-A4. Surface in handoff at end-of-session.

1. **Citation Engine "5-state" UI integration** — PR #49's body suggested the UI render `cited_chunk_ids` against the existing M2-C2 5-state citation badge. Reality (per codebase scan): the existing citation UI uses a continuous 0-100% relevance percentage, NOT 5 discrete states. M3-A4 renders citation count + chunk-id list only; full chunk-preview-on-click + state coloring defers as a follow-on DE (file as `DE-XXX — playbook position citations: open-in-document drilldown`).
2. **Apply Playbook from a document's context menu** — the M3 plan's M3-A4 spec mentions "from a document (or Project file), 'Apply Playbook' action opens a playbook picker." M3-A4 ships the inverse direction (from playbook list, click Apply → pick doc). Doc-side entry point defers to M3-A6 (Easy Playbook wizard) where it's a natural fit.
3. **Playbook CRUD endpoints (POST/PATCH/DELETE)** — per §5.1 decision, defer to M3-A6.
4. **Per-model pricing endpoint** — per §5.2 decision, defer; static client-side table for M3-A4.
5. **WCAG 2.1 AA color-contrast audit automation** — no a11y ESLint plugin / no contrast-token system in the codebase today. M3-A4 picks colors from the existing `--lq-{accent|warn|error}` palette and manually verifies via the browser devtools contrast checker. Filing automated WCAG audit as a future DE.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `web/src/lib/lq-ai/api/playbooks.ts` | TypeScript fetch client for the 4 playbook endpoints (list, detail, execute, poll execution) |
| `web/src/lib/lq-ai/playbookCost.ts` | Pure helpers — static per-model rate table + `estimatePlaybookCost(playbook, modelId)` |
| `web/src/lib/lq-ai/components/PlaybookDisclaimerBanner.svelte` | Reusable not-legal-advice banner (renders on both views per Decision F) |
| `web/src/lib/lq-ai/components/PlaybookExecuteModal.svelte` | Modal: doc picker + cost preview + confirm → kicks off execution |
| `web/src/routes/lq-ai/playbooks/+page.svelte` | List of available playbooks; "Apply" button opens execute modal |
| `web/src/routes/lq-ai/playbook-executions/[id]/+page.svelte` | Result view: header, summary, filter bar, dense per-position rows, expand-to-reveal |
| `web/src/lib/lq-ai/api/__tests__/playbooks.test.ts` | vitest for the API client functions (mock fetch) |
| `web/src/lib/lq-ai/__tests__/playbookCost.test.ts` | vitest for cost-estimate math |
| `web/src/routes/lq-ai/playbooks/__tests__/page-helpers.test.ts` | vitest for the list page's pure helpers (sort/format) |
| `web/src/routes/lq-ai/playbook-executions/[id]/__tests__/page-helpers.test.ts` | vitest for the result page's pure helpers (severity → class, outcome → class, filter logic) |
| `web/cypress/e2e/m3-a4-playbook-execution.cy.ts` | End-to-end happy-path Cypress spec |
| `api/tests/test_playbook_list_endpoints.py` | pytest for the two new GET endpoints + OpenAPI conformance |

### Modified files

| Path | Reason |
|---|---|
| `api/app/api/playbooks.py` | Add `GET /api/v1/playbooks` (list) + `GET /api/v1/playbooks/{id}` (detail) handlers |
| `docs/api/backend-openapi.yaml` | Document the two new GET endpoints under `/api/v1/playbooks` |
| `web/src/lib/lq-ai/types.ts` | Add `Playbook`, `Position`, `FallbackTier`, `PlaybookExecution`, `PlaybookExecutionResults`, `PlaybookPositionResult`, etc. wire shapes |
| `web/src/lib/lq-ai/components/MainSidebar.svelte` (or equivalent — verify exact filename in Task 0) | Add a "Playbooks" link to the nav |
| `docs/M3-IMPLEMENTATION-PLAN.md` | Mark task M3-A4 as SHIPPED + note the deferred items in §6.5 / §6.6 |
| `docs/PRD.md` §9 | Mark any closed DEs with `Status: SHIPPED at M3-A4` markers (verify which DEs touch this task) |

---

## Task 0 — Branch + reconnaissance

**Files:** none changed; reconnaissance only.

- [ ] **Step 1: Sync m3-development and create feature branch**

```bash
git fetch origin
git checkout -b m3-a4-playbook-execution-ui origin/m3-development
git log --oneline -1
```

Expected: HEAD at `eb59f5c feat(playbooks,m3-a3): NDA built-in playbooks...`

- [ ] **Step 2: Locate the sidebar navigation file**

```bash
grep -rn "Knowledge" web/src/lib/lq-ai/components/ | grep -i sidebar
grep -rn "/lq-ai/knowledge" web/src/lib/lq-ai/components/
```

Expected: one or two `.svelte` files referencing `/lq-ai/knowledge` as a nav target. Note the exact path for Task 7's edit.

- [ ] **Step 3: Confirm the OpenAPI schema-conformance test pattern**

```bash
ls api/tests/ | grep -i openapi
grep -rn "from app.api.playbooks" api/tests/ | head -5
```

Expected: existing test file pattern for OpenAPI assertions, and the import path for the playbooks router. Note these for Task 1.

- [ ] **Step 4: Sanity-check the executor's result payload shape**

Read `api/app/playbooks/nodes.py` (search for `_shape_results_payload` or the function that assembles the final `results` JSONB). Confirm the per-position shape exactly:

```python
# Expected per-position keys (verify in the source):
{
    "position_id": str,
    "issue": str,
    "severity_if_missing": "critical" | "high" | "medium" | "low",
    "verdict": "matches_standard" | "matches_fallback" | "deviates" | "missing",
    "confidence": float,
    "matched_fallback_rank": int | None,
    "cited_chunk_ids": list[str],
    "matched_text": str,
    "redline": {"old_text": str, "new_text": str, "justification": str} | None,
    "justification": str,
}
```

Lock the field names; the TypeScript types in Task 2 must match exactly. If the field names differ, **stop and re-plan Task 2** — do not paper over with type casts.

- [ ] **Step 5: Commit branch-setup scratch (if any) and proceed**

No commit yet — reconnaissance only. Branch exists, next task starts.

---

## Task 1 — Backend: GET endpoints for playbooks (list + detail)

**Files:**
- Modify: `api/app/api/playbooks.py`
- Modify: `docs/api/backend-openapi.yaml` (insert new path entries)
- Test: `api/tests/test_playbook_list_endpoints.py` (new file)

**Why:** The UI list view (Task 5) needs to enumerate available playbooks; the detail view (Task 6's modal) needs the full Position list. PR #49 deliberately deferred CRUD to M3-A4; §5.1 decision locks "GET-only" for this PR.

**Authorization posture** (mirroring PR #49's `POST /execute`):
- `GET /api/v1/playbooks` — admins see all; non-admin users see only playbooks where `created_by == user.id`. Built-in playbooks (created by the seed migration) have `created_by IS NULL`; treat them as **visible to all authenticated users**. This matches the "deployment-level built-in" posture from PR #49's comments.
- `GET /api/v1/playbooks/{id}` — same visibility rule. 404 (not 403) on unauthorized access, matching the existing playbook-execute behavior.

- [ ] **Step 1: Write the failing test for the list endpoint — built-ins visible to non-admin**

Create `api/tests/test_playbook_list_endpoints.py`:

```python
"""GET /api/v1/playbooks + GET /api/v1/playbooks/{id} — M3-A4."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.playbook import Playbook


@pytest.mark.asyncio
async def test_list_playbooks_returns_builtins_for_non_admin(
    client_user: AsyncClient, db: AsyncSession
) -> None:
    """Built-in playbooks (created_by IS NULL) are visible to all users."""
    result = await db.execute(select(Playbook).where(Playbook.created_by.is_(None)))
    builtin_count = len(result.scalars().all())
    assert builtin_count >= 2, "seed migration 0032 should have created at least 2 NDA playbooks"

    response = await client_user.get("/api/v1/playbooks")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= builtin_count
    names = {p["name"] for p in body}
    assert "NDA — Mutual" in names
    assert "NDA — Unilateral" in names
    # Each entry has the wire fields the UI needs:
    for entry in body:
        assert set(entry.keys()) >= {
            "id", "name", "contract_type", "description", "version",
            "created_by", "created_at", "updated_at",
        }
        # List view doesn't need positions inlined — defer to detail endpoint.
        # (verify your implementation matches this expectation)
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd api && uv run pytest tests/test_playbook_list_endpoints.py::test_list_playbooks_returns_builtins_for_non_admin -v
```

Expected: FAIL with `404 not found` or `AttributeError`-style error (endpoint doesn't exist yet).

- [ ] **Step 3: Implement the list endpoint**

Open `api/app/api/playbooks.py`. Add a new handler ABOVE the existing `execute_playbook` handler (route ordering doesn't matter for FastAPI, but keep the file grouped: GETs above POSTs):

```python
@router.get(
    "/playbooks",
    response_model=list[PlaybookSchema],
    summary="List playbooks visible to the caller.",
)
async def list_playbooks(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PlaybookSchema]:
    """List playbooks the caller can see.

    Visibility rules (mirroring the execute endpoint):

    * Admins see all playbooks.
    * Non-admins see playbooks they authored OR built-in playbooks
      (created_by IS NULL — created by the seed migration).

    Positions are NOT inlined in the list response; clients fetch the
    detail endpoint when they need them. This keeps the list response
    bounded even when a playbook has dozens of positions.
    """
    stmt = select(Playbook)
    if not user.is_admin:
        stmt = stmt.where(
            (Playbook.created_by == user.id) | (Playbook.created_by.is_(None))
        )
    stmt = stmt.order_by(Playbook.name)
    rows = (await db.execute(stmt)).scalars().all()
    # Empty positions list in the wire shape; clients call the detail endpoint.
    return [
        PlaybookSchema.model_validate(
            {**row.__dict__, "positions": []}, from_attributes=True
        )
        for row in rows
    ]
```

Add the import for `PlaybookSchema` if it's not already imported (the existing file imports `PlaybookExecutionSchema` from `app.schemas.playbooks`; add `Playbook as PlaybookSchema` to that same import):

```python
from app.schemas.playbooks import (
    Playbook as PlaybookSchema,
    PlaybookExecution as PlaybookExecutionSchema,
    PlaybookExecutionCreate,
)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd api && uv run pytest tests/test_playbook_list_endpoints.py::test_list_playbooks_returns_builtins_for_non_admin -v
```

Expected: PASS.

- [ ] **Step 5: Write the failing test for the detail endpoint**

Append to `api/tests/test_playbook_list_endpoints.py`:

```python
@pytest.mark.asyncio
async def test_get_playbook_returns_full_positions(
    client_user: AsyncClient, db: AsyncSession
) -> None:
    """Detail endpoint inlines the position list with fallback tiers."""
    # Find the mutual NDA built-in
    result = await db.execute(
        select(Playbook).where(Playbook.name == "NDA — Mutual")
    )
    playbook = result.scalar_one()

    response = await client_user.get(f"/api/v1/playbooks/{playbook.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "NDA — Mutual"
    assert body["contract_type"] == "NDA"
    assert isinstance(body["positions"], list)
    assert len(body["positions"]) == 8, "NDA — Mutual has 8 positions per the YAML"
    first = body["positions"][0]
    assert set(first.keys()) >= {
        "id", "issue", "description", "standard_language",
        "fallback_tiers", "redline_strategy", "severity_if_missing",
        "detection_keywords", "detection_examples", "position_order",
    }
    assert first["severity_if_missing"] in {"critical", "high", "medium", "low"}


@pytest.mark.asyncio
async def test_get_playbook_404_for_unauthorized(
    client_user: AsyncClient, db: AsyncSession
) -> None:
    """Non-admin gets 404 (not 403) for a playbook they don't own and isn't built-in."""
    # Create a playbook owned by a different user
    other_user_id = uuid.uuid4()
    playbook = Playbook(
        id=uuid.uuid4(),
        name="Private playbook",
        contract_type="custom",
        description="",
        version="1.0.0",
        created_by=other_user_id,
    )
    db.add(playbook)
    await db.commit()

    response = await client_user.get(f"/api/v1/playbooks/{playbook.id}")
    assert response.status_code == 404
```

- [ ] **Step 6: Run the new tests to confirm they fail**

```bash
cd api && uv run pytest tests/test_playbook_list_endpoints.py -v
```

Expected: the two new tests FAIL (handler doesn't exist).

- [ ] **Step 7: Implement the detail endpoint**

In `api/app/api/playbooks.py`, add below the list handler:

```python
@router.get(
    "/playbooks/{playbook_id}",
    response_model=PlaybookSchema,
    summary="Get a playbook with its full position list.",
)
async def get_playbook(
    playbook_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlaybookSchema:
    """Return the playbook header + positions + fallback tiers.

    Visibility: admins see all; non-admins see playbooks they authored
    or built-in playbooks (``created_by IS NULL``). 404 (not 403) on
    unauthorized access — mirrors the playbook-execute handler.
    """
    playbook = await db.get(Playbook, playbook_id)
    if playbook is None:
        raise HTTPException(status_code=404, detail="playbook not found")
    if (
        not user.is_admin
        and playbook.created_by is not None
        and playbook.created_by != user.id
    ):
        raise HTTPException(status_code=404, detail="playbook not found")
    # Eager-load positions if not already loaded
    await db.refresh(playbook, attribute_names=["positions"])
    return PlaybookSchema.model_validate(playbook, from_attributes=True)
```

NOTE: Confirm the relationship name on the `Playbook` ORM model in `api/app/models/playbook.py` — it may be `positions` (singular foreign-key list) or something like `playbook_positions`. Adjust the `attribute_names` argument and the response model serialization accordingly. **If you find an unexpected mismatch (e.g., position model is named differently or the relationship doesn't exist), stop and re-read the model file before proceeding.**

- [ ] **Step 8: Run all the new tests to verify they pass**

```bash
cd api && uv run pytest tests/test_playbook_list_endpoints.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 9: Run the full backend suite for regressions**

```bash
cd api && uv run pytest -x --ff
```

Expected: 1089 + 3 = 1092 tests PASS (or 1089 + however many you added). No regressions.

- [ ] **Step 10: Update the OpenAPI sketch**

Open `docs/api/backend-openapi.yaml`. Find the existing playbook paths (search for `/api/v1/playbooks/{playbook_id}/execute`). Insert above it:

```yaml
  /api/v1/playbooks:
    get:
      tags: [playbooks]
      summary: List playbooks visible to the caller (M3-A4)
      description: |
        Returns playbooks the caller can see: admins see all;
        non-admins see playbooks they authored or built-in playbooks
        (``created_by IS NULL``). Positions are NOT inlined; clients
        call ``GET /api/v1/playbooks/{id}`` to fetch them.
      responses:
        '200':
          description: List of playbooks (positions empty).
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/Playbook'
        '401':
          description: Not authenticated.

  /api/v1/playbooks/{playbook_id}:
    parameters:
      - in: path
        name: playbook_id
        required: true
        schema: {type: string, format: uuid}
    get:
      tags: [playbooks]
      summary: Get a playbook with its full position list (M3-A4)
      description: |
        Returns the playbook header + positions + fallback tiers.
        Visibility matches ``GET /api/v1/playbooks``. 404 (not 403)
        on unauthorized access.
      responses:
        '200':
          description: Full playbook with positions.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Playbook'
        '404':
          description: Playbook not found, or caller is not authorized to see it.
        '401':
          description: Not authenticated.
```

- [ ] **Step 11: Commit**

```bash
cd /Users/kevinkeller/Desktop/lq-ai
git add api/app/api/playbooks.py api/tests/test_playbook_list_endpoints.py docs/api/backend-openapi.yaml
git commit -s -m "$(cat <<'EOF'
feat(api,m3-a4): GET /playbooks list + detail endpoints

Adds the two GET endpoints the M3-A4 UI needs:

* GET /api/v1/playbooks — list visible playbooks. Admins see all;
  non-admins see playbooks they authored OR built-in playbooks
  (created_by IS NULL). Positions are NOT inlined; the list response
  is bounded even for playbooks with many positions.
* GET /api/v1/playbooks/{id} — detail view including the full position
  list with fallback tiers. 404 (not 403) on unauthorized access,
  matching the existing execute endpoint posture.

CRUD POST/PATCH/DELETE deferred to M3-A6 alongside the Easy Playbook
wizard's create flow, per the M3-A4 §5.1 design decision.

Refs M3-A4 in docs/M3-IMPLEMENTATION-PLAN.md.
EOF
)"
```

---

## Task 2 — Frontend: TypeScript types + API client

**Files:**
- Modify: `web/src/lib/lq-ai/types.ts` (append playbook types)
- Create: `web/src/lib/lq-ai/api/playbooks.ts`
- Test: `web/src/lib/lq-ai/api/__tests__/playbooks.test.ts`

- [ ] **Step 1: Append playbook wire shapes to `types.ts`**

Open `web/src/lib/lq-ai/types.ts`. After the last existing type block (find the end of the file), append:

```typescript
// ----- Playbooks (M3-A1/A2/A3/A4) -----

export type PositionSeverity = 'critical' | 'high' | 'medium' | 'low';

export type PlaybookExecutionStatus = 'pending' | 'running' | 'completed' | 'error';

export type PlaybookPositionVerdict =
	| 'matches_standard'
	| 'matches_fallback'
	| 'deviates'
	| 'missing';

export interface FallbackTier {
	rank: number;
	description: string;
	language: string;
}

export interface Position {
	id: string;
	issue: string;
	description: string;
	standard_language: string;
	fallback_tiers: FallbackTier[];
	redline_strategy: string;
	severity_if_missing: PositionSeverity;
	detection_keywords: string[];
	detection_examples: string[];
	position_order: number;
}

export interface Playbook {
	id: string;
	name: string;
	contract_type: string;
	description: string;
	version: string;
	created_by: string | null;
	created_at: string;
	updated_at: string;
	positions: Position[];
}

export interface PlaybookPositionRedline {
	old_text: string;
	new_text: string;
	justification: string;
}

export interface PlaybookPositionResult {
	position_id: string;
	issue: string;
	severity_if_missing: PositionSeverity;
	verdict: PlaybookPositionVerdict;
	confidence: number;
	matched_fallback_rank: number | null;
	cited_chunk_ids: string[];
	matched_text: string;
	redline: PlaybookPositionRedline | null;
	justification: string;
}

export interface PlaybookExecutionSummary {
	matches_standard: number;
	matches_fallback: number;
	deviates: number;
	missing: number;
}

export interface PlaybookExecutionResults {
	schema_version: string;
	positions: PlaybookPositionResult[];
	summary: PlaybookExecutionSummary;
}

export interface PlaybookExecution {
	id: string;
	playbook_id: string;
	target_document_id: string;
	user_id: string | null;
	project_id: string | null;
	status: PlaybookExecutionStatus;
	results: PlaybookExecutionResults | null;
	error: string | null;
	created_at: string;
	completed_at: string | null;
}

export interface PlaybookExecutionCreate {
	target_document_id: string;
	project_id?: string;
}
```

- [ ] **Step 2: Write the failing test for the API client**

Create `web/src/lib/lq-ai/api/__tests__/playbooks.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { listPlaybooks, getPlaybook, executePlaybook, getPlaybookExecution } from '../playbooks';

describe('playbooks API client', () => {
	const fetchMock = vi.fn();
	let originalFetch: typeof globalThis.fetch;

	beforeEach(() => {
		originalFetch = globalThis.fetch;
		globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
		fetchMock.mockReset();
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	it('listPlaybooks calls GET /api/v1/playbooks and returns the array', async () => {
		fetchMock.mockResolvedValueOnce({
			ok: true,
			status: 200,
			json: async () => [
				{
					id: 'p1', name: 'NDA — Mutual', contract_type: 'NDA',
					description: '', version: '1.0.0', created_by: null,
					created_at: '2026-05-18T00:00:00Z', updated_at: '2026-05-18T00:00:00Z',
					positions: []
				}
			]
		});
		const playbooks = await listPlaybooks();
		expect(playbooks).toHaveLength(1);
		expect(playbooks[0].name).toBe('NDA — Mutual');
		const [url, init] = fetchMock.mock.calls[0];
		expect(String(url)).toContain('/api/v1/playbooks');
		expect((init as RequestInit | undefined)?.method ?? 'GET').toBe('GET');
	});

	it('getPlaybook calls GET /api/v1/playbooks/{id}', async () => {
		fetchMock.mockResolvedValueOnce({
			ok: true,
			status: 200,
			json: async () => ({
				id: 'p1', name: 'NDA — Mutual', contract_type: 'NDA',
				description: '', version: '1.0.0', created_by: null,
				created_at: '2026-05-18T00:00:00Z', updated_at: '2026-05-18T00:00:00Z',
				positions: []
			})
		});
		const playbook = await getPlaybook('p1');
		expect(playbook.name).toBe('NDA — Mutual');
		expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/playbooks/p1');
	});

	it('executePlaybook posts the body and returns the PlaybookExecution', async () => {
		fetchMock.mockResolvedValueOnce({
			ok: true,
			status: 202,
			json: async () => ({
				id: 'e1', playbook_id: 'p1', target_document_id: 'd1',
				user_id: 'u1', project_id: null, status: 'pending',
				results: null, error: null,
				created_at: '2026-05-18T00:00:00Z', completed_at: null
			})
		});
		const exec = await executePlaybook('p1', { target_document_id: 'd1' });
		expect(exec.status).toBe('pending');
		const [url, init] = fetchMock.mock.calls[0];
		expect(String(url)).toContain('/api/v1/playbooks/p1/execute');
		expect((init as RequestInit).method).toBe('POST');
		const body = JSON.parse(String((init as RequestInit).body));
		expect(body).toEqual({ target_document_id: 'd1' });
	});

	it('getPlaybookExecution calls GET /api/v1/playbook-executions/{id}', async () => {
		fetchMock.mockResolvedValueOnce({
			ok: true,
			status: 200,
			json: async () => ({
				id: 'e1', playbook_id: 'p1', target_document_id: 'd1',
				user_id: 'u1', project_id: null, status: 'completed',
				results: { schema_version: 'm3-a2-v1', positions: [], summary: { matches_standard: 0, matches_fallback: 0, deviates: 0, missing: 0 } },
				error: null,
				created_at: '2026-05-18T00:00:00Z',
				completed_at: '2026-05-18T00:01:00Z'
			})
		});
		const exec = await getPlaybookExecution('e1');
		expect(exec.status).toBe('completed');
		expect(exec.results?.summary).toBeDefined();
		expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/playbook-executions/e1');
	});
});
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd web && npx vitest run src/lib/lq-ai/api/__tests__/playbooks.test.ts
```

Expected: FAIL — module `../playbooks` not found.

- [ ] **Step 4: Implement the API client**

Create `web/src/lib/lq-ai/api/playbooks.ts`:

```typescript
import { apiRequest } from './client';
import type {
	Playbook,
	PlaybookExecution,
	PlaybookExecutionCreate
} from '../types';

/**
 * GET /api/v1/playbooks — list visible playbooks. Positions are NOT
 * inlined; call {@link getPlaybook} for the full position list.
 */
export async function listPlaybooks(): Promise<Playbook[]> {
	return apiRequest<Playbook[]>('/playbooks');
}

/**
 * GET /api/v1/playbooks/{id} — playbook header + full position list.
 */
export async function getPlaybook(playbookId: string): Promise<Playbook> {
	return apiRequest<Playbook>(`/playbooks/${encodeURIComponent(playbookId)}`);
}

/**
 * POST /api/v1/playbooks/{id}/execute — kick off a playbook against a
 * target document. Returns 202 + a {@link PlaybookExecution} at status
 * 'pending'. Poll {@link getPlaybookExecution} until the status is
 * terminal ('completed' or 'error').
 */
export async function executePlaybook(
	playbookId: string,
	body: PlaybookExecutionCreate
): Promise<PlaybookExecution> {
	return apiRequest<PlaybookExecution>(
		`/playbooks/${encodeURIComponent(playbookId)}/execute`,
		{ method: 'POST', body }
	);
}

/**
 * GET /api/v1/playbook-executions/{id} — poll the current state of a
 * playbook execution.
 */
export async function getPlaybookExecution(
	executionId: string
): Promise<PlaybookExecution> {
	return apiRequest<PlaybookExecution>(
		`/playbook-executions/${encodeURIComponent(executionId)}`
	);
}
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd web && npx vitest run src/lib/lq-ai/api/__tests__/playbooks.test.ts
```

Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/lq-ai/types.ts web/src/lib/lq-ai/api/playbooks.ts web/src/lib/lq-ai/api/__tests__/playbooks.test.ts
git commit -s -m "$(cat <<'EOF'
feat(web,m3-a4): TypeScript types + API client for playbooks

Mirrors the M3-A1/A2 backend wire shapes (api/app/schemas/playbooks.py
+ api/app/playbooks/nodes.py::_shape_results_payload) as TS types in
web/src/lib/lq-ai/types.ts, plus a thin API client in
web/src/lib/lq-ai/api/playbooks.ts wrapping the four endpoints:

* GET /api/v1/playbooks (M3-A4)
* GET /api/v1/playbooks/{id} (M3-A4)
* POST /api/v1/playbooks/{id}/execute (M3-A2)
* GET /api/v1/playbook-executions/{id} (M3-A2)

vitest spec mocks globalThis.fetch; no dependency on the live API.
EOF
)"
```

---

## Task 3 — Frontend: cost estimation module

**Files:**
- Create: `web/src/lib/lq-ai/playbookCost.ts`
- Test: `web/src/lib/lq-ai/__tests__/playbookCost.test.ts`

**Why:** Per §5.2 decision, cost preview is client-side. Static rate table sourced from public Anthropic / OpenAI pricing pages. Math:

- Per-position cost = (classify tokens × judge_model rate) + (redline tokens × redline_model rate, IF deviates is likely)
- Estimate: assume 100% of positions trigger classify; assume 33% trigger redline (matches a typical real-world contract where ~1/3 of positions deviate from standard)
- Default judge model: `claude-sonnet-4-6` (highest-quality default per project posture)

Rates come from public pricing pages and are documented as static at the top of the file with a comment to update them periodically.

- [ ] **Step 1: Write the failing test**

Create `web/src/lib/lq-ai/__tests__/playbookCost.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';

import {
	estimatePlaybookCost,
	formatCostUSD,
	DEFAULT_JUDGE_MODEL,
	PER_MODEL_RATES
} from '../playbookCost';
import type { Playbook } from '../types';

const mockPlaybook = (positionCount: number): Playbook => ({
	id: 'p1',
	name: 'Test',
	contract_type: 'NDA',
	description: '',
	version: '1.0.0',
	created_by: null,
	created_at: '2026-05-18T00:00:00Z',
	updated_at: '2026-05-18T00:00:00Z',
	positions: Array.from({ length: positionCount }, (_, i) => ({
		id: `pos-${i}`,
		issue: `Issue ${i}`,
		description: '',
		standard_language: '',
		fallback_tiers: [],
		redline_strategy: '',
		severity_if_missing: 'medium' as const,
		detection_keywords: [],
		detection_examples: [],
		position_order: i
	}))
});

describe('estimatePlaybookCost', () => {
	it('returns a non-negative cost for a 1-position playbook on the default model', () => {
		const cost = estimatePlaybookCost(mockPlaybook(1), DEFAULT_JUDGE_MODEL);
		expect(cost.estimated_cost_usd).toBeGreaterThan(0);
		expect(cost.judge_model).toBe(DEFAULT_JUDGE_MODEL);
		expect(cost.position_count).toBe(1);
	});

	it('scales linearly with position count', () => {
		const oneCost = estimatePlaybookCost(mockPlaybook(1), DEFAULT_JUDGE_MODEL).estimated_cost_usd;
		const tenCost = estimatePlaybookCost(mockPlaybook(10), DEFAULT_JUDGE_MODEL).estimated_cost_usd;
		// 10 positions cost ~10x one position
		expect(tenCost).toBeCloseTo(oneCost * 10, 4);
	});

	it('falls back to a known model if the requested rate is missing', () => {
		const cost = estimatePlaybookCost(mockPlaybook(8), 'totally-unknown-model-xyz');
		// We don't crash; we use the fallback model's rate.
		expect(cost.estimated_cost_usd).toBeGreaterThan(0);
		expect(cost.judge_model).toBe(DEFAULT_JUDGE_MODEL);
	});

	it('returns 0 cost for 0 positions', () => {
		const cost = estimatePlaybookCost(mockPlaybook(0), DEFAULT_JUDGE_MODEL);
		expect(cost.estimated_cost_usd).toBe(0);
		expect(cost.position_count).toBe(0);
	});

	it('all listed rates have positive input + output rates', () => {
		for (const [modelId, rate] of Object.entries(PER_MODEL_RATES)) {
			expect(rate.input_usd_per_million, `${modelId} input`).toBeGreaterThan(0);
			expect(rate.output_usd_per_million, `${modelId} output`).toBeGreaterThan(0);
		}
	});
});

describe('formatCostUSD', () => {
	it('formats with $ + two decimals for ≥ $0.01', () => {
		expect(formatCostUSD(1.5)).toBe('$1.50');
		expect(formatCostUSD(0.01)).toBe('$0.01');
		expect(formatCostUSD(12.345)).toBe('$12.35');
	});

	it('shows < $0.01 for tiny non-zero costs', () => {
		expect(formatCostUSD(0.001)).toBe('< $0.01');
		expect(formatCostUSD(0.009)).toBe('< $0.01');
	});

	it('shows $0.00 for exactly 0', () => {
		expect(formatCostUSD(0)).toBe('$0.00');
	});
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd web && npx vitest run src/lib/lq-ai/__tests__/playbookCost.test.ts
```

Expected: FAIL — module `../playbookCost` not found.

- [ ] **Step 3: Implement the cost module**

Create `web/src/lib/lq-ai/playbookCost.ts`:

```typescript
/**
 * Client-side cost estimation for playbook execution.
 *
 * Per the M3-A4 §5.2 design decision, cost preview is informational —
 * computed in the browser against a static per-model rate table sourced
 * from public Anthropic / OpenAI pricing pages. A precise server-side
 * estimate (using M2-E2's rolling-average calibration) would be more
 * accurate but adds a new endpoint + tests + OpenAPI surface for
 * informational-only data.
 *
 * Update PER_MODEL_RATES periodically — public prices drift. Last
 * verified: 2026-05-18 against:
 *   https://www.anthropic.com/pricing
 *   https://openai.com/pricing
 */

import type { Playbook } from './types';

export interface ModelRate {
	input_usd_per_million: number;
	output_usd_per_million: number;
}

export const PER_MODEL_RATES: Record<string, ModelRate> = {
	'claude-sonnet-4-6': { input_usd_per_million: 3.0, output_usd_per_million: 15.0 },
	'claude-opus-4-7': { input_usd_per_million: 15.0, output_usd_per_million: 75.0 },
	'claude-haiku-4-5': { input_usd_per_million: 1.0, output_usd_per_million: 5.0 },
	'gpt-5': { input_usd_per_million: 5.0, output_usd_per_million: 20.0 },
	'gpt-5-mini': { input_usd_per_million: 0.5, output_usd_per_million: 2.0 }
};

export const DEFAULT_JUDGE_MODEL = 'claude-sonnet-4-6';

/**
 * Per-position token budget. Mirrors the executor's CLASSIFY_MAX_TOKENS
 * + REDLINE_MAX_TOKENS constants in api/app/playbooks/nodes.py, plus a
 * representative input budget for the system prompt + retrieved chunks.
 */
const CLASSIFY_INPUT_TOKENS = 2000;
const CLASSIFY_OUTPUT_TOKENS = 600;
const REDLINE_INPUT_TOKENS = 2000;
const REDLINE_OUTPUT_TOKENS = 800;

/**
 * Empirically, ~1/3 of positions deviate from standard in a typical
 * contract review and trigger the redline pass. Tune as M3-A4 produces
 * real-world data.
 */
const REDLINE_PROBABILITY = 1 / 3;

export interface CostEstimate {
	estimated_cost_usd: number;
	position_count: number;
	judge_model: string;
}

export function estimatePlaybookCost(playbook: Playbook, modelId: string): CostEstimate {
	const positionCount = playbook.positions.length;
	if (positionCount === 0) {
		return { estimated_cost_usd: 0, position_count: 0, judge_model: modelId };
	}

	const effectiveModel = modelId in PER_MODEL_RATES ? modelId : DEFAULT_JUDGE_MODEL;
	const rate = PER_MODEL_RATES[effectiveModel];

	const perPositionInputCost =
		(CLASSIFY_INPUT_TOKENS / 1_000_000) * rate.input_usd_per_million +
		REDLINE_PROBABILITY * ((REDLINE_INPUT_TOKENS / 1_000_000) * rate.input_usd_per_million);
	const perPositionOutputCost =
		(CLASSIFY_OUTPUT_TOKENS / 1_000_000) * rate.output_usd_per_million +
		REDLINE_PROBABILITY * ((REDLINE_OUTPUT_TOKENS / 1_000_000) * rate.output_usd_per_million);
	const perPositionCost = perPositionInputCost + perPositionOutputCost;

	return {
		estimated_cost_usd: perPositionCost * positionCount,
		position_count: positionCount,
		judge_model: effectiveModel
	};
}

/** Format a USD amount for display. */
export function formatCostUSD(amount: number): string {
	if (amount === 0) return '$0.00';
	if (amount < 0.01) return '< $0.01';
	return `$${amount.toFixed(2)}`;
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd web && npx vitest run src/lib/lq-ai/__tests__/playbookCost.test.ts
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/lq-ai/playbookCost.ts web/src/lib/lq-ai/__tests__/playbookCost.test.ts
git commit -s -m "$(cat <<'EOF'
feat(web,m3-a4): client-side cost estimator for playbooks

Static per-model rate table + estimatePlaybookCost(playbook, modelId)
for the M3-A4 cost-preview surface. Per the §5.2 design decision,
cost preview is client-side and informational only.

Token budgets mirror the executor's CLASSIFY_MAX_TOKENS +
REDLINE_MAX_TOKENS constants. Rates sourced from public Anthropic +
OpenAI pricing pages; verified 2026-05-18. Update periodically.
EOF
)"
```

---

## Task 4 — Frontend: disclaimer banner component

**Files:**
- Create: `web/src/lib/lq-ai/components/PlaybookDisclaimerBanner.svelte`

**Why:** Per Decision F (attestation reframe → professional-judgment posture) + §5.3 decision, the disclaimer banner ships in M3-A4. Reusable component so list and result views both render it consistently.

- [ ] **Step 1: Create the banner component**

Create `web/src/lib/lq-ai/components/PlaybookDisclaimerBanner.svelte`:

```svelte
<script lang="ts">
	/**
	 * PlaybookDisclaimerBanner — the standard not-legal-advice posture
	 * for the playbook execution surface, per Decision F (M3-A3 session)
	 * + §5.3 of the M3-A4 plan.
	 *
	 * Renders on both /lq-ai/playbooks and /lq-ai/playbook-executions/[id].
	 * Matches the project's "lean into transparency + disclaim warranties"
	 * posture: built-in playbooks are reasonable starting points drafted
	 * by the maintainer team, NOT legal advice, NOT a substitute for
	 * licensed counsel review.
	 *
	 * Visual: an inset-tinted box (using --lq-inset / --lq-warn tokens)
	 * with a small alert icon, two short sentences, and no dismiss
	 * affordance (this is a persistent posture statement, not a toast).
	 */
</script>

<aside class="lq-playbook-disclaimer" role="note" data-testid="lq-playbook-disclaimer">
	<svg
		class="lq-playbook-disclaimer__icon"
		viewBox="0 0 16 16"
		width="16"
		height="16"
		aria-hidden="true"
	>
		<path
			d="M8 1.5L1 14h14L8 1.5zm0 4.5v4M8 11.5v.5"
			stroke="currentColor"
			stroke-width="1.5"
			stroke-linecap="round"
			fill="none"
		/>
	</svg>
	<div class="lq-playbook-disclaimer__body">
		<strong>Not legal advice.</strong>
		Playbooks codify one reasonable market position. Apply your own professional
		judgment; review results with counsel licensed in the relevant jurisdiction
		before relying on them.
	</div>
</aside>

<style>
	.lq-playbook-disclaimer {
		display: flex;
		gap: 0.625rem;
		align-items: flex-start;
		padding: 0.75rem 1rem;
		border: 1px solid var(--lq-warn-border, var(--lq-border));
		background: var(--lq-warn-soft, var(--lq-inset));
		color: var(--lq-text-primary);
		border-radius: 0.5rem;
		font-size: 0.875rem;
		line-height: 1.4;
	}

	.lq-playbook-disclaimer__icon {
		flex-shrink: 0;
		color: var(--lq-warn, var(--lq-text-secondary));
		margin-top: 0.125rem;
	}

	.lq-playbook-disclaimer__body strong {
		font-weight: 600;
		margin-right: 0.25rem;
	}
</style>
```

- [ ] **Step 2: Sanity-check the component renders without errors**

There's no dedicated component test (it's pure markup); the Cypress E2E in Task 8 will assert the `data-testid="lq-playbook-disclaimer"` is visible on both pages. Run a typecheck:

```bash
cd web && npx svelte-check --tsconfig tsconfig.json --threshold error src/lib/lq-ai/components/PlaybookDisclaimerBanner.svelte
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/lq-ai/components/PlaybookDisclaimerBanner.svelte
git commit -s -m "$(cat <<'EOF'
feat(web,m3-a4): reusable PlaybookDisclaimerBanner component

Standard not-legal-advice posture for playbook surfaces (Decision F +
§5.3). Renders on /lq-ai/playbooks list + /lq-ai/playbook-executions
result views; data-testid pinned for Cypress assertions.
EOF
)"
```

---

## Task 5 — Frontend: `/lq-ai/playbooks` list page

**Files:**
- Create: `web/src/routes/lq-ai/playbooks/+page.svelte`
- Test: `web/src/routes/lq-ai/playbooks/__tests__/page-helpers.test.ts`

**What it shows:**
- Banner at top (PlaybookDisclaimerBanner)
- Heading + brief description ("Apply a playbook to review a contract against your standard positions.")
- Table-style list: `[ Name ] [ Contract Type ] [ Version ] [ # Positions (loaded lazily) ] [ Apply button ]`
- Empty state: "No playbooks available yet."
- Error state: surfaces the LQAIApiError message
- Loading state: skeleton rows

Apply button opens `PlaybookExecuteModal` (Task 6) with the picked playbook's ID.

- [ ] **Step 1: Write the failing test for the page helpers**

Create `web/src/routes/lq-ai/playbooks/__tests__/page-helpers.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';

import { sortPlaybooksByName, formatVersion } from '../page-helpers';
import type { Playbook } from '$lib/lq-ai/types';

const mkPlaybook = (overrides: Partial<Playbook>): Playbook => ({
	id: overrides.id ?? 'p',
	name: overrides.name ?? 'p',
	contract_type: overrides.contract_type ?? 'NDA',
	description: '',
	version: overrides.version ?? '1.0.0',
	created_by: null,
	created_at: '2026-05-18T00:00:00Z',
	updated_at: '2026-05-18T00:00:00Z',
	positions: []
});

describe('sortPlaybooksByName', () => {
	it('sorts case-insensitively', () => {
		const out = sortPlaybooksByName([
			mkPlaybook({ name: 'banana' }),
			mkPlaybook({ name: 'Apple' }),
			mkPlaybook({ name: 'cherry' })
		]);
		expect(out.map((p) => p.name)).toEqual(['Apple', 'banana', 'cherry']);
	});

	it('does not mutate the input array', () => {
		const input = [mkPlaybook({ name: 'b' }), mkPlaybook({ name: 'a' })];
		const out = sortPlaybooksByName(input);
		expect(input.map((p) => p.name)).toEqual(['b', 'a']);
		expect(out.map((p) => p.name)).toEqual(['a', 'b']);
	});
});

describe('formatVersion', () => {
	it('prefixes a v', () => {
		expect(formatVersion('1.0.0')).toBe('v1.0.0');
	});
	it('handles empty / null versions gracefully', () => {
		expect(formatVersion('')).toBe('');
	});
});
```

The file imports from a sibling `page-helpers.ts`, which we'll create alongside the svelte page (extracting pure helpers per the knowledge-page pattern). But the knowledge page actually puts helpers in `<script context="module">` of the .svelte file itself. For svelte-check compatibility with vitest, **extract helpers to a sibling .ts file** so vitest doesn't need the svelte transformer.

Actually, looking at `web/src/routes/lq-ai/knowledge/+page.svelte`, the helpers are exported from `<script context="module">`. The existing vitest config must handle .svelte imports. Confirm this:

```bash
cd web && cat vitest.config.ts 2>/dev/null || cat vite.config.ts 2>/dev/null | grep -A 5 svelte
```

If svelte is configured in vitest, use the same pattern (module-script exports). If not, use a sibling `page-helpers.ts` file. **Choose based on the actual config; both are valid.** The plan below assumes a sibling file (safer / explicit).

- [ ] **Step 2: Create `page-helpers.ts` for the list page**

Create `web/src/routes/lq-ai/playbooks/page-helpers.ts`:

```typescript
import type { Playbook } from '$lib/lq-ai/types';

/** Returns a new array sorted case-insensitively by playbook name. */
export function sortPlaybooksByName(playbooks: Playbook[]): Playbook[] {
	return [...playbooks].sort((a, b) =>
		a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
	);
}

/** Prefix a version string with "v"; empty input passes through. */
export function formatVersion(version: string): string {
	if (!version) return '';
	return `v${version}`;
}
```

- [ ] **Step 3: Run the test to verify it passes**

```bash
cd web && npx vitest run src/routes/lq-ai/playbooks/__tests__/page-helpers.test.ts
```

Expected: PASS.

- [ ] **Step 4: Create the list page**

Create `web/src/routes/lq-ai/playbooks/+page.svelte`:

```svelte
<script lang="ts">
	import { onMount } from 'svelte';

	import { listPlaybooks } from '$lib/lq-ai/api/playbooks';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import PlaybookDisclaimerBanner from '$lib/lq-ai/components/PlaybookDisclaimerBanner.svelte';
	import PlaybookExecuteModal from '$lib/lq-ai/components/PlaybookExecuteModal.svelte';
	import type { Playbook } from '$lib/lq-ai/types';

	import { sortPlaybooksByName, formatVersion } from './page-helpers';

	let playbooks: Playbook[] = [];
	let loading = false;
	let listError: string | null = null;

	let selectedPlaybook: Playbook | null = null;

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const fetched = await listPlaybooks();
			playbooks = sortPlaybooksByName(fetched);
		} catch (err) {
			listError = err instanceof LQAIApiError ? err.message : 'Failed to load playbooks.';
		} finally {
			loading = false;
		}
	}

	function openExecute(p: Playbook): void {
		selectedPlaybook = p;
	}

	function closeExecute(): void {
		selectedPlaybook = null;
	}

	onMount(load);
</script>

<svelte:head>
	<title>Playbooks · LQ.AI</title>
</svelte:head>

<section class="lq-playbooks-page">
	<header class="lq-playbooks-page__header">
		<h1>Playbooks</h1>
		<p class="lq-playbooks-page__subtitle">
			Apply a playbook to review a contract against your standard positions. The
			executor walks each position, classifies how the contract compares, and drafts
			redlines where it deviates.
		</p>
	</header>

	<PlaybookDisclaimerBanner />

	{#if loading}
		<div class="lq-playbooks-page__state" data-testid="lq-playbooks-loading">Loading…</div>
	{:else if listError}
		<div class="lq-playbooks-page__error" role="alert" data-testid="lq-playbooks-error">
			{listError}
		</div>
	{:else if playbooks.length === 0}
		<div class="lq-playbooks-page__state" data-testid="lq-playbooks-empty">
			No playbooks available yet.
		</div>
	{:else}
		<table class="lq-playbooks-table" data-testid="lq-playbooks-table">
			<thead>
				<tr>
					<th scope="col">Name</th>
					<th scope="col">Contract type</th>
					<th scope="col">Version</th>
					<th scope="col" class="lq-playbooks-table__actions">&nbsp;</th>
				</tr>
			</thead>
			<tbody>
				{#each playbooks as p (p.id)}
					<tr data-testid="lq-playbook-row" data-playbook-id={p.id}>
						<td class="lq-playbooks-table__name">
							<div class="lq-playbooks-table__name-text">{p.name}</div>
							{#if p.description}
								<div class="lq-playbooks-table__desc">{p.description}</div>
							{/if}
						</td>
						<td>{p.contract_type}</td>
						<td>{formatVersion(p.version)}</td>
						<td class="lq-playbooks-table__actions">
							<button
								type="button"
								class="lq-playbooks-table__apply"
								data-testid="lq-playbook-apply"
								on:click={() => openExecute(p)}
							>
								Apply
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}

	{#if selectedPlaybook}
		<PlaybookExecuteModal playbook={selectedPlaybook} on:close={closeExecute} />
	{/if}
</section>

<style>
	.lq-playbooks-page {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		max-width: 64rem;
		margin: 0 auto;
		padding: 1.5rem;
	}
	.lq-playbooks-page__header h1 {
		margin: 0 0 0.5rem;
		font-size: 1.5rem;
	}
	.lq-playbooks-page__subtitle {
		margin: 0;
		color: var(--lq-text-secondary);
	}
	.lq-playbooks-page__state,
	.lq-playbooks-page__error {
		padding: 1.5rem;
		text-align: center;
		color: var(--lq-text-secondary);
		background: var(--lq-inset);
		border-radius: 0.5rem;
	}
	.lq-playbooks-page__error {
		color: var(--lq-error);
		background: var(--lq-error-soft, var(--lq-inset));
		border: 1px solid var(--lq-error-border, var(--lq-border));
	}
	.lq-playbooks-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		overflow: hidden;
	}
	.lq-playbooks-table th,
	.lq-playbooks-table td {
		padding: 0.75rem 1rem;
		text-align: left;
		border-bottom: 1px solid var(--lq-border);
	}
	.lq-playbooks-table tbody tr:last-child td {
		border-bottom: none;
	}
	.lq-playbooks-table__name-text {
		font-weight: 600;
	}
	.lq-playbooks-table__desc {
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
		margin-top: 0.25rem;
	}
	.lq-playbooks-table__actions {
		text-align: right;
		width: 1%;
		white-space: nowrap;
	}
	.lq-playbooks-table__apply {
		padding: 0.375rem 0.75rem;
		background: var(--lq-accent);
		color: var(--lq-on-accent, white);
		border: none;
		border-radius: 0.375rem;
		cursor: pointer;
		font-size: 0.875rem;
		font-weight: 500;
	}
	.lq-playbooks-table__apply:hover {
		opacity: 0.9;
	}
</style>
```

NOTE: `PlaybookExecuteModal` is the import target for Task 6. The page won't compile yet; that's fine — Task 6 creates the modal next.

- [ ] **Step 5: Defer typecheck until Task 6 lands**

The list page imports `PlaybookExecuteModal` which doesn't exist yet. **Do not run svelte-check now**; it will fail with an unresolvable import. Proceed to Task 6.

- [ ] **Step 6: Commit (helper file only — page commits with the modal)**

```bash
git add web/src/routes/lq-ai/playbooks/page-helpers.ts web/src/routes/lq-ai/playbooks/__tests__/page-helpers.test.ts
git commit -s -m "$(cat <<'EOF'
feat(web,m3-a4): list-page pure helpers (sortPlaybooksByName, formatVersion)

vitest-tested helpers for the /lq-ai/playbooks route. Page .svelte file
ships with the PlaybookExecuteModal in the next commit.
EOF
)"
```

---

## Task 6 — Frontend: `PlaybookExecuteModal` (doc picker + cost preview + execute)

**Files:**
- Create: `web/src/lib/lq-ai/components/PlaybookExecuteModal.svelte`

**What it does:**
1. Loads the user's documents (using the existing `listFiles` or equivalent — verify the right helper for "list user's documents that have a parsed `documents` row").
2. Shows a document picker (dropdown or radio list).
3. When a doc is picked, shows the cost preview: `Estimated cost: $X.XX (Y positions × judge model)`.
4. "Cancel" closes; "Run playbook" calls `executePlaybook` and on success redirects to `/lq-ai/playbook-executions/{newExecution.id}`.

**Confirm at Task start:**

```bash
grep -rn "listFiles\|GET /api/v1/files" web/src/lib/lq-ai/api/ | head -10
```

Identify the right function to list documents. The execute endpoint takes a `target_document_id` (Document, not File); the existing UI may surface files and you may need a "list documents" endpoint OR derive document_id from a file_id. **If a `listDocuments` helper doesn't exist, surface this to the user before proceeding** — it may need a small new API client function, OR may already exist under a different name (e.g., `listKnowledgeBaseFiles` returns documents indirectly).

- [ ] **Step 1: Discover the document/file listing pattern**

```bash
git show origin/m3-development:web/src/lib/lq-ai/api/files.ts 2>&1 | head -60
```

Read what exists. The execute endpoint wants `target_document_id` (a Document UUID). Identify whether there's a clean list-my-documents helper, OR whether you need to read knowledge-base files and surface the document_id from there. Document your finding and pick a path.

If the cleanest path is "user picks a KB → user picks a doc within the KB," do that. The Cypress test will mock the responses anyway.

- [ ] **Step 2: Implement the modal**

Create `web/src/lib/lq-ai/components/PlaybookExecuteModal.svelte`:

```svelte
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { goto } from '$app/navigation';

	import { executePlaybook } from '$lib/lq-ai/api/playbooks';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import {
		estimatePlaybookCost,
		formatCostUSD,
		DEFAULT_JUDGE_MODEL
	} from '$lib/lq-ai/playbookCost';
	import type { Playbook } from '$lib/lq-ai/types';

	// IMPORTANT: replace this with the actual helper for listing the
	// user's documents discovered in Step 1. If the helper returns
	// files (not documents) plus a `document_id` field, adapt the
	// picker rendering below to surface the doc name + file name.
	import { listKnowledgeBaseFiles } from '$lib/lq-ai/api/knowledgeBases';

	export let playbook: Playbook;

	const dispatch = createEventDispatcher<{ close: void }>();

	let documents: Array<{ id: string; name: string }> = [];
	let docsLoading = false;
	let docsError: string | null = null;

	let selectedDocId = '';
	let executing = false;
	let executeError: string | null = null;

	$: cost = estimatePlaybookCost(playbook, DEFAULT_JUDGE_MODEL);

	async function loadDocs(): Promise<void> {
		docsLoading = true;
		docsError = null;
		try {
			// REPLACE THIS with the correct helper from Step 1's reconnaissance.
			// The shape we need: an array of { id: document_id, name: human_label }.
			// Example using KB files (adjust as needed):
			//   const files = await listKnowledgeBaseFiles(someKbId);
			//   documents = files.map(f => ({ id: f.document_id, name: f.filename }));
			documents = [];
		} catch (err) {
			docsError = err instanceof LQAIApiError ? err.message : 'Failed to load documents.';
		} finally {
			docsLoading = false;
		}
	}

	async function handleExecute(): Promise<void> {
		if (!selectedDocId) return;
		executing = true;
		executeError = null;
		try {
			const exec = await executePlaybook(playbook.id, { target_document_id: selectedDocId });
			dispatch('close');
			await goto(`/lq-ai/playbook-executions/${exec.id}`);
		} catch (err) {
			executeError =
				err instanceof LQAIApiError ? err.message : 'Failed to start playbook execution.';
			executing = false;
		}
	}

	loadDocs();
</script>

<div
	class="lq-modal-overlay"
	on:click={() => dispatch('close')}
	role="presentation"
></div>

<div
	class="lq-modal"
	role="dialog"
	aria-modal="true"
	aria-labelledby="lq-execute-title"
	data-testid="lq-playbook-execute-modal"
>
	<header class="lq-modal__header">
		<h2 id="lq-execute-title">Apply playbook: {playbook.name}</h2>
		<button
			type="button"
			class="lq-modal__close"
			on:click={() => dispatch('close')}
			aria-label="Close"
		>
			×
		</button>
	</header>

	<div class="lq-modal__body">
		<div class="lq-modal__field">
			<label for="lq-execute-doc">Target document</label>
			{#if docsLoading}
				<div class="lq-modal__placeholder">Loading documents…</div>
			{:else if docsError}
				<div class="lq-modal__placeholder" role="alert">{docsError}</div>
			{:else if documents.length === 0}
				<div class="lq-modal__placeholder">No documents available.</div>
			{:else}
				<select
					id="lq-execute-doc"
					bind:value={selectedDocId}
					data-testid="lq-playbook-execute-doc-picker"
				>
					<option value="">Choose a document…</option>
					{#each documents as d (d.id)}
						<option value={d.id}>{d.name}</option>
					{/each}
				</select>
			{/if}
		</div>

		<div class="lq-modal__cost" data-testid="lq-playbook-cost-preview">
			<div class="lq-modal__cost-label">Estimated cost</div>
			<div class="lq-modal__cost-amount">{formatCostUSD(cost.estimated_cost_usd)}</div>
			<div class="lq-modal__cost-detail">
				{cost.position_count} positions · model: {cost.judge_model}
			</div>
		</div>

		{#if executeError}
			<div class="lq-modal__error" role="alert" data-testid="lq-playbook-execute-error">
				{executeError}
			</div>
		{/if}
	</div>

	<footer class="lq-modal__footer">
		<button
			type="button"
			class="lq-modal__btn lq-modal__btn--secondary"
			on:click={() => dispatch('close')}
			disabled={executing}
		>
			Cancel
		</button>
		<button
			type="button"
			class="lq-modal__btn lq-modal__btn--primary"
			on:click={handleExecute}
			disabled={!selectedDocId || executing}
			data-testid="lq-playbook-execute-confirm"
		>
			{executing ? 'Starting…' : 'Run playbook'}
		</button>
	</footer>
</div>

<style>
	.lq-modal-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.4);
		z-index: 1000;
	}
	.lq-modal {
		position: fixed;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		width: min(90vw, 32rem);
		max-height: 90vh;
		overflow-y: auto;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		z-index: 1001;
		display: flex;
		flex-direction: column;
	}
	.lq-modal__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 1rem 1.25rem;
		border-bottom: 1px solid var(--lq-border);
	}
	.lq-modal__header h2 {
		margin: 0;
		font-size: 1.125rem;
	}
	.lq-modal__close {
		background: none;
		border: none;
		font-size: 1.5rem;
		line-height: 1;
		cursor: pointer;
		color: var(--lq-text-secondary);
	}
	.lq-modal__body {
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.lq-modal__field label {
		display: block;
		font-size: 0.875rem;
		font-weight: 500;
		margin-bottom: 0.375rem;
	}
	.lq-modal__field select {
		width: 100%;
		padding: 0.5rem 0.625rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		background: var(--lq-surface);
		font-size: 0.9375rem;
	}
	.lq-modal__placeholder {
		padding: 0.5rem 0.625rem;
		background: var(--lq-inset);
		border-radius: 0.375rem;
		font-size: 0.875rem;
		color: var(--lq-text-secondary);
	}
	.lq-modal__cost {
		padding: 0.875rem 1rem;
		background: var(--lq-inset);
		border-radius: 0.5rem;
	}
	.lq-modal__cost-label {
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
	}
	.lq-modal__cost-amount {
		font-size: 1.5rem;
		font-weight: 600;
		margin: 0.125rem 0;
	}
	.lq-modal__cost-detail {
		font-size: 0.8125rem;
		color: var(--lq-text-tertiary, var(--lq-text-secondary));
	}
	.lq-modal__error {
		padding: 0.625rem 0.875rem;
		background: var(--lq-error-soft, var(--lq-inset));
		border: 1px solid var(--lq-error-border, var(--lq-border));
		color: var(--lq-error);
		border-radius: 0.375rem;
		font-size: 0.875rem;
	}
	.lq-modal__footer {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		padding: 1rem 1.25rem;
		border-top: 1px solid var(--lq-border);
	}
	.lq-modal__btn {
		padding: 0.5rem 1rem;
		border-radius: 0.375rem;
		font-size: 0.875rem;
		cursor: pointer;
		border: 1px solid transparent;
	}
	.lq-modal__btn--secondary {
		background: var(--lq-surface);
		border-color: var(--lq-border);
		color: var(--lq-text-primary);
	}
	.lq-modal__btn--primary {
		background: var(--lq-accent);
		color: var(--lq-on-accent, white);
	}
	.lq-modal__btn--primary:disabled,
	.lq-modal__btn--secondary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
```

- [ ] **Step 3: Fix the document-listing code path**

Edit the `loadDocs()` body to use the actual helper discovered in Step 1. This may require a small refactor to surface a "list my documents" client function. **If the cleanest path requires adding a new TS helper that wraps an existing endpoint, add it and commit it as part of this task.** If it requires a NEW backend endpoint, stop and surface to the user — that's scope creep beyond §5.1.

- [ ] **Step 4: Run svelte-check now that the page + modal both exist**

```bash
cd web && npx svelte-check --tsconfig tsconfig.json --threshold error
```

Expected: no errors related to the playbook files. Pre-existing errors elsewhere are fine.

- [ ] **Step 5: Commit the page + modal together**

```bash
git add web/src/routes/lq-ai/playbooks/+page.svelte web/src/lib/lq-ai/components/PlaybookExecuteModal.svelte
git commit -s -m "$(cat <<'EOF'
feat(web,m3-a4): /lq-ai/playbooks list page + execute modal

* /lq-ai/playbooks list page: table of available playbooks; Apply
  button opens the execute modal. Includes the disclaimer banner
  (Decision F) at the top.
* PlaybookExecuteModal: doc picker + client-side cost preview + run
  button. On success redirects to /lq-ai/playbook-executions/{id}.

Cost math uses the static rate table from playbookCost.ts; the §5.2
decision keeps this client-side for M3-A4.
EOF
)"
```

---

## Task 7 — Frontend: `/lq-ai/playbook-executions/[id]` result page

**Files:**
- Create: `web/src/routes/lq-ai/playbook-executions/[id]/+page.svelte`
- Create: `web/src/routes/lq-ai/playbook-executions/[id]/page-helpers.ts`
- Test: `web/src/routes/lq-ai/playbook-executions/[id]/__tests__/page-helpers.test.ts`

**What it shows:**
- Header with playbook name, target document name, status pill, started/completed timestamps
- PlaybookDisclaimerBanner
- Summary bar: counts of matches_standard / matches_fallback / deviates / missing
- Filter bar: dropdown for severity (all/critical/high/medium/low), dropdown for outcome (all/matches/deviates/missing)
- Dense rows table: each row = severity pill, issue title, outcome pill, citation count, chevron toggle
- Expanded row reveals: standard language, actual matched text, redline (old → new with justification), citation chunk IDs
- Status polling: if status is `pending` or `running`, poll every 3s. Stop polling when terminal.
- Error state if `status='error'`: show the `error` field with retry guidance.

- [ ] **Step 1: Write the failing test for helpers**

Create `web/src/routes/lq-ai/playbook-executions/[id]/__tests__/page-helpers.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';

import {
	severityClass,
	outcomeClass,
	severityLabel,
	outcomeLabel,
	filterPositions
} from '../page-helpers';
import type { PlaybookPositionResult } from '$lib/lq-ai/types';

describe('severityClass', () => {
	it('maps each severity to a unique class', () => {
		expect(severityClass('critical')).toBe('lq-severity--critical');
		expect(severityClass('high')).toBe('lq-severity--high');
		expect(severityClass('medium')).toBe('lq-severity--medium');
		expect(severityClass('low')).toBe('lq-severity--low');
	});
});

describe('outcomeClass', () => {
	it('maps each verdict to a unique class', () => {
		expect(outcomeClass('matches_standard')).toBe('lq-outcome--matches-standard');
		expect(outcomeClass('matches_fallback')).toBe('lq-outcome--matches-fallback');
		expect(outcomeClass('deviates')).toBe('lq-outcome--deviates');
		expect(outcomeClass('missing')).toBe('lq-outcome--missing');
	});
});

describe('severityLabel + outcomeLabel', () => {
	it('returns short human-readable labels', () => {
		expect(severityLabel('critical')).toBe('Critical');
		expect(severityLabel('high')).toBe('High');
		expect(outcomeLabel('matches_standard')).toBe('Matches standard');
		expect(outcomeLabel('matches_fallback')).toBe('Matches fallback');
		expect(outcomeLabel('deviates')).toBe('Deviates');
		expect(outcomeLabel('missing')).toBe('Missing');
	});
});

describe('filterPositions', () => {
	const positions: PlaybookPositionResult[] = [
		{
			position_id: '1', issue: 'A', severity_if_missing: 'critical',
			verdict: 'deviates', confidence: 0.9, matched_fallback_rank: null,
			cited_chunk_ids: [], matched_text: '', redline: null, justification: ''
		},
		{
			position_id: '2', issue: 'B', severity_if_missing: 'low',
			verdict: 'matches_standard', confidence: 0.9, matched_fallback_rank: null,
			cited_chunk_ids: [], matched_text: '', redline: null, justification: ''
		},
		{
			position_id: '3', issue: 'C', severity_if_missing: 'high',
			verdict: 'missing', confidence: 0.7, matched_fallback_rank: null,
			cited_chunk_ids: [], matched_text: '', redline: null, justification: ''
		}
	];

	it('returns all when filters are "all"', () => {
		expect(filterPositions(positions, 'all', 'all')).toHaveLength(3);
	});

	it('filters by severity', () => {
		const out = filterPositions(positions, 'critical', 'all');
		expect(out.map((p) => p.position_id)).toEqual(['1']);
	});

	it('filters by outcome', () => {
		const out = filterPositions(positions, 'all', 'missing');
		expect(out.map((p) => p.position_id)).toEqual(['3']);
	});

	it('filters by both', () => {
		expect(filterPositions(positions, 'high', 'missing').map((p) => p.position_id)).toEqual(['3']);
		expect(filterPositions(positions, 'critical', 'matches_standard')).toEqual([]);
	});
});
```

- [ ] **Step 2: Create the helpers file**

Create `web/src/routes/lq-ai/playbook-executions/[id]/page-helpers.ts`:

```typescript
import type {
	PlaybookPositionResult,
	PlaybookPositionVerdict,
	PositionSeverity
} from '$lib/lq-ai/types';

export type SeverityFilter = 'all' | PositionSeverity;
export type OutcomeFilter = 'all' | PlaybookPositionVerdict;

export function severityClass(s: PositionSeverity): string {
	return `lq-severity--${s}`;
}

export function outcomeClass(v: PlaybookPositionVerdict): string {
	// matches_standard → matches-standard for CSS-friendly slugs
	return `lq-outcome--${v.replace(/_/g, '-')}`;
}

export function severityLabel(s: PositionSeverity): string {
	return s.charAt(0).toUpperCase() + s.slice(1);
}

export function outcomeLabel(v: PlaybookPositionVerdict): string {
	switch (v) {
		case 'matches_standard':
			return 'Matches standard';
		case 'matches_fallback':
			return 'Matches fallback';
		case 'deviates':
			return 'Deviates';
		case 'missing':
			return 'Missing';
	}
}

export function filterPositions(
	positions: PlaybookPositionResult[],
	severity: SeverityFilter,
	outcome: OutcomeFilter
): PlaybookPositionResult[] {
	return positions.filter((p) => {
		if (severity !== 'all' && p.severity_if_missing !== severity) return false;
		if (outcome !== 'all' && p.verdict !== outcome) return false;
		return true;
	});
}
```

- [ ] **Step 3: Run the test to verify it passes**

```bash
cd web && npx vitest run "src/routes/lq-ai/playbook-executions/[id]/__tests__/page-helpers.test.ts"
```

Expected: PASS.

- [ ] **Step 4: Create the result page**

Create `web/src/routes/lq-ai/playbook-executions/[id]/+page.svelte`:

```svelte
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/stores';

	import { getPlaybook, getPlaybookExecution } from '$lib/lq-ai/api/playbooks';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import PlaybookDisclaimerBanner from '$lib/lq-ai/components/PlaybookDisclaimerBanner.svelte';
	import type {
		Playbook,
		PlaybookExecution,
		PositionSeverity,
		PlaybookPositionVerdict
	} from '$lib/lq-ai/types';

	import {
		severityClass,
		severityLabel,
		outcomeClass,
		outcomeLabel,
		filterPositions,
		type SeverityFilter,
		type OutcomeFilter
	} from './page-helpers';

	let execution: PlaybookExecution | null = null;
	let playbook: Playbook | null = null;
	let loading = true;
	let loadError: string | null = null;

	let expanded = new Set<string>();
	let severityFilter: SeverityFilter = 'all';
	let outcomeFilter: OutcomeFilter = 'all';

	let pollTimer: ReturnType<typeof setTimeout> | null = null;

	$: executionId = $page.params.id;
	$: positions = execution?.results?.positions ?? [];
	$: filteredPositions = filterPositions(positions, severityFilter, outcomeFilter);
	$: summary = execution?.results?.summary ?? {
		matches_standard: 0,
		matches_fallback: 0,
		deviates: 0,
		missing: 0
	};

	async function loadOnce(): Promise<void> {
		loadError = null;
		try {
			const exec = await getPlaybookExecution(executionId);
			execution = exec;
			if (playbook === null) {
				playbook = await getPlaybook(exec.playbook_id);
			}
			scheduleNextPoll();
		} catch (err) {
			loadError = err instanceof LQAIApiError ? err.message : 'Failed to load execution.';
		} finally {
			loading = false;
		}
	}

	function scheduleNextPoll(): void {
		if (!execution) return;
		const terminal = execution.status === 'completed' || execution.status === 'error';
		if (terminal) {
			if (pollTimer) clearTimeout(pollTimer);
			pollTimer = null;
			return;
		}
		if (pollTimer) clearTimeout(pollTimer);
		pollTimer = setTimeout(loadOnce, 3000);
	}

	function toggleExpand(positionId: string): void {
		if (expanded.has(positionId)) expanded.delete(positionId);
		else expanded.add(positionId);
		expanded = new Set(expanded);
	}

	onMount(loadOnce);
	onDestroy(() => {
		if (pollTimer) clearTimeout(pollTimer);
	});
</script>

<svelte:head>
	<title>Playbook execution · LQ.AI</title>
</svelte:head>

<section class="lq-pbx-page">
	{#if loading && !execution}
		<div class="lq-pbx-page__state" data-testid="lq-pbx-loading">Loading…</div>
	{:else if loadError && !execution}
		<div class="lq-pbx-page__error" role="alert" data-testid="lq-pbx-error">{loadError}</div>
	{:else if execution}
		<header class="lq-pbx-page__header">
			<div>
				<h1>{playbook?.name ?? 'Playbook execution'}</h1>
				<p class="lq-pbx-page__sub">
					Status: <span class="lq-pbx-status lq-pbx-status--{execution.status}"
						data-testid="lq-pbx-status">{execution.status}</span>
					{#if execution.completed_at}
						· completed {new Date(execution.completed_at).toLocaleString()}
					{:else}
						· started {new Date(execution.created_at).toLocaleString()}
					{/if}
				</p>
			</div>
		</header>

		<PlaybookDisclaimerBanner />

		{#if execution.status === 'error'}
			<div class="lq-pbx-page__error" role="alert" data-testid="lq-pbx-execution-error">
				Execution failed: {execution.error ?? 'unknown error'}
			</div>
		{:else if execution.status === 'pending' || execution.status === 'running'}
			<div class="lq-pbx-page__state" data-testid="lq-pbx-running">
				Playbook is {execution.status}. Refreshing every 3 seconds…
			</div>
		{:else if execution.status === 'completed' && execution.results}
			<aside class="lq-pbx-summary" data-testid="lq-pbx-summary">
				<div class="lq-pbx-summary__item">
					<div class="lq-pbx-summary__count">{summary.matches_standard}</div>
					<div class="lq-pbx-summary__label">Matches standard</div>
				</div>
				<div class="lq-pbx-summary__item">
					<div class="lq-pbx-summary__count">{summary.matches_fallback}</div>
					<div class="lq-pbx-summary__label">Matches fallback</div>
				</div>
				<div class="lq-pbx-summary__item">
					<div class="lq-pbx-summary__count">{summary.deviates}</div>
					<div class="lq-pbx-summary__label">Deviates</div>
				</div>
				<div class="lq-pbx-summary__item">
					<div class="lq-pbx-summary__count">{summary.missing}</div>
					<div class="lq-pbx-summary__label">Missing</div>
				</div>
			</aside>

			<div class="lq-pbx-filters" data-testid="lq-pbx-filters">
				<label>
					Severity:
					<select bind:value={severityFilter} data-testid="lq-pbx-filter-severity">
						<option value="all">All</option>
						<option value="critical">Critical</option>
						<option value="high">High</option>
						<option value="medium">Medium</option>
						<option value="low">Low</option>
					</select>
				</label>
				<label>
					Outcome:
					<select bind:value={outcomeFilter} data-testid="lq-pbx-filter-outcome">
						<option value="all">All</option>
						<option value="matches_standard">Matches standard</option>
						<option value="matches_fallback">Matches fallback</option>
						<option value="deviates">Deviates</option>
						<option value="missing">Missing</option>
					</select>
				</label>
				<div class="lq-pbx-filters__count">
					{filteredPositions.length} of {positions.length} positions
				</div>
			</div>

			<table class="lq-pbx-table" data-testid="lq-pbx-table">
				<thead>
					<tr>
						<th class="lq-pbx-table__chev" scope="col">&nbsp;</th>
						<th scope="col">Severity</th>
						<th scope="col">Issue</th>
						<th scope="col">Outcome</th>
						<th scope="col">Citations</th>
					</tr>
				</thead>
				<tbody>
					{#each filteredPositions as pos (pos.position_id)}
						{@const isOpen = expanded.has(pos.position_id)}
						<tr
							class="lq-pbx-row"
							class:lq-pbx-row--open={isOpen}
							data-testid="lq-pbx-row"
							data-position-id={pos.position_id}
						>
							<td class="lq-pbx-table__chev">
								<button
									type="button"
									class="lq-pbx-chev-btn"
									aria-expanded={isOpen}
									aria-controls={`lq-pbx-detail-${pos.position_id}`}
									on:click={() => toggleExpand(pos.position_id)}
								>
									{isOpen ? '▼' : '▶'}
								</button>
							</td>
							<td>
								<span class="lq-severity-pill {severityClass(pos.severity_if_missing)}">
									{severityLabel(pos.severity_if_missing)}
								</span>
							</td>
							<td class="lq-pbx-table__issue">{pos.issue}</td>
							<td>
								<span class="lq-outcome-pill {outcomeClass(pos.verdict)}">
									{outcomeLabel(pos.verdict)}
								</span>
							</td>
							<td>{pos.cited_chunk_ids.length}</td>
						</tr>
						{#if isOpen}
							<tr id={`lq-pbx-detail-${pos.position_id}`} class="lq-pbx-detail-row">
								<td colspan="5">
									<div class="lq-pbx-detail">
										<div class="lq-pbx-detail__field">
											<div class="lq-pbx-detail__label">Confidence</div>
											<div>{(pos.confidence * 100).toFixed(0)}%</div>
										</div>
										{#if pos.matched_text}
											<div class="lq-pbx-detail__field">
												<div class="lq-pbx-detail__label">Contract clause</div>
												<blockquote class="lq-pbx-detail__quote">{pos.matched_text}</blockquote>
											</div>
										{/if}
										<div class="lq-pbx-detail__field">
											<div class="lq-pbx-detail__label">Justification</div>
											<div>{pos.justification}</div>
										</div>
										{#if pos.redline}
											<div class="lq-pbx-detail__field lq-pbx-detail__redline">
												<div class="lq-pbx-detail__label">Suggested redline</div>
												<div class="lq-pbx-detail__redline-old">{pos.redline.old_text}</div>
												<div class="lq-pbx-detail__redline-new">{pos.redline.new_text}</div>
												<div class="lq-pbx-detail__redline-just">
													{pos.redline.justification}
												</div>
											</div>
										{/if}
										{#if pos.cited_chunk_ids.length > 0}
											<div class="lq-pbx-detail__field">
												<div class="lq-pbx-detail__label">Cited chunks</div>
												<div class="lq-pbx-detail__chunks">
													{#each pos.cited_chunk_ids as chunkId (chunkId)}
														<code class="lq-pbx-detail__chunk-id">{chunkId}</code>
													{/each}
												</div>
											</div>
										{/if}
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		{/if}
	{/if}
</section>

<style>
	.lq-pbx-page {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		max-width: 80rem;
		margin: 0 auto;
		padding: 1.5rem;
	}
	.lq-pbx-page__header h1 {
		margin: 0 0 0.25rem;
		font-size: 1.5rem;
	}
	.lq-pbx-page__sub {
		margin: 0;
		color: var(--lq-text-secondary);
		font-size: 0.875rem;
	}
	.lq-pbx-page__state,
	.lq-pbx-page__error {
		padding: 1.5rem;
		text-align: center;
		background: var(--lq-inset);
		border-radius: 0.5rem;
		color: var(--lq-text-secondary);
	}
	.lq-pbx-page__error {
		color: var(--lq-error);
		background: var(--lq-error-soft, var(--lq-inset));
		border: 1px solid var(--lq-error-border, var(--lq-border));
	}

	.lq-pbx-status {
		display: inline-block;
		padding: 0.125rem 0.5rem;
		border-radius: 9999px;
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.lq-pbx-status--pending,
	.lq-pbx-status--running {
		background: var(--lq-warn-soft, var(--lq-inset));
		color: var(--lq-warn, var(--lq-text-secondary));
	}
	.lq-pbx-status--completed {
		background: var(--lq-accent-soft, var(--lq-inset));
		color: var(--lq-accent);
	}
	.lq-pbx-status--error {
		background: var(--lq-error-soft, var(--lq-inset));
		color: var(--lq-error);
	}

	.lq-pbx-summary {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 0.75rem;
	}
	.lq-pbx-summary__item {
		padding: 0.875rem 1rem;
		background: var(--lq-inset);
		border-radius: 0.5rem;
		text-align: center;
	}
	.lq-pbx-summary__count {
		font-size: 1.5rem;
		font-weight: 600;
	}
	.lq-pbx-summary__label {
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
	}

	.lq-pbx-filters {
		display: flex;
		gap: 1rem;
		align-items: center;
		padding: 0.625rem 0.875rem;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		font-size: 0.875rem;
	}
	.lq-pbx-filters label {
		display: inline-flex;
		gap: 0.375rem;
		align-items: center;
	}
	.lq-pbx-filters select {
		padding: 0.25rem 0.5rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		background: var(--lq-surface);
		font-size: 0.875rem;
	}
	.lq-pbx-filters__count {
		margin-left: auto;
		color: var(--lq-text-secondary);
	}

	.lq-pbx-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		overflow: hidden;
	}
	.lq-pbx-table th,
	.lq-pbx-table td {
		padding: 0.625rem 0.875rem;
		text-align: left;
		border-bottom: 1px solid var(--lq-border);
		font-size: 0.875rem;
	}
	.lq-pbx-table__chev {
		width: 2rem;
		text-align: center;
	}
	.lq-pbx-table__issue {
		font-weight: 500;
	}
	.lq-pbx-chev-btn {
		background: none;
		border: none;
		cursor: pointer;
		color: var(--lq-text-secondary);
		font-size: 0.875rem;
	}
	.lq-pbx-detail-row td {
		background: var(--lq-inset);
		padding: 1rem;
	}
	.lq-pbx-detail {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.lq-pbx-detail__field {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.lq-pbx-detail__label {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.lq-pbx-detail__quote {
		margin: 0;
		padding: 0.5rem 0.75rem;
		border-left: 3px solid var(--lq-border);
		background: var(--lq-surface);
		font-style: italic;
	}
	.lq-pbx-detail__redline-old {
		text-decoration: line-through;
		color: var(--lq-error);
	}
	.lq-pbx-detail__redline-new {
		color: var(--lq-accent);
	}
	.lq-pbx-detail__redline-just {
		margin-top: 0.25rem;
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
	}
	.lq-pbx-detail__chunks {
		display: flex;
		flex-wrap: wrap;
		gap: 0.375rem;
	}
	.lq-pbx-detail__chunk-id {
		font-size: 0.75rem;
		padding: 0.125rem 0.375rem;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.25rem;
	}

	/* Severity pills — match the existing --lq-* token palette */
	.lq-severity-pill {
		display: inline-block;
		padding: 0.125rem 0.5rem;
		border-radius: 9999px;
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.lq-severity--critical {
		background: var(--lq-error-soft, var(--lq-inset));
		color: var(--lq-error);
		border: 1px solid var(--lq-error-border, transparent);
	}
	.lq-severity--high {
		background: var(--lq-warn-soft, var(--lq-inset));
		color: var(--lq-warn);
		border: 1px solid var(--lq-warn-border, transparent);
	}
	.lq-severity--medium {
		background: var(--lq-inset);
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
	}
	.lq-severity--low {
		background: var(--lq-inset);
		color: var(--lq-text-tertiary, var(--lq-text-secondary));
		border: 1px solid var(--lq-border);
	}

	/* Outcome pills */
	.lq-outcome-pill {
		display: inline-block;
		padding: 0.125rem 0.5rem;
		border-radius: 9999px;
		font-size: 0.75rem;
		font-weight: 500;
	}
	.lq-outcome--matches-standard {
		background: var(--lq-accent-soft, var(--lq-inset));
		color: var(--lq-accent);
	}
	.lq-outcome--matches-fallback {
		background: var(--lq-inset);
		color: var(--lq-text-secondary);
	}
	.lq-outcome--deviates {
		background: var(--lq-warn-soft, var(--lq-inset));
		color: var(--lq-warn);
	}
	.lq-outcome--missing {
		background: var(--lq-error-soft, var(--lq-inset));
		color: var(--lq-error);
	}
</style>
```

- [ ] **Step 5: Verify with svelte-check**

```bash
cd web && npx svelte-check --tsconfig tsconfig.json --threshold error
```

Expected: no errors related to the playbook files.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/lq-ai/playbook-executions/
git commit -s -m "$(cat <<'EOF'
feat(web,m3-a4): /lq-ai/playbook-executions/[id] result view

Dense-row + expand-to-reveal layout per §5.4 design decision:

* Header: playbook name, status pill, started/completed timestamps
* Disclaimer banner (Decision F)
* Summary bar: per-outcome counts
* Filter bar: severity (all/critical/high/medium/low) +
  outcome (all/matches_standard/matches_fallback/deviates/missing)
* Position table: severity pill, issue, outcome pill, citation count,
  chevron toggle. Expand reveals contract clause, justification,
  redline (old/new/why), and cited chunk IDs.
* Status polling: 3s interval while status is pending/running.

Severity + outcome colors derived from the existing --lq-{accent|
warn|error} token palette. WCAG 2.1 AA verified manually via browser
devtools (no automated a11y tooling in the codebase today).
EOF
)"
```

---

## Task 8 — Frontend: sidebar nav link

**Files:**
- Modify: the sidebar nav file located in Task 0 Step 2

- [ ] **Step 1: Re-confirm the sidebar nav file path**

From Task 0 Step 2's recon, identify the file that lists `/lq-ai/knowledge` as a nav target. Read it.

- [ ] **Step 2: Add a "Playbooks" entry**

Edit the sidebar nav file. Find the entry for `/lq-ai/knowledge` and add a sibling entry pointing to `/lq-ai/playbooks` with an appropriate icon (search for the icon import pattern used by the knowledge entry — use a similar svg path or `<Icon />` invocation; if iconography uses a separate icon file, add a "playbook" icon there too).

Example shape (adapt to the file's actual style):

```svelte
<a href="/lq-ai/playbooks" data-testid="lq-nav-playbooks" class:active={isActive('/lq-ai/playbooks')}>
	<!-- icon -->
	<span>Playbooks</span>
</a>
```

If the sidebar uses a data-driven array of nav entries, add an entry to that array instead.

- [ ] **Step 3: Smoke-check by booting the dev server**

```bash
cd /Users/kevinkeller/Desktop/lq-ai
docker compose up -d
sleep 5
open http://localhost:3000/lq-ai/playbooks
```

Visually confirm:
1. Sidebar shows "Playbooks" entry
2. Clicking it routes to /lq-ai/playbooks
3. Page renders disclaimer banner + table (or empty state)

If the stack isn't running or DB is empty, the empty state is acceptable for now — Cypress will mock data. Capture the smoke-check observation in the commit message.

- [ ] **Step 4: Commit**

```bash
git add <the-sidebar-file>
git commit -s -m "$(cat <<'EOF'
feat(web,m3-a4): add Playbooks entry to sidebar nav

Routes users to /lq-ai/playbooks alongside the existing Knowledge and
Chat entries. data-testid="lq-nav-playbooks" pinned for Cypress.
EOF
)"
```

---

## Task 9 — Cypress E2E: full happy path

**Files:**
- Create: `web/cypress/e2e/m3-a4-playbook-execution.cy.ts`

**Flow:** Login → visit /lq-ai/playbooks → see two NDA built-ins → click Apply on NDA — Mutual → pick a doc → see cost preview → confirm → land on execution view → poll once → see completed status + summary + filtered positions.

- [ ] **Step 1: Create the spec**

Create `web/cypress/e2e/m3-a4-playbook-execution.cy.ts`:

```typescript
/**
 * M3-A4 — Playbook execution UI happy path.
 *
 * All API responses are mocked via cy.intercept so the spec runs without
 * a populated database. The mocked responses mirror the wire shapes
 * defined by api/app/schemas/playbooks.py and the executor's
 * _shape_results_payload (api/app/playbooks/nodes.py).
 *
 * Run requires a live web stack (the SvelteKit server):
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/m3-a4-playbook-execution.cy.ts'
 */

/// <reference types="cypress" />

const PLAYBOOK_ID = 'pb-mutual-nda';
const EXECUTION_ID = 'exec-1';
const DOC_ID = 'doc-1';

const mockPlaybook = {
	id: PLAYBOOK_ID,
	name: 'NDA — Mutual',
	contract_type: 'NDA',
	description: 'Mutual NDA playbook covering 8 standard positions.',
	version: '1.0.0',
	created_by: null,
	created_at: '2026-05-18T00:00:00Z',
	updated_at: '2026-05-18T00:00:00Z',
	positions: Array.from({ length: 8 }, (_, i) => ({
		id: `pos-${i + 1}`,
		issue: `Position ${i + 1}`,
		description: '',
		standard_language: 'Standard language here.',
		fallback_tiers: [{ rank: 1, description: 'Fallback A', language: 'Fallback A text.' }],
		redline_strategy: '',
		severity_if_missing: (['critical', 'high', 'medium', 'low'] as const)[i % 4],
		detection_keywords: ['nda'],
		detection_examples: [],
		position_order: i
	}))
};

const mockExecutionPending = {
	id: EXECUTION_ID,
	playbook_id: PLAYBOOK_ID,
	target_document_id: DOC_ID,
	user_id: 'u1',
	project_id: null,
	status: 'pending',
	results: null,
	error: null,
	created_at: '2026-05-18T00:00:00Z',
	completed_at: null
};

const mockExecutionCompleted = {
	...mockExecutionPending,
	status: 'completed',
	completed_at: '2026-05-18T00:01:00Z',
	results: {
		schema_version: 'm3-a2-v1',
		positions: mockPlaybook.positions.map((p, i) => ({
			position_id: p.id,
			issue: p.issue,
			severity_if_missing: p.severity_if_missing,
			verdict: (['matches_standard', 'matches_fallback', 'deviates', 'missing'] as const)[
				i % 4
			],
			confidence: 0.9,
			matched_fallback_rank: null,
			cited_chunk_ids: ['chunk-a', 'chunk-b'],
			matched_text: 'The actual clause text from the contract.',
			redline:
				i % 4 === 2
					? {
							old_text: 'old clause',
							new_text: 'new clause',
							justification: 'tighter than fallback'
					  }
					: null,
			justification: 'Reason for the verdict.'
		})),
		summary: {
			matches_standard: 2,
			matches_fallback: 2,
			deviates: 2,
			missing: 2
		}
	}
};

describe('M3-A4 — Playbook execution happy path', () => {
	beforeEach(() => {
		// Successful login intercept (mirror M3-0.1 pattern)
		cy.intercept('POST', '**/api/v1/auth/login', {
			statusCode: 200,
			body: {
				access_token: 'fake-token',
				token_type: 'Bearer',
				expires_in: 3600,
				user: {
					id: 'u1',
					email: 'admin@lq.ai',
					is_admin: true,
					mfa_enabled: false,
					must_change_password: false,
					created_at: '2026-01-01T00:00:00Z'
				}
			}
		}).as('login');

		// Playbook list
		cy.intercept('GET', '**/api/v1/playbooks', {
			statusCode: 200,
			body: [
				mockPlaybook,
				{ ...mockPlaybook, id: 'pb-unilateral-nda', name: 'NDA — Unilateral' }
			]
		}).as('listPlaybooks');

		// Playbook detail
		cy.intercept('GET', `**/api/v1/playbooks/${PLAYBOOK_ID}`, {
			statusCode: 200,
			body: mockPlaybook
		}).as('getPlaybook');

		// Documents list — adapt to the helper chosen in Task 6 Step 1.
		// Example shown is for the knowledge-bases-files path:
		cy.intercept('GET', '**/api/v1/knowledge-bases/**/files', {
			statusCode: 200,
			body: [{ id: 'file-1', filename: 'sample-nda.pdf', document_id: DOC_ID }]
		}).as('listDocs');

		// Execute → 202 pending
		cy.intercept('POST', `**/api/v1/playbooks/${PLAYBOOK_ID}/execute`, {
			statusCode: 202,
			body: mockExecutionPending
		}).as('executePlaybook');

		// First poll → still pending; second poll → completed
		let pollCount = 0;
		cy.intercept('GET', `**/api/v1/playbook-executions/${EXECUTION_ID}`, (req) => {
			pollCount += 1;
			req.reply({
				statusCode: 200,
				body: pollCount === 1 ? mockExecutionPending : mockExecutionCompleted
			});
		}).as('pollExecution');
	});

	it('login → playbooks list → apply → cost preview → confirm → execution result', () => {
		// Login
		cy.visit('/lq-ai/login');
		cy.get('[data-testid="lq-ai-login-email"]').type('admin@lq.ai');
		cy.get('[data-testid="lq-ai-login-password"]').type('password');
		cy.get('[data-testid="lq-ai-login-submit"]').click();
		cy.wait('@login');

		// Navigate to playbooks
		cy.visit('/lq-ai/playbooks');
		cy.wait('@listPlaybooks');
		cy.get('[data-testid="lq-playbook-disclaimer"]').should('be.visible');
		cy.get('[data-testid="lq-playbooks-table"]').should('be.visible');
		cy.get('[data-testid="lq-playbook-row"]').should('have.length', 2);

		// Apply on the mutual NDA
		cy.get(`[data-playbook-id="${PLAYBOOK_ID}"]`)
			.find('[data-testid="lq-playbook-apply"]')
			.click();

		// Modal opens
		cy.get('[data-testid="lq-playbook-execute-modal"]').should('be.visible');
		cy.get('[data-testid="lq-playbook-cost-preview"]').should('contain', '$');
		cy.get('[data-testid="lq-playbook-cost-preview"]').should('contain', '8 positions');

		// Pick a doc
		cy.get('[data-testid="lq-playbook-execute-doc-picker"]').select(DOC_ID);

		// Confirm execution
		cy.get('[data-testid="lq-playbook-execute-confirm"]').click();
		cy.wait('@executePlaybook');

		// Redirected to the execution page
		cy.url().should('include', `/lq-ai/playbook-executions/${EXECUTION_ID}`);
		cy.wait('@pollExecution'); // first poll → pending
		cy.get('[data-testid="lq-pbx-running"]').should('be.visible');

		// Second poll fires after 3s → completed
		cy.wait('@pollExecution');
		cy.get('[data-testid="lq-pbx-status"]', { timeout: 10_000 }).should('contain', 'completed');
		cy.get('[data-testid="lq-pbx-summary"]').should('be.visible');
		cy.get('[data-testid="lq-pbx-table"]').should('be.visible');
		cy.get('[data-testid="lq-pbx-row"]').should('have.length', 8);

		// Filter by deviates
		cy.get('[data-testid="lq-pbx-filter-outcome"]').select('deviates');
		cy.get('[data-testid="lq-pbx-row"]').should('have.length', 2);

		// Expand the first row
		cy.get('[data-testid="lq-pbx-row"]')
			.first()
			.find('.lq-pbx-chev-btn')
			.click();
		cy.contains('Suggested redline').should('be.visible');
	});
});
```

- [ ] **Step 2: Run the spec against a live `docker compose up`**

```bash
cd /Users/kevinkeller/Desktop/lq-ai
docker compose up -d
sleep 8
cd web && npx cypress run --spec 'cypress/e2e/m3-a4-playbook-execution.cy.ts'
```

Expected: PASSING test. If it fails, the most common causes:
- The doc-picker intercept path doesn't match the helper chosen in Task 6 (adjust the URL pattern)
- Polling timeout: increase the `timeout` on the status assertion
- Selector mismatch from Task 5/7 — confirm data-testid names

**Do not relax the test to make it pass — fix the implementation.** The spec is the verification contract.

- [ ] **Step 3: Commit**

```bash
git add web/cypress/e2e/m3-a4-playbook-execution.cy.ts
git commit -s -m "$(cat <<'EOF'
test(web,m3-a4): Cypress E2E for playbook execution happy path

Covers: login → /lq-ai/playbooks → apply → cost preview → confirm →
poll → see completed result + summary + filter + expand. All API
responses mocked via cy.intercept so the spec runs without a populated
database.
EOF
)"
```

---

## Task 10 — Docs + final verification

**Files:**
- Modify: `docs/M3-IMPLEMENTATION-PLAN.md` (mark M3-A4 SHIPPED)
- Modify: `docs/PRD.md` (if any DE-XXX entries close at this task — check before editing)
- Optionally: `docs/HONEST-STATE.md`

- [ ] **Step 1: Run all backend tests one final time**

```bash
cd api && uv run pytest -x --ff
```

Expected: green.

- [ ] **Step 2: Run all frontend vitest tests**

```bash
cd web && npx vitest run
```

Expected: green; +N tests added by Tasks 2/3/5/7.

- [ ] **Step 3: Run ruff format + ruff check (per CI gate convention)**

```bash
cd api && uv run ruff format . && uv run ruff check .
```

Expected: no diffs, no errors. Per project memory `feedback_ruff_format_check.md`, CI runs both as separate gates; local pre-push verification must run both.

- [ ] **Step 4: Run eslint + prettier check on the web changes**

```bash
cd web && npx eslint 'src/lib/lq-ai/api/playbooks.ts' 'src/lib/lq-ai/playbookCost.ts' 'src/routes/lq-ai/playbooks/**/*' 'src/routes/lq-ai/playbook-executions/**/*' 'src/lib/lq-ai/components/PlaybookDisclaimerBanner.svelte' 'src/lib/lq-ai/components/PlaybookExecuteModal.svelte' --max-warnings 0
cd web && npx prettier --check 'src/lib/lq-ai/api/playbooks.ts' 'src/lib/lq-ai/playbookCost.ts' 'src/routes/lq-ai/playbooks/**/*' 'src/routes/lq-ai/playbook-executions/**/*' 'src/lib/lq-ai/components/PlaybookDisclaimerBanner.svelte' 'src/lib/lq-ai/components/PlaybookExecuteModal.svelte'
```

Expected: clean.

- [ ] **Step 5: Run svelte-check on the whole web/**

```bash
cd web && npx svelte-check --tsconfig tsconfig.json --threshold error
```

Expected: no NEW errors. Pre-existing errors elsewhere are fine.

- [ ] **Step 6: Visual + WCAG verification**

```bash
cd /Users/kevinkeller/Desktop/lq-ai
docker compose up -d
sleep 5
```

Then in a browser:
1. Visit http://localhost:3000/lq-ai/playbooks. Verify the disclaimer banner reads correctly and the table renders with the two NDA built-ins.
2. Apply one. Verify the cost preview shows a non-zero dollar amount and the position count (8).
3. Open browser devtools → Inspect → check the contrast of the severity pill text against its background using devtools' Accessibility / Contrast checker. Verify each of critical / high / medium / low passes WCAG 2.1 AA (contrast ratio ≥ 4.5:1 for normal text; ≥ 3:1 for large text).
4. Verify keyboard navigation: tab through the list, then on the result page, tab to a chevron and press Enter — the row should expand.

**If any severity pill fails WCAG AA**, adjust the color in the result page's `<style>` block. Likely candidate: `--lq-warn` may be too light for the "high" pill — switch to a darker accent or add a `color-mix(in srgb, var(--lq-warn), black 20%)` adjustment.

Capture the verification outcome (pass / which colors needed adjustment) in the final commit message.

- [ ] **Step 7: Update the M3 plan's M3-A4 entry**

Open `docs/M3-IMPLEMENTATION-PLAN.md`. Find the M3-A4 task entry. Append `Status: SHIPPED at M3-A4` and note the deferred-from-scope items inline. Mirror the markers used by M3-0.1 / M3-0.2 / M3-0.3 entries.

- [ ] **Step 8: Final commit**

```bash
git add docs/M3-IMPLEMENTATION-PLAN.md
git commit -s -m "$(cat <<'EOF'
docs(m3-a4): mark M3-A4 SHIPPED + record deferred items

Playbook execution UI lands. Deferred from scope (M3-A4 follow-ons):

* Citation Engine 5-state UI integration (file as DE-XXX)
* Apply-Playbook-from-document-context entry point (M3-A6)
* CRUD POST/PATCH/DELETE endpoints (M3-A6)
* Per-model pricing endpoint (deferred indefinitely; static client-side
  table is sufficient for informational cost preview)
* Automated WCAG audit tooling (filed as future DE; M3-A4 verified
  manually via browser devtools contrast checker)

Visual verification: <captured from Step 6's browser check>
EOF
)"
```

- [ ] **Step 9: Push and open PR**

```bash
git push -u origin m3-a4-playbook-execution-ui
gh pr create --base m3-development --title "feat(m3-a4): Playbook execution UI — list view + execute modal + result view" --body "$(cat <<'EOF'
## Summary

M3 Phase A, fourth task. Ships the operator-facing UI for the M3-A1/A2/A3 Playbook engine: a list view, an execute modal with cost preview, and a result view with dense per-position rows + expand-to-reveal.

Per the M3-A4 design decisions:
- §5.1 GET-only CRUD (list + detail endpoints); POST/PATCH/DELETE defer to M3-A6
- §5.2 client-side cost preview against a static rate table
- §5.3 disclaimer banner ships in M3-A4 (Decision F)
- §5.4 dense-rows + expand-to-reveal layout

## Test plan

- [x] api/ pytest green (+3 tests for the new GET endpoints)
- [x] web/ vitest green (+N tests for types/client/cost/page-helpers)
- [x] web/ svelte-check clean
- [x] Cypress E2E `m3-a4-playbook-execution.cy.ts` green
- [x] ruff format + ruff check green
- [x] eslint + prettier green on changed files
- [x] Visual: disclaimer banner reads correctly on both views
- [x] WCAG 2.1 AA verified manually for severity pill contrast

## Deferred from scope (M3-A4 follow-ons)

1. Citation Engine 5-state UI integration — file as DE-XXX
2. Apply-Playbook from a document's context menu — M3-A6
3. CRUD POST/PATCH/DELETE — M3-A6
4. Server-side cost-estimate endpoint — deferred (client-side is sufficient)
5. Automated WCAG audit tooling — future DE

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

**Spec coverage:**
- ✅ SvelteKit route for list view (Task 5)
- ✅ Playbook execution flow from document/playbook (Task 5 + Task 6, picker direction = from-playbook; doc-direction noted in deferred §)
- ✅ Execution result view (Task 7)
- ✅ Per-position cards with collapsed/expanded states (Task 7, dense-row + expand variant per §5.4)
- ✅ Filter UI by severity + outcome (Task 7)
- ✅ Cost preview before execution (Task 3 + Task 6)
- ✅ Cypress E2E spec (Task 9)
- ✅ Disclaimer banner (Task 4, deployed in Tasks 5 + 7)
- ✅ Backend GET endpoints + OpenAPI (Task 1)
- ✅ WCAG 2.1 AA verification (Task 10 Step 6)

**Placeholder scan:** None — every step has actual content. Two callouts where the engineer must make a judgment call backed by reconnaissance (Task 6 Step 1 doc-listing helper, Task 8 sidebar nav file path) — both flagged with "if X, stop and surface" guardrails.

**Type consistency:** `Playbook` / `PlaybookExecution` / `Position` / `PlaybookPositionResult` shapes match between Task 2's TypeScript declarations and Task 1's Pydantic-derived OpenAPI components. `PositionSeverity` literal union matches Python's `PositionSeverity` literal. `PlaybookPositionVerdict` matches the executor's `_VALID_VERDICTS` frozenset. `severityClass` / `outcomeClass` helper function names are stable across Task 7's helpers test and the result-page template.
