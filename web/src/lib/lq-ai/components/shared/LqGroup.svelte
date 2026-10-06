<script lang="ts">
	/**
	 * LqGroup — horizontal flex layout primitive, modeled on Mantine's Group.
	 *
	 * Exists to replace the repeated `flex items-center gap-2` Tailwind
	 * incantations across lq-ai components with a single prop-driven layout
	 * component, same spirit as Mantine's Group/Stack pair.
	 */
	import { LQ_GAPS, LQ_GAP_VAR, type LqGap, type LqJustify, type LqAlign } from './types';

	export let gap: LqGap | number | string = 'sm';
	export let justify: LqJustify = 'flex-start';
	export let align: LqAlign = 'center';
	export let wrap: 'wrap' | 'nowrap' | 'wrap-reverse' = 'wrap';
	export let grow = false;
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
	class="lq-group {klass}"
	class:lq-group-grow={grow}
	style:gap={resolvedGap}
	style:justify-content={justify}
	style:align-items={align}
	style:flex-wrap={wrap}
	style:max-width={resolvedMaxWidth}
>
	<slot />
</div>

<style>
	.lq-group {
		display: flex;
	}

	.lq-group-grow > :global(*) {
		flex-grow: 1;
		flex-basis: 0;
	}
</style>
