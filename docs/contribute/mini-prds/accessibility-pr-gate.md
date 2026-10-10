# DE-232 — deterministic accessibility checks on pull requests

The three implementation choices were ratified by maintainer @houfu on 2026-10-10: a frontend-only Cypress job on every PR, exact pre-existing noncritical exceptions, and the original seven route states as an explicitly partial first slice. These choices implement [DE-232](../../PRD.md#de-232--wcag-21-aa-accessibility-audit-and-ci-gate), without claiming its manual audit is complete.

Credit: reimplementation of the accessibility work proposed by **@SaifAlYounan in [#437](https://github.com/LegalQuants/lq-ai/pull/437)**, tracked by [#386](https://github.com/LegalQuants/lq-ai/issues/386). The route-state inventory, reporting and separation of automated checks from conformance work are retained. This replacement changes execution from nightly-only to per-PR, replaces blanket route/rule exemptions with exact fingerprints, and rejects new findings at every severity. #432 supplied the existing nightly Cypress infrastructure.

## Execution and containment

`accessibility.yml` runs `npm ci`, builds the production frontend, then runs a dedicated Cypress configuration against Vite preview on loopback. It starts no API, database, compose stack or model. The scanner uses fixed synthetic responses, including a stubbed upstream timezone-update call; unexpected API requests fail. Dedicated support excludes upstream signup hooks. No deployment/provider secrets are supplied; permissions are `contents: read`, actions are pinned, checkout credentials are not persisted, and the trigger is `pull_request`, never `pull_request_target`.

The frontend build needs `NODE_OPTIONS=--max-old-space-size=6144` with the current upstream bundle. The workflow has a 25-minute bound; local production-build success does not establish Linux-runner duration or flake rate.

The check appears on every PR, avoiding path-filtered required checks that remain pending. Its name is `Accessibility (axe A/AA regressions)`. A maintainer must separately add it to the branch ruleset after its CI result is established. Until then, it reports failure but is not an enforced merge gate. The broader deterministic Cypress work in #706 remains separate.

## Exact exception policy

Each fingerprint retains state, viewport/theme, axe rule, the complete target path (including frame/shadow paths), impact, and a capped count. A new element cannot reuse another element's exception; losing one old violation cannot offset a new one. Critical and unknown-impact findings always fail. New serious, moderate and minor findings fail. Malformed/duplicate entries and incomplete/duplicate state inventories fail.

The initial measurement comes from main at `3ecf284177b97ff6acdcaff5eda57bee0bf86a98` with axe-core 4.14.0: **230 exact serious fingerprints across 28 state variants**. No critical findings were observed. This replaces the July route/rule observations rather than treating them as current evidence. Metadata records owner, reason, source SHA and capture date.

Subsequent exceptions may only shrink relative to the PR base. Fixed entries are flagged as stale and must be removed or have their count reduced. The job rejects new exceptions/count growth and scanner/matrix changes. An intentional policy change or scanner upgrade needs its own maintainer-reviewed decision and update to these controls, not automatic regeneration to green.

## Reproduce

From `web/`:

```sh
npm ci
NODE_OPTIONS=--max-old-space-size=6144 npm run build
npm run cy:a11y
npm run cy:a11y:proof
npx tsc --project tsconfig.a11y.json
npm run test:frontend -- --run
```

`cy:a11y:proof` injects a new unnamed button on the login page and succeeds only when that specific finding makes the integrated scanner fail. It must not treat an arbitrary Cypress failure as proof. The normal gate and negative-proof reports are separate.

For an approved local measurement on a clean current-main product tree, `A11Y_BASELINE_SOURCE_SHA=<current-main-sha> npm run cy:a11y:baseline` writes `cypress/results/a11y-baseline.candidate.json`. Capture is refused in CI. Review the candidate and source identity before replacing `cypress/fixtures/a11y-baseline.json`; do not baseline defects introduced by the implementation under review. After initial adoption, automatic additions will be rejected.

Dependency justification: axe-core supplies the established WCAG rule engine, which we cannot reasonably recreate; cypress-axe injects that engine into the existing Cypress environment. Both are exact dev dependency pins, leaving production application code unchanged. Their upstream licenses are MPL-2.0 and MIT respectively; no third-party source is vendored.

## Honest acceptance state

Local evidence: production build passed with the bounded heap; standalone TypeScript and ESLint checks passed; 25 comparison tests passed; 28 browser variants passed; an injected critical unnamed-button finding failed the integrated job as intended. The full frontend suite passed: 888 tests across 90 files.

PR #712 reached its first GitHub run: the production build passed, but the initial baseline guard stopped the scanner because main had gained shared-navigation changes after the measurement. A second GitHub run stopped at the same provenance boundary after frontend feature #710 merged into main. The baseline was remeasured on that refreshed base with all 230 fingerprints unchanged; the guard now tolerates only unrelated base commits with identical production frontend inputs and adopted ancestry. Required-check status has not been changed. Fresh Linux/fork CI evidence remains a prerequisite to claiming that enforcement is active. GitHub-verified cryptographic signatures and DCO trailers are separate requirements for the replacement commits.

## Baseline source provenance

The first baseline must name a commit in the PR base history. Its production frontend inputs must match the current base: source/assets/config, frontend/build dependency lock entries (excluding only the standalone axe additions), and production build commands. Docs/backend/unit-test-only commits do not invalidate identical UI inputs. The checks resolve paths from the repository root even when Cypress runs in web/. Local capture checks the selected source against the product tree being measured. A changed component, asset, production dependency, build command or scanner still requires deliberate fresh evidence; this is not an automatic baseline expansion.
