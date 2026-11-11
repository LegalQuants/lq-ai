/**
 * Token guard: LQ.AI code must not hard-code colours.
 *
 * ADR 0043 gives the LQ.AI shell one colour vocabulary: the `--lq-*` custom
 * properties defined in `src/lib/lq-ai/styles/practice.css` (and the type
 * tokens in `typography.css`). The interface-redesign work plan (Annex B, P1.1)
 * cleaned the code up to that vocabulary: undefined tokens were defined, inline
 * `var()` fallbacks dropped, exact hex replaced by tokens and Tailwind palette
 * classes replaced by token-backed classes. This test keeps it that way: a new
 * hard-coded colour fails CI the day it is written, so the palette can later be
 * changed in one file.
 *
 * Scanned: every `.svelte`, `.css`, `.ts` and `.js` file under
 * `src/lib/lq-ai` and `src/routes/lq-ai`, except `__tests__/` directories (test
 * files and fixtures assert or carry colours on purpose). Comments are removed
 * before matching (`/* *\/` in CSS and script, `//` in script, `<!-- -->` in
 * markup), so an issue number such as `#282` in a comment is not a colour.
 *
 * Four rules, each with its own context:
 *
 * 1. No hex colour literal in CSS contexts: `.css` files, `<style>` blocks,
 *    `style="…"` attributes and `style:prop=` values. The token files are where
 *    hex belongs and are not scanned. A `var(--x, fallback)` fallback is removed
 *    first, so a fallback hex counts once, under rule 2. Hex in TypeScript
 *    string literals is out of scope here.
 * 2. No `var(--lq-…, fallback)` anywhere: the token is defined, so the fallback
 *    only hides a typo or a stale value. `components/shared/` is excluded: ADR
 *    0043 lets the primitives carry fallbacks so they render outside the shell.
 * 3. No Tailwind palette colour class (`text-gray-500`, `bg-rose-50`, …) in class
 *    contexts: `class=` attribute values, `class:name` directives, and string
 *    literals in `<script>` blocks and `.ts`/`.js` files (conditional class
 *    names live in ternaries and helper functions).
 * 4. No `dark:` utility in the same class contexts: the shell is light-only.
 *    The rules are independent, so `dark:bg-gray-900` counts under 3 and 4.
 *
 * Code that predates the rules is listed in ALLOWED with an exact count per
 * file and rule and a reason. The list only shrinks: a count above the entry
 * is a new offender, and a count below it means the entry is stale and must be
 * lowered (or removed at zero), so the list cannot hide new work.
 */
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
/** `web/`, resolved from this file so the test does not depend on the cwd. */
const webRoot = resolve(here, '..', '..', '..', '..');
const roots = [join(webRoot, 'src', 'lib', 'lq-ai'), join(webRoot, 'src', 'routes', 'lq-ai')];
const scannedExtensions = new Set(['.svelte', '.css', '.ts', '.js']);

/** Where hex belongs: the token definitions. Not scanned by rule 1. */
const TOKEN_FILES = new Set([
	'src/lib/lq-ai/styles/practice.css',
	'src/lib/lq-ai/styles/typography.css'
]);
/** ADR 0043 primitives may carry fallbacks. Not scanned by rule 2. */
const FALLBACK_DIRECTORY = 'src/lib/lq-ai/components/shared/';

type Rule = 'hex' | 'fallback' | 'palette-class' | 'dark-class';

const RULE_TEXT: Record<Rule, string> = {
	hex: 'rule 1, hex colour literal in CSS',
	fallback: 'rule 2, var(--lq-…, fallback)',
	'palette-class': 'rule 3, Tailwind palette colour class',
	'dark-class': 'rule 4, dark: utility'
};

const RULE_FIX: Record<Rule, string> = {
	hex: 'use var(--lq-…) with a token from src/lib/lq-ai/styles/practice.css',
	fallback:
		'write var(--lq-…) without a fallback; define the token in practice.css if it is missing',
	'palette-class':
		'use a class in the component <style> block that reads a --lq-* token (the lq-t-* classes are the pattern)',
	'dark-class': 'remove it; the LQ.AI shell is light-only and dark: never applies'
};

interface Allowed {
	/** Path relative to `web/`, with forward slashes. */
	file: string;
	rule: Rule;
	/** Exact number of hits today. Lower it when you remove one. */
	count: number;
	why: string;
}

const ALLOWED: readonly Allowed[] = [
	{
		file: 'src/routes/lq-ai/word-addin/oauth-start/+page.svelte',
		rule: 'fallback',
		count: 19,
		why: 'renders under the root layout (Office OAuth hop) where the token file is not loaded; the fallbacks go when that is fixed'
	},
	{
		file: 'src/lib/lq-ai/components/DualBrandingFooter.svelte',
		rule: 'palette-class',
		count: 6,
		why: 'pre-token footer; S1-5 rewrites it'
	},
	{
		file: 'src/lib/lq-ai/components/DualBrandingFooter.svelte',
		rule: 'dark-class',
		count: 3,
		why: 'pre-token footer; S1-5 rewrites it'
	},
	{
		file: 'src/lib/lq-ai/components/MessageBubble.svelte',
		rule: 'dark-class',
		count: 1,
		why: 'dark:prose-invert is not a colour class but is still a dark: utility; counted until P1.2 decides on dark mode'
	}
];

interface Hit {
	rule: Rule;
	/** 1-based line number in the file. */
	line: number;
	text: string;
}

// The palette regex is the S1-1a inventory's TW_COLOR, unchanged.
const paletteClass =
	/(?<![\w-])(?:bg|text|border|ring|from|to|via|fill|stroke|outline|decoration|divide|placeholder|accent|caret|shadow)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black)(?:-\d{2,3})?(?:\/\d{1,3})?(?![\w-])/g;
const darkClass = /(?<![\w-])dark:(?:[\w-]+:)*[\w-]+(?:\/\d+)?/g;
const hexColour = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g;
const lqFallback = /var\(\s*--lq-[\w-]+\s*,/g;
const anyFallback = /var\(\s*--[\w-]+\s*,/g;

function walk(dir: string, out: string[] = []): string[] {
	for (const name of readdirSync(dir)) {
		const full = join(dir, name);
		if (statSync(full).isDirectory()) {
			if (name !== '__tests__') walk(full, out);
		} else if (scannedExtensions.has(extensionOf(name))) {
			out.push(full);
		}
	}
	return out;
}

function extensionOf(name: string): string {
	const dot = name.lastIndexOf('.');
	return dot === -1 ? '' : name.slice(dot);
}

function toPosix(path: string): string {
	return path.split(sep).join('/');
}

/** Replaces `src[start, end)` with spaces, keeping newlines so offsets and lines stay true. */
function blank(src: string, start: number, end: number): string {
	return src.slice(0, start) + src.slice(start, end).replace(/[^\n]/g, ' ') + src.slice(end);
}

interface Span {
	start: number;
	end: number;
}

/** Blanks CSS `/* *\/` comments, leaving quoted strings alone. */
function stripCssComments(src: string): string {
	let out = src;
	let i = 0;
	while (i < src.length) {
		const c = src[i];
		if (c === '"' || c === "'") {
			i = endOfQuoted(src, i);
		} else if (c === '/' && src[i + 1] === '*') {
			const close = src.indexOf('*/', i + 2);
			const end = close === -1 ? src.length : close + 2;
			out = blank(out, i, end);
			i = end;
		} else {
			i++;
		}
	}
	return out;
}

/** Index just past the closing quote of the string that opens at `start`. */
function endOfQuoted(src: string, start: number): number {
	const quote = src[start];
	let i = start + 1;
	while (i < src.length && src[i] !== quote && src[i] !== '\n') {
		i += src[i] === '\\' ? 2 : 1;
	}
	return Math.min(i + 1, src.length);
}

/** Characters after which a `/` starts a regular expression rather than a division. */
const regexAllowedAfter = new Set([
	'',
	'(',
	',',
	'=',
	':',
	'[',
	'!',
	'&',
	'|',
	'?',
	'{',
	'}',
	';',
	'+',
	'-',
	'*',
	'%',
	'<',
	'>',
	'~',
	'^'
]);

/**
 * Tokenises JavaScript or TypeScript just enough to tell strings, comments and
 * regular expressions apart. Returns the source with comments blanked and the
 * spans of the string literals (a template literal is one opaque span).
 */
function scanScript(src: string): { code: string; strings: Span[] } {
	let code = src;
	const strings: Span[] = [];
	let lastSignificant = '';
	let lastWord = '';
	let i = 0;
	while (i < src.length) {
		const c = src[i];
		const next = src[i + 1];
		if (c === '/' && next === '/') {
			const newline = src.indexOf('\n', i);
			const end = newline === -1 ? src.length : newline;
			code = blank(code, i, end);
			i = end;
		} else if (c === '/' && next === '*') {
			const close = src.indexOf('*/', i + 2);
			const end = close === -1 ? src.length : close + 2;
			code = blank(code, i, end);
			i = end;
		} else if (c === '"' || c === "'") {
			const end = endOfQuoted(src, i);
			strings.push({ start: i, end });
			i = end;
			lastSignificant = c;
		} else if (c === '`') {
			const end = endOfTemplate(src, i);
			strings.push({ start: i, end });
			i = end;
			lastSignificant = c;
		} else if (
			c === '/' &&
			(regexAllowedAfter.has(lastSignificant) || ['return', 'typeof', 'case'].includes(lastWord))
		) {
			i = endOfRegex(src, i);
			lastSignificant = '/';
		} else {
			if (/\s/.test(c)) {
				i++;
				continue;
			}
			if (/[\w$]/.test(c)) {
				let j = i;
				while (j < src.length && /[\w$]/.test(src[j])) j++;
				lastWord = src.slice(i, j);
				lastSignificant = 'a';
				i = j;
				continue;
			}
			lastWord = '';
			lastSignificant = c;
			i++;
		}
	}
	return { code, strings };
}

/** Index just past the closing backtick of the template literal at `start`, `${}` included. */
function endOfTemplate(src: string, start: number): number {
	let i = start + 1;
	while (i < src.length) {
		const c = src[i];
		if (c === '\\') {
			i += 2;
		} else if (c === '`') {
			return i + 1;
		} else if (c === '$' && src[i + 1] === '{') {
			let depth = 1;
			i += 2;
			while (i < src.length && depth > 0) {
				const d = src[i];
				if (d === '"' || d === "'") {
					i = endOfQuoted(src, i);
				} else if (d === '`') {
					i = endOfTemplate(src, i);
				} else {
					if (d === '{') depth++;
					if (d === '}') depth--;
					i++;
				}
			}
		} else {
			i++;
		}
	}
	return src.length;
}

/** Index just past a regular-expression literal that opens at `start`. */
function endOfRegex(src: string, start: number): number {
	let i = start + 1;
	let inClass = false;
	while (i < src.length && src[i] !== '\n') {
		const c = src[i];
		if (c === '\\') {
			i += 2;
			continue;
		}
		if (c === '[') inClass = true;
		else if (c === ']') inClass = false;
		else if (c === '/' && !inClass) {
			i++;
			while (i < src.length && /[a-z]/i.test(src[i])) i++;
			return i;
		}
		i++;
	}
	return i;
}

/**
 * Reads an attribute value starting at `start` (a quote or `{`): quoted values
 * may contain `{…}` expressions, brace values are balanced. Returns the span of
 * the value including its delimiters.
 */
function readAttributeValue(src: string, start: number): Span | null {
	const open = src[start];
	if (open === '"' || open === "'") {
		let depth = 0;
		let i = start + 1;
		while (i < src.length) {
			const c = src[i];
			if (c === '{') depth++;
			else if (c === '}') depth--;
			else if (c === open && depth <= 0) return { start, end: i + 1 };
			i++;
		}
		return null;
	}
	if (open === '{') {
		let depth = 0;
		let i = start;
		while (i < src.length) {
			const c = src[i];
			if (c === '"' || c === "'") {
				i = endOfQuoted(src, i);
				continue;
			}
			if (c === '`') {
				i = endOfTemplate(src, i);
				continue;
			}
			if (c === '{') depth++;
			if (c === '}') {
				depth--;
				if (depth === 0) return { start, end: i + 1 };
			}
			i++;
		}
	}
	return null;
}

/** Spans of the attribute values that follow each match of `pattern` (which ends at the `=`). */
function attributeValues(markup: string, pattern: RegExp): Span[] {
	const spans: Span[] = [];
	for (const match of markup.matchAll(pattern)) {
		const valueStart = (match.index ?? 0) + match[0].length;
		const span = readAttributeValue(markup, valueStart);
		if (span) spans.push(span);
	}
	return spans;
}

/** The comment-free source and the spans that form each rule's context. */
interface Contexts {
	/** Whole file with comments blanked. Rule 2 runs on this. */
	code: string;
	/** CSS contexts. Rule 1 runs on these. */
	css: Span[];
	/** Class contexts. Rules 3 and 4 run on these. */
	classes: Span[];
}

const scriptBlock = /(<script\b[^>]*>)([\s\S]*?)<\/script>/g;
const styleBlock = /(<style\b[^>]*>)([\s\S]*?)<\/style>/g;

function contextsOf(file: string, src: string): Contexts {
	if (file.endsWith('.css')) {
		const code = stripCssComments(src);
		return { code, css: [{ start: 0, end: code.length }], classes: [] };
	}
	if (file.endsWith('.ts') || file.endsWith('.js')) {
		const { code, strings } = scanScript(src);
		return { code, css: [], classes: strings };
	}
	// .svelte: script blocks, then style blocks, then the markup that is left.
	let code = src;
	let markup = src;
	const css: Span[] = [];
	const classes: Span[] = [];
	for (const match of src.matchAll(scriptBlock)) {
		const start = (match.index ?? 0) + match[1].length;
		const end = start + match[2].length;
		const scanned = scanScript(src.slice(start, end));
		code = code.slice(0, start) + scanned.code + code.slice(end);
		for (const s of scanned.strings) classes.push({ start: start + s.start, end: start + s.end });
		markup = blank(markup, match.index ?? 0, (match.index ?? 0) + match[0].length);
	}
	for (const match of markup.matchAll(styleBlock)) {
		const start = (match.index ?? 0) + match[1].length;
		const end = start + match[2].length;
		code = code.slice(0, start) + stripCssComments(src.slice(start, end)) + code.slice(end);
		css.push({ start, end });
		markup = blank(markup, match.index ?? 0, (match.index ?? 0) + match[0].length);
	}
	for (const match of markup.matchAll(/<!--[\s\S]*?-->/g)) {
		const start = match.index ?? 0;
		code = blank(code, start, start + match[0].length);
		markup = blank(markup, start, start + match[0].length);
	}
	css.push(...attributeValues(markup, /(?<![\w:-])style\s*=\s*/g));
	css.push(...attributeValues(markup, /(?<![\w:-])style:[\w-]+(?:\|important)?\s*=\s*/g));
	classes.push(...attributeValues(markup, /(?<![\w:-])class\s*=\s*/g));
	for (const match of markup.matchAll(/(?<![\w:-])class:([\w\-/:.]+)/g)) {
		const start = (match.index ?? 0) + 'class:'.length;
		classes.push({ start, end: start + match[1].length });
	}
	return { code, css, classes };
}

/** Blanks the fallback of every `var(--x, fallback)`, from the comma to before the close paren. */
function withoutFallbacks(css: string): string {
	let out = css;
	for (const match of css.matchAll(anyFallback)) {
		const comma = (match.index ?? 0) + match[0].length - 1;
		let depth = 1;
		let i = comma + 1;
		while (i < css.length && depth > 0) {
			if (css[i] === '(') depth++;
			if (css[i] === ')') depth--;
			if (depth > 0) i++;
		}
		out = blank(out, comma, i);
	}
	return out;
}

function lineAt(src: string, index: number): number {
	let line = 1;
	for (let i = 0; i < index; i++) if (src[i] === '\n') line++;
	return line;
}

function hitsIn(file: string, src: string): Hit[] {
	const { code, css, classes } = contextsOf(file, src);
	const hits: Hit[] = [];
	const add = (rule: Rule, text: string, index: number) =>
		hits.push({ rule, text, line: lineAt(src, index) });

	if (!TOKEN_FILES.has(file)) {
		for (const span of css) {
			const text = withoutFallbacks(code.slice(span.start, span.end));
			for (const m of text.matchAll(hexColour)) add('hex', m[0], span.start + (m.index ?? 0));
		}
	}
	if (!file.startsWith(FALLBACK_DIRECTORY)) {
		for (const m of code.matchAll(lqFallback)) add('fallback', m[0], m.index ?? 0);
	}
	for (const span of classes) {
		const text = code.slice(span.start, span.end);
		for (const m of text.matchAll(paletteClass))
			add('palette-class', m[0], span.start + (m.index ?? 0));
		for (const m of text.matchAll(darkClass)) add('dark-class', m[0], span.start + (m.index ?? 0));
	}
	return hits;
}

interface Tally {
	file: string;
	rule: Rule;
	count: number;
	sites: string[];
}

describe('LQ.AI code uses --lq-* tokens, not hard-coded colours', () => {
	const files = roots.flatMap((root) => walk(root));
	let cssContexts = 0;
	const tallies = new Map<string, Tally>();
	for (const path of files) {
		const file = toPosix(relative(webRoot, path));
		const src = readFileSync(path, 'utf8');
		cssContexts += contextsOf(file, src).css.length;
		for (const hit of hitsIn(file, src)) {
			const key = `${file}\u0000${hit.rule}`;
			const tally = tallies.get(key) ?? { file, rule: hit.rule, count: 0, sites: [] };
			tally.count++;
			tally.sites.push(`line ${hit.line}: ${hit.text}`);
			tallies.set(key, tally);
		}
	}
	const allowedCount = (file: string, rule: Rule) =>
		ALLOWED.find((a) => a.file === file && a.rule === rule)?.count ?? 0;

	it('scans the LQ.AI source tree', () => {
		expect(files.length).toBeGreaterThan(100);
		expect(cssContexts).toBeGreaterThan(1);
	});

	for (const rule of Object.keys(RULE_TEXT) as Rule[]) {
		it(`adds no new hit for ${RULE_TEXT[rule]}`, () => {
			const offenders = [...tallies.values()]
				.filter((t) => t.rule === rule && t.count > allowedCount(t.file, t.rule))
				.map((t) => ({ ...t, allowed: allowedCount(t.file, t.rule) }));
			expect(
				offenders,
				`new hard-coded colour (${RULE_TEXT[rule]}); ${RULE_FIX[rule]}. The rules are in the header of token-guard.test.ts`
			).toEqual([]);
		});
	}

	it('keeps the allowlist exact', () => {
		const stale = ALLOWED.filter(
			(a) => (tallies.get(`${a.file}\u0000${a.rule}`)?.count ?? 0) < a.count
		).map((a) => ({ ...a, found: tallies.get(`${a.file}\u0000${a.rule}`)?.count ?? 0 }));
		expect(
			stale,
			'ALLOWED entry counts more hits than the file has; lower the count to the number found (remove the entry at zero)'
		).toEqual([]);
	});
});
