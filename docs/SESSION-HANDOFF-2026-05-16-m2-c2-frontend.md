# Session Handoff — 2026-05-16 — M2 Phase C 2/3, frontend (M2-C2) next

> **Purpose:** Context transfer for the next session. **M2-B3** (anonymization middleware), **M2-C1** (paraphrase judge), and **M2-C3** (round-trip tests) all shipped or in-review this session. **M2-C2 is the next task** — the frontend (web/) work that makes citation engine value visible to operators. Captured here because M2-C2 is the first frontend task in M2 (different headspace from python work) AND because the spike I did during this session surfaced two real gaps the plan doesn't anticipate.
>
> Read time: 10 minutes. Decisions to surface to Kevin before any code: §5.

---

## 1. State at handoff

### Repo HEAD on `m2-development`

`f8504b8` ("feat(gateway,api,m2-b3): anonymization middleware wired end-to-end (#27)") — assuming PR #29 (M2-C3) merges before the next session starts; check with `git log -1 m2-development`.

Mirrors: `origin` (LegalQuants) and `tucuxi` (Tucuxi-Inc) should be at the same SHA. Confirm with `git fetch --all && git log --oneline m2-development origin/m2-development tucuxi/m2-development` before branching.

### What landed this session

Three PRs across two phases (B3 closing Phase B, C1 + C3 advancing Phase C):

| PR | Task | Status | Lines |
|---|---|---|---|
| [#27](https://github.com/LegalQuants/lq-ai/pull/27) | M2-B3: Anonymization middleware end-to-end | **MERGED** (`f8504b8`) | +2160/-67 |
| [#28](https://github.com/LegalQuants/lq-ai/pull/28) | M2-C1: Citation Engine Stage 3 (paraphrase judge) | **MERGED** | +1010/-49 |
| [#29](https://github.com/LegalQuants/lq-ai/pull/29) | M2-C3: Anonymization round-trip correctness suite | **OPEN** (Kevin merging) | +643/-0 |

### Test counts at handoff

- **api/:** 962 passed, 1 skipped (was 921/1 at M2-B2 baseline; +41 from M2-B3 + M2-C1).
- **gateway/:** 485 passed, 2 skipped (was 412/1 at M2-B2 baseline; +73 from M2-B3 + M2-C1 + M2-C3; includes +17 slow round-trip tests).
- **mypy strict + ruff format + ruff check:** all clean both subsystems.

### Local branches

- `m2-development`, `main`, `kk/main/Frontend_Design` — long-lived.
- `m2/b3-middleware-integration`, `m2/c1-paraphrase-judge`, `m2/c3-anonymization-round-trip` — squash-merged or about to merge; delete after merge with `git branch -D <name>`.

---

## 2. M2 plan status

```
Phase A — Foundation                ✓ COMPLETE (A1, A2, A3)
Phase B — Verification + recognizers ✓ COMPLETE (B1, B2, B3)
Phase C — LLM judge + UI            — 2/3 done (C1 ✓, C3 in #29; C2 ⏳ NEXT)
Phase D — Ensemble + integration    — (D1, D2, D3, D4)
Phase E — Azure adapter + tuning    — (E1, E2)
Phase F — Acceptance + docs         — (F1, F2, F3)
```

8 of 18 tasks shipped or in-review. M2-C2 is the next single-session task and **completes Phase C** when it lands.

---

## 3. M2-C2 task brief — Failed-citation UI rendering

Source: `docs/M2-IMPLEMENTATION-PLAN.md` §M2-C2 (lines 281-309).

**Effort:** 8-10 hours (plan estimate).

**Literal scope from the plan:**

Five citation states with distinct visual treatment:

| State | Visual | Click behavior | Tooltip |
|---|---|---|---|
| **Verified-exact** | Green checkmark + underline | Highlights span in source viewer | "Verified verbatim against source." |
| **Verified-tolerant** | Green checkmark + underline | Highlights span in source viewer | "Verified against source (minor formatting differences)." |
| **Verified-paraphrase** | Yellow checkmark + underline | Highlights cited chunks; surfaces judge justification | `Verified by judge ({confidence}): "{justification}"` |
| **Unverified** | Greyed text + inline "[unverified]" marker | Not clickable | "Could not verify this citation against the source. The model may have produced a claim that doesn't follow from the cited content." |
| **System error** | Yellow warning icon + greyed text | Not clickable | "Verification could not complete due to a system error. Treat as unverified." |

**Plan emphasis (load-bearing for the visual choice):**

> The visual treatment is **load-bearing for procurement reviews**. Verified citations look distinctly different from unverified ones. The procurement-reviewer test: scrolling the report, a reviewer should be able to identify unverified citations without reading the tooltips.

**Other plan items:**

- Update `docs/quickstart.md` "Walk through the output" section to describe the visual states and the procurement context.
- Update `docs/architecture.md` Citation Engine section to reflect the five-state UI.
- Visual-regression tests: snapshot tests in `web/tests/citation-render.test.tsx` covering each state.
- WCAG AA color-contrast compliance.

**Plan dependencies:** M2-C1 — MERGED. M2-C2 is unblocked.

---

## 4. Code surfaces M2-C2 will touch (with findings the plan doesn't anticipate)

This is where the next session needs to slow down. The plan assumes a tighter scope than the codebase warrants.

### 4.1 Existing `web/` surface

```
web/src/lib/components/chat/Messages/
├── Citations.svelte         — OpenWebUI's stock citation chip rendering
├── Citations/               — modal subcomponent
└── ...
```

`Citations.svelte` exists today but **it is OpenWebUI's stock citation component**, built around RAG-retrieved sources (a different mental model from LLM-emitted citation rows). It reads citations from the OpenWebUI chat-message JSON envelope, NOT from the M2 `message_citations` table.

### 4.2 Existing api/ citation endpoint

`GET /api/v1/chats/{chat_id}/messages/{message_id}/citations` (in `api/app/api/chats.py` around line 1205) returns the persisted `message_citations` rows. Today it returns:

```python
{
    "id": str, "source_file_id": str,
    "source_offset_start": int, "source_offset_end": int,
    "source_page": int | None, "source_text": str,
    "verified": bool, "verification_method": str | None,
    "verification_confidence": float | None,
    "created_at": ISO8601,
}
```

### 4.3 Finding 1 — frontend never wired to the M2 citation surface

**No `web/` code calls `/api/v1/chats/{chat_id}/messages/{message_id}/citations` today.** Search:

```bash
grep -rn "message_citations\|/messages/.*/citations\|verification_method" web/src/ 2>/dev/null
# (empty — zero hits)
```

The M2-A2 PR shipped the endpoint; M2-B1 + M2-C1 extended its semantics. But the **frontend has never consumed it.** This means M2-C2 is wider than the plan describes:

- **Plan says**: "Update chat-message rendering in `web/` ... implement five citation states with distinct visual treatment."
- **Reality**: There is no existing M2-citation-rendering code path to update. M2-C2 needs to wire the endpoint into the frontend in the first place — fetch citations after each assistant message, hydrate them into the renderer, then add the five-state visual treatment.

### 4.4 Finding 2 — api endpoint omits `partial`

The endpoint's dict (api/app/api/chats.py ~lines 1262-1277) was written before M2-C1 added `MessageCitation.partial`. The field **is persisted** (line 1435 in `_persist_message_citations`) but **is NOT in the response**:

```python
return [
    {
        "id": str(c.id),
        # ... existing fields ...
        "verification_method": c.verification_method,
        "verification_confidence": (...),
        "created_at": c.created_at.isoformat(),
        # ← `partial` field missing here
    }
    for c in rows
]
```

The frontend can't distinguish "verified-paraphrase" (verified-with-caveats) from "verified-exact" without this. Add `"partial": c.partial` to the dict; trivial change but required for M2-C2 to even be possible.

### 4.5 Finding 3 — interaction with anonymization rehydration

The persisted `message_citations.source_text` is the model's literal quoted citation from the chat response. Under M2-B3, that response is rehydrated post-middleware (`PERSON_0001` → "John Smith") BEFORE the api/'s citation extraction runs (`_persist_message_citations` is downstream of the gateway round-trip). So `source_text` carries the rehydrated originals, not pseudonyms — this is per Decision D from M2-B3 ("gateway rehydrates response content only; citation extraction operates on already-rehydrated content").

**The frontend doesn't need to worry about pseudonyms in citation text.** What it sees from the api/ is real source quotes. This is correct behavior but worth confirming with the M2-C2 author so they don't accidentally try to de-pseudonymize.

### 4.6 Suggested reads at session start

1. **`web/src/lib/components/chat/Messages/Citations.svelte`** — the existing stock component. Read end-to-end (~150 lines) to understand the OpenWebUI mental model.
2. **`web/src/lib/components/chat/Messages/ResponseMessage.svelte`** — the assistant-message renderer where the Citations chip slots in. Find the hook point for M2 citation injection.
3. **`web/src/lib/apis/chats/index.ts`** (or wherever the chat-API client lives) — to find the pattern for adding a new endpoint client function.
4. **`api/app/api/chats.py` line 1205** — the existing `get_citations` endpoint shape.
5. **`docs/security/anonymization.md` "Round-trip correctness (M2-C3)" section** — the four invariants that govern data the frontend can / cannot trust (the api/'s citation rows carry rehydrated content, not pseudonyms).

---

## 5. Architectural decisions M2-C2 will surface

Per the honest-framing rule, the next session should surface these to Kevin before writing code:

### Decision A — replace, extend, or coexist with `Citations.svelte`?

OpenWebUI's `Citations.svelte` renders RAG-retrieved source chips inline below the assistant message. The M2 mental model is **per-quote citations woven into the message text** (a quote like "the agreement was signed" is itself the citation; it has byte-precise offsets into a specific source document).

Three paths:

- **(i)** **Replace** `Citations.svelte` with M2-aware rendering. Highest churn; possibly breaks RAG-source-chip UX from upstream OpenWebUI.
- **(ii)** **Extend** `Citations.svelte` to handle both data shapes. Conflates two concepts in one component.
- **(iii)** **New component** for M2 citations alongside the existing one. Lowest churn; cleanest separation. Skills that don't use M2 citations (e.g., a non-RAG chat) keep the old behavior; M2-citation skills get the new component.

Recommend (iii). The OpenWebUI fork pin (ADR 0001) is more stable when we add components than when we modify them.

### Decision B — fetch citations how?

Two paths:

- **(1) Lazy fetch** after each assistant message renders — call `GET /messages/{id}/citations`. Simple; one extra round-trip per message. Latency-cheap because it runs in parallel with the user's next-message typing.
- **(2) Embed citations in the chat-message JSON envelope** — extend the api/'s assistant-message response shape so the citations land alongside the content. Avoids the second round-trip; bigger refactor on both sides.

Recommend (1). The M2-A2 endpoint exists; using it is the smaller change. M2-D2 (Citation Engine integration) is the right time to revisit if latency matters.

### Decision C — render the visual states how?

The plan calls the visual treatment "load-bearing for procurement reviews." This is more designer judgment than engineering choice. Options:

- **(α) Tailwind classes directly** — fastest; consistent with OpenWebUI's existing Citations.svelte style.
- **(β) Design tokens** — introduce M2-citation-* CSS variables. Cleaner separation; more upfront work.

Recommend (α). M2 is the first time we're surfacing this taxonomy; we can refactor to design tokens once we know what stays.

For the actual color choices: Tailwind's `emerald-*` for verified-green and `amber-*` for verified-yellow are WCAG AA at contrast against the OpenWebUI default chat background. Pin specific shades when the work starts.

### Decision D — snapshot tests vs interactive tests?

Plan says snapshot tests in `web/tests/citation-render.test.tsx` (note: .tsx — but the OpenWebUI fork is Svelte, not React; this is a plan-prose typo). The frontend's test stack is **Vitest + Playwright** per `docs/test-strategy.md` (M1) and `web/cypress.config.ts`.

Two paths:

- **(*)** Vitest snapshot tests on the Svelte component with all five states fixture-rendered. Fast, runs in CI.
- **(**)** Playwright visual regression on a sample chat with all five states present. Slower, more realistic, catches integration bugs Vitest snapshots would miss.

Recommend (*). Add (**) in M2-F1's acceptance corpus work.

### Decision E — pre-flight api change

`api/app/api/chats.py` line 1262 — add `"partial": c.partial` to the get_citations response dict. This is a one-line change; it must land BEFORE the frontend can render the verified-paraphrase state distinctly.

Confirm: add to the M2-C2 PR (single PR closing the gap), or carve into a tiny separate api-only PR first? Recommend single PR — the api change is two lines and the test update is trivial.

---

## 6. Suggested workflow for next session

1. **Read this doc + plan §M2-C2 + the existing Citations.svelte** before any decision.

2. **Surface the five decisions in §5 to Kevin** in one round. Don't expand scope unilaterally — the plan's "Update chat-message rendering" is narrower than what's actually required, and Kevin should know that before approving.

3. **Branch off latest m2-development:**
   ```
   git fetch --all
   git checkout m2-development
   git pull origin m2-development
   git checkout -b m2/c2-failed-citation-ui
   ```

4. **Sequence the work:**
   - api/ side: add `"partial"` to get_citations response + a test that asserts it.
   - web/ api client: new function that calls `/messages/{id}/citations`.
   - web/ component: M2Citations.svelte (or similar) that renders the five states.
   - Wire into ResponseMessage.svelte.
   - Snapshot tests on the new component with fixture data for each state.
   - Docs: update quickstart.md + architecture.md.

5. **Run the dev stack** to actually see the citations render:
   ```
   docker compose up -d
   cd web && npm run dev  # SvelteKit dev server
   ```
   Confirm the visual states look distinct on a real chat with all five citation outcomes. The procurement-reviewer test (per the plan) is "scrolling the report, identify unverified without reading tooltips" — verify this passes by manual inspection.

6. **Full triple-check before PR:**
   ```
   cd web && npm run check && npm run test && npm run lint  # (or whatever the OpenWebUI fork uses)
   cd api && pytest tests/ && mypy app/ && ruff format --check app/ tests/ && ruff check app/ tests/
   ```

7. **PR back to m2-development** with the standard template — call out the wider-than-planned scope (the frontend wiring) and the api/ side micro-change in the summary.

---

## 7. Memory updates already in place

- `project_lq_ai_status.md` — updated end-of-session 2026-05-16 with PRs #27, #28, #29 status.
- `feedback_ruff_format_check.md` (new) — `ruff check` and `ruff format --check` are separate gates; CI runs both; local verification must run both.
- `feedback_check_real_setup.md` (existing) — verify what's actually loaded in Ollama / running in docker-compose before copying fixture values.
- All M2 architectural decisions through C3 are documented:
  - M2-1, M2-2 (kickoff)
  - M2-A2-B+I+(a) (PR #23)
  - M2-B1-faithful (PR #25)
  - M2-B2 spaCy (PR #26)
  - M2-B3 A/B/C/D (PR #27)
  - M2-C1 A/B/C/D/E (PR #28)
  - M2-C3's surfaced finding (cross-mapper collision; updated DE-274) (PR #29)

Other relevant memories: `feedback_honest_framing.md`, `feedback_tech_debt_tracking.md`, `feedback_dry_run_value.md`, `reference_lq_ai_locations.md`, `reference_lq_ai_dev_quirks.md`, `reference_lq_ai_m2_plan.md`.

---

## 8. What's NOT in this handoff but is worth knowing

- **DE-274** (pseudonym-collision in source documents) — surfaced during M2-C3; per-request salt is the recommended path; tracked in PRD §9. **Not blocking M2-C2.**
- **Phase A acceptance corpus (M2-F2)** still TBD; until it lands, recognizer calibration is unit-test-driven.
- **M2-D1 (ensemble verification)** — parallel-track candidate after M2-C2 if Kevin wants two streams.
- **Operator-side M2 verification items** carried forward:
  - M2-A2 manual NDA-Review run.
  - M2-B3 chat-with-anonymization smoke test against a real provider.
  - v0.1.0 tag + two-remote push (waiting on second-machine fresh-pull verification).

---

*Handoff written end-of-session 2026-05-16. Next session entry point: read this doc + plan §M2-C2, then surface §5's five decisions before any code.*
