# Design — DE-365 sub-project 3: vendor-neutral, evidence-linked comparison

**Date:** 2026-07-03
**Owner:** Claude Code (driven), maintainer review
**Tracking:** DE-365 (launch-docs + fiduciary positioning), sub-project 3 of 3 (final)
**Branch:** `feat/de365-sub3-comparison`
**Status:** Approved design — ready for implementation plan
**Not security-gated** (docs + one Svelte Learn page + small README/PRD edits; no gateway/citation-code/auth/CI).

---

## 1. Problem

DE-365 item #2 asks for an **honest, evidence-linked capability comparison** that positions LQ.AI against the proprietary "fiduciary-grade"-claiming legal-tech category. The README carries the vendor-neutral positioning in prose, but there is **no structured matrix where each LQ.AI claim resolves to a proving artifact**. This sub-project builds that matrix — the last piece before DE-365 is complete and the release ritual is unblocked.

## 2. The core thesis (drives every choice)

The comparison axis is **verifiability, not capability**. We do **not** claim the proprietary category *lacks* a feature (unprovable → strawman → self-defeating for an honesty thesis). We claim: **LQ.AI's capability is inspectable / forkable / demonstrable — here is the artifact; a closed-source product's equivalent claim is not independently verifiable or forkable by the user.** That asymmetry is architecturally true. "Honest but unflinching, never a dig" (maintainer directive) — let the demonstrable evidence land the punch.

## 3. Goals / non-goals

**Goals**
- A canonical `docs/comparison.md`: an exhaustive matrix, every LQ.AI cell linking to proof (ADR + code + interactive playground + HONEST-STATE row) on `main`.
- A `/lq-ai/learn/compare` Svelte page: the three fundamental truths + a condensed highlight matrix + per-row links to the **interactive playgrounds** ("proof you can play with") + a prominent pointer to the canonical doc.
- README links both.
- **Vendor-neutral cleanup** folded in: genericize the DE-365 PRD §9 entry's own vendor names; close DE-377 (README "Streamline AI" reference).

**Non-goals (YAGNI)**
- No named competitor anywhere (Thomson Reuters / Westlaw / CoCounsel / any product).
- No new capability claims — the matrix only reflects what HONEST-STATE.md already records as shipped, with the same caveats.
- No new API/backend/gateway code; no new playgrounds (this reuses the 24 from sub-2).
- The Learn page does **not** duplicate the full matrix — it's a narrative + highlights surface that points at the canonical doc (single source of truth, avoids drift).

## 4. Design

### 4.1 Canonical doc — `docs/comparison.md`
Sections:
- **Intro — the three fundamental truths** (vendor-neutral):
  1. *Demonstrable vs. asserted* — every LQ.AI ✓ resolves to a clickable artifact; a closed product's ✓ is a claim you must trust.
  2. *Show the work vs. trust us* — an opaque editorial "good/bad-law" verdict is **architecturally** un-inspectable; LQ.AI derives-and-shows-the-work ([PRD §1.3](PRD.md#13-transparency-as-a-founding-principle) made competitive).
  3. *Named accountability vs. committee-anonymized* — LQ.AI work product carries a **named practicing-attorney attestation** ([skills/CONTRIBUTING.md](../skills/CONTRIBUTING.md)); a closed product diffuses responsibility.
  Plus the honest framing: the proprietary category's *announced* fiduciary-grade direction is the inspiration — and per those public statements it is not yet shipped; LQ.AI delivers it transparently, open-source, self-hosted, **now**.
- **How to read this table**: the axis is verifiability; the "proprietary category" column states the verifiability gap, never asserts capability absence.
- **The matrix** (§4.3).
- **Where LQ.AI is partial or roadmapped** (consolidated honest list, also inline in the rows): DE-370/371 gate parity, EUR-Lex get-by-CELEX-only (DE-374/375), no dedicated matter-intake UI, anonymization recall unmeasured on legal corpus, Word/intake scaffolding.
- **How to verify this comparison**: clone it, read the linked code, run the playgrounds, read [HONEST-STATE.md](HONEST-STATE.md). "If the table claims something the code doesn't back up, the code is canonical — open an issue."

### 4.2 Learn page — `web/src/routes/lq-ai/learn/compare/+page.svelte`
- Follows the existing Learn page pattern (`learn/how`, `learn/use`): `lq-*` design-system classes, `data-testid`s, `<a>` links (not iframes) to the playgrounds + the canonical doc.
- Content: the three fundamental truths (short), a **condensed** highlight matrix (~6–8 headline rows), each row linking to its playground (`/learn/playgrounds/<slug>.html`) and its ADR/code, and a prominent "Full evidence-linked comparison + verification paths → `docs/comparison.md`" callout.
- Wired into the Learn landing (`web/src/routes/lq-ai/learn/+page.svelte`) alongside use/how/build.
- Honest caveats surface here too (partial/roadmap rows carry their note), consistent with the how-page pattern.

### 4.3 The matrix rows (canonical doc)
Each row: **Capability | LQ.AI — verifiable (proof links) | Proprietary category — closed → not user-verifiable/forkable | Honest caveat (if partial)**. Proof links per row (all real on `main`):

| # | Capability | LQ.AI proof artifacts | Honest caveat |
|---|---|---|---|
| 1 | Derive-don't-assert citation verification (4-stage cascade) | ADR 0018; `api/app/citation/verification.py`; playground `citation-engine-cascade` | — |
| 2 | Citation Ledger — every source read, id/offset, **P3 no-raw-payload** | ADR 0018 + ADR 0016 (P3); `api/app/citation/ledger.py`; playground `citation-ledger` | — |
| 3 | Fiduciary-grade gate (PASS/SUPPORTED/FAIL over every citation) | ADR 0018; `api/app/citation/gate.py`; playground `fiduciary-gate` | chat/autonomous verdict-tier parity open (DE-370/371) |
| 4 | Derived validity/treatment ("derived, not editorial") | ADR 0019; `api/app/citation/treatment.py`; playground `treatment-layer` | not an authoritative citator |
| 5 | Free primary-authority retrieve-and-verify (CourtListener/GovInfo/EDGAR/EUR-Lex) | ADR 0021; `api/app/research/registry.py`; playground `authority-sources` | EUR-Lex get-by-CELEX only (DE-374/375) |
| 6 | Governed agentic matter sessions under R5→R6→R4 brakes | ADR 0020; `api/app/autonomous/planner.py` + `guard.py`; playground `matter-session-flow` | no dedicated matter-intake UI yet |
| 7 | Single audited egress boundary (SSRF/tier-gated, per-call audit) | ADR 0014/0015; playground `governed-tool-flow` | — |
| 8 | OpenTelemetry tracing (counts/types only, never raw values) | `docs/observability.md`; playground `otel-eval` | — |
| 9 | Anonymization before egress (pseudonymize + rehydrate) | `gateway/app/anonymization/`; playground `anonymization-layer` | Presidio recall on legal corpus empirically unmeasured (`docs/security/anonymization.md`) |
| 10 | Data residency — self-hosted / BYOK / air-gapped | `docs/architecture.md`; playground `data-residency` | — |
| 11 | Tiered provider governance (refuse below the matter's floor) | `gateway/app/tier_floor.py`; playground `tier-system` | — |
| 12 | Open-source, forkable skills (the work product is visible) | `skills/`; [PRD §1.3](PRD.md#13-transparency-as-a-founding-principle) | — |
| 13 | Named practicing-attorney attestation on legal work product | `skills/CONTRIBUTING.md` (attestation process) | — |
| 14 | Honest self-disclosure of what is NOT wired | `docs/HONEST-STATE.md` | — |

(The plan may trim/merge rows for the doc's readability, but every row that ships must carry a real proof link, and every partial capability must carry its caveat.)

### 4.4 Vendor-neutral cleanup (folded in)
- **DE-365 PRD §9 entry** (`docs/PRD.md`): replace the three named vendors (TR/Westlaw/CoCounsel) with the generic category ("proprietary 'fiduciary-grade'-claiming legal tech" / "closed-source incumbents"), keeping the "their announced direction inspired this" framing generic. Mark sub-project 3 status.
- **DE-377** (`docs/PRD.md`): genericize the README "Streamline AI" reference (e.g. "dedicated legal-intake/triage platforms") and mark DE-377 resolved. Apply the actual README edit in the same pass.

## 5. Honesty guardrails (the whole point)

- The "proprietary category" column states only the **verifiability/forkability gap** — never "they can't do X."
- Every LQ.AI ✓ links to a real artifact resolvable on `main`.
- Every partial/roadmapped capability carries its caveat **inline** (not buried) — DE-370/371, EUR-Lex, matter-intake UI, anonymization validation.
- No named vendor anywhere in the doc, the Learn page, or the edited backlog text.
- Tone: unflinching but never a dig; the demonstrable evidence is the argument.

## 6. Verification

- **Every proof link in `comparison.md` resolves** — a link-check pass (the files/ADRs/playgrounds exist at those paths on `main`; the playground slugs match the 24 shipped in sub-2).
- **Rebuild `web`** (pre-built static bundle — no HMR) and eyeball `/lq-ai/learn/compare`: it renders, the playground links open, the canonical-doc link resolves, caveats are visible; the Learn landing shows the new entry.
- **Prettier + ESLint** on the new Svelte page + the Learn landing edit.
- No new API routes → `IMPLEMENTED_ROUTES` / `EXPECTED_PATHS` guards untouched.
- Vendor-neutral grep: no "Thomson", "Westlaw", "CoCounsel", "Streamline" remain in `README.md`, `docs/comparison.md`, the Learn page, or the edited DE entries.

## 7. Process

Branch first (done) → spec → `writing-plans` → `subagent-driven-development` → rebuild-web verify → normal review + merge → mirror `origin`→`tucuxi`. **On merge, DE-365 is complete** (all 3 sub-projects shipped) → the [fiduciary release gate](HONEST-STATE.md) (fresh-clone Docker bring-up → GHCR → macOS app → version tag) is unblocked, maintainer-driven.

## 8. Risks / open items

- **Doc/Learn-page drift:** two surfaces carry matrix content. Mitigation: the doc is canonical (stated in both); the Learn page is condensed highlights + a pointer, not a full copy.
- **Tone drift toward a dig:** the verifiability-not-capability framing is the guardrail; a reviewer pass explicitly checks the "them" column asserts no capability absence.
- **Link rot:** proof links are pinned to `main` paths that exist today; the link-check verification catches any typo before merge.
