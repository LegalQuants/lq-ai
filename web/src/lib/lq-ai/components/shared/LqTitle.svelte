<script lang="ts">
	/**
	 * LqTitle — heading primitive, modeled on Mantine's Title. `order`
	 * (1–6) picks both the rendered tag (`h1`–`h6`) and the size step —
	 * separate from LqText's size scale, since headings and body text
	 * shouldn't share one scale.
	 */
	import { LQ_TEXT_TONE_VAR, LQ_WEIGHT_VAR, type LqTextTone, type LqWeight } from './types';

	export let order: 1 | 2 | 3 | 4 | 5 | 6 = 1;
	export let tone: LqTextTone | undefined = undefined;
	export let weight: LqWeight = 'bold';

	const ORDER_SIZE: Record<1 | 2 | 3 | 4 | 5 | 6, string> = {
		1: '34px',
		2: '26px',
		3: '22px',
		4: '18px',
		5: '16px',
		6: '14px'
	};

	let klass = '';
	export { klass as class };
</script>

<svelte:element
	this={`h${order}`}
	{...$$restProps}
	class="lq-title {klass}"
	style:font-size={ORDER_SIZE[order]}
	style:font-weight={LQ_WEIGHT_VAR[weight]}
	style:color={tone ? LQ_TEXT_TONE_VAR[tone] : undefined}
>
	<slot />
</svelte:element>

<style>
	.lq-title {
		margin: 0;
		line-height: 1.3;
	}
</style>
