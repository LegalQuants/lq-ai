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
	 */
	import {
		LQ_TEXT_SIZE_VAR,
		LQ_WEIGHT_VAR,
		LQ_TEXT_TONE_VAR,
		type LqTextSize,
		type LqWeight,
		type LqTextTone
	} from './types';

	export let as: 'p' | 'span' | 'div' | 'label' = 'p';
	export let size: LqTextSize = 'md';
	export let weight: LqWeight = 'normal';
	export let tone: LqTextTone | undefined = undefined;
	export let mono = false;
	export let truncate = false;
	export let align: 'left' | 'center' | 'right' | 'justify' | undefined = undefined;
	export let transform: 'none' | 'uppercase' | 'lowercase' | 'capitalize' = 'none';

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
	style:text-align={align}
	style:text-transform={transform === 'none' ? undefined : transform}
>
	<slot />
</svelte:element>

<style>
	.lq-text {
		margin: 0;
		line-height: 1.4;
	}

	.lq-text-mono {
		font-family: var(--lq-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
	}

	.lq-text-truncate {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
