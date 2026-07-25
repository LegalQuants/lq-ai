# Accessibility: WCAG 2.1 AA audit plan and automated gate (DE-232)

> **Drafting note:** AI-drafted; reviewed and owned by the maintainer team.
>
> **Honest-state summary:** LQ.AI is **not** WCAG 2.1 AA compliant and this
> document does not claim otherwise. What exists today is (a) an automated
> CI gate over the *automatable subset* of WCAG 2.1 A/AA rules on LQ.AI-owned
> routes, with a checked-in baseline of pre-existing violations, and (b) the
> manual-audit plan below, which is **not yet executed**.

---

## 1. What the automated gate is — and is not

The Cypress spec [`web/cypress/e2e/a11y.cy.ts`](../../web/cypress/e2e/a11y.cy.ts)
runs [axe-core](https://github.com/dequelabs/axe-core) (via `cypress-axe`)
against a set of LQ.AI-owned routes with
`runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']`.

axe-core automates roughly **30–50% of WCAG 2.1 AA success criteria** — the
machine-checkable ones (contrast ratios, missing labels/alt text, ARIA misuse,
document structure). It cannot verify keyboard operability, focus order,
screen-reader comprehensibility, meaningful sequence, or content that relies
on color alone in ways that need human judgment.

Therefore:

- A green a11y gate means **"no regressions on the automatable-rule subset"**.
- It is **never** evidence of WCAG 2.1 AA conformance. Conformance requires
  the manual audit in §5, which has not been performed.
- Per the project's conservative-posture rule, no LQ.AI documentation or
  marketing may cite this gate as a compliance claim.

## 2. Scope: LQ.AI-owned routes only

The gate audits LQ.AI-owned surfaces (`/lq-ai/...`), not the inherited
OpenWebUI shell. The upstream fork has never been audited and would fail
wholesale; gating on it would bury LQ.AI regressions in upstream noise. This
mirrors the `check:lq-ai` precedent (`tsconfig.lq-ai.json` scopes svelte-check
the same way).

Routes/states audited today (each state audited separately — including
non-initial states such as open modals, per the "audit per state, not per
route" practice):

| Audited state | Notes |
|---|---|
| `/lq-ai/login` | unauthenticated |
| `/lq-ai` | guided dashboard |
| `/lq-ai/matters` | matters list |
| `/lq-ai/matters [new-matter modal]` | dialog-open state |
| `/lq-ai/knowledge` | knowledge-base list |
| `/lq-ai/skills` | skill-creator landing |
| `/lq-ai/settings/appearance` | settings surface |

The spec is fully `cy.intercept`-mocked (auth + every backend list the pages
call), so it is deterministic, read-only against any stack, and rides the
DETERMINISTIC Cypress track in CI (`web/cypress.config.ts`, run nightly by
`.github/workflows/e2e.yml`). Adding a route = adding an `it()` block with the
mock pattern already in the spec.

Known coverage gaps of the current route set: matter workspace
(`/lq-ai/matters/[id]`), tabular review, playbooks, autonomous surfaces,
admin pages, learn pages. These are tracked as follow-up route additions;
the upstream OpenWebUI chat shell stays out of automated scope and is a
manual-audit item only.

## 3. Gate semantics — the severity ratchet

Implemented in [`web/cypress/support/a11y-gate.ts`](../../web/cypress/support/a11y-gate.ts)
(pure logic; unit-tested in
`web/src/lib/lq-ai/__tests__/a11y-gate.test.ts`, which proves with synthetic
violations that a new critical violation fails the gate):

| axe impact | Gate behavior |
|---|---|
| `critical` | **FAIL, always.** No baseline escape — critical entries may not be added to the baseline. |
| `serious` | **FAIL unless** the `(route, rule)` pair is in the checked-in baseline `web/cypress/a11y-baseline.json`. |
| `moderate` / `minor` | Logged to the report, never fail. |

Every run writes the full inventory (all impacts, all audited states) to
`web/cypress/results/a11y-report.json` (gitignored locally; uploaded as the
`a11y-report` artifact by `e2e.yml` on every run, pass or fail). This is the
"log-all" phase of the ratchet: the violations that don't gate are still
visible on every run.

This is the incremental-adoption pattern (log-all → block critical → block
serious) converged on by GOV.UK-style practice: automation gates regressions;
humans do conformance.

## 4. The baseline: contents and how to shrink it

`web/cypress/a11y-baseline.json` holds the **pre-existing serious violations**
recorded when the gate was introduced (2026-07-25, axe-core 4.12.1, run
against the local dev stack). Matching is by `(route, rule)`; node counts in
the file are informational.

Rules of the baseline:

1. **It may only shrink.** Fixing a violation means deleting its entry in the
   same PR. New entries require maintainer sign-off and a dated `note`
   explaining why the violation is being accepted rather than fixed.
2. **Critical violations are never baselined.** (None existed at
   introduction; the gate enforces this by ignoring the baseline for
   critical.)
3. Regeneration process, when an accepted-violation entry is intentionally
   added: run the spec, copy the failing `(route, rule)` rows from
   `cypress/results/a11y-report.json` into the baseline with a dated note,
   re-run to green.

### Baseline contents at introduction (honest inventory)

15 serious entries across the 7 audited states — no critical violations
anywhere:

| Rule | Where | Substance |
|---|---|---|
| `color-contrast` (serious) | all 7 states (5–14 nodes each) | Low-contrast text throughout the shared shell and design-system text classes: footer spans, `.lq-text-label` form labels (login), `.lq-text-caption`, `.strikethrough` (dashboard), `.lq-kbd` keyboard hint + `.nmm-optional` label (new-matter modal), `.underline` links. Likely a small number of design-token fixes (`--lq-*` colors) clearing many entries at once. |
| `list` (serious) | all 7 states (1 node each) | A shared-shell `<ol>` contains non-`<li>` children — one component fix clears 7 entries. |
| `link-in-text-block` (serious) | `/lq-ai` (1 node) | The Chats link inside dashboard body text is distinguished by color alone. |

Logged but not gating: `meta-viewport` (moderate, all states — the app-shell
viewport meta disables user scaling, which is also a manual-audit zoom item).

The concentration in `color-contrast` + the single shared `list` structure
means the realistic path to an empty baseline is 2–3 targeted fixes in the
design tokens and the shared shell, not 15 separate fixes.

## 5. Manual audit plan (the actual "AA audit" half — NOT yet performed)

Owner: **maintainer team**. Automated tooling cannot substitute for this;
DE-232 is not complete-complete until this table is filled in. Each surface
gets four checks:

- **Keyboard navigation** — every interactive control reachable and operable
  by keyboard alone; visible focus indicator; no traps; modal focus is
  contained and returns on close; logical tab order.
- **Screen reader** — VoiceOver (macOS/Safari) + NVDA (Windows/Firefox) pass:
  landmarks, headings, control names/roles/values announced sensibly; dynamic
  updates (toasts, streaming responses) announced via live regions.
- **Zoom / reflow** — usable at 200% zoom and 320px-equivalent reflow
  (WCAG 1.4.4 / 1.4.10); no two-dimensional scrolling for text content; note
  the current viewport meta blocks pinch-zoom on mobile (see §4).
- **Color independence** — all state distinctions (errors, trust pills,
  citation states, diff/redline colors) carry a non-color cue.

| Surface | Keyboard | Screen reader | Zoom/reflow | Color independence | Status |
|---|---|---|---|---|---|
| Login + change-password | — | — | — | — | not audited |
| Guided dashboard | — | — | — | — | not audited |
| Matters list + workspace (chat, citations) | — | — | — | — | not audited |
| Knowledge (list + detail, ingest states) | — | — | — | — | not audited |
| Skills (list, new, edit) | — | — | — | — | not audited |
| Tabular review | — | — | — | — | not audited |
| Playbooks + executions | — | — | — | — | not audited |
| Autonomous surfaces | — | — | — | — | not audited |
| Settings + admin pages | — | — | — | — | not audited |
| Upstream OpenWebUI chat shell | — | — | — | — | not audited (upstream; largest unknown) |

Findings from the manual audit land as issues labeled `a11y`; fixes to
automatable findings must also shrink the baseline (§4).

## 6. Running locally

```bash
docker compose up -d          # stack at localhost:3000
cd web
npx cypress run --spec cypress/e2e/a11y.cy.ts
# full inventory: cypress/results/a11y-report.json
```

The spec needs no seeded admin and performs no writes (fully mocked), so it
is safe against a development stack with real data.
