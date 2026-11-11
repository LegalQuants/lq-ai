<script lang="ts">
	/**
	 * The ADR 0001 attribution footer below the page, for the LQ.AI layout.
	 *
	 * With the redesigned chrome off this is today's footer, unchanged and
	 * always shown. With it on, `ShellSidebar` carries the footer in its foot
	 * whenever its panel is rendered; when the sidebar is collapsed to its strip
	 * (on a phone it starts that way) the footer shows here instead, so the
	 * attribution is on screen without opening anything. Both read the same
	 * collapse state (`../leftSidebar`), so exactly one copy is on the page.
	 *
	 * No wrapper element: the footer is placed by the layout.
	 */
	import { attributionBelowPage, leftSidebarNarrow, leftSidebarOpen } from '../leftSidebar';
	import DualBrandingFooter from './DualBrandingFooter.svelte';

	export let sidebarChrome: boolean;

	$: shown = attributionBelowPage({
		sidebarChrome,
		open: $leftSidebarOpen,
		narrow: $leftSidebarNarrow
	});
</script>

{#if shown}
	<DualBrandingFooter />
{/if}
