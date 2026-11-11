<script lang="ts">
	/**
	 * LqTitle — heading primitive, modeled on Mantine's Title. `order`
	 * (1–6) picks the rendered tag (`h1`–`h6`) and a default size on ADR
	 * 0045's type scale; `size` overrides that size with any step of the
	 * scale, so the heading level follows the document outline and the size
	 * follows the design. `leading` sets a line height, otherwise inherited.
	 */
	import {
		LQ_TEXT_SIZE_VAR,
		LQ_TEXT_TONE_VAR,
		LQ_WEIGHT_VAR,
		LQ_TRACKING_VAR,
		LQ_LEADING_VAR,
		type LqTextSize,
		type LqTextTone,
		type LqWeight,
		type LqTracking,
		type LqLeading,
		type LqTextTransform
	} from './types';

	export let order: 1 | 2 | 3 | 4 | 5 | 6 = 1;
	export let size: LqTextSize | undefined = undefined;
	export let tone: LqTextTone | undefined = undefined;
	export let weight: LqWeight = 'bold';
	export let tracking: LqTracking | undefined = undefined;
	export let leading: LqLeading | undefined = undefined;
	export let transform: LqTextTransform = 'none';

	// Default sizes per order, on the scale: 32 px, the Home greeting (26),
	// page titles (20), then 16, 14.5 (header titles) and body size.
	const ORDER_SIZE: Record<1 | 2 | 3 | 4 | 5 | 6, LqTextSize> = {
		1: '32',
		2: '26',
		3: '20',
		4: '16',
		5: '14.5',
		6: '14'
	};

	let klass = '';
	export { klass as class };
</script>

<svelte:element
	this={`h${order}`}
	{...$$restProps}
	class="lq-title {klass}"
	style:font-size={LQ_TEXT_SIZE_VAR[size ?? ORDER_SIZE[order]]}
	style:font-weight={LQ_WEIGHT_VAR[weight]}
	style:color={tone ? LQ_TEXT_TONE_VAR[tone] : undefined}
	style:letter-spacing={tracking ? LQ_TRACKING_VAR[tracking] : undefined}
	style:line-height={leading ? LQ_LEADING_VAR[leading] : undefined}
	style:text-transform={transform === 'none' ? undefined : transform}
>
	<slot />
</svelte:element>

<!-- No margin reset: Tailwind's preflight zeroes heading margins, and an unlayered
     reset here would beat Tailwind v4's layered margin utilities on the caller. -->
