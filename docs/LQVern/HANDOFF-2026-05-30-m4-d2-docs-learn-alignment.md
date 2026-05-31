# Handoff — M4-D2 docs + Learn honest-alignment (resume at plan Task 4) → then tag v0.4.0

> **For:** the next Claude Code session rounding out M4 on branch **`feat/lqvern-m4-autonomous`** in **`~/Code/lq-ai`** (canonical repo — NEVER `~/Desktop/lq-ai`; Bash cwd resets to `~/Desktop` between calls, so **prefix every command with `cd ~/Code/lq-ai &&`**).
>
> **Where we are:** **M4 code is DONE** (all 19 executor tasks + brake-receipt fix + DE-325 + DE-326; fresh-install acceptance PASSED live). The **docs + Learn honest-alignment phase (M4-D2) has STARTED**: brainstorm → spec → plan committed, and **Task 1 (rewrite `HONEST-STATE.md` as the truth-map) is DONE**. Branch HEAD `0cd0bf3`, pushed origin + tucuxi, tree clean. **RESUME AT plan Task 4.**
>
> **The contracts:** spec [`docs/superpowers/specs/2026-05-30-honest-alignment-docs-learn-design.md`] + plan [`docs/superpowers/plans/2026-05-30-honest-alignment-docs-learn.md`]. The plan is the task-by-task source. The anchor for every edit is the rewritten [`docs/HONEST-STATE.md`].

---

## 1. The big picture — what "rounding out M4" means

M4 (the Autonomous Layer) is code-complete and acceptance-passed. To **tag v0.4.0**, three things remain, in order:

1. **Finish the docs + Learn honest-alignment sweep** (this handoff — plan Tasks 4–20). M4-D2 doc finalization.
2. **Attorney legal-substance walk-through** — **KEVIN owns this** per [[feedback_no_maintainer_legal_review]]. Inputs are ready (the live acceptance stack + its memory/precedent/receipt output).
3. **Tag v0.4.0** — the M4 branch (code + honest docs + Learn viz) merges to `main` and tags together.

Why the docs work rides the M4 branch (not a branch off main): the docs *describe* M4, and M4 isn't merged to `main` yet, so a main-based branch would lack the code to read and cite.

---

## 2. The locked decisions (do NOT re-litigate)

Kevin made these explicitly during the brainstorm:

- **Pragmatic split on historical docs.** Current-facing docs (README, PRD, architecture, per-feature docs, boundary-registers, HONEST-STATE) + Learn viz + **the current M4 handoff** reflect current reality. **DO NOT retroactively rewrite earlier-stage docs** — all past `docs/SESSION-HANDOFF-*.md` and the `M1-IMPLEMENTATION-ORDER.md` / `M1-PROGRESS.md` / `M{2,3,4}-IMPLEMENTATION-PLAN.md` / `docs/LQVern/` plan+design docs are **preserved untouched** as honest point-in-time artifacts.
- **One combined pass, no inter-phase approval gate.** But anchored on the HONEST-STATE truth-map (Task 1) so a ~50-artifact sweep stays self-consistent.
- **Comprehensive Learn coverage** — every shipped capability ends up both honestly documented AND represented in Learn (build new viz for the gaps).
- **Execution = subagent-driven** (`superpowers:subagent-driven-development`): fresh implementer per task (or tight cluster) + spec review + code-quality review; each subagent is handed the relevant HONEST-STATE truth-map section as its reference.

---

## 3. Task 1 — DONE (the anchor). What it established.

`docs/HONEST-STATE.md` rewritten (commit `0cd0bf3`) from a 4-agent parallel ground-truth read. The truth-map (use it as the reference for every later task):

- **M1** workspace surface, gateway/providers (anthropic/openai/azure/ollama), tiers — shipped. Caveat baked in: `skills/community/` submodule is **empty until `git submodule update --init --remote`** (the "30+ skills" claim depends on it).
- **M2** Citation Engine (4-stage cascade) + Anonymization Layer (middleware IS wired at `gateway/app/api/inference.py`) — shipped.
- **M3:** Playbooks **shipped** (in-process BackgroundTasks exec; built-ins immutable; tracked-changes→Word deferred DE-287); Tabular review **shipped** (caveat: no backend tests yet); Word add-in **SCAFFOLD ONLY** (installable/auth/version-safe; in-Word features are DE-287 deep-link cards); Slack/Teams intake bridge **PARTIAL** (plumbing+OAuth+encrypted persistence+admin wired & unit-tested, but never run end-to-end against live Slack/MS — DE-312; `/lq` slash command inert — DE-288).
- **M4** Autonomous Layer **shipped end-to-end** (five-phase executor, R4/R5/R6 brakes, four primitives, receipts, opt-in, dashboard).
- **Not built:** Contract Repository auto-relationship graph (PRD §3.16); MCP client (M5).
- **Corrected facts:** PRD cross-refs (Autonomous §3.10, Tabular §3.14, Slack/Teams §3.15, Contract-Repo §3.16); migration head **0045**; test **file** counts (api 144 / gateway 41 / cypress 17 / vitest 71) — cite file counts, not fabricated pass numbers (autonomous suite = 361 passing is verified).
- **IMPORTANT correction to earlier recall:** `data-residency.html` does **NOT** claim anonymization is "not running" (that was stale memory). The real Learn drift is `autonomous-flow.html` + `data-residency.html` marking the **M4 layer as "PLANNED"** when it's shipped. Verify against source, never memory.

---

## 4. RESUME HERE — plan Tasks 4–20 (subagent-driven)

Read the plan for each task's exact steps + verification commands. Summary:

- **Tasks 4–9 — core docs:** README (4), PRD capability statuses incl. §3.10 autonomous → SHIPPED (5), architecture (6), db-schema vs migrations 0001→0045 (7), observability spans/audit-actions (8), `docs/security/boundary-registers.md` R4/R5/R6 → SHIPPED with live citations (9). NOTE: boundary-registers is `docs/security/**` → security-review-gated per CODEOWNERS; expected.
- **Tasks 10–13:** per-feature docs reconciled one-per-commit (citation-engine, playbooks, tabular-review, word-addin, intake-bridges, skill-authoring-guide, quickstart) (10); **NEW `docs/autonomous-layer.md`** (11); file **DE-325 / DE-326 / DE-327** in PRD §9 (12 — 325/326 as resolved-DEs with commit SHAs, 327 = Helm worker-migration parity, community-suitable); align the active M4 handoff (`HANDOFF-2026-05-29-...`) to HONEST-STATE (13).
- **Task 14 — Learn audit:** all 14 playgrounds + 4 pages; fix every stale claim. Confirmed fixes: flip `autonomous-flow.html` + `data-residency.html` M4 "PLANNED" → shipped. Preserve each viz's design; correct content/claims only.
- **Tasks 15+ — new Learn viz (the GAPS):** build one playground each, following existing conventions (self-contained offline HTML, Learn design-system, no new color palette, honest PLANNED badges only for genuinely-unshipped sub-parts). Confirmed gaps from Task 1:
  1. **Intake-bridges** (Slack/Teams OAuth install + workspace/tenant lifecycle).
  2. **Autonomous four primitives** (watches/schedules/memory/precedent lifecycle — `autonomous-flow.html` covers phases+brakes only).
  3. **Projects/matters + org-profile + privilege tiers**.
  4. **KB hybrid retrieval** (BM25 + vector).
- **Task 20 — final consistency pass:** re-grep for residual dishonesty across the touched set; confirm historical artifacts untouched (`git diff --name-only main...HEAD | rg "SESSION-HANDOFF|M[1-4]-IMPLEMENTATION"` returns nothing but the allowed current handoff); report the full edited/created list for the v0.4.0 readiness check.

---

## 5. Hard rules (memorize)

- **Canonical repo `~/Code/lq-ai`**; prefix every command `cd ~/Code/lq-ai &&` (cwd resets to `~/Desktop`).
- **Truth discipline:** never write a capability/status/path/field/label from memory — grep/read the source first. No overclaiming, no understating. On any conflict, HONEST-STATE wins.
- **Preserve historical docs** — never edit past SESSION-HANDOFF-* or the M*-IMPLEMENTATION-PLAN docs.
- **DCO:** every commit `git commit -s` + trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` (kept at 4.7 for branch consistency even though the session model is 4.8).
- **Push BOTH remotes** after each task: `git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous`. Never delete branches.
- **Commit in reviewable clusters** (not 50 micro-commits, not one mega-commit): truth-map (done) → core docs → per-feature+autonomous-layer.md → Learn fixes → new viz.
- **NEVER run host-side `alembic upgrade head` against `127.0.0.1:15432/lq_ai`** (the live dev DB; crash-loops the stack — [[feedback_no_host_alembic_on_dev_db]]). Verify migrations via pytest's throwaway DB only.
- For Learn SvelteKit routes touched: `cd web && npm run check:lq-ai`. For playgrounds: confirm the self-contained HTML renders with no JS error.

---

## 6. Stack + acceptance state (preserve for the attorney walk-through)

- Stack is UP + healthy (fresh-built this session; daemon bounced once mid-session and recovered — data intact). Admin `admin@lq.ai` / `AcceptTest12345!`; dashboard `localhost:3000`; dev DB at migration head **0045**.
- Acceptance data lives in the dev DB: KB `9003dbc6-abf5-4f25-922b-588714f26405`; 4 autonomous sessions (3 completed @ $0.005 each with real findings/memory/precedents, 1 halted via R4 with `terminal_reason=cost_cap_reached`). **Do NOT `docker compose down -v`** — it would wipe the attorney-review inputs. (DE-326 was verified non-destructively for exactly this reason.)

---

## 7. Where to start (fresh-session paste-ready)

```
Continue M4-D2 (docs + Learn honest-alignment) on LQ.AI in ~/Code/lq-ai
(canonical; NEVER ~/Desktop; prefix every command `cd ~/Code/lq-ai &&`), branch
feat/lqvern-m4-autonomous (HEAD ~0cd0bf3).

Read docs/LQVern/HANDOFF-2026-05-30-m4-d2-docs-learn-alignment.md first — full
state. M4 code is DONE + acceptance PASSED. The docs/Learn alignment phase has
started: spec + plan committed, Task 1 (rewrite HONEST-STATE.md as the truth-map)
DONE. RESUME AT plan Task 4.

Plan (task-by-task source): docs/superpowers/plans/2026-05-30-honest-alignment-
docs-learn.md. Anchor (reference for every edit): docs/HONEST-STATE.md.

Workflow: subagent-driven (superpowers:subagent-driven-development) — fresh
implementer per task/cluster handed the relevant HONEST-STATE truth-map section,
then spec review + code-quality review. One combined pass, no gate.

LOCKED decisions (don't re-litigate): pragmatic split — current-facing docs +
Learn + current handoff reflect reality; DO NOT touch past SESSION-HANDOFF-* or
M*-IMPLEMENTATION-PLAN docs (preserved historical artifacts). HONEST-STATE is the
consistency spine. Comprehensive Learn coverage (build new viz for the 4 gaps:
intake-bridges, autonomous four primitives, projects/org-profile, KB hybrid
retrieval). Verify EVERY claim against source — never memory.

Hard rules: DCO `git commit -s` + Co-Authored-By: Claude Opus 4.7 (1M context)
trailer; push BOTH remotes after each task; commit in reviewable clusters; NEVER
host-side alembic against 127.0.0.1:15432/lq_ai; do NOT `docker compose down -v`
(preserves the attorney-review acceptance data).

After the sweep (Task 20) passes → Kevin's attorney walk-through → tag v0.4.0
(M4 branch merges to main with code + docs + Learn together).
```

---

*Drafted 2026-05-30 at the M4-D2 kickoff checkpoint (Task 1 done). The spec + plan are the contracts; this handoff is the navigation aid.*
