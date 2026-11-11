<script context="module" lang="ts">
	/**
	 * LqToneIcon — the icon that carries a note's or a caution's meaning now that
	 * `info` and `warning` are neutral ink (ADR 0045 §1: "neutral ink, with a distinct
	 * icon"). One map, so every caution draws the same triangle and every note the same
	 * circle; WCAG 1.4.1 is met by the icon and the text, not by colour.
	 *
	 * Decorative by default (`aria-hidden`), because the text beside it says what it is.
	 * Pass `label` when the icon stands alone and must name itself (`role="img"`).
	 */
	import { IconAlertTriangle, IconInfoCircle } from '@tabler/icons-svelte';

	export type LqToneIconTone = 'info' | 'warning';

	export const LQ_TONE_ICON = {
		info: IconInfoCircle,
		warning: IconAlertTriangle
	} as const;

	/** The Tabler name each tone draws, for tests (`tabler-icon-<name>`). */
	export const LQ_TONE_ICON_NAME: Record<LqToneIconTone, string> = {
		info: 'info-circle',
		warning: 'alert-triangle'
	};
</script>

<script lang="ts">
	export let tone: LqToneIconTone;
	export let size = 14;
	export let label: string | undefined = undefined;

	let klass = '';
	export { klass as class };
</script>

{#if label}
	<svelte:component
		this={LQ_TONE_ICON[tone]}
		{size}
		stroke={1.75}
		class="lq-tone-icon {klass}"
		role="img"
		aria-label={label}
	/>
{:else}
	<svelte:component
		this={LQ_TONE_ICON[tone]}
		{size}
		stroke={1.75}
		class="lq-tone-icon {klass}"
		aria-hidden="true"
	/>
{/if}

<style>
	:global(.lq-tone-icon) {
		flex: none;
		vertical-align: -0.125em;
		margin-inline-end: 0.25em;
	}
</style>
