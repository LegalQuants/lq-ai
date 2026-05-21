# Session Handoff — 2026-05-21 (evening) — M3 Phase B plumbing shipped (PR #59) → Phase C kickoff next

> **Purpose:** Context transfer for the next session. The 2026-05-21 evening session opened and merged **PR #59** (M3 Phase B plumbing — Word add-in scaffold + OAuth + version handshake + DE-295 community handoff for the signed manifest). The next session opens M3 Phase C (Tabular Review) on a fresh branch off `main`.
>
> Read time: ~10 minutes. The detail lives in memory at `~/.claude/projects/.../memory/project_lq_ai_status.md`; this handoff covers what the next session specifically needs to do.

---

## 1. State at handoff

| Branch / Tag | SHA | Meaning |
|---|---|---|
| `main` | `e6877cc` | **PR #59 merged 2026-05-21 evening** — M3 Phase B plumbing complete |
| `m3-development` | `a7aa719` | Still divergent — has M3-A6 Easy Playbook wizard (PR #57) but lacks PRs #58/#59. Resolve before any further M3-development work, OR keep branching off main per the Phase B precedent. |
| `v0.2.0` (tag) | `8a1b3fc` | Unchanged. v0.3.0 at M3-close. |
| `m3-phase-b-word-addin-plumbing` | `1b49eb3` | Source branch for PR #59 (preserved per branch-preservation policy) |
| `roadmap-enhancements-parked` | (committed) | Lavern + boundary-registers analysis archive |

The full PR #59 commit list + M3-B7-community-descope detail lives in memory. This handoff focuses on what the next session does.

---

## 2. PR #59 — what shipped (in one block)

| Commit | What |
|---|---|
| `c2318fd` | Phase B prep doc (8 design decisions locked at kickoff) |
| `c17223e` | M3-B1 scaffold (Office.js manifest template + React 18 task pane + admin manifest generator) |
| `70dc009` | M3-B2 OAuth (Office.js Dialog API + LQ.AI JWT path; no MSAL, no exchange-token endpoint) |
| `aad9ced` | M3-B8 version handshake + update-needed overlay + router split (admin_router + public_router) |
| `0e8ea52` | **M3-B7 descoped to community-led effort per DE-295** (procurement plan, 3 vendor paths, 5 gated UX implications) |
| `1b49eb3` | CI fix — adds the two new word-addin paths to `IMPLEMENTED_ROUTES` in `test_endpoints.py` |

**Effort and test surface:** 5 feature commits + 1 CI fix, +457/-37 line LOC delta across 50 files at PR open (final tally larger after the M3-B7 descope commit). Coverage: 468 backend pytest passed (no regressions), 488 web vitest passed, 39 word-addin vitest tests (auth + version) designed against jsdom + ready to execute when `npm install` runs in CI.

---

## 3. First task next session — reconcile `m3-development` with `main`

Before Phase C work begins, the branch landscape needs to be single-trunk again. Today's state:

- **`main`** has PR #58 (boundary-register catalog + DE-287/288 descopes) + PR #59 (Phase B plumbing + DE-295 community handoff) — but lacks the M3-A6 Easy Playbook wizard.
- **`m3-development`** has the M3-A6 Easy Playbook wizard (PR #57 squash-merge `a7aa719`) — but lacks PRs #58 and #59.

The Phase B precedent established branch-off-main + PR-to-main as the M3 workflow. That means `m3-development` is no longer the dev branch — it's a side channel carrying the M3-A6 wizard work that hasn't yet landed on `main`. To restore single-trunk:

### Recommended path — merge `m3-development` → `main` (the squash-merge or merge-commit lands the M3-A6 wizard on main)

1. **Open a PR** from `m3-development` → `main` with title roughly: `Sync m3-development → main — M3-A6 Easy Playbook wizard`. The PR diff is the M3-A6 wizard content only — PRs #58 and #59 are already on `main` so they don't appear in the diff.
2. **Resolve any conflicts** if the PR shows them. The M3-A6 work touches `api/`, `web/`, `skills/`, and the M3-IMPLEMENTATION-PLAN. PR #58 touched the M3 plan + PRD §1.8/§3.10 + new posture doc. PR #59 touched `word-addin/`, `api/`, `web/`, and the M3 plan + PRD §3.9. **The likely conflict zones:**
   - `docs/M3-IMPLEMENTATION-PLAN.md` Task M3-A6 status line + the total-effort table (PR #58 + #59 both edited this file; M3-A6 also wrote to it). Resolve by keeping main's structural updates + adding M3-A6's task status flip to "shipped."
   - `docs/PRD.md` §9 DE numbering (M3-A6 added DE-284/285/286; main has DE-287 onward). DE-284/285/286 insert before DE-287 in numerical order — no logical conflict, just a textual ordering question.
   - Possibly `api/app/api/__init__.py` if both branches edited the router-registration list (PR #57 added the M3-A6 endpoints; PR #59 added the word-addin endpoints).
3. **Verify CI passes** — same gates as PR #59 (ruff + mypy + pytest on api/, ruff + mypy --strict + pytest on gateway/, svelte-check + Vitest on web/).
4. **Merge the PR** via the standard squash-merge or merge-commit path (the project has been using squash; check Kevin's preference if you need to deviate).
5. **Mirror to `tucuxi`** per the two-remote push convention: `git push origin main && git push tucuxi main`.
6. **Preserve `m3-development`** per the branch-preservation policy — do NOT delete from origin. The branch is the historical record of the M3 Phase A 6-task arc.

### After the reconciliation

`main` is now the single source of truth for M3. `m3-development` stays on origin as a historical archive. Future Phase C / D / E PRs branch off `main` and PR to `main` directly. Estimated reconciliation effort: **~30–60 min** if the conflicts resolve cleanly; **~1.5–2 hr** if conflicts need careful manual resolution (most likely on the M3 plan + the PRD §9 DE-list ordering).

---

## 4. What's queued for the next session — Phase C (Tabular Review)

After the reconciliation lands, Phase C is the next maintainer track per the M3-IMPLEMENTATION-PLAN. The four tasks are tightly coupled and likely ship as a single PR, similar to Phase B's PR #59:

| Task | Scope | Effort |
|---|---|---|
| **M3-C1** | `output_format: table` Skill mode — new skill type that returns N-column structured rows instead of free text | ~6–8 hr |
| **M3-C2** | Tabular LangGraph workflow — applies a Skill to M documents, produces an M×N grid with citations per cell | ~12–16 hr |
| **M3-C3** | Tabular UI surface — `/lq-ai/tabular-reviews/[id]` page with filterable grid + per-cell citation drawer | ~10–14 hr |
| **M3-C4** | Bulk operations + XLSX/CSV export — multi-select rows, batch-rerun, export | ~8–10 hr |

**Total ~36–48 hr.** The largest remaining maintainer track. Per Decision M3-3 (locked at M3 kickoff), Tabular Review is "a new Skill output type, not a parallel system" — most of the existing Skill execution path is reused; the new surface is the grid renderer + the `output_format: table` schema.

### 4.1 Branch + prep doc

1. Branch off `main` AT THE POST-RECONCILIATION HEAD — same pattern as Phase B. Suggested name: `m3-phase-c-tabular-review`.
2. Write a Phase C prep doc at `docs/superpowers/plans/2026-05-XX-m3-phase-c-tabular-review.md` (date when the work actually starts). Lock the design decisions before touching code, M3-A6 / Phase B pattern. Likely decisions to lock:
   - Wire shape of the `output_format: table` Skill frontmatter (column definitions, types, optional widths/labels)
   - Per-cell citation surface — embed citations alongside the grid value, or sidecar them like M2-C2 did for chat citations?
   - Tabular execution: synchronous (small N) vs ARQ-backed (large N like the 200-doc × 10-column scenarios the M3 plan's risk row 7 mentions)
   - XLSX library choice (`openpyxl` is the project's pinned XLSX dep historically; confirm)
   - Cost preview UX — modal-confirm-before-execute, same pattern M3-A4 used for playbook execution

### 4.2 Branching strategy reminder

Once §3's reconciliation lands, `main` is the single source of truth for M3. Continue the **branch off `main`, PR back to `main`** pattern through Phases C/D/E. `m3-development` stays on origin as a historical archive.

---

## 5. Community-track parallel items (already filed; no maintainer work this session)

Three DEs that the community can pick up while the maintainer track runs Phases C/D/E:

* **DE-295** — Word add-in code-signing certificate + signed manifest CI. **SignPath open-source sponsorship is the recommended first path** (free for qualifying OSS); community-funded DigiCert EV / Sectigo OV are alternatives. Cert issued to **LegalQuants, Inc.** regardless of path. Community needs to organize procurement + funding; LegalQuants signs application materials and holds the legal cert artifact. See PRD §9 DE-295 for the full procurement plan + acceptance criteria.
* **DE-287** — Word add-in feature surfaces (chat / skills / playbook execution / Inference Tier badge). Each task (M3-B3/B4/B5/B6) can be claimed individually by a community contributor as a standalone PR against the Phase B plumbing.
* **DE-288** — Slack/Teams `/lq` slash command + Teams parity. Slack and Teams flows can ship as independent community PRs.

**Recommended next move for the project**: post a community announcement (project blog / GitHub Discussions / community channel) calling out DE-295's procurement track specifically — the 2–4 week SignPath approval clock starts when a community member files the tracking issue. The longer that clock runs in parallel, the sooner v0.3.x can flip the unsigned-manifest warning off.

---

## 6. Memory references the next session should re-read first

* `~/.claude/projects/-Users-kevinkeller-Desktop-lq-ai/memory/project_lq_ai_status.md` (most recent block: "Status end-of-session 2026-05-21 evening — M3 Phase B plumbing PR #59 MERGED into main"). Contains the PR #59 commit list, the M3-B7 community handoff detail, the remaining-M3-effort breakdown, and the sequenced-next-steps.
* `~/.../memory/feedback_honest_framing.md` — surface scope changes as choices, not unilaterally absorb.
* `~/.../memory/feedback_branch_preservation.md` — never delete merged feature branches.
* `~/.../memory/feedback_ruff_format_check.md` — run BOTH `ruff format --check` AND `ruff check` locally before push; CI gates on both as separate steps.
* `~/.../memory/feedback_migration_rebuild_all_workers.md` — when a migration lands, rebuild `api` + `arq-worker` + `ingest-worker` together. Phase C's M3-C2 LangGraph workflow may need a migration (e.g., `tabular_executions` table); plan accordingly.

---

## 7. What's NOT in scope for the next session

Per the conservative-posture rule, named explicitly so a future reader can verify scope was held:

* **No Phase D / E work** until Phase C lands cleanly. The sequencing matters because Phase E (fresh-install verification) needs the whole M3 surface in place.
* **No M3-B7 work.** Community-led per DE-295. The maintainer team does not procure the cert.
* **No M3-B3/B4/B5/B6 (Word add-in feature surfaces) work.** Descoped to community per DE-287.
* **No M4 design work.** M4 starts after v0.3.0 ships. The DE-289 Phase 1 ADR (Lavern design study) can start any time, but it's reading + writing work that doesn't gate Phase C.

---

## 8. Operator-side action items outstanding (none blocking)

* M3-A6 manual UAT on a live stack against real prior agreements (Easy Playbook wizard end-to-end against a 5-document corpus). Tracked in the M3-A6 PR description.
* Community announcement for DE-295 procurement track (community sourcing).
* Two-machine fresh-install validation against `main` tip before v0.3.0 tag (lands in M3-E1).

---

## 9. Sequenced next steps for the next session

**Step 0 — reconcile `m3-development` with `main`** (per §3 above):

0. **Open a PR** `m3-development` → `main` titled `Sync m3-development → main — M3-A6 Easy Playbook wizard`. Resolve conflicts (likely on M3-IMPLEMENTATION-PLAN.md + PRD §9 DE-list ordering + maybe `api/app/api/__init__.py`); verify CI green; merge via squash; push to `tucuxi`. Preserve `m3-development` branch on origin.

**Step 1 onwards — Phase C:**

1. **Branch off `main`** at the post-reconciliation head — suggested `m3-phase-c-tabular-review` per Phase B precedent.
2. **Write the Phase C prep doc** (`docs/superpowers/plans/2026-05-XX-m3-phase-c-tabular-review.md`) — lock the design decisions for `output_format: table` schema, per-cell citations, sync-vs-async execution, XLSX library, cost preview UX. M3-A6 / Phase B prep doc patterns are the model.
3. **Implement M3-C1** (`output_format: table` Skill mode) as the foundation. Existing Skill infrastructure should give us most of the wire shape for free.
4. **Implement M3-C2** (Tabular LangGraph workflow) on top of M3-C1. This is where the citation-engine integration happens per-cell.
5. **Implement M3-C3** (Tabular UI surface) — `/lq-ai/tabular-reviews/[id]` route + grid renderer + per-cell citation drawer.
6. **Implement M3-C4** (Bulk ops + XLSX/CSV export) — multi-select, batch-rerun, exports.
7. **Open PR** against `main` once all four tasks verify against a fresh-install Docker stack + a reviewing-attorney walk-through against real-world contracts (M3 plan §3 risk row mentions the latter).

---

## 10. What to say to the next CC session

Paste the following block into the next CC session's first message. It points at this handoff, makes the reconciliation step explicit, and tees up Phase C:

> Resume the M3 work parked at the end of the 2026-05-21 evening session.
>
> Start by reading these in order:
>
> 1. `~/.claude/projects/-Users-kevinkeller-Desktop-lq-ai/memory/project_lq_ai_status.md` (the most recent block, "Status end-of-session 2026-05-21 evening — M3 Phase B plumbing PR #59 MERGED into main")
> 2. `docs/SESSION-HANDOFF-2026-05-21-evening-m3-phase-b-shipped-phase-c-kickoff.md` (the resume order)
> 3. `docs/M3-IMPLEMENTATION-PLAN.md` Phase C section (Tasks M3-C1 through M3-C4)
> 4. `docs/PRD.md` §3.14 Tabular / Multi-Document Review (M3)
>
> Then do these in order:
>
> - **Step 0: Reconcile m3-development with main first.** Open a PR `m3-development` → `main` titled "Sync m3-development → main — M3-A6 Easy Playbook wizard." Resolve the expected conflicts on `docs/M3-IMPLEMENTATION-PLAN.md`, `docs/PRD.md` §9 DE-list, and possibly `api/app/api/__init__.py`. Verify CI green; squash-merge; push to `tucuxi`. Preserve `m3-development` on origin per the branch-preservation policy. This restores single-trunk M3 development on `main`.
>
> - **Step 1: Phase C kickoff.** After the reconciliation merges to `main`, branch off the new `main` head (suggested name `m3-phase-c-tabular-review`) and write a Phase C prep doc at `docs/superpowers/plans/2026-05-XX-m3-phase-c-tabular-review.md` (date when work actually starts). Lock the design decisions before touching code — `output_format: table` Skill frontmatter shape, per-cell citation surface (inline vs sidecar), sync-vs-ARQ execution boundary for tabular workflows, XLSX library choice, cost-preview UX. M3-A6 / Phase B prep docs are the model.
>
> - **Step 2: Implement Phase C** — M3-C1 (Skill mode) → M3-C2 (LangGraph workflow) → M3-C3 (UI) → M3-C4 (bulk ops + export). Single PR against `main` once all four tasks verify against a fresh-install Docker stack + a reviewing-attorney walk-through.
>
> Estimated maintainer effort: ~36–48 hr for Phase C, with the reconciliation step adding ~30 min to ~2 hr depending on conflict density.
>
> Community parallel tracks (no maintainer work; see PRD §9):
>
> - DE-295 — Word add-in code-signing certificate procurement (SignPath OSS sponsorship recommended)
> - DE-287 — Word add-in feature surfaces (M3-B3/B4/B5/B6)
> - DE-288 — Slack/Teams /lq slash command + Teams parity (M3-D2)
>
> After Phase C: Phase D plumbing (~12–20 hr), then Phase E fresh-install verification + docs finalization → v0.3.0 tag.

---

*End of handoff. Next session opens with the m3-development reconciliation (per §3, §9 step 0), then Phase C per §4 onward. PR #59 commit detail + M3-B7 community-descope context lives in memory (`project_lq_ai_status.md`); refer there rather than restating in subsequent handoffs.*
