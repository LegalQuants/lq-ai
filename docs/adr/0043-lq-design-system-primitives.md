# ADR 0043 — `lq` design-system primitives for the LQ.AI shell

**Status:** Accepted (2026-10-18)
**Decision-maker for the maintainer revision:** @houfu (2026-10-17)
**Original proposal and reference implementation:** Simon Booth (@sgbooth), PR #282
**Approval record:** The LQ.AI weekly committee call on 2026-10-18 approved adoption of ADR 0043 with an “adopt first, refine later” approach. No objection was recorded; this is not a claim of a counted formal vote or a completed code review. The October 17 maintainer revision defines the bounded scope below. [Joel's October 20 meeting follow-up](https://legalquants.slack.com/archives/C0BDS8RR7JM/p1792441109058609) records the adoption and action O18-04 to update the canonical decision records. The public minutes remain a draft under review until October 26; their publication is separate from this approval record.
**Affected components:** `web/src/lib/lq-ai/**`
**Supersedes:** none. **Refers to:** [ADR 0009](0009-web-lq-ai-shell-coexistence.md), [ADR 0001](0001-openwebui-fork-pin.md), [CONTRIBUTING.md](../../CONTRIBUTING.md), [CLAUDE.md](../../CLAUDE.md).

---

## Context

CONTRIBUTING.md and CLAUDE.md have both carried this line since M1:

> Component conventions: match the OpenWebUI conventions for shared components; use the project's design system primitives rather than ad-hoc Tailwind.

Until now, "the project's design system primitives" pointed at nothing concrete for `/lq-ai/*`. Every component under `lib/lq-ai/components/**` independently decided its own spacing, color, size, and interaction logic in raw Tailwind utility classes — TrustPill's tone-mapping, the old `.lq-btn-secondary`/`.lq-btn-send`/`.lq-btn-abort` classes hand-rolled inside `ChatPanel.svelte`, ad hoc `flex items-center gap-2` layout soup repeated across a dozen files, a tier→description mapping independently duplicated (with drifting wording) across `TierBadge.svelte`, `TierDetailsPanel.svelte`, and `MessageBubble.svelte`. Nothing was wrong file-by-file; the absence of a shared vocabulary meant every file was its own small design decision.

This ADR retains the existing Svelte/SvelteKit and Tailwind implementation context. The shared primitives provide a reusable API within that stack; they do not replace Tailwind or decide whether another application framework would be preferable. Any wider framework or OpenWebUI-fork decision is separate work.

## Decision

The maintainer's decision is to finish the primitive layer already proposed in this PR as a bounded reusable contract, demonstrated by the reference components already included. This does not require migration of the remaining shell or resolution of every existing visual inconsistency.

Adopt a small primitive layer at `web/src/lib/lq-ai/components/shared/`, modeled on Mantine's component API shape (`variant`/`size`/`tone`/`shadow` props, `Component.Part` compound namespacing) as a naming and ergonomics reference only — not an added runtime dependency. Every primitive is plain Svelte + CSS custom properties, plus two existing pieces of `web/`'s dependency tree used rather than reimplemented (`bits-ui`'s headless `Switch`/`Portal`; see below). One genuinely new dependency was added alongside this effort — `@tabler/icons-svelte`, justified in "Typography and iconography" below — consistent with CLAUDE.md's "don't add libraries without justification" (the justification being the actual reason, not an exemption from it).

**Token layer** (`shared/types.ts`): every option list is a `const` array with a type derived via `(typeof X)[number]`, never a hand-typed string-literal union — one file to extend, full autocomplete everywhere. This is a deliberate, load-bearing design goal, not an incidental side effect: every prop on every primitive is typed specifically so the editor's IntelliSense surfaces the full set of valid values at the call site — a contributor should never need to open `types.ts` or another component's source to discover what `tone`/`variant`/`gap`/etc. accept. Current scales: `LqVariant`, `LqTone`, `LqSize`, `LqGap`, `LqShadow`, `LqWeight`, `LqTextSize`, `LqTextTone`, `LqJustify`, `LqAlign`, and the lower-level `LqColor`+`LqShade` pair (`lqColorShade()`, computed via CSS `color-mix()` off five base `--lq-*` vars rather than a hand-authored shade table).

### Tone vocabulary

Public tone options describe roles rather than the current hue. Apply this naming change to the primitive types and their reference consumers together; preserve the current CSS values and visual assignments.

| Existing option | Public role | Existing CSS family | Foreground / soft / border |
| --- | --- | --- | --- |
| `sage` | `accent` | `--lq-accent*` | `#1f7a6b` / `#e8f4ec` / `#c5e6d1` |
| `slate` | `info` | `--lq-tier*` | `#355a82` / `#e8eff7` / `#d4e2f1` |
| `amber` | `warning` | `--lq-warn*` | `#a16e1f` / `#fdf3e2` / `#ead9c5` |
| `red` | `danger` | `--lq-error*` | `#b54848` / `#fbeaea` / `#f1d2d2` |
| `neutral` | `neutral` | Existing neutral text/surface/border treatment | Unchanged |

The role vocabulary is `accent`, `info`, `warning`, `danger`, `neutral`. Text emphasis (`primary`, `secondary`, `tertiary`) remains distinct from tone. Internal CSS variable names can stay as they are; this ADR does not require a token-file rename. Any lower-level helper exposing the same public tone options stays consistent with this vocabulary.

There is no new `success` role in this contribution. In particular, this rename does not reclassify provider, tier, completion or citation states across the application. Those meanings can be considered separately.

**Primitives:**
- `LqButton` — `variant` × `tone` × `size`.
- `LqGroup` / `LqStack` — Mantine `Group`/`Stack`-style flex layout (`gap`, `justify`, `align`, `maxWidth`), replacing repeated Tailwind flex-utility soup.
- `LqText` / `LqTitle` — semantic text (`as`/`order` pick the rendered tag) instead of styled `<div>`s.
- `LqAlert` — status banner; fills its container width by default (no `w-full`/`max-w-full` escape hatch needed).
- `LqPill` — tag/chip with an optional removable-✕ affordance.
- `LqSwitch` — styled wrapper around `bits-ui`'s headless `Switch` (behavior/a11y from bits-ui, tone-based look from us).
- `LqCard` — static container (padding/shadow).
- `LqHoverCard` — compound component (`LqHoverCard` / `.Target` / `.Dropdown`, assembled via direct property assignment on the Root export — the same technique this codebase's own `bits-ui` usage already relies on for `Button.Root`). Portaled through `bits-ui`'s `Portal` to `document.body` so it isn't clipped by a scrolling ancestor's `overflow: hidden`/`auto`.

**Governing rules for new primitives:**
1. Reuse an existing scale from `types.ts` before adding a new one; only add a new scale when no existing one fits (e.g. `LqTextSize` was added separately from `LqSize` because Button's `sm/md/lg` has no `xs`/`xl` CSS defined).
2. Spacing between sibling elements is the parent `LqGroup`/`LqStack`'s `gap` — never a self-margin (`mt-*`/`mb-*`) on the child. A component needing to visually span its row (`w-full`) is a legitimate exception; a component reaching for a margin utility to create breathing room from its neighbor is not.
3. A component that should always fill its container (e.g. `LqAlert`) declares `width: 100%` in its own default CSS — the caller should never need to say so.
4. Any primitive taking arbitrary attributes (`data-testid`, `aria-*`) forwards them to its documented native element or headless root; any primitive accepting an additional `class` combines it with its own classes. Caller classes must not disappear or replace the primitive's base classes. In the submitted legacy Svelte style, use `$$restProps` for attributes and the explicit `let klass = ''; export { klass as class };` pattern for class forwarding, rather than relying on spread-vs-static-class merging. `LqButton`, `LqPill` and `LqSwitch` follow the same declared contract as the other primitives.
5. Prefer a primitive's typed props over its `class` escape hatch. `class` exists only for concerns with no corresponding prop and no sane default — a one-off test hook, a genuinely unsupported CSS need. It is not a shortcut around adding a real option to a scale in `types.ts` when the same value will recur (if a second call site wants the same "unsupported" thing, that's the signal to promote it to a prop, not to keep copy-pasting the class string). Reaching for `class` where a prop already exists (e.g. a raw `flex` utility class instead of `LqGroup`, a color utility instead of `tone`) defeats the IntelliSense goal described in the token-layer paragraph above — the whole point is that the typed prop is discoverable at the call site and the raw class is not.

### Supported behavior and syntax

Retain the contributor's supported Svelte syntax. This ADR does not require a migration to Svelte 5 runes; event or headless-component API differences are corrected where they cause a concrete compatibility or behavior problem. The reference implementation retains native activation, disabled state, accessible names and expected event behavior.

Existing routing details, prompt comparisons and citation traces remain readable and reachable with pointer, keyboard and touch. A hover-card reference does not authorize removing the existing deliberate access to those details. If a submitted presentation change needs a larger interaction redesign to satisfy that requirement, it can be handled separately by the maintainer without expanding the primitive contract.

## Typography and iconography

**Fonts:** the `/lq-ai/*` shell self-hosts Inter Variable (`@fontsource-variable/inter`, loaded by `styles/typography.css`, which the `/lq-ai/*` layout imports — not loaded globally, so the OpenWebUI shell's own font stack is untouched per ADR 0009's boundary). `--lq-font-sans` is the single font-family var; `.lq-shell` applies it at the root of the `/lq-ai` tree.

`typography.css` already carries a pre-existing "Practice type scale" (`.lq-text-label`, `.lq-text-caption`, `.lq-text-body-sm`, `.lq-text-body`, `.lq-text-panel-h`, `.lq-text-page-h`, `.lq-text-welcome` — fixed px sizes per spec §5.4), predating this ADR's `LqText`/`LqTitle` primitives and their own `LqTextSize` (12–18px, `xs`–`xl`) and `LqTitle` order (14–34px, 1–6) scales. These are two parallel, unreconciled type-scale systems as of this writing — exactly the "different decisions in different files" failure mode CLAUDE.md warns against. Reconciling them (either retiring the `.lq-text-*` classes in favor of `LqText`, or deriving `LqTextSize`'s px values from the same scale) is follow-up work, not done here.

Font-size and shadow values may remain component-local for this reference implementation, with their limits documented. This ADR does not require a new global font/shadow token family or resolution of the parallel type scales. Existing spacing tokens remain the reference where a prop maps to them; a fallback must not silently give a different value for the same token.

**Icons:** `@tabler/icons-svelte` is a **new dependency proposed in this PR**, recorded in `web/package.json` and `package-lock.json`. It's the icon source for every primitive built under this ADR (`IconX` in `LqPill`/`LqAlert`, plus the icons already wired into `ChatPanel.svelte`'s composer row). Justification per CLAUDE.md's "new dependencies need justification" rule:

Emoji glyphs are the thing being replaced, and the problem with them isn't taste — it's that every call site using an emoji as an icon ends up hand-tuning inline styles (`font-size`, `line-height`, manual margin nudges) to make the glyph sit correctly next to text or inside a button, because an emoji has no `size` prop and no predictable box model. That's exactly the failure mode this whole primitive effort exists to eliminate: inline one-off styling that produces inconsistent spacing and sizing across call sites, the same problem `LqGroup`'s `gap` solves for layout. An SVG icon component (`<IconX size={14} />`) has a real, explicit size and a predictable geometry, so it composes cleanly with the `LqGap`/`LqTextSize` scales already established — no inline style needed to make it line up.

Secondary reasons emoji specifically are a poor icon vocabulary, independent of the inline-style problem:
- **Not stylable.** An emoji is a font glyph rendered by the OS/browser's emoji font — it can't inherit `currentColor`, so it can't pick up a button's `tone` the way an SVG icon does.
- **Not visually consistent.** The same emoji renders differently per OS/browser (Apple's colorful emoji set vs. Windows'/Linux's, or a missing glyph entirely on some platforms) — a security/legal product where "what does this icon mean" matters shouldn't depend on the reader's OS to render it recognizably.

The emoji glyphs still in `ProvenancePill`/`TrustPill`/the capture button are pre-existing and out of scope for this ADR to migrate wholesale — flagged as a natural Tabler-icon migration candidate for later, not undone here.

## Scope / boundary

Everything above lives under `web/src/lib/lq-ai/**`. Per ADR 0009, the OpenWebUI shell at `/` (`web/src/lib/components/**`) is untouched — this doesn't reopen that boundary. ADR 0009 already anticipated this: "the LQ.AI shell can be redesigned, refactored, or rewritten without touching upstream code."

The completion boundary is the contributed catalog, its typed vocabulary and the reference components in this PR. The card and compound hover-card remain part of the submitted design; their removal is not required merely to satisfy a different preferred catalog. Normal dependency, compatibility and changed-surface behavior checks still apply.

Whole-shell migration, palette redesign, a separate success tone, application-wide status reclassification, typography reconciliation, OKLCH, dark-mode completion, new grid/popover APIs and framework evaluation are outside this PR's acceptance criteria. Future work on these topics requires its own scope; this ADR does not commit the contributor to doing it.

## Consequences

**Positive:** migrated components gain a discoverable shared API for layout, typography and controls. Role-based tone names permit future palette changes without renaming that API. The contributor's reference examples provide a concrete basis for reviewing the contract.

**Costs:** existing components outside the reference set continue using their current styles until separately migrated. The reference type and heading scales remain alongside the existing Practice classes. Neither inconsistency becomes an application-wide cleanup prerequisite for this PR. Tailwind utilities and shared Svelte primitives can coexist within the LQ.AI shell.

**Verification:** meaningful component tests cover the behavior affected by the wrappers, including declared class/attribute forwarding, activation and disabled state. Normal frontend type/component checks and inspection of the migrated screens are required before merge. This is a check of the changed surfaces, not a new whole-application accessibility audit or a claim of complete dark-mode coverage.

**Reversibility:** the component layer is additive within the LQ.AI shell, but reverting it requires restoring the migrated consumers and reviewing the icon dependency. This ADR does not claim the contribution has no external dependency.

## Follow-up candidates

These are separate possible ADRs or PRs, not prerequisites, assignments or commitments made by this contribution:

- A punch list for migrating remaining components, considered incrementally.
- Reconciliation of the existing Practice type scale with the primitive type/heading scales.
- A broader semantic review of provider, tier, completion and citation colors, including whether a distinct success role is useful.
- OKLCH palette authoring and dark-mode completion.
- Additional `LqPopover` or `LqSimpleGrid` primitives when separately scoped.
- Any reassessment of the application framework or the OpenWebUI fork.

The maintainer coordinates ADR numbering, integration conflicts and any extraction needed to keep review manageable. Following the invitation to Simon, @houfu is applying the agreed contract and resolving integration conflicts on the maintainer’s behalf. Existing routing, prompt-comparison and citation-ledger dialogs retain deliberate click, keyboard and touch access; adopting a hover-only replacement is deferred. Attribution for the original primitive design and implementation remains with Simon Booth.
