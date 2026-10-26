/**
 * Text that would do harm if anything between the API and the screen turned it into
 * markup. Model output, a document's file name, a chat's title and a profile's wording
 * all arrive as strings the run code does not control, so the helpers must hand them
 * back as the same strings and the components must show them as text.
 */
import { expect } from 'vitest';

export const HOSTILE_STRINGS: readonly string[] = [
	'<img src=x onerror=alert(1)>',
	'<script>alert(1)</script>',
	'[x](javascript:alert(1))',
	'"><svg/onload=alert(1)>',
	'\'><iframe srcdoc="<script>alert(1)</script>"></iframe>',
	'</title></script><img src=x onerror=alert(1)>',
	'<a href="javascript:alert(1)">open</a>',
	'&lt;script&gt;alert(1)&lt;/script&gt;',
	"{@html '<img src=x onerror=alert(1)>'}",
	'javascript:alert(1)'
];

const TAG =
	/<([a-zA-Z][\w:-]*)((?:\s+[^\s"'<>/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)\s*\/?>/g;
const ATTRIBUTE = /([^\s"'<>/=]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?/g;

export interface Element {
	tag: string;
	/** The names, not the values, of its attributes. */
	attributes: string[];
}

/**
 * Every element in some markup. A tag only counts when it is well formed, with each
 * attribute value quoted, so text that was escaped (`&lt;img`) is not an element, and a
 * quote that broke out of an attribute value shows up as an attribute that is not
 * supposed to be there.
 */
export function elementsIn(html: string): Element[] {
	return [...html.matchAll(TAG)].map((tag) => ({
		tag: tag[1].toLowerCase(),
		attributes: [...tag[2].matchAll(ATTRIBUTE)].map((attribute) => attribute[1].toLowerCase())
	}));
}

const ATTRIBUTE_WITH_VALUE = /([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;

/** The value of every attribute called `name`, on every element in some markup. */
export function attributeValues(html: string, name: string): string[] {
	const values: string[] = [];
	for (const tag of html.matchAll(TAG)) {
		for (const attribute of tag[2].matchAll(ATTRIBUTE_WITH_VALUE)) {
			if (attribute[1].toLowerCase() === name) {
				values.push(attribute[2] ?? attribute[3] ?? attribute[4] ?? '');
			}
		}
	}
	return values;
}

function escapeForPattern(text: string): string {
	return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * `output` is a plain string made from `input`: once every copy of `input` is taken out
 * of it (as it is, with its first letter capitalised, or written inside JSON), what is
 * left is the helper's own words and holds no angle bracket and no entity. So nothing
 * wrapped the text in markup, and nothing escaped it into entities that a component
 * would then show literally. Where the helper echoes the text, the caller checks that
 * the echo is intact.
 */
export function expectPlainText(output: unknown, input: string, label: string): void {
	expect(typeof output, `${label}: a string`).toBe('string');
	const copies = new RegExp(
		[input, JSON.stringify(input).slice(1, -1)].map(escapeForPattern).join('|'),
		'gi'
	);
	const rest = (output as string).replace(copies, '');
	expect(
		rest,
		`${label}: what is left of the output once ${JSON.stringify(input)} is taken out`
	).not.toMatch(/[<>]|&(?:[a-z][a-z0-9]*|#\d+|#x[0-9a-f]+);/i);
}
