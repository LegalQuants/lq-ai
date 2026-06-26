# Handoff — 2026-06-26 — Fiduciary-grade milestone: Phase 1 nearly done; P1-B1c is next

`main` (LegalQuants + tucuxi, both == **`25898e5`**) at session end. Everything below is **merged to `main`** unless marked otherwise. Next migration number = **`0061`**.

---

## ⭐ SESSION-START NOTE — read this first. Next task: **P1-B1c** (brainstorm → spec → plan → build)

**Goal of P1-B1c:** safe **caselaw FAIL** — flag a *fabricated or materially misquoted* caselaw quote so the fiduciary gate marks the turn `flagged`, **without** false-positives on legitimate non-caselaw blockquotes (a statute, a KB quote, an emphasis quote). This is the one honesty gap left in Phase 1: today a caselaw quote that matches no consulted opinion is **silently dropped** (invisible), so a fabricated quote leaves no trace and the gate can't flag it.

**Why it was split out of P1-B1b (the load-bearing reason):** B1b shipped the **SUPPORTED** tier (paraphrased-but-faithful caselaw quotes → `paraphrase_judge` → `supported_only`) as *additive-only* — it never writes a FAIL row. Safe FAIL needs **per-passage → opinion attribution**, which does **not exist today**: `extract_blockquote_passages` returns a flat `list[str]` with no case association, and the verify loop tries every passage against *every* consulted opinion. So a whole-opinion judge run over a dropped passage against *all* consulted opinions would also reject a legitimate statute quote → a wrong FAIL → a wrongly-`flagged` good draft. **That is the worst failure mode for a fiduciary tool**, which is exactly why FAIL is its own slice with attribution done right.

**The attribution signal exists but is unparsed.** The case-law-research skill (`skills/case-law-research/SKILL.md` ~lines 99–136) mandates that each cited passage render as a markdown blockquote **directly under a `### [Case Name], [Court], [Year] ([Citation])` H3 heading**, preceded by a `**Relevant passage:**` line. So the parseable signal is *"the nearest `###` heading above the blockquote."* No `(Source: [N])` markers, no inline cluster ids in the answer text. The job of B1c's parser: blockquote → nearest `### Case` heading → **match that case name to one consulted opinion** → judge the passage against *that opinion only* → judge-reject → FAIL row attributed to that opinion. No confident match → stays dropped (today's behavior).

**What's already in place (so B1c is mostly orchestration + a parser):**
- `message_caselaw_citations` **already permits `verified=False, method=NULL` FAIL rows** — the CHECK `chk_message_caselaw_citations_verified_has_method` only requires a method when `verified=True`. **So B1c likely needs NO migration for the FAIL rows themselves.** (Confirm during the plan.)
- The **gate already flags FAIL**: `assemble_ledger_entries` maps `verified=False` → `verification_status="unverified"` (the P1-B1 assembler fix), and `gate.py`'s `FAIL_STATUSES = {"unverified","failed"}` → `gate_status="flagged"`. So a B1c FAIL row flows to `flagged` **with no gate/ledger change**.
- The **whole-opinion judge already exists** (`api/app/citation/case_content_judge.py`, `judge_case_content` + `estimate_case_content_cost_usd` + the per-turn cost budget) from B1b — B1c reuses it, but runs it against the **attributed** opinion only and persists a FAIL row on reject (B1b drops on reject).
- The **C1 UI already renders the FAIL state** (gray/red "unverified" chip + a `flagged` red fiduciary badge) — no UI work needed; B1c data flows into it automatically.

**Brainstorm forks to resolve with the maintainer (surface via AskUserQuestion):**
1. **Attribution data source + matching.** Where do consulted opinions' case names come from to match the H3 heading? Candidates: `ResearchOpinionMetadata` (does it carry `case_name`/`citation`? — *verify first*), and/or `message_tool_sources.label` for the consulted clusters (earlier grounding saw labels like `"Cluster 22"` — may lack case names). Decide the matcher (exact/normalized case-name match? citation match? fuzzy with a confidence floor?) and the **confidence threshold** below which a passage stays dropped (not flagged). This is the crux — over-matching reintroduces the false-positive risk the whole slice exists to avoid.
2. **FAIL strictness.** Only flag when (a) the blockquote is confidently attributed to exactly one consulted opinion AND (b) the whole-opinion judge rejects it against that opinion? (Recommended — conservative.) What about a blockquote whose H3 matches a case that was *named but not actually fetched/consulted* (no opinion text to judge against)? Drop, or flag as "cited-but-not-verifiable"? (Lean drop for v1 — no opinion text = can't judge = can't confidently call it fabricated.)
3. **Over-budget / judge-error on the attributed opinion.** B1b drops these. For B1c, an *attributed* passage we couldn't afford to judge is arguably "unverified (claims case X, not checked)" → flag — but only if attribution is solid. Decide: drop (safest) vs. flag-as-unverified (more conservative-honest). Tie to the cost budget already in `case_content_judge`.
4. **Relationship to DE-279.** DE-279 (Bluebook case-citation → opinion resolution, a `message_case_citations` table + `case_resolver.py`) is **deferred/unbuilt**. B1c's H3-heading parser is a lighter, skill-format-coupled attribution. Decide whether B1c builds the minimal parser now (coupled to the skill's `### Case` convention) or waits on / partially pulls in DE-279. (Lean: minimal parser now; note the skill-format coupling as a risk; DE-279 can later supersede the matcher.)

**Then:** brainstorm (forks → AskUserQuestion) → spec (`docs/superpowers/specs/`) → writing-plans → subagent-driven-development (sonnet implementers, **opus final whole-branch review**) → push origin+tucuxi → PR. **Security-gated** (new gateway egress via the judge + the citation/audit surface) → **do NOT self-merge**; Kevin/security merges; mirror `origin/main → tucuxi` after.

**Relevant files to read first:** `api/app/citation/caselaw.py` (`extract_blockquote_passages` flat-list + the verbatim/judge loops + the drop path), `api/app/citation/case_content_judge.py` (the judge to reuse), `api/app/models/message_caselaw_citation.py` (FAIL-row support), `skills/case-law-research/SKILL.md` (the `### Case` output contract the parser depends on), `api/app/research/service.py` + the `ResearchOpinionMetadata` model (opinion metadata / case names for matching), `api/app/citation/gate.py` + `ledger.py` (confirm no change needed). Spec that deferred B1c: `docs/superpowers/specs/2026-06-25-p1b1b-caselaw-paraphrase-judge-design.md` (§"Out of scope"). Proposal slice: `docs/proposals/fiduciary-grade-agentic-legal-work.md` (P1-B1c entry).

---

## What shipped this session (7 PRs, all mirrored, no self-merges on gated ones)

| PR | Slice | Squash | Gated |
|---|---|---|---|
| #223 | **P1-A3** — Citation Ledger read API + one-click trace (`GET /chats/{id}/ledger`) | `0da951b` | sec |
| #224 | **DE-360** — gateway-native quality-escalation routing (docs; renumbered from a colliding DE-345) | `0aeb3e1` | docs |
| #225 | **P1-B1** — deterministic fiduciary gate (`work_product_fiduciary_gate`, mig 0059) | `bf23ae0` | sec |
| #226 | **DE-361** — route `llm_judge` into the gate (forward-consistency docs) | `65291ef` | docs |
| #227 | **P1-B1c split** — corrected B1b→SUPPORTED-only + filed B1c (docs) | `101ee77` | docs |
| #228 | **P1-C1** — Citation Ledger UI (fiduciary badge + trace panel) | `07f3216` | — |
| #229 | **P1-B1b** — caselaw paraphrase/content judge, SUPPORTED tier (mig 0060) | `25898e5` | sec |

Each non-trivial slice: brainstorm (forks → AskUserQuestion) → spec → writing-plans → subagent-driven-development (per-task spec+quality reviews + an **Opus whole-branch review**) → PR. Specs/plans dated `2026-06-25` under `docs/superpowers/{specs,plans}/`.

**Opus final reviews caught real, gate-passing defects this session** (worth repeating the pattern):
- **P1-C1:** a Svelte **CSS-scoping** bug — the entry chip reused M2Citations' *component-scoped* `.state-*` classes, so the verification colors silently no-op'd (the feature's whole point). Fixed by defining the chip + 4 state colors locally; **verified visually** with a throwaway Vite + headless-Chrome render (chips render green/amber/gray, light + dark).
- **P1-B1b:** the caselaw judge ignored the operator-configured judge model (hardcoded `"fast"`, diverging from the document-citation path) and had a theoretical zero-cost-estimate hole that could defeat the per-turn budget. Both fixed (resolve `gateway.get_citation_engine_judge_model()`; floor the estimate at `DEFAULT_PER_JUDGE_USD`).

## Phase 1 status — WS-A / WS-B / WS-C

```
WS-A  Citation Ledger artifact ........ DONE  (P1-A1 #218, P1-A2 #219, P1-A3 #223; DE-350 #220)
WS-B  Fiduciary-grade gate ............ MOSTLY DONE
        P1-B1  deterministic gate ...... DONE (#225, mig 0059)
        P1-B1b SUPPORTED tier (caselaw) DONE (#229, mig 0060)
        P1-B1c FAIL tier (caselaw) ..... NEXT — brainstorm → spec → plan → build
WS-C  Matter/chat-scoped ledger UI .... DONE  (P1-C1 #228)   ← yes, WS-C is complete; not skipped
```

**The end-to-end fiduciary chain works on `main` today:** ledger records every source a turn used → KB *and* caselaw quotes are verbatim-verified → non-verbatim caselaw quotes get a SUPPORTED (paraphrase) tier → the gate computes `fiduciary_grade`/`supported_only`/`flagged` per turn → the C1 UI shows a badge + one-click trace with per-entry verification chips. **P1-B1c closes the last gap: flagging fabricated caselaw quotes.** After it, Phase 1 (WS-A/B/C) is complete.

## After P1-B1c — Phase 2 (each ADR-gated, **ADR before build**)

WS-D plain-language matter intake → agentic session; WS-E content-source registry + free-source expansion (note: free-source expansion = the deferred Research surface PRD §3.6, *not* DE-280/281; CourtListener today is BYO-key-gated); **WS-G** transparent validity/treatment layer (derives followed/distinguished/criticized/… from the citation graph + an LLM-judge over citing passages; populates the reserved `citation_ledger_entry.treatment_id`; first proving ground for **DE-360** escalation routing); WS-F MCP-server *ingress* (the inbound boundary). Each needs its own **(ADR needed)** doc accepted before its workstream starts.

## Workflow reminders (load-bearing)

- **Branch off `main`** (never commit on `main`); push feature branches to **origin + tucuxi**; after a PR merges, **mirror `origin/main → tucuxi main`** (`git push tucuxi origin/main:main`) and confirm `origin == tucuxi`. Planning docs (spec/plan) commit on the **feature branch**, not main.
- **Security review per CODEOWNERS** for `api/app/citation/**`, `chats.py`, `gateway/**`, and anything touching auth/authz/audit/crypto — Kevin/security merges; **Claude does NOT self-merge gated branches.** Docs-only + `web/`-only PRs are not gated (safe to self-merge after CI).
- **Tests via host venv + a throwaway pgvector** (conftest auto-migrates): container `lqai-test-pg` on `:55432`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test`. **NEVER** host `alembic upgrade` the dev DB; never port `15432`. Mocked gateway in tests → no `-m provider` for this work. **Next migration = `0061`** (0057 caselaw, 0058 ledger, 0059 gate, 0060 caselaw-method-CHECK). `web/` gate: `npm run check:lq-ai` + `npm run test:frontend` (Vitest); **don't run repo-wide `npm run format`** (it rewrites 161 unrelated not-yet-prettier-clean files — format only your touched files).
- **web has no Svelte component-test harness** — put logic in pure, unit-tested helpers; keep `.svelte` thin (svelte-check only). For a visual claim, a throwaway Vite + headless-Chrome render is a cheap way to get real evidence (`"/Applications/Google Chrome.app/.../Google Chrome" --headless=new --screenshot=out.png <url>`).
- **Opus for the final whole-branch review** — it has repeatedly caught gate-passing defects (CSS scoping, config-honoring, cost-bound holes). Worth the cost on every slice.
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. SDD ledger lives at `.superpowers/sdd/progress.md` (git-ignored scratch).

## Pointers
- Strategy: `docs/proposals/fiduciary-grade-agentic-legal-work.md` (Phase-1 PR decomposition has the P1-B1c slice)
- Decision: `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md` (D2 external quote-verify, D3 the gate)
- Specs/plans this session: `docs/superpowers/{specs,plans}/2026-06-25-{p1a3,p1b1,p1c1,p1b1b}-*`
- Memory: `project-fiduciary-grade-milestone`, `project-tool-use-and-ingest-state`
- Prior handoff: `docs/LQVern/HANDOFF-2026-06-25-fiduciary-phase1-progress.md`
