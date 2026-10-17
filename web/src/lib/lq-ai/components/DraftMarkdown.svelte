<script lang="ts">
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';
	export let content = '';
	// Model output is untrusted. Match the existing assistant/skill-view pattern.
	$: rendered = DOMPurify.sanitize(marked.parse(content, { async: false }) as string);
</script>

<div class="prose prose-sm max-w-none draft-markdown" data-testid="lq-draft-markdown">
	{@html rendered}
</div>

<style>
	.draft-markdown {
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.draft-markdown :global(pre) {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.draft-markdown :global(table) {
		display: block;
		max-width: 100%;
		overflow-x: auto;
	}
	.draft-markdown :global(img) {
		max-width: 100%;
	}
</style>
