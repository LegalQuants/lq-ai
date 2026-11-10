<script lang="ts">
	/**
	 * A sentence that names things somebody wrote, such as the knowledge bases a task may search. Each
	 * name is drawn by itself, in an element that isolates its text from the text around it, and the
	 * names are separated by a comma and a space. A name with a comma in it is then one name and not
	 * two, and a name that holds a control character that reorders text cannot move the names after
	 * it or the words around them.
	 *
	 * The parts come from the helper that wrote the sentence (`NamedLine`), and every name is the
	 * owner's own text: interpolated, never rendered as markup.
	 */
	import type { NamedLine } from '$lib/lq-ai/run/format';

	export let line: NamedLine;
</script>

<!-- prettier-ignore -->
{line.lead}{#each line.names as name, at}{#if at > 0}{', '}{/if}<bdi>{name}</bdi>{/each}{line.tail}
