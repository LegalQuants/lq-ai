/**
 * Reading a Svelte component's source for the tests that scan it (`folds.test.ts`, the checks on
 * what ChatPanel hands to its children). Not a parser: enough of one to take a start tag whole, with
 * an attribute that holds an expression, a quote or a `>`, and to leave out comments that name what
 * they forbid.
 */

/** Source without its comments, which may name what they forbid. */
export function withoutComments(source: string): string {
	return source
		.replace(/<!--[\s\S]*?-->/g, '')
		.replace(/\/\*[\s\S]*?\*\//g, '')
		.replace(/(^|\s)\/\/[^\n]*/g, '$1');
}

/**
 * Every start tag of an element or component called `name` in some source, whole: an attribute may
 * hold an expression with a `>` in it, and a tag may run over several lines. `name` is matched as a
 * whole word, so `MessageList` is not `MessageListItem`.
 */
export function startTags(source: string, name: string): string[] {
	const tags: string[] = [];
	for (const start of source.matchAll(new RegExp(`<${name}(?![\\w:.-])`, 'g'))) {
		let depth = 0;
		let quote = '';
		let at = start.index!;
		for (; at < source.length; at += 1) {
			const char = source[at];
			if (quote) {
				if (char === quote) quote = '';
			} else if (char === '"' || char === "'" || char === '`') {
				quote = char;
			} else if (char === '{') {
				depth += 1;
			} else if (char === '}') {
				depth -= 1;
			} else if (char === '>' && depth === 0) {
				break;
			}
		}
		tags.push(source.slice(start.index!, at + 1));
	}
	return tags;
}
