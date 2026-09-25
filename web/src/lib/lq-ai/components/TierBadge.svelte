<script lang="ts">
	/**
	 * Inference Tier badge per PRD §3.13.
	 *
	 * Now delegates to TrustPill (variant="tier") so the LQ.AI ambient chrome
	 * stays visually consistent. Public API preserved — callers are unchanged.
	 *
	 * Prop mapping:
	 *   tier      → label ("Tier N" / "Tier ?") + TrustTone override
	 *   provider  → tooltip text (title on wrapper span)
	 *   interactive → onClick forwarded to TrustPill; false = no handler
	 *
	 * The component continues to dispatch a Svelte "open" event so existing
	 * callers using `on:open` don't need to change.
	 *
	 * Tone + description per tier come from `chat/tierDescriptions.ts` — the
	 * single source of truth also consumed by TierDetailsPanel and
	 * MessageBubble's tier hover-popover, so the three don't drift.
	 */
	import { createEventDispatcher } from 'svelte';
	import TrustPill from './TrustPill.svelte';
	import type { TrustTone } from './TrustPill.svelte';
	import { TIER_DESCRIPTIONS } from '../chat/tierDescriptions';

	export let tier: 1 | 2 | 3 | 4 | 5 | null | undefined = null;
	export let provider: string | null | undefined = null;
	/**
	 * When `false` the badge renders as a static pill (no click /
	 * keyboard handlers). Used by surfaces where the parent has its
	 * own interaction model (admin alias UI, model picker resolution
	 * preview).
	 */
	export let interactive: boolean = true;

	const dispatch = createEventDispatcher<{ open: void }>();

	$: label = tier ? `Tier ${tier}` : 'Tier ?';
	$: tone = (tier ? TIER_DESCRIPTIONS[tier].tone : 'neutral') as TrustTone;
	$: description = tier
		? TIER_DESCRIPTIONS[tier].blurb
		: 'Tier unknown — routing source not yet resolved.';
	$: title = provider
		? `${label} — ${provider}\n${description}\n(click for details)`
		: `${label}\n${description}\n(click for details)`;
	$: handleClick = interactive ? () => dispatch('open') : undefined;
</script>

<!--
  Wrap in a span so we can attach `title` (hover tooltip) and
  `data-testid` without modifying TrustPill's public API.
  `display: contents` keeps the wrapper invisible in layout.
-->
<span {title} data-testid="lq-ai-tier-badge" style="display: contents">
	<TrustPill variant="tier" {label} {tone} onClick={handleClick} />
</span>
