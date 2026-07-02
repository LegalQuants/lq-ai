# Donna ⇄ LQ.AI capability + visualization sync — 2026-07-02

> **Purpose:** a canonical, versioned reference for Donna CC when updating Donna's "About" and other information that links back to LQ.AI capabilities and visualizations. It states, honestly, **what LQ.AI shipped and can be linked to today** vs. **what is planned but not yet built** (so Donna's back-links don't 404 and Donna's copy doesn't overclaim).
>
> **Maintenance:** update this file when new capabilities ship or new Learn visualizations land. The next planned update is when **DE-365 sub-project 2** (fiduciary-grade playgrounds) ships — at which point the "Planned" slugs below become live URLs. If this doc and the code disagree, the code is canonical.

---

## 1. What is available to Donna now (shipped on `main`)

The **fiduciary-grade agentic legal work** milestone (Phase 2) is fully merged. Each row links to a proving artifact; each caveat is the honest current limit.

| Capability | What it is | Honest caveat (carry this into Donna's copy) | Proof |
|---|---|---|---|
| **Free authority sources** | Retrieve-and-verify primary law by identifier across **four** sources: CourtListener (US case law), GovInfo (US Code / CFR), SEC EDGAR (public filings), EUR-Lex (EU legislation + CJEU case law, by CELEX) | **EUR-Lex is get-by-CELEX only** (no keyword search yet); all sources are behind operator config | [ADR 0021](https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0021-content-source-registry-and-free-source-expansion.md), [SOURCE_REGISTRY](https://github.com/LegalQuants/lq-ai/blob/main/api/app/research/registry.py) |
| **Citation Ledger** | Matter/turn-scoped record of every source + passage the agent actually read, with one-click "trace this claim to its source" | References content by id/offset only — no raw payloads in the audit layer | [ADR 0018](https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md), [ledger.py](https://github.com/LegalQuants/lq-ai/blob/main/api/app/citation/ledger.py) |
| **Fiduciary-grade gate** | Derive-don't-assert: the verification cascade runs over every tool-retrieved citation → PASS / FAIL → `flagged` | Chat vs autonomous verdict-tier parity gaps remain ([DE-370](https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md#9-deferred-enhancements-and-identified-future-work) / DE-371) | [gate.py](https://github.com/LegalQuants/lq-ai/blob/main/api/app/citation/gate.py) |
| **Governed agentic matter sessions** | Plain-language "describe your matter" → planned, closed-set, multi-source session under hard brakes → work product + ledger | Backend shipped; **no dedicated matter-intake UI yet** (reuses the autonomous session UI) | [ADR 0020](https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0020-governed-agentic-legal-matter-sessions.md), [planner.py](https://github.com/LegalQuants/lq-ai/blob/main/api/app/autonomous/planner.py) |
| **Validity / treatment layer** | Derived case-law treatment signals (followed / distinguished / criticized) with trace to each citing case | **"Derived, not editorial"** — not an authoritative citator | [ADR 0019](https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0019-transparent-validity-treatment-layer.md), [treatment.py](https://github.com/LegalQuants/lq-ai/blob/main/api/app/citation/treatment.py) |

**EUR-Lex, specifically:** LQ.AI can fetch and character-verify EU regulations, directives, decisions, and CJEU judgments by CELEX id (e.g. `32016R0679` = GDPR), through the same governed gateway egress + citation-verify path as the US sources. Get-by-CELEX today; full-text search is the tracked next step ([DE-374](https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md#9-deferred-enhancements-and-identified-future-work)).

For the full, honest shipped-vs-roadmap picture, Donna should treat these as source of truth: [README Project status](https://github.com/LegalQuants/lq-ai/blob/main/README.md#project-status), [HONEST-STATE.md](https://github.com/LegalQuants/lq-ai/blob/main/docs/HONEST-STATE.md), [ROADMAP.md](https://github.com/LegalQuants/lq-ai/blob/main/docs/ROADMAP.md).

---

## 2. Visualizations Donna can link to now (19 live playgrounds)

The interactive playgrounds are self-contained HTML in [`web/static/learn/playgrounds/`](https://github.com/LegalQuants/lq-ai/blob/main/web/static/learn/playgrounds), surfaced through the Learn tab. On a running deployment they are served at the runtime URL pattern:

```
https://<lq-ai-host>/learn/playgrounds/<slug>.html      # a single playground
https://<lq-ai-host>/lq-ai/learn/{use, how, build}       # the Learn narrative pages
```

**Most relevant to Donna's "About" / transparency story:**

| Slug | Topic |
|---|---|
| `governed-tool-flow` | the governed tool boundary — case-law + connectors, gateway egress, per-call audit, confirmation gate |
| `citation-engine-cascade` | the 4-stage character-fidelity citation verification (exact → tolerant → paraphrase judge → ensemble) |
| `autonomous-flow` / `autonomous-primitives` | the audited autonomous layer (watches, schedules, memory, precedent) |
| `tier-system`, `anonymization-layer`, `data-residency`, `request-lifecycle`, `system-architecture` | the security / privacy / data-residency architecture |

**Full set (19):** `anonymization-layer`, `autonomous-flow`, `autonomous-primitives`, `citation-engine-cascade`, `data-residency`, `governed-tool-flow`, `intake-bridges`, `kb-hybrid-retrieval`, `otel-eval`, `playbook-cascade`, `projects-org-tiers`, `request-lifecycle`, `skill-composition`, `skill-format`, `system-architecture`, `tabular-review`, `test-landscape`, `tier-system`, `word-addin-flow`.

> ⚠️ **Coverage gap Donna should know:** none of the 19 existing playgrounds cover the fiduciary-grade milestone yet. Today Donna can link to `governed-tool-flow` and `citation-engine-cascade` for the "how it verifies" story, but the **Citation Ledger / fiduciary gate / authority-source / treatment** story has **no visualization yet**. Those are sub-project 2 (below).

---

## 3. Planned — DE-365 sub-project 2 (fiduciary-grade playgrounds) — NOT YET BUILT

Five new playgrounds are planned to cover the uncovered fiduciary-grade capabilities, in the same self-contained-HTML + verify-in-source pattern. **Slugs are PROPOSED, not final** — sub-project 2 is not yet specced, so do not hard-link these yet.

| Proposed slug | Will cover |
|---|---|
| `citation-ledger` | source → passage-read → verification status → one-click trace |
| `fiduciary-gate` | derive-don't-assert PASS / FAIL / flagged over every citation |
| `matter-session-flow` | plan → act → observe → replan, closed-set tools, under R4/R5/R6 brakes |
| `authority-sources` | the content-source registry + retrieve-and-verify across GovInfo / EDGAR / EUR-Lex / CourtListener |
| `treatment-layer` | derived validity/treatment signals + trace to citing cases |

When these ship they land at `/learn/playgrounds/<slug>.html` and are wired into `/lq-ai/learn/how`.

**Recommendation for Donna CC:** link the existing 19 now; wait for the final slugs/URLs (this doc will be updated when sub-project 2 ships) before adding fiduciary-grade viz links, so Donna's back-links don't 404.

---

## 4. Sequence

DE-365 is three sub-projects, built in order: **(1) docs/README honesty audit — shipped (PR #260); (2) fiduciary-grade playgrounds — next; (3) vendor-neutral competitor comparison.** A release ritual (fresh-clone Docker bring-up → package Docker images + macOS app → version tag → handoff) follows once the milestone is ready to version.
