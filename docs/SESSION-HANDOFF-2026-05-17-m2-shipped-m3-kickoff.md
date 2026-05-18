# Session Handoff — 2026-05-17 — M2 shipped (v0.2.0) → M3 kickoff next

> **Purpose:** Context transfer for the M3-kickoff session. **M2 is complete and tagged v0.2.0** on `main` (squash-merged from `m2-development` via PR #42). The next session opens M3 — Playbooks, Word Add-In, Tabular Review, Slack/Teams bridge per [PRD §8 M3](PRD.md#m3--playbooks-word-add-in-tabular-review-and-slackteams-8-weeks-after-m2). M3 is multi-track and benefits from upfront scope decisions before any code lands.
>
> Read time: ~8 minutes. Decisions to surface to Kevin before any code: §4.

---

## 1. State at handoff

### Repo state

| Branch / Tag | SHA | Meaning |
|---|---|---|
| `main` | `8a1b3fc` | M2 squash-merge commit; v0.2.0 release point |
| `v0.2.0` (tag) | `8a1b3fc` | M2 release; GitHub Release published |
| `v0.1.0` (tag) | `3cb2b17` | M1 release; retro-tagged at M2 close |
| `m2-development` | `05b7da4` | Archive branch; kept per Kevin's call for git-blame archaeology |

**Mirrors:** `origin` (LegalQuants) and `tucuxi` (Tucuxi-Inc) both synced. Tags pushed to both. Confirm with `git fetch --all && git log --oneline main origin/main tucuxi/main` before branching for M3.

**GitHub Release:** https://github.com/LegalQuants/lq-ai/releases/tag/v0.2.0 — contains the canonical M2 changelog including all scope-reframe reasoning.

### What landed in M2 (v0.2.0)

* **Citation Engine** — 4-stage cascade (exact match / tolerant match / paraphrase judge / ensemble). M2-A2, M2-B1, M2-C1, M2-D1. 4-state UI (M2-C2). Cost calibration from routing log (M2-E2).
* **Anonymization Layer** — pre/post middleware in the Inference Gateway. Custom legal recognizers (M2-B2). Privileged-project handling (M2-D3). Retrieval-context skip (M2-D2). Streaming-aware rehydrator.
* **Azure OpenAI provider adapter** — M2-E1 / DE-267. API-key auth this release; AD path at DE-278.
* **Documentation finalization (M2-F3)** — two new Learn-tab playgrounds (Citation Engine cascade, Anonymization Layer); PRD §3.3 / §3.8 / §4.7 flipped from "deferred" to "shipped"; honest validation posture surfaced in `docs/security/anonymization.md` §"What's validated vs unvalidated" + README.

### What was deferred via principled scope reframes (NOT busywork — read the reasoning if unsure why)

* **M2-F1** Citation Engine acceptance corpus — closed because existing unit + integration + Cypress + browser + round-trip + edge-case tests already pin the load-bearing behavior. Citation type 2 (case-citation validation, [DE-279](PRD.md#de-279--case-citation-validation-bluebook-resolution-via-courtlistener)) and type 3 (case-content accuracy, [DE-280](PRD.md#de-280--case-content-accuracy-statement-vs-judicial-opinion)) are architecturally distinct surfaces and tracked separately.
* **M2-F2** Anonymization acceptance corpus — closed via *transparency-first deferral*. Recognizer recall/precision on legal corpus is empirically unmeasured but a maintainer-built partial corpus would understate the scope. The principled response: document the gap (`docs/security/anonymization.md` §"What's validated vs unvalidated") + invite community contribution via [DE-282](PRD.md#de-282--anonymization-layer-empirical-validation-on-legal-document-corpus) + give operators actionable guidance (route to Tier 1 / disable anonymization / pre-redact / per-message review).

### Test deltas (M1 → v0.2.0)

| Suite | M1 baseline | v0.2.0 | Delta |
|---|---|---|---|
| `api/` | ~700 | 1013 | +313 |
| `gateway/` | ~300 | 515 | +215 |
| `web/` vitest | ~400 | 456 | +56 |
| Cypress E2E suites | 6 | 7 | +1 (`m2-c2-citation-states`) |

All gates green at v0.2.0: ruff format + ruff check + mypy (strict on gateway, standard on api) + pytest + svelte-check + Vitest.

### Pre-tag fresh-install validation

Performed against `m2-development@05b7da4` (now `main@8a1b3fc`): volumes destroyed, images removed, fresh clone, full `docker compose up --build`. All 7 services healthy; migrations applied through 0029; both new Learn-tab playgrounds serve cleanly. **One UX paper-cut surfaced and filed as [DE-283](PRD.md#de-283--fresh-install-login-ux-surface-the-bootstrap-password-path-on-first-401)** — bootstrap admin password is in `docker compose logs api` but not surfaced at the login UI on 401. Community-friendly first contribution.

---

## 2. New DE entries filed during M2 — relevance for M3

10 DEs filed across M2 (DE-274 through DE-283). The ones likely to bear on M3 decisions:

| DE | Why M3 cares |
|---|---|
| [DE-276](PRD.md#de-276--ingest-observability-surface-silent-embedparse-failures) — Ingest observability | If M3 Tabular Review or Playbooks rely on KB content being reliably embedded, the silent-fail surface from DE-276 hits them too. May want to address as M3 dependency. |
| [DE-279](PRD.md#de-279--case-citation-validation-bluebook-resolution-via-courtlistener) — Case citation validation | If M3 wants citation-grounded research surfaces (litigation work), the Citation Engine type-1 (KB-quote) doesn't cover Bluebook resolution. This is the natural next-citation-type to land. |
| [DE-280](PRD.md#de-280--case-content-accuracy-statement-vs-judicial-opinion) — Case-content accuracy | Hardest of the three citation surfaces. Likely M4, not M3, given complexity. |
| [DE-282](PRD.md#de-282--anonymization-layer-empirical-validation-on-legal-document-corpus) — Anonymization empirical validation | Community-friendly DE. M3 surfaces interact with this (Word Add-In sees the same anonymized content; Tabular Review does too). |

Full list at PRD §9.

---

## 3. M3 scope (per PRD §8)

> **M3 — Playbooks, Word Add-In, Tabular Review, and Slack/Teams (~8 weeks after M2)**
>
> **Theme:** Feature parity with commercial legal AI; surface coverage beyond the web.

The PRD's M3 deliverables:

1. **Playbook engine + 4 built-in playbooks** — Playbook schema + LangGraph executor + Easy Playbook auto-generation wizard. 4 built-ins: Generic SaaS MSA, NDA, DPA (GDPR-aligned), Commercial MSA. Playbook execution UI in web app.
2. **Word Add-In (Office.js)** — Chat against open document; apply skills to selection or whole doc; execute Playbooks against the doc; redlines as Word tracked changes; comments as Word comments; Inference Tier badge in the task pane; enterprise sideload distribution package.
3. **Tabular / Multi-Document Review** (PRD §3.14) — `output_format: table` skill mode; tabular UI surface; bulk operations; XLSX/CSV export; cost preview before execution.
4. **Slack / Teams Light Intake Bridge** (PRD §3.15) — OAuth install on Slack and Teams; `/lq` slash command (forward-as-chat) and `/lq ask` quick-skill flows; bot configuration in LQ.AI admin UI.

These are four largely-independent tracks, not a sequential cascade like M2 was. Some can run in parallel; some have ordering implications. Surface that question to Kevin first.

---

## 4. Decisions to surface to Kevin before any M3 code

These are the choice points I'd ask before opening a `docs/M3-IMPLEMENTATION-PLAN.md` analogous to M2's. **Don't decide unilaterally.**

### A. Phase ordering for the 4 tracks

The four M3 tracks are largely independent. Options:

1. **Sequential by complexity** — Playbook engine first (the substrate; Word Add-In + Tabular both can call playbooks), then Word Add-In, then Tabular, then Slack/Teams. ~weeks 1-3, 4-5, 6, 7-8.
2. **Sequential by visibility** — Word Add-In first (most-requested surface for legal teams already on Word), Playbook engine second, Tabular third, Slack/Teams last (lowest priority).
3. **Parallel where possible** — Playbook engine + Word Add-In in parallel (different stacks: Python + Office.js); Tabular + Slack/Teams after.

Kevin's call. The PRD doesn't lock an order.

### B. Out-of-scope-for-M3 candidates

The PRD lists everything in M3 as committed. Realistic question: is all of it shipping in M3, or is the maintainer-team budget likely to require a similar scope-reframe pass at M3 close? Worth being honest up-front about which of the 4 tracks are "must ship" vs "would be nice."

### C. Plan format

M2 had a detailed `docs/M2-IMPLEMENTATION-PLAN.md` with 18 numbered tasks across 6 phases. Same structure for M3? Or a lighter-touch plan given M3's parallel-track nature?

### D. Word Add-In — distribution + signing

The Office.js add-in needs a signed manifest for enterprise sideload. This is procurement-relevant (operators' IT will require signed builds). Worth deciding upfront whether v0.3 ships a signed manifest or a development-only manifest with a v0.3.1 follow-on for the signing.

### E. Pre-M3 DE landings

Three DEs surfaced during M2 are worth picking up *before* M3 starts (or as M3-phase-0 tasks) rather than during M3:

* **DE-283** (fresh-install login UX) — small, community-friendly, easy win. Worth filing as the first community-contribution PR target.
* **DE-276** (ingest observability) — load-bearing for Tabular Review since silent embed failures break tabular outputs.
* **DE-277** (citation extractor chunk-boundary fallback) — small, isolated, would land cleanly between milestones.

Kevin's call on which of these become M3-phase-0 vs M3.1 vs deferred to M4.

---

## 5. Next-session entry point

After this handoff merges, the next session opens with this prompt:

> Start M3. Read `docs/SESSION-HANDOFF-2026-05-17-m2-shipped-m3-kickoff.md` first. §4 has the open decisions. Don't write code; surface the decisions to Kevin, then propose a `docs/M3-IMPLEMENTATION-PLAN.md`.

The session opens with **§4 decision-A through E pending**. The new Claude should NOT default to building anything. The right move is to read the handoff + surface the four decisions + wait for Kevin.

If Kevin gives explicit direction (e.g., "build the Playbook engine first") then the next session writes the M3 plan + the first PR's investigation map and branches off `main`.

---

## 6. Memory state at end-of-session

* `MEMORY.md` updated — points at this handoff as the M2-close + M3-kickoff entry.
* `project_lq_ai_status.md` updated — M2 SHIPPED at v0.2.0 / `8a1b3fc`; M3 next.
* Other memory files (user role, feedback, references) unchanged.

---

## 7. Open PRs at handoff time

None. PRs #22–#42 all merged. The release-cycle PRs (#41 DE-283 doc; #42 main merge) closed cleanly.

This branch (`handoff/m2-shipped-m3-kickoff`) is doc-only and adds this file. After merging it, no open PRs.

---

## 8. Loose ends explicitly NOT being carried into M3

* **Per-skill prompt-injection detection rates** — PRD §1.9 commits to publishing these; M2 didn't ship them. Tracked at PRD §9 Engineering Discipline subsection. Worth noting on the M3 plan since it's a continuing commitment.
* **OpenSSF Scorecard / Best Practices Badge** — Silver tier targeted at M2 release per PRD §1.8. Not yet shipped. Decision: address in M3 or push to M3.x?
* **Mutation testing per release** — PRD §1.9 commits to this; M2 release didn't include a mutation score. Tracked at PRD §9. Decision: M3 or later?

These are public commitments the project has made. The honest framing for M3 is to surface them explicitly + decide which to pick up vs leave on the deferred list.

---

*End of handoff. The next session begins at §4 with the five decisions for Kevin.*
