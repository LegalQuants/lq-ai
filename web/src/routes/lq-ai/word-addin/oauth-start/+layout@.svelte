<!--
  Reset layout for the Word add-in OAuth dialog (M3-B2).

  This page is loaded by Office.js inside a dialog window — it's not part
  of the normal LQ.AI navigation hierarchy. The `@` suffix on the
  filename tells SvelteKit to reset the inherited layout chain, so the
  global nav / sidebar / footer don't render here.

  The reset also drops the LQ.AI layout's stylesheets, so the colour
  tokens are loaded here. With them the dialog follows the theme like
  every other LQ.AI page (ADR 0045 §2).
-->
<script lang="ts">
	import '$lib/lq-ai/styles/practice.css';
</script>

<slot />
