<script lang="ts">
	/**
	 * LqText — semantic text primitive, modeled on Mantine's Text.
	 *
	 * Exists to replace ad hoc `<div class="text-xs text-gray-600 ...">`
	 * markup (which carries no semantics — a div is not text) with a
	 * component that (a) renders the right element for the content
	 * (`as`, default `p`) and (b) drives size/weight/color/mono/truncate
	 * off this file's shared token scales instead of one-off Tailwind
	 * color/size classes per call site.
	 *
	 * `size` takes a step of ADR 0045's type scale ("11" to "32") or one of
	 * the older named steps. `tracking` and `transform` carry the uppercase
	 * label style; `leading` sets a line height, which is otherwise inherited.
	 */
	import {
		LQ_TEXT_SIZE_VAR,
		LQ_WEIGHT_VAR,
		LQ_TEXT_TONE_VAR,
		LQ_TRACKING_VAR,
		LQ_LEADING_VAR,
		type LqTextSize,
		type LqWeight,
		type LqTextTone,
		type LqTracking,
		type LqLeading,
		type LqTextElement,
		type LqTextTransform
	} from './types';

	export let as: LqTextElement = 'p';
	export let size: LqTextSize = 'md';
	export let weight: LqWeight = 'normal';
	export let tone: LqTextTone | undefined = undefined;
	export let tracking: LqTracking | undefined = undefined;
	export let leading: LqLeading | undefined = undefined;
	export let mono = false;
	export let truncate = false;
	export let align: 'left' | 'center' | 'right' | 'justify' | undefined = undefined;
	export let transform: LqTextTransform = 'none';

	let klass = '';
	export { klass as class };
</script>

<svelte:element
	this={as}
	{...$$restProps}
	class="lq-text {klass}"
	class:lq-text-mono={mono}
	class:lq-text-truncate={truncate}
	style:font-size={LQ_TEXT_SIZE_VAR[size]}
	style:font-weight={LQ_WEIGHT_VAR[weight]}
	style:color={tone ? LQ_TEXT_TONE_VAR[tone] : undefined}
	style:letter-spacing={tracking ? LQ_TRACKING_VAR[tracking] : undefined}
	style:line-height={leading ? LQ_LEADING_VAR[leading] : undefined}
	style:text-align={align}
	style:text-transform={transform === 'none' ? undefined : transform}
>
	<slot />
</svelte:element>

<style>
	/* No margin reset here: Tailwind's preflight already zeroes the margins of
	   p, headings and lists, and an unlayered reset in this component would beat
	   Tailwind v4's layered margin utilities (`mt-1`, `mb-2`) on the caller. */

	.lq-text-mono {
		font-family: var(--lq-font-mono, ui-monospace, 'SF Mono', Menlo, Consolas, monospace);
	}

	.lq-text-truncate {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
