# DE-365 Sub-project 1 — Docs/README claims-vs-reality honesty audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `README.md`, `docs/HONEST-STATE.md`, and `docs/ROADMAP.md` faithfully reflect what the code does as of the fiduciary-grade milestone — by auditing every existing capability/status claim against the code (fixing over/under-statements) and adding the missing Phase-2 capabilities, backed by a durable audit worksheet.

**Architecture:** A bidirectional audit. A durable worksheet (`docs/audits/2026-07-01-claims-vs-reality.md`) is built first — Direction A (docs→code: verdict every existing claim) then Direction B (code→docs: find shipped-but-undocumented capabilities). Its resolutions are then applied to each doc in a reconciled pass, and a final consistency + link-resolution verification closes it out.

**Tech Stack:** Markdown docs only. Verification via a small Python link-resolution script + grep-based consistency checks. No code, test, or product changes.

## Global Constraints

Copied from the spec — every task implicitly includes these:

- **Documentation only.** No changes to code, tests, or product behavior. Do not edit anything under `api/app/**`, `gateway/app/**`, `web/src/**`, `alembic/**`, or any test.
- **CLAUDE.md principle 4 (never overclaim).** A "shipped ✓" claim must be demonstrable by an in-house lawyer on real documents. Where a capability is partial or roadmapped, say so.
- **Every "shipped ✓" claim links to the artifact that proves it** — an ADR, a code path, or a test. Prefer GitHub blob links on `main` for code (`https://github.com/LegalQuants/lq-ai/blob/main/<path>`), consistent with the README's existing style.
- **Vendor-neutral.** No named competitor products (no Thomson Reuters / Westlaw / CoCounsel), even in honesty prose. That comparison is sub-project 3 and is itself vendor-neutral.
- **Cross-document consistency.** Nothing marked "shipped" in `README.md` may appear as unbuilt in `docs/HONEST-STATE.md`; `docs/ROADMAP.md` must agree with both.
- **`docs/PRD.md` is finding-gated.** Edit PRD §8 status lines ONLY where the worksheet records a concrete inaccuracy — never a blanket sweep.
- **Facts pinned at authoring time (verify, don't trust):** latest migration = **0064**; live authority sources in `SOURCE_REGISTRY` = govinfo, edgar, eurlex; open fiduciary DEs = **DE-370** (attributed-authority FAIL tier, chat), **DE-371** (autonomous SUPPORTED tier), **DE-374** (EUR-Lex search), **DE-375** (treaty/corrigendum CELEX), **DE-376** (EUR-Lex subtitle/test). Milestone ADRs: **0018** citation ledger + fiduciary gate, **0019** transparent validity/treatment, **0020** governed agentic matter sessions, **0021** content-source registry + free sources.

---

## Shared verification tooling (used by Tasks 3–6)

The "test" for a docs task is a **link-resolution check** — every repo-relative or GitHub-blob link in a changed file must resolve to a real path on disk. Create this helper once, in Task 1, and reuse it.

`scripts/check_doc_links.py` (throwaway audit tool — committed under `docs/audits/` next to the worksheet, NOT under top-level `scripts/`, to keep it clearly non-product):

```python
#!/usr/bin/env python3
"""Resolve markdown links in the given files against the repo tree.

Checks two link shapes and asserts the referenced repo path exists:
  1. relative markdown links:      [text](docs/foo.md)  or  [text](../adr/0018-x.md)
  2. GitHub blob links on main:    https://github.com/LegalQuants/lq-ai/blob/main/<path>
Anchors (#...) and pure-external URLs (http[s] not to our blob) are ignored.
Exit 1 (and print) if any link dangles.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # docs/audits/ -> repo root
BLOB = "https://github.com/LegalQuants/lq-ai/blob/main/"
LINK_RE = re.compile(r"\]\(([^)]+)\)")


def resolve(target: str, doc: Path) -> Path | None:
    target = target.split("#", 1)[0].strip()
    if not target:
        return None
    if target.startswith(BLOB):
        return REPO / target[len(BLOB):]
    if target.startswith(("http://", "https://", "mailto:")):
        return None  # external, not our concern
    return (doc.parent / target).resolve()


def main(files: list[str]) -> int:
    dangling: list[str] = []
    for f in files:
        doc = Path(f).resolve()
        for m in LINK_RE.finditer(doc.read_text(encoding="utf-8")):
            path = resolve(m.group(1), doc)
            if path is not None and not path.exists():
                dangling.append(f"{f}: {m.group(1)} -> {path}")
    for d in dangling:
        print("DANGLING:", d)
    print(f"{'FAIL' if dangling else 'OK'}: {len(dangling)} dangling link(s)")
    return 1 if dangling else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

Run shape: `python docs/audits/check_doc_links.py README.md docs/HONEST-STATE.md docs/ROADMAP.md`

---

## Task 1: Audit worksheet + Direction A (docs → code verdicts)

**Files:**
- Create: `docs/audits/2026-07-01-claims-vs-reality.md`
- Create: `docs/audits/check_doc_links.py` (the helper above)

**Interfaces:**
- Produces: the worksheet with a Direction-A table whose columns are `claim | where | artifact | verdict | resolution`; verdict ∈ {Accurate, Overstated, Understated, Stale}. Tasks 3–5 consume the `resolution` column as their edit list. Produces `check_doc_links.py` consumed by Tasks 3–6.

- [ ] **Step 1: Create the link-check helper**

Create `docs/audits/check_doc_links.py` with the exact script from "Shared verification tooling" above. Make it executable: `chmod +x docs/audits/check_doc_links.py`.

- [ ] **Step 2: Verify the helper runs on an unchanged doc**

Run: `python docs/audits/check_doc_links.py README.md`
Expected: prints `OK: 0 dangling link(s)` (or, if the *current* README already has a dangling link, note it in the worksheet as a pre-existing finding — do not fix unrelated links unless the audit touches that line).

- [ ] **Step 3: Extract every claim from the three docs**

Read `README.md` (esp. the intro, "What you can verify", "What it does", "Project status" + roadmap table), `docs/HONEST-STATE.md` (all sections), and `docs/ROADMAP.md`. For each capability/status assertion, add a worksheet row with `claim` (quoted) and `where` (file + section). Seed set to guarantee coverage (not exhaustive — add all you find):
  - README "What it does": Citation Engine four-stage cascade; Anonymization Layer; Projects; Org Profile; Inference Tier Awareness + tier-floor; Audit log.
  - README "Project status" prose: "M1 through M4 shipped"; the "current shipped = Legal research + connectors (MCP)" framing; the roadmap table rows M1–M4 + "Legal research + connectors (MCP)" + M5–M7.
  - HONEST-STATE: every "not yet wired / roadmap" item (Word feature surfaces, chat-platform intake, Contract Repository graph, etc.).

- [ ] **Step 4: Verdict each claim against the code**

For each row, locate the proving-or-refuting artifact (ADR / code path / test) and set `verdict` + `resolution`. Rules:
  - **Accurate** → resolution = "attach proving link" (if missing) or "no change".
  - **Overstated** (claims more than code does) → resolution = the softened wording.
  - **Understated / missing** (code does more, or a shipped thing is under roadmap) → resolution = the upgrade/move.
  - **Stale** (outdated milestone framing) → resolution = the updated framing.
  Verify against real files — e.g. the "current shipped" framing is **Stale** because the fiduciary-grade milestone (ADRs 0018–0021, merged) is not mentioned. Confirm each cited path exists with `test -e`.

- [ ] **Step 5: Commit**

```bash
git add docs/audits/2026-07-01-claims-vs-reality.md docs/audits/check_doc_links.py
git commit -s -m "docs(DE-365): claims-vs-reality worksheet — Direction A (docs->code verdicts)"
```

---

## Task 2: Direction B (code → docs — shipped-but-undocumented)

**Files:**
- Modify: `docs/audits/2026-07-01-claims-vs-reality.md` (append the Direction-B section)

**Interfaces:**
- Consumes: the worksheet from Task 1.
- Produces: a Direction-B table listing each shipped fiduciary-grade capability, its anchor artifact, its honest caveat, and where it must be added in the docs. Tasks 3–5 consume this as their "additions" list.

- [ ] **Step 1: Enumerate shipped capabilities from authoritative sources**

Read the milestone ADRs and confirm live state:
  - `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md`, `docs/adr/0019-transparent-validity-treatment-layer.md`, `docs/adr/0020-governed-agentic-legal-matter-sessions.md`, `docs/adr/0021-content-source-registry-and-free-source-expansion.md`.
  - `api/app/research/registry.py` — confirm `SOURCE_REGISTRY` keys (govinfo, edgar, eurlex).
  - `grep -n "eur_regulation\|_VERIFIABLE_CONTENT_KINDS" api/app/citation/authority.py`; confirm `api/app/citation/ledger.py`, `gate.py`, `treatment.py`, `api/app/tools/governance.py` exist.
  - PRD §9 DE state for DE-370/371/374/375/376 (open) — `grep -n "DE-37[0-6]" docs/PRD.md`.

- [ ] **Step 2: Add a Direction-B row per capability**

Append a table with columns `capability | anchor artifact | honest caveat | add-to`. Populate at minimum these six (verify each against Step 1's reads):

| capability | anchor | honest caveat | add-to |
|---|---|---|---|
| Citation Ledger | ADR 0018; `api/app/citation/ledger.py` | references content by id/offset only — no raw payloads in the audit layer (P3, ADR 0016) | README narrative + status; HONEST-STATE |
| Fiduciary-grade gate | ADR 0018; `api/app/citation/gate.py` | chat vs autonomous parity gaps: DE-370, DE-371 still open | README narrative + status; HONEST-STATE |
| Governed agentic matter sessions | ADR 0020; PRs #239/#240 | on the autonomous layer under R5→R6→R4 brakes; no dedicated matter-intake UI yet | README status/roadmap; HONEST-STATE (UI gap) |
| Content-source registry + free authority sources | ADR 0021; `SOURCE_REGISTRY` | behind operator config; EUR-Lex get-by-CELEX only (search=DE-374; treaty=DE-375) | README narrative + status; ROADMAP |
| Validity / treatment layer | ADR 0019; `api/app/citation/treatment.py` | "derived, not editorial," not an authoritative citator; per-case judge budget | README narrative + status; HONEST-STATE |
| Governed egress cost model | DE-344; `api/app/tools/governance.py` | configured per-call rate, not response-parsed; fails-open on gateway-config failure | README status |

- [ ] **Step 3: Reconcile the two directions**

Add a short "Reconciliation notes" subsection: flag any Direction-A "Stale" row that a Direction-B capability resolves (e.g. the "current shipped = MCP milestone" staleness is resolved by adding the fiduciary-grade milestone). Confirm no contradictions between the planned edits.

- [ ] **Step 4: Commit**

```bash
git add docs/audits/2026-07-01-claims-vs-reality.md
git commit -s -m "docs(DE-365): claims-vs-reality worksheet — Direction B (code->docs additions)"
```

---

## Task 3: Reconcile README.md

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the worksheet's README-scoped `resolution` rows (Task 1) and Direction-B `add-to = README` rows (Task 2).

- [ ] **Step 1: Apply Direction-A README resolutions**

Edit only the README lines whose worksheet verdict is Overstated / Understated / Stale. Attach proving links to Accurate claims that lack one. Do not rewrite Accurate prose.

- [ ] **Step 2: Add the fiduciary-grade milestone**

In "What it does", add concise paragraphs for the Citation Ledger, the fiduciary-grade gate, governed agentic matter sessions, free authority sources (GovInfo/SEC EDGAR/EUR-Lex), and the treatment/validity layer — each with its honest caveat and a proving link (ADR blob URL + a code path). In "Project status": update the "current shipped" prose to name the fiduciary-grade milestone, and add a roadmap-table row:

```markdown
| **Fiduciary-grade agentic legal work** | Citation Ledger (matter/turn record of every source + passage read, one-click trace); derive-don't-assert fiduciary gate over every tool-retrieved citation (PASS/FAIL → flagged); governed plain-language matter sessions on the autonomous layer under R5→R6→R4 brakes; free authority sources (GovInfo, SEC EDGAR, EUR-Lex) via a content-source registry with retrieve-and-verify; a "derived, not editorial" validity/treatment layer with one-click trace to citing cases | ✓ **Shipped** (matter-intake UI + some chat/autonomous verify-parity items roadmap) |
```

- [ ] **Step 3: Verify links resolve**

Run: `python docs/audits/check_doc_links.py README.md`
Expected: `OK: 0 dangling link(s)`. Fix any dangling link you introduced.

- [ ] **Step 4: No-overclaim / vendor-neutral read-through**

Re-read every changed paragraph. Confirm: no capability stated more strongly than its caveat allows; no named competitor; each "✓ Shipped" has a proving link. Note the read-through result in the worksheet.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/audits/2026-07-01-claims-vs-reality.md
git commit -s -m "docs(DE-365): reconcile README with current state — add fiduciary-grade milestone"
```

---

## Task 4: Reconcile docs/HONEST-STATE.md

**Files:**
- Modify: `docs/HONEST-STATE.md`

**Interfaces:**
- Consumes: worksheet HONEST-STATE rows (Task 1) + Direction-B `add-to = HONEST-STATE` rows (Task 2).
- Produces: a HONEST-STATE that is cross-consistent with the reconciled README from Task 3.

- [ ] **Step 1: Move now-shipped items out of "not yet built"**

For every HONEST-STATE row the worksheet marks Understated (i.e. now shipped), move it from the not-yet-wired section to a shipped/landed framing (or delete if fully covered by README) — matching how README now describes it.

- [ ] **Step 2: Add the fiduciary-grade honest caveats**

Add the genuinely-still-partial items as honest-state entries with verification paths: the **matter-intake UI gap** (backend #239/#240 shipped, no dedicated intake UI — reuses autonomous session UI), **chat/autonomous gate parity** (DE-370 attributed-authority FAIL tier; DE-371 autonomous SUPPORTED tier), and **EUR-Lex get-only scope** (search=DE-374, treaty/corrigendum=DE-375). Each links to its DE / code path.

- [ ] **Step 3: Cross-consistency check vs README**

Run: `grep -niE "shipped|✓" README.md` and confirm no capability marked shipped in README is listed as unbuilt in HONEST-STATE. Run `python docs/audits/check_doc_links.py docs/HONEST-STATE.md` → `OK`.

- [ ] **Step 4: Commit**

```bash
git add docs/HONEST-STATE.md docs/audits/2026-07-01-claims-vs-reality.md
git commit -s -m "docs(DE-365): reconcile HONEST-STATE — fiduciary-grade shipped state + honest gaps"
```

---

## Task 5: Reconcile docs/ROADMAP.md (+ PRD §8 finding-gated)

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify (only on a concrete finding): `docs/PRD.md`

**Interfaces:**
- Consumes: worksheet ROADMAP rows + Direction-B `add-to = ROADMAP` rows; the reconciled README/HONEST-STATE from Tasks 3–4.

- [ ] **Step 1: Apply ROADMAP resolutions**

Update `docs/ROADMAP.md` so the fiduciary-grade milestone items are reflected as shipped and the ordered punch-list matches current DE state (DE-370/371/374/375/376 open; DE-373 shipped). Remove/relabel entries the milestone completed.

- [ ] **Step 2: PRD §8 — finding-gated only**

Only if the worksheet recorded a concrete PRD §8 inaccuracy, fix that exact line. Otherwise make NO PRD edit. (PRD §9 DE entries are already current — do not touch.)

- [ ] **Step 3: Verify links + three-way consistency**

Run: `python docs/audits/check_doc_links.py docs/ROADMAP.md` → `OK`. Then confirm ROADMAP agrees with both README and HONEST-STATE (no item shipped in one and roadmap in another). Record the three-way check in the worksheet.

- [ ] **Step 4: Commit**

```bash
git add docs/ROADMAP.md docs/audits/2026-07-01-claims-vs-reality.md
# add docs/PRD.md ONLY if step 2 changed it
git commit -s -m "docs(DE-365): reconcile ROADMAP with current milestone/DE state"
```

---

## Task 6: Whole-set verification + finalize worksheet

**Files:**
- Modify: `docs/audits/2026-07-01-claims-vs-reality.md` (append the verification report)

**Interfaces:**
- Consumes: all reconciled docs (Tasks 3–5).
- Produces: the definition-of-done evidence.

- [ ] **Step 1: Link resolution over all changed docs**

Run: `python docs/audits/check_doc_links.py README.md docs/HONEST-STATE.md docs/ROADMAP.md` (add `docs/PRD.md` if Task 5 touched it).
Expected: `OK: 0 dangling link(s)`.

- [ ] **Step 2: Cross-document consistency sweep**

Confirm the six definition-of-done criteria from the spec: (1) links resolve; (2) markdown well-formed (headings/tables render — eyeball each changed table); (3) nothing shipped-in-README is unbuilt-in-HONEST-STATE; (4) each fiduciary caveat matches DE-ledger state — `grep -n "DE-37[0-6]" docs/PRD.md` and confirm 370/371/374/375/376 are still open; (5) no overclaim + no named vendor (`grep -niE "thomson|westlaw|cocounsel|reuters" README.md docs/HONEST-STATE.md docs/ROADMAP.md` → no hits); (6) every worksheet row has a verdict + resolution (no "TBD").

- [ ] **Step 3: Append the verification report to the worksheet**

Add a "Verification (DONE)" section recording each of the six checks and its result (command + outcome).

- [ ] **Step 4: Commit**

```bash
git add docs/audits/2026-07-01-claims-vs-reality.md
git commit -s -m "docs(DE-365): claims-vs-reality verification report — sub-project 1 DoD"
```

---

## Final gates (before PR)

- [ ] `git diff --name-only main..HEAD` shows ONLY `README.md`, `docs/HONEST-STATE.md`, `docs/ROADMAP.md`, `docs/audits/**`, `docs/superpowers/{specs,plans}/**`, and (if a finding required it) `docs/PRD.md` — NO code/test/web files.
- [ ] `python docs/audits/check_doc_links.py README.md docs/HONEST-STATE.md docs/ROADMAP.md` → `OK: 0 dangling link(s)`.
- [ ] Vendor-neutral grep clean (Step 2 above).
- [ ] Opus whole-branch review (docs honesty is the crux — reviewer checks for overclaim + link accuracy + cross-doc consistency) → fix Critical/Important.
- [ ] Push origin (+ tucuxi per project convention), open PR. Not security-gated (docs-only, no `gateway/**`/citation-code changes) — normal review + merge, then mirror `origin`→`tucuxi`.

## Self-review notes (plan ↔ spec)

- **Spec coverage:** Approach bidirectional worksheet → Tasks 1 (Dir A) + 2 (Dir B); durable worksheet → `docs/audits/` created Task 1; README reconcile → Task 3; HONEST-STATE → Task 4; ROADMAP + PRD finding-gated → Task 5; the six-point DoD → Task 6 + Final gates; fiduciary-grade additions table → Task 2 Step 2 (same six capabilities/caveats as the spec table); evidence-linking + vendor-neutral → Global Constraints + Task 3/6 read-throughs.
- **Placeholder scan:** no "TBD/TODO/handle-edge-cases"; the only "TBD" string is the DoD check that forbids it. The link-check script is complete, not sketched. The roadmap-table row and worksheet columns are given concretely.
- **Type/name consistency:** worksheet columns `claim|where|artifact|verdict|resolution` (Task 1) and `capability|anchor|caveat|add-to` (Task 2) are referenced identically by Tasks 3–5; `check_doc_links.py` path (`docs/audits/check_doc_links.py`) identical across Tasks 1,3,4,5,6; the six capabilities + caveats identical between spec table and Task 2 Step 2.
