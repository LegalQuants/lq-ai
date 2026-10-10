# Accessibility: automated first slice and outstanding manual audit

LQ.AI does not claim WCAG 2.1 AA conformance from an axe pass. The automated check only covers the selected machine-checkable A/AA rules, states and synthetic fixtures below. The manual/third-party audit required by [DE-232](../PRD.md#de-232--wcag-21-aa-accessibility-audit-and-ci-gate) remains outstanding.

Source credit: @SaifAlYounan's accessibility inventory and audit plan in [#437](https://github.com/LegalQuants/lq-ai/pull/437), tracked by [#386](https://github.com/LegalQuants/lq-ai/issues/386). The credited replacement's design and measured evidence are in [the implementation plan](../contribute/mini-prds/accessibility-pr-gate.md).

## Automated coverage

The dedicated pull-request job scans the production frontend using mocked API responses at desktop (1440×900) and phone (390×844) widths with explicit light/dark preference variants. Testing those variants does not assert that dark mode is a supported product capability; the inherited styling and supported-theme limitations remain as documented by the application. Every intended state must reach its page-specific ready condition before scanning.

| State                       | Fixture                    |
| --------------------------- | -------------------------- |
| /lq-ai/login                | LQ.AI signed out           |
| /lq-ai                      | Guided dashboard           |
| /lq-ai/matters              | Empty list                 |
| /lq-ai/matters, dialog open | New-matter form, no submit |
| /lq-ai/knowledge            | Empty list                 |
| /lq-ai/skills               | Skill landing/list         |
| /lq-ai/settings/appearance  | Appearance controls        |

A passing run means no new axe violations under the exact measured exception policy. Critical and unknown-impact findings always fail; new serious/moderate/minor findings fail. Exact exceptions cannot expand automatically. Resolved exceptions must be removed. The sanitized report contains target paths/rule IDs/counts and incomplete-rule IDs, without HTML, request bodies or real user data. See the implementation plan for capture and reproduction commands.

Incomplete axe checks remain manual follow-ups. The initial measurement included incomplete `label-content-name-mismatch` and `color-contrast` checks; these are not converted to passes or hidden by the baseline. A green automated check is neither a keyboard audit nor an assistive-technology audit.

## Uncovered and unaudited surfaces

Matter workspace, knowledge detail/ingest states, skill editing, tabular review, playbooks, autonomous surfaces, admin/learn pages and the inherited OpenWebUI shell remain outside this seven-state slice. Filled-data, error/loading and other dialog states also remain uncovered unless explicitly listed. Coverage expansion continues under #386/DE-232; the broader general Cypress on-PR work is #706.

## Manual audit — not executed

Owner: maintainer team; a third-party engagement has not been commissioned or completed by this change.

For each product surface, record keyboard reachability/operation and focus order; screen-reader labels, roles and dynamic announcements; zoom/reflow usability; non-color state cues; tested browser/assistive-technology versions; and the audited release SHA. Include dialog open/close/focus restoration and non-initial states. Publish the resulting report, tracking all critical findings as remediated or documented under DE-232. The PRD's M2 audit and roadmap's per-release wording need an explicit cadence decision, not a silent completion claim.

| Work                                   | State                                                      |
| -------------------------------------- | ---------------------------------------------------------- |
| Seven-state synthetic axe scan         | Locally exercised; GitHub job/enforcement evidence pending |
| Full product route/state matrix        | Partial; gaps above                                        |
| Keyboard / focus audit                 | Not audited                                                |
| Screen-reader audit                    | Not audited                                                |
| Zoom/reflow / color-independence audit | Not audited                                                |
| Third-party engagement / public report | Outstanding                                                |

DE-232 and #386 remain open.
