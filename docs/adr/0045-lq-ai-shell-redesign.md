# ADR 0045 — The LQ.AI shell redesign: colour, themes, type and navigation

**Status:** Proposed (2026-11-09). First draft 25 October 2026, revised 9 November.
**Revised 9 November:** four rulings by Houfu (the grey token's name, the type-class migration, the
light field-edge value, and a darker light governance orange), and the committee's 25 October
palette asks, answered in
[How this answers the committee's 25 October asks](#how-this-answers-the-committees-25-october-asks).
**Proposer:** @houfu. The design rounds of 20–21 October 2026 are recorded as changes C1–C54 and
flags F1–F9 in the interface redesign mini-PRD, a draft that is not yet in the repository (it moves
to `docs/contribute/mini-prds/interface-redesign/` when accepted; link it here then).
**Decision-maker:** the LQ.AI committee (scope and the flags it raises: F1, F3, F9; F2 is noted).
**Affected components:**
- **Web:** `web/src/lib/lq-ai/**` and `web/src/routes/lq-ai/**`; the theme code in `web/src/app.html`
  and `web/src/routes/+layout.svelte`; the five files of the PR #280 stopgap (carried patches,
  ADR 0001).
- **Api and docs:** `api/app/api/users.py` and `api/app/models/user.py` (one preference, one
  migration); `docs/db-schema.md`; `docs/api/backend-openapi.yaml`.
- **Accessibility check:** `web/cypress.a11y.config.ts`, its baseline and its mini-PRD.
- **Other docs:** `docs/openwebui-rebase-runbook.md`; PRD §3.2.1 and DE-394.
**Amends:** [ADR 0043](0043-lq-design-system-primitives.md): its tone values, typography and radii.
Its primitives, its typed scales and its role names stay.
**Resolves:** DE-394 (dark mode for LQ.AI).
**Supersedes:** the top-tab navigation of `docs/superpowers/specs/2026-05-10-m1-frontend-design.md`.
**Refers to:** [ADR 0001](0001-openwebui-fork-pin.md) (branding clause),
[ADR 0009](0009-web-lq-ai-shell-coexistence.md) (the LQ.AI shell boundary),
[ADR 0025](0025-release-versioning-and-pipeline-ordering.md) (upgrade classes).

---

## Context

The LQ.AI shell under `/lq-ai` has one light palette. ADR 0043 (accepted 18 October 2026) named its
tones by role: accent `#1f7a6b`, info `#355a82`, warning `#a16e1f`, danger `#b54848`, and neutral.
It set Inter as the typeface. It left "palette redesign … typography reconciliation …
dark-mode completion" to future work with "its own scope". This ADR is that scope.

Dark mode was deferred, not rejected (DE-394). LQ.AI is held light in three places:
- `app.html`, a script that runs before the page loads;
- `light-theme.ts` (#405);
- the root `+layout.svelte`.

PR #280 also made Open WebUI's "System" theme resolve to light. That was a stopgap: LQ.AI then
inherited Open WebUI's theme, and anyone with a dark OS saw a half-dark LQ.AI. The accessibility
check on every PR asserts that every LQ.AI route renders light.

Navigation is a logo bar and an eleven-tab row with emoji icons (`tabs.ts`), from the M1 design.

Houfu's redesign, drawn as before-and-after pictures of 50 screens, proposes:
- a black-and-white look, with orange kept for governance signals and red for errors;
- a dark theme and the system typeface;
- a left sidebar in place of the header and the tab row;
- a contextual right sidebar.

This ADR records the decisions that are architectural or apply everywhere: colour, themes, type,
shape, and the shell's layout and navigation. The screen-by-screen changes stay in the mini-PRD.
Labs and the admin switches (F5, F6) get an ADR of their own.

## Decision

### 1. Colour: roles keep their names, and colour means governance or error

ADR 0043's role vocabulary stays. One role is added, `governance`, and the values change:

| Role | Used for | Light | Dark |
|---|---|---|---|
| `accent` (ink) | primary buttons, selection, focus, links | `#111114`, with `#FFFFFF` on it | `#FFFFFF`, with `#08080A` on it |
| `governance` (new) | the model tier, privileged matters, Trust & Privacy, and nothing else | `#A34A00` (text and marks) | `#F26B1F` (text and marks) |
| `danger` | errors and destructive confirmations, and nothing else | `#B42318` | `#FDA29B` |
| `info`, `warning` | notes and cautions | neutral ink, with a distinct icon | neutral ink, with a distinct icon |
| `neutral` | everything else | below | below |

- **Info and warning become neutral with icons** (Houfu, 25 October). The names stay in
  `shared/types.ts` so no call site breaks. The tier, which uses the `info` family today
  (`--lq-tier*`), moves to `governance` (C15). Severity and outcomes are monochrome (C28).
- **There is no success role**, as in ADR 0043.
- **`#E8590C`, legalquants.com's orange, is not a token.** It reaches only 2.95:1 on a selected row
  in light, below the 3:1 that icons and dots need. Each theme uses one governance colour, for text
  and marks alike.

Neutral tokens. The existing `--lq-*` names are kept where they exist:

| Token | Used for | Light | Dark |
|---|---|---|---|
| `--lq-canvas` | the page | `#FFFFFF` | `#0E0F12` |
| `--lq-inset` | sidebars | `#F9F9FA` | `#08080A` |
| `--lq-surface-muted` (new) | table header rows, inactive pills | `#F1F1F3` | `#1A1B1F` |
| `--lq-raised` (new) | cards, the message box | `#FFFFFF` | `#141518` |
| `--lq-selected` (new) | the selected row | `#E9E9EC` | `#1E1F23` |
| `--lq-border` | dividers | `#E4E4E7` | `#25262B` |
| `--lq-border-strong` | the edges of fields and controls | `#80828A` | `#6A6B72` |
| `--lq-text` | text | `#111114` | `#F4F4F5` |
| `--lq-text-secondary` | secondary text | `#4F5158` | `#B4B4BB` |
| `--lq-text-tertiary` | captions, placeholders | `#65676F` | `#8E8E96` |

- **Shadows:** light keeps a soft shadow on raised surfaces; dark has none.
- **Derived states:** hover, pressed, disabled and the soft and border shades of each role derive
  from these values with `color-mix()`, as ADR 0043's `lqColorShade()` does today. This ADR sets
  no separate values for them.
- **The name `--lq-surface` stays as it is today.** It is used in 75 places but is not defined on
  main, so those places render transparent over the white canvas. The token-hygiene groundwork
  (PR #797) defines it as an alias of `--lq-canvas`, so they render white by name. The grey
  the pictures call "surface" therefore takes the new name `--lq-surface-muted`, so adopting this
  ADR changes no existing surface by accident (Houfu, 9 November).
- **Retired:** `--lq-inset-secure` folds into `--lq-surface-muted`. `--lq-tier*` and `--lq-warn*`
  alias to the new roles while components migrate, then go.

**Two values differ from the current pictures, and one was corrected earlier.**
- **Governance orange on white** was `#C2410C` (C3, after legalquants.com). It is now `#A34A00`, for
  two reasons. On a selected row `#C2410C` reaches 4.27:1, below AA; and the interim `#B93C0A`
  that cured that sat only 12 colour-difference units from the error red (CIELAB ΔE76), and the
  committee found the pair too close on 25 October. A difference of about 20 or more is clearly
  visible side by side; that is a rule of thumb, not a standard. `#A34A00` is amber-leaning (HSL
  hue 27°, against the red's 4°), 24 units from the red, and reaches 4.9:1 on a selected row.
  Houfu chose it on 9 November.
- **Tertiary text** was `#686A72` in the first pictures. It became `#65676F` on 25 October
  (`#686A72` reaches 4.45:1 on a selected row), and the current pictures already carry it.
- **Field and control edges (`--lq-border-strong`)** were `#8A8C94`, which reaches 3.35:1 on the
  canvas but 2.97:1 on a muted surface and 2.77:1 on a selected row, below the 3:1 that field edges
  need. It is now `#80828A` (Houfu, 9 November), which reaches 3.16:1 or more on all four light
  surfaces.

The alternative was to keep the pictures' values and never put tertiary text, governance text or a
field edge on a selected or muted surface. That rule is easy to break and hard to check. Houfu
chose the new values on 25 October and 9 November 2026. The pictures were last redrawn with the
25 October values (`#B93C0A` and `#65676F`); the orange `#A34A00` and the edge grey `#80828A` have
not been drawn yet, so the pictures lag the ADR on those two until they are re-rendered.

**Contrast** (WCAG 2.x ratio; AA needs 4.5:1 for body text and 3:1 for icons and field edges).

| Light | canvas | inset | surface-muted | raised | selected |
|---|---|---|---|---|---|
| text `#111114` | 18.8 | 17.9 | 16.7 | 18.8 | 15.6 |
| secondary `#4F5158` | 7.9 | 7.5 | 7.0 | 7.9 | 6.5 |
| tertiary `#65676F` | 5.6 | 5.4 | 5.0 | 5.6 | 4.7 |
| governance `#A34A00` | 5.9 | 5.6 | 5.3 | 5.9 | 4.9 |
| danger `#B42318` | 6.6 | 6.2 | 5.8 | 6.6 | 5.4 |

| Dark | canvas | inset | surface-muted | raised | selected |
|---|---|---|---|---|---|
| text `#F4F4F5` | 17.4 | 18.2 | 15.7 | 16.6 | 15.0 |
| secondary `#B4B4BB` | 9.3 | 9.7 | 8.3 | 8.9 | 8.0 |
| tertiary `#8E8E96` | 5.9 | 6.2 | 5.3 | 5.6 | 5.1 |
| governance `#F26B1F` | 6.3 | 6.6 | 5.7 | 6.0 | 5.4 |
| danger `#FDA29B` | 9.9 | 10.3 | 8.9 | 9.4 | 8.5 |

Field and control edges (`--lq-border-strong`) in light reach 3.83:1 on the canvas, 3.64:1 on the
inset, 3.40:1 on the muted surface and 3.16:1 on a selected row; in dark they reach 3.6:1 on the
canvas.
Dividers (`--lq-border`) are decorative and need no ratio. For comparison, today's tertiary text,
`#9ca3af`, reaches 2.5:1 on white.

**Focus** is a 2 px ink outline with a 2 px offset, in both themes, on every focusable element. Ink
reaches over 18:1 on the canvas in either theme.

### 2. Themes: Light, Dark and Match system (resolves DE-394)

- **Choices.** People choose Light, Dark or Match system in Account settings › Appearance (C30).
  The theme toggle at the foot of the left sidebar switches between them.
- **Default: Match system** (Houfu, 25 October), for new users and for anyone who has never
  chosen. Match system follows the device's `prefers-color-scheme` and changes with it.
- **Saved to the account** (Houfu, 25 October). It is a new preference, `appearance_theme`
  (`light`, `dark` or `system`; default `system`), on `/api/v1/users/me/preferences`. Like the
  other preferences, it is a column on `users`, with one migration. The browser keeps a copy
  (`localStorage['lq-ai.theme']`) so the page paints in the right theme before sign-in has loaded.
  The account's value wins once it arrives.
- **Applying it.** On `/lq-ai` routes, the script in `app.html` and the root layout's
  route-change handler set:
  - `data-lq-theme` on `<html>`,
  - `color-scheme`, so native controls and scrollbars follow,
  - the matching `light` or `dark` class, for any carried Open WebUI component inside the shell,
  - the browser theme colour: `#FFFFFF` in light, `#08080A` in dark.

  `light-theme.ts` becomes a theme module that resolves "system" and listens for changes.
- **Tokens only.** The `--lq-*` tokens are defined for both themes under `data-lq-theme`. LQ.AI's
  own components use tokens and never Tailwind `dark:` variants. Thirteen LQ.AI files carried them on
  main; the Tailwind-class groundwork (PR #798) leaves two components and the source check's own test. A source check in CI (PR #799, rule 4)
  already fails on any new `dark:` under `web/src/lib/lq-ai` or `web/src/routes/lq-ai`, and counts
  the remaining ones down to zero as the dark theme replaces them (DE-394 (e)).
- **Dark ships whole.** Dark and Match system cannot be chosen until every LQ.AI surface and modal
  is token-driven and the accessibility check passes in both themes. Until then, Appearance offers
  Light only and the default resolves to light.
- **Open WebUI keeps its own theme** (Houfu, 25 October). The Open WebUI shell at `/` keeps its
  theme menu, including Dark and OLED Dark (DE-394 (d)), untouched (ADR 0009). LQ.AI no longer reads
  Open WebUI's theme, so #280's stopgap is no longer needed. It is reverted in its five upstream
  files (`app.html`, `app.css`, `Flow.svelte`, `General.svelte`, `+layout.svelte`), and its
  carried-patch entry leaves `docs/openwebui-rebase-runbook.md` (DE-394 (c)). This reduces the fork's
  divergence. Verification: `/` renders as upstream does, in each of its themes.

### 3. The accessibility check follows the theme

The check's mini-PRD requires "its own maintainer-reviewed decision" to change what it scans. Once
Accepted, this ADR is that decision, and only for the following changes:
- **The matrix keeps its 28 variants:** 7 route states × desktop and phone × a saved input of
  light or dark. Each variant pins its theme input, so no variant follows the CI runner's OS
  setting.
- **The last part of each variant's name now names the rendered theme.** Each variant asserts that
  theme: the root class, `data-lq-theme`, `color-scheme`, native controls and the theme colour.
- **Dark variants are measured once,** in the PR that ships dark. A finding in a dark variant that
  its light variant of the same state does not have is fixed, never added to the baseline.
  Exceptions keep shrinking, as the check requires.
- **The check's mini-PRD and `cypress.a11y.config.ts` change in that same PR.**

### 4. Typography: the system typeface and one type scale (resolves F3, if agreed)

- **Typeface:** `-apple-system, "SF Pro Text", "Segoe UI", sans-serif` (C2): SF on Apple
  devices, Segoe UI on Windows, the platform's sans-serif elsewhere. Apple's licence does not allow
  serving SF as a web font, so no web font is shipped. `@fontsource-variable/inter` is removed, a
  dependency dropped.
- **Code:** `ui-monospace, "SF Mono", Menlo, Consolas, monospace`.
- **One scale.** `LqText` and `LqTitle` carry it. The older typography classes (`.lq-text-body`,
  `-caption`, `-label` and four more; about 380 uses in 65 files today) are not aliased: they are migrated to `LqText` and `LqTitle` and deleted in the same body of work
  (Houfu, 9 November), which reconciles the two scales ADR 0043 recorded. The primitives' sizes
  today (12, 13, 14, 16 and 18 px for text; 34 to 14 px for titles) do not cover the scale below,
  so extending the primitives to it comes first in that work. Its values come from the pictures:

| Size | Used for |
|---|---|
| 11 px | the attribution line, badge counts |
| 12 px | captions, column headings, sidebar group labels |
| 12.5 px | meta lines (dates, counts) |
| 13 px | secondary text, table cells |
| 13.5 px | navigation rows, buttons, pills |
| 14 px | body text |
| 14.5 px | page and section header titles |
| 16 px | text in the message box |
| 20 px | page titles |
| 24 px | large headings (Learn articles) |
| 32 px | the Home greeting |

- **Weights** are 400, 500, 600 and 700. Other sizes in the pictures (11.5, 15, 15.5, 17, 19 and
  30 px) are one-offs and snap to the nearest step.

### 5. Shape and icons

- **Buttons** are pills or circles (C4).
- **Radii:** 10 px for small tiles, 12 px for inputs and menus, 16 px for cards, 18 px for lists
  and tables, 24 px for the message box. The pill radius stays. This replaces today's
  4, 6 and 8 px radii in `practice.css`.
- **Icons** are Tabler line icons only (C16). The remaining emoji in the LQ.AI shell (the tab row,
  `ProvenancePill`, `TrustPill`) go, which completes ADR 0043's follow-up.

### 6. The shell's layout and navigation

- **No app header and no tab row** (C5). `TopTabBar`, `tabs.ts`, the inline top bar and
  `AmbientTrustChrome` are removed.
- **Three columns** (C6):
  - a 264 px left sidebar for navigation;
  - the main column, with a 52 px header over its own column only (C14);
  - a 340 px right sidebar that shows details of whatever is open or selected, closes, and is
    absent when there is nothing to show (C19).
- **The left sidebar** (C7, C10, C11, C31):
  - at the top: New;
  - then Home, Tabular, Labs and Customise;
  - recent matters, each with its chats, then other chats, with "All matters" and "All chats";
  - at the foot: Learn, Trust & Privacy, Admin, and the account with the theme toggle.

  Role and opt-in visibility work as the tab row's do today.
- **The notification bell** (DE-324) appears twice, as Houfu decided on 24 October: an icon with an
  unread count beside the sidebar toggle, and a "Notifications" row. Both appear only when
  Automations is on, and both open the list in the right sidebar. Counts are ink, never orange or
  red.
- **Sections with their own navigation.** Admin (C54) and each lab (C38) replace the left sidebar
  with their own navigation, which starts with "Back to LQ.AI". Account settings keeps the main
  sidebar.
- **Narrow screens.** The left sidebar collapses behind a menu button and the right sidebar opens
  as a sheet. Every screen stays usable at the accessibility check's phone viewport.
- **The attribution line.** The foot of the left sidebar carries the Open WebUI attribution that
  ADR 0001 requires. Shortening it to "LQ.AI v<version> · Built on Open WebUI" is F2: a committee
  question under ADR 0001, which this ADR does not decide. Until the committee rules, the sidebar
  shows the full wording of today's `DualBrandingFooter`.
- **Boundary.** All of this lives under `/lq-ai` (ADR 0009). The only upstream files touched are
  the existing theme patches in `app.html` and the root layout, and the #280 revert.

## Not decided here

- Labs, per-lab switches and admin offering (F5, F6): a separate ADR.
- The playbook notice (F4), Enhance (F7) and Saved skill work (F8): committee rulings, and
  amendments to the PRD and the docs.
- OKLCH colour authoring (an ADR 0043 follow-up): not adopted. Values stay in hex.
- The Today view ([ADR 0044](0044-workspace-events-today-email.md), DE-208): not built here. Labs
  lists it only if it is on the roadmap when Labs ships.
- The screen-by-screen changes: the mini-PRD.

## Consequences

**Positive:**
- Colour carries meaning again: orange for governance, red for errors.
- Dark mode exists and covers all of LQ.AI, with a guard against regressions.
- One type scale replaces two, and a dependency (Inter) is dropped.
- The fork carries one patch fewer (#280).
- Every text colour meets AA on every surface in both themes; today's tertiary grey does not.

**Costs:**
- **Every LQ.AI component is re-tokenised.** `--lq-accent` appears in 116 files on main, and its
  meaning changes from teal to ink. `--lq-tier` (11 files) moves to governance. `--lq-warn` (35 files on main)
  moves to neutral with icons. `dark:` utilities go from 13 files on main (two components remain after PR #798).
- **The text classes are migrated, not aliased.** The 65 files that use the typography classes
  are rewritten to `LqText` and `LqTitle`, so the change is a large review. The `--lq-text-*`
  colour tokens are not affected. It is separate from the colour flip
  so each can be read on its own.
- One preference field and migration.
- A change to the accessibility check.
- The nightly Cypress specs that check the tab row are rewritten.

**What users see change:**
- **The look changes for everyone** at the release that ships it.
- **People whose device is set to dark** get the dark theme at the release that enables Dark and
  Match system, without having chosen it.

  Both belong in that release's notes, under its upgrade class (ADR 0025).

**Verification:**
- The accessibility check passes in both themes with no new findings.
- Render tests cover the primitives in both themes.
- The `dark:` check is in CI.
- `/` renders as upstream after the #280 revert.
- Focus is visible on every control in both themes. A manual keyboard pass checks this, since axe
  does not.

**Reversibility:**
- The tokens are central, so the palette can be changed in one place.
- The theme preference is an added column, and it can be ignored.
- Bringing the tab row back means restoring the removed components.

## Alternatives considered

- **Keep ADR 0043's teal palette and add dark values for it.** Teal everywhere competes with
  governance signals, and the redesign's point is that colour means governance or error.
- **Keep Inter, served from the app.** The same type on every platform. Houfu chose the system
  typeface (C2): it matches legalquants.com, and SF cannot be served. F3 asks the committee.
- **Default to Light** (today's look) until people choose. Not chosen: DE-394 expects System to
  follow the OS once coverage is complete.
- **Save the theme in the browser only** (no api change). Not chosen: the choice would not follow
  people across devices.
- **Keep amber for warnings.** Not chosen: a third hue weakens "orange means governance".
- **Info in slate, warning neutral.** Gives info its own hue, which is the committee's literal 25
  October ask. Not chosen: it adds a colour to a palette whose point is two colours with one job
  each. The committee may prefer it.
- **Keep `#B93C0A` for governance.** Passes AA, but 12 ΔE76 units from the red, which the committee
  already found too close.
- **Move the red instead** (`#B3183A`, 32 units from `#B93C0A`). Strongest separation, but errors
  start to read as rose and every error and destructive control changes.
- **Rename today's `--lq-surface` uses to `--lq-raised`**, keeping the grey's name. Not chosen:
  75 call sites change name for no visible gain.
- **Keep the field-edge grey `#8A8C94` and forbid it on muted and selected surfaces.** Not chosen:
  a usage rule is easy to break and hard to check, the same reason as for tertiary text.
- **Alias `.lq-text-*` to the new scale, retire later.** Not chosen: two vocabularies would live in
  the code for a release. Houfu ruled for one migration.
- **One theme setting for LQ.AI and Open WebUI.** Not chosen: it would change upstream theme
  handling as a carried patch, against ADR 0009's boundary.

## How this answers the committee's 25 October asks

The committee asked for two palette changes and one exploration.
- **Separate governance orange from the error red.** In light the two were 12 ΔE76 units apart. The
  governance orange moves to `#A34A00`, 24 units from the red, and each role keeps an exclusive
  job and its own icon. In dark they are 50 units apart already.
- **Express the info colour.** Info is neutral ink with its own icon, not a hue (§1). A hue would
  weaken "orange means governance". The committee can still choose a slate info colour instead; the
  alternative is listed under Alternatives considered.
- **A more welcoming or distinctive feel.** Not answered by this ADR: it fixes the neutral base,
  and any distinctive feature is a separate proposal.

## Committee questions this ADR answers if adopted

- **F1:** the palette departs from ADR 0043.
- **F3:** the system typeface.
- **F9:** dark mode, against DE-394 and the accessibility check's light-only assertion.

F2, the attribution line, stays open under ADR 0001.
