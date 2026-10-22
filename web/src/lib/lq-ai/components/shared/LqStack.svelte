<script lang="ts">
	/**
	 * LqStack — vertical flex layout primitive, modeled on Mantine's Stack.
	 * Same gap vocabulary as LqGroup so the two compose predictably.
	 */
	import { LQ_GAPS, LQ_GAP_VAR, type LqGap, type LqJustify, type LqAlign } from './types';

	export let gap: LqGap | number | string = 'sm';
	export let justify: LqJustify = 'flex-start';
	export let align: LqAlign = 'stretch';
	export let maxWidth: number | string | undefined = undefined;

	let klass = '';
	export { klass as class };

	$: resolvedGap =
		typeof gap === 'string' && (LQ_GAPS as readonly string[]).includes(gap)
			? LQ_GAP_VAR[gap as LqGap]
			: typeof gap === 'number'
				? `${gap}px`
				: gap;

	$: resolvedMaxWidth = typeof maxWidth === 'number' ? `${maxWidth}px` : maxWidth;
</script>

<div
	{...$$restProps}
	class="lq-stack {klass}"
	style:gap={resolvedGap}
	style:justify-content={justify}
	style:align-items={align}
	style:max-width={resolvedMaxWidth}
>
	<slot />
</div>

<style>
	.lq-stack {
		display: flex;
		flex-direction: column;
	}
</style>
