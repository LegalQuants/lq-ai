# Donna ⇄ LQ.AI capability + visualization sync — 2026-07-02

> **Purpose:** a canonical, versioned reference for Donna CC when updating Donna's "About" and other information that links back to LQ.AI capabilities and visualizations. It states, honestly, **what LQ.AI shipped and can be linked to today** vs. **what is planned but not yet built** (so Donna's back-links don't 404 and Donna's copy doesn't overclaim).
>
> **Maintenance:** update this file when new capabilities ship or new Learn visualizations land. **DE-365 sub-project 2** (the five fiduciary-grade playgrounds) shipped 2026-07-02 — §2/§3 now list them as live with final slugs/URLs. The next planned update is **DE-365 sub-project 3** (the vendor-neutral comparison). If this doc and the code disagree, the code is canonical.

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

## 2. Visualizations Donna can link to now (24 live playgrounds)

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
| `authority-sources`, `citation-ledger`, `fiduciary-gate`, `treatment-layer`, `matter-session-flow` | **the fiduciary-grade loop** (new — see §3): authority registry → ledger → gate → treatment → governed matter session |

**Full set (24):** `anonymization-layer`, `authority-sources`, `autonomous-flow`, `autonomous-primitives`, `citation-engine-cascade`, `citation-ledger`, `data-residency`, `fiduciary-gate`, `governed-tool-flow`, `intake-bridges`, `kb-hybrid-retrieval`, `matter-session-flow`, `otel-eval`, `playbook-cascade`, `projects-org-tiers`, `request-lifecycle`, `skill-composition`, `skill-format`, `system-architecture`, `tabular-review`, `test-landscape`, `tier-system`, `treatment-layer`, `word-addin-flow`.

> ✅ **Coverage gap now CLOSED (2026-07-02, DE-365 sub-2).** The five fiduciary-grade playgrounds shipped — the **Citation Ledger / fiduciary gate / authority-source / treatment / governed matter session** story now has dedicated visualizations. Donna may link them (final slugs/URLs in §3). The earlier gap note is superseded.

---

## 3. Available — DE-365 sub-project 2 (fiduciary-grade playgrounds) — SHIPPED (2026-07-02)

The five fiduciary-grade playgrounds are **built, reviewed, and merged to `main`** in the same self-contained-HTML + verify-in-source pattern as the other 19. **Slugs below are FINAL** — safe to hard-link. Each is a self-contained static file (no live network calls) and each surfaces its own honest caveat in-viz.

**Runtime URLs** (on any running deployment):

```
https://<lq-ai-host>/learn/playgrounds/<slug>.html   # a single playground, full-screen
https://<lq-ai-host>/lq-ai/learn/how                  # the "How it works" page — the 5 are sections 18–22, a labeled cluster
```

| # | Final slug | Runtime URL | Covers | Honest caveat carried in-viz |
|---|---|---|---|---|
| 18 | `authority-sources` | `/learn/playgrounds/authority-sources.html` | the content-source registry + retrieve-and-verify across CourtListener / GovInfo / SEC EDGAR / EUR-Lex; toggle which providers the operator configured and watch each report `enabled` or unavailable-with-reason | EUR-Lex is get-by-CELEX only (search=DE-374, treaty=DE-375); sources operator-config-gated, reported unavailable-with-reason, never silently hidden |
| 19 | `citation-ledger` | `/learn/playgrounds/citation-ledger.html` | source → passage-read → verification status → one-click trace to source + character offset; provenance-only entries flagged as non-assertions | references content by **id + character offset only — no raw payloads** in the audit layer (P3) |
| 20 | `fiduciary-gate` | `/learn/playgrounds/fiduciary-gate.html` | derive-don't-assert: assemble a turn's citations and watch the deterministic bucketing into **PASS / SUPPORTED / FAIL** (provenance excluded) | chat vs autonomous verdict-tier parity gaps remain (DE-370 / DE-371). NB: real tiers are **PASS / SUPPORTED / FAIL** (the earlier "PASS / FAIL / flagged" shorthand was imprecise) |
| 21 | `treatment-layer` | `/learn/playgrounds/treatment-layer.html` | derived validity/treatment signals (followed / distinguished / criticized) + trace to each citing case; two-pass graph→judge derivation | **"derived, not editorial"** — not an authoritative citator; judge snippets never stored (P3), 30-day TTL |
| 22 | `matter-session-flow` | `/learn/playgrounds/matter-session-flow.html` | the capstone: plan → act → observe → replan over a closed tool set, under the brakes (order **R5 → R6 → R4**) + a per-phase step cap; orchestrates 18–21 | backend shipped; **no dedicated matter-intake UI yet** (reuses the autonomous session UI) |

**How Donna integrates these:**
- For a single-capability deep link, point at `/learn/playgrounds/<slug>.html` (opens full-screen, self-contained — safe to embed in an `<iframe>` too; that's how the Learn page renders them).
- For the whole fiduciary story, link `/lq-ai/learn/how` — the 5 are a contiguous labeled cluster (sections 18–22) that reads authority → ledger → gate → treatment → session.
- Each playground's "Verify in source ↗" links resolve to the real backend module + ADR on `main`, so Donna's "how we know this is real" story can chain straight through to code.
- These are **illustrative** (synthetic/static data, no live calls) — the honest caveats in §1 remain the source of truth for what the *backend* actually does today.

**Recommendation for Donna CC:** the fiduciary-grade viz links are now live and stable — add them. The five slugs above will not change.

---

## 4. Sequence

DE-365 is three sub-projects, built in order: **(1) docs/README honesty audit — shipped (PR #260); (2) fiduciary-grade playgrounds — next; (3) vendor-neutral competitor comparison.** A release ritual (fresh-clone Docker bring-up → package Docker images + macOS app → version tag → handoff) follows once the milestone is ready to version.
