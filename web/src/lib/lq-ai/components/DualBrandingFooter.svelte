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
	class="text-xs text-gray-500 dark:text-gray-400 px-4 py-2 border-t border-gray-200 dark:border-gray-700 flex flex-wrap items-center justify-between gap-2"
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
			class="underline hover:text-gray-700 dark:hover:text-gray-200"
		>
			Open WebUI
		</a>
		(forked at v0.9.2; see ADR&nbsp;0001).
	</span>
</footer>
