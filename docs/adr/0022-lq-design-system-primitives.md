# ADR 0022 — `lq` design-system primitives for the LQ.AI shell

**Status:** Accepted (2026-07-06)
**Decision-makers:** Simon Booth
**Affected components:** `web/src/lib/lq-ai/**`
**Supersedes:** none. **Refers to:** [ADR 0009](0009-web-lq-ai-shell-coexistence.md), [ADR 0001](0001-openwebui-fork-pin.md), [CONTRIBUTING.md](../../CONTRIBUTING.md), [CLAUDE.md](../../CLAUDE.md).

---

## Context

CONTRIBUTING.md and CLAUDE.md have both carried this line since M1:

> Component conventions: match the OpenWebUI conventions for shared components; use the project's design system primitives rather than ad-hoc Tailwind.

Until now, "the project's design system primitives" pointed at nothing concrete for `/lq-ai/*`. Every component under `lib/lq-ai/components/**` independently decided its own spacing, color, size, and interaction logic in raw Tailwind utility classes — TrustPill's tone-mapping, the old `.lq-btn-secondary`/`.lq-btn-send`/`.lq-btn-abort` classes hand-rolled inside `ChatPanel.svelte`, ad hoc `flex items-center gap-2` layout soup repeated across a dozen files, a tier→description mapping independently duplicated (with drifting wording) across `TierBadge.svelte`, `TierDetailsPanel.svelte`, and `MessageBubble.svelte`. Nothing was wrong file-by-file; the absence of a shared vocabulary meant every file was its own small design decision.

A React/Mantine migration and a "push the fix upstream into OpenWebUI" option were both considered and rejected in favor of a design-system layer native to this codebase (see discussion trail; not separately documented as those were explicitly rejected, not adopted). The rejection reasoning: a framework migration reverses ADR 0009/ADR 0001's SvelteKit-only decision and its rebase-cost rationale for no real benefit — the actual problem is missing convention + discipline, not the framework.

## Decision

Adopt a small primitive layer at `web/src/lib/lq-ai/components/shared/`, modeled on Mantine's component API shape (`variant`/`size`/`tone`/`shadow` props, `Component.Part` compound namespacing) as a naming and ergonomics reference only — not an added runtime dependency. Every primitive is plain Svelte + CSS custom properties, plus two existing pieces of `web/`'s dependency tree used rather than reimplemented (`bits-ui`'s headless `Switch`/`Portal`; see below). One genuinely new dependency was added alongside this effort — `@tabler/icons-svelte`, justified in "Typography and iconography" below — consistent with CLAUDE.md's "don't add libraries without justification" (the justification being the actual reason, not an exemption from it).

**Token layer** (`shared/types.ts`): every option list is a `const` array with a type derived via `(typeof X)[number]`, never a hand-typed string-literal union — one file to extend, full autocomplete everywhere. This is a deliberate, load-bearing design goal, not an incidental side effect: every prop on every primitive is typed specifically so the editor's IntelliSense surfaces the full set of valid values at the call site — a contributor should never need to open `types.ts` or another component's source to discover what `tone`/`variant`/`gap`/etc. accept. Current scales: `LqVariant`, `LqTone`, `LqSize`, `LqGap`, `LqShadow`, `LqWeight`, `LqTextSize`, `LqTextTone`, `LqJustify`, `LqAlign`, and the lower-level `LqColor`+`LqShade` pair (`lqColorShade()`, computed via CSS `color-mix()` off five base `--lq-*` vars rather than a hand-authored shade table).

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
4. Any primitive taking arbitrary attributes (`data-testid`, `aria-*`) forwards `$$restProps`; any primitive taking an additional class forwards it via the `let klass = ''; export { klass as class };` pattern, not by relying on Svelte's spread-vs-static-class merging.
5. Prefer a primitive's typed props over its `class` escape hatch. `class` exists only for concerns with no corresponding prop and no sane default — a one-off test hook, a genuinely unsupported CSS need. It is not a shortcut around adding a real option to a scale in `types.ts` when the same value will recur (if a second call site wants the same "unsupported" thing, that's the signal to promote it to a prop, not to keep copy-pasting the class string). Reaching for `class` where a prop already exists (e.g. a raw `flex` utility class instead of `LqGroup`, a color utility instead of `tone`) defeats the IntelliSense goal described in the token-layer paragraph above — the whole point is that the typed prop is discoverable at the call site and the raw class is not.

## Typography and iconography

**Fonts:** the `/lq-ai/*` shell self-hosts Inter Variable (`@fontsource-variable/inter`, loaded by `styles/typography.css`, which the `/lq-ai/*` layout imports — not loaded globally, so the OpenWebUI shell's own font stack is untouched per ADR 0009's boundary). `--lq-font-sans` is the single font-family var; `.lq-shell` applies it at the root of the `/lq-ai` tree.

`typography.css` already carries a pre-existing "Practice type scale" (`.lq-text-label`, `.lq-text-caption`, `.lq-text-body-sm`, `.lq-text-body`, `.lq-text-panel-h`, `.lq-text-page-h`, `.lq-text-welcome` — fixed px sizes per spec §5.4), predating this ADR's `LqText`/`LqTitle` primitives and their own `LqTextSize` (12–18px, `xs`–`xl`) and `LqTitle` order (14–34px, 1–6) scales. These are two parallel, unreconciled type-scale systems as of this writing — exactly the "different decisions in different files" failure mode CLAUDE.md warns against. Reconciling them (either retiring the `.lq-text-*` classes in favor of `LqText`, or deriving `LqTextSize`'s px values from the same scale) is follow-up work, not done here.

**Icons:** `@tabler/icons-svelte` is a **new dependency, introduced as part of this design-system effort** (not a pre-existing one being reused — `web/package.json`/`package-lock.json` carry it as an uncommitted addition alongside this work). It's the icon source for every primitive built under this ADR (`IconX` in `LqPill`/`LqAlert`, plus the icons already wired into `ChatPanel.svelte`'s composer row). Justification per CLAUDE.md's "new dependencies need justification" rule:

Emoji glyphs are the thing being replaced, and the problem with them isn't taste — it's that every call site using an emoji as an icon ends up hand-tuning inline styles (`font-size`, `line-height`, manual margin nudges) to make the glyph sit correctly next to text or inside a button, because an emoji has no `size` prop and no predictable box model. That's exactly the failure mode this whole primitive effort exists to eliminate: inline one-off styling that produces inconsistent spacing and sizing across call sites, the same problem `LqGroup`'s `gap` solves for layout. An SVG icon component (`<IconX size={14} />`) has a real, explicit size and a predictable geometry, so it composes cleanly with the `LqGap`/`LqTextSize` scales already established — no inline style needed to make it line up.

Secondary reasons emoji specifically are a poor icon vocabulary, independent of the inline-style problem:
- **Not stylable.** An emoji is a font glyph rendered by the OS/browser's emoji font — it can't inherit `currentColor`, so it can't pick up a button's `tone` the way an SVG icon does.
- **Not visually consistent.** The same emoji renders differently per OS/browser (Apple's colorful emoji set vs. Windows'/Linux's, or a missing glyph entirely on some platforms) — a security/legal product where "what does this icon mean" matters shouldn't depend on the reader's OS to render it recognizably.

The emoji glyphs still in `ProvenancePill`/`TrustPill`/the capture button are pre-existing and out of scope for this ADR to migrate wholesale — flagged as a natural Tabler-icon migration candidate for later, not undone here.

## Scope / boundary

Everything above lives under `web/src/lib/lq-ai/**`. Per ADR 0009, the OpenWebUI shell at `/` (`web/src/lib/components/**`) is untouched — this doesn't reopen that boundary. ADR 0009 already anticipated this: "the LQ.AI shell can be redesigned, refactored, or rewritten without touching upstream code."

## Consequences

**Positive:** one place to change a spacing/color/size decision for the whole `/lq-ai` shell; new components have an actual answer to "what do I use instead of Tailwind" instead of reverse-engineering convention from nearby files; several latent bugs surfaced and were fixed while migrating existing call sites to these primitives (a `gap={2}` typo silently falling through to a raw-number branch; a tier-description mapping duplicated three times with drifting wording; a hover popover clipped by a scrolling ancestor).

**Negative:** components under `lib/lq-ai/components/**` not yet migrated remain inconsistent until touched — this is an incremental migration, not a rewrite. Two visual-language systems still coexist in `web/` (Tailwind-utility for the OpenWebUI shell, tone/token-based for `lq-ai/**`), which is accepted as the cost of ADR 0009's boundary, not something this ADR changes.

**Reversibility:** low cost either way — primitives are additive Svelte files with no external dependency; abandoning them means falling back to Tailwind per-file, no migration required in the other direction beyond the components already converted.

## Follow-up

- Audit `lib/lq-ai/components/**` for the highest-traffic remaining ad hoc Tailwind patterns (badges/pills/buttons) as a punch list, rather than a big-bang rewrite.
- `LqCard` and `lqColorShade()` have no consumer yet as of this ADR; both exist because a concrete near-term need was anticipated, not speculatively.
- Reconcile the two parallel type scales described above (`typography.css`'s `.lq-text-*` classes vs. `LqText`/`LqTitle`'s own scales).

**Do next:**
1. **Migrate the base color tokens to OKLCH.** `practice.css`'s five tone base vars (`--lq-accent`, `--lq-tier`, `--lq-warn`, `--lq-error`, and the text/border grays) are still authored as flat hex/sRGB. `lqColorShade()` already mixes *from* those bases `in oklab` (a perceptually uniform space) — but the bases themselves aren't, so the shade ramp only gets partway to perceptually-even. Authoring the base tokens directly as `oklch(L C H)` (independently tunable lightness/chroma/hue) would close that gap. This isn't a new idea for this codebase — `web/src/tailwind.css` already defines OpenWebUI's own gray scale in `oklch()` (`--color-gray-50: oklch(0.98 0 0)`, etc.); the `lq-ai` tone palette is the one part of `web/` still on hex.
2. **Add `LqPopover`.** Same Root/Target/Dropdown/context/Portal architecture as `LqHoverCard`, but click-triggered with click-outside-to-close instead of hover/focus — Mantine ships both `HoverCard` and `Popover` as siblings for exactly this reason (glance-and-go vs. deliberate open). This is the primitive the modals correctly *not* converted to `LqHoverCard` earlier (interactive/mutating content, or simple click-triggered menus that don't need full modal backdrop+focus-trap treatment) should eventually sit on.
3. **Add `LqSimpleGrid`.** Mantine's `SimpleGrid` (`cols`, `spacing`, responsive breakpoints) has no equivalent here — `LqGroup`/`LqStack` only cover row/column flex layouts. Several components already hand-roll `grid grid-cols-*` Tailwind utilities for card-grid layouts (`TierDetailsPanel`, `FeaturedToolsRow`, `PlaybookEditor`, among others) — real, existing call sites to migrate once it exists.
