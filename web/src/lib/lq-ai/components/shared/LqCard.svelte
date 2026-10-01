<script lang="ts">
	/**
	 * LqCard — static content container, modeled on Mantine's Paper/Card.
	 * Same visual box (background/border/radius/shadow) LqHoverCard.Dropdown
	 * uses, but with no hover/open state — just a container.
	 */
	import { LQ_GAPS, LQ_GAP_VAR, LQ_SHADOW_VAR, type LqGap, type LqShadow } from './types';

	export let padding: LqGap | number | string = 'md';
	export let shadow: LqShadow = 'xs';

	let klass = '';
	export { klass as class };

	$: resolvedPadding =
		typeof padding === 'string' && (LQ_GAPS as readonly string[]).includes(padding)
			? LQ_GAP_VAR[padding as LqGap]
			: typeof padding === 'number'
				? `${padding}px`
				: padding;
</script>

<div
	{...$$restProps}
	class="lq-card {klass}"
	style:padding={resolvedPadding}
	style:box-shadow={LQ_SHADOW_VAR[shadow]}
>
	<slot />
</div>

<style>
	.lq-card {
		background: var(--lq-canvas, #fff);
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius-lg, 8px);
	}
</style>
