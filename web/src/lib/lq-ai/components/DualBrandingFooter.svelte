<script lang="ts">
	/**
	 * Dual-branding footer per ADR 0001 clause 4: "Open WebUI" branding is
	 * preserved alongside (not replaced by) LQ.AI's identity. This footer
	 * renders in every LQ.AI shell route and in the OpenWebUI shell's
	 * `+layout.svelte` so the OpenWebUI deployment also carries the
	 * attribution.
	 *
	 * Operators above the 50-user threshold who want full re-branding need an
	 * enterprise license from OpenWebUI; the README / deploy docs link out.
	 */
</script>

<footer
	class="lq-branding-footer text-xs px-4 py-2 border-t flex flex-wrap items-center justify-between gap-2"
	data-testid="lq-ai-dual-branding-footer"
>
	<span>
		<strong>LQ.AI</strong> — Open-Source Legal AI
	</span>
	<span>
		Web shell powered by
		<a
			href="https://github.com/open-webui/open-webui"
			target="_blank"
			rel="noopener noreferrer"
			class="underline"
		>
			Open WebUI
		</a>
		(forked at v0.11.0; see ADR&nbsp;0001).
	</span>
</footer>

<style>
	/* Tertiary text is the nearest token to the grey this footer had, and it
	   passes 4.5:1 on the page and on the sidebar in both themes. */
	.lq-branding-footer {
		color: var(--lq-text-tertiary);
		border-color: var(--lq-border);
	}
	.lq-branding-footer a:hover {
		color: var(--lq-text);
	}
</style>
