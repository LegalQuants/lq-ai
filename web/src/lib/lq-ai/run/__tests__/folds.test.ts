/**
 * The rule for a fold (a native `<details>`) in the run panel and the model picker: its open state
 * is local state bound with `bind:open`, or nothing at all. Never `open={value}`.
 *
 * Svelte assigns `open` on an element drawn as `open={value}` again whenever any other attribute of
 * the element changes, so a fold the reader had opened or closed was shut or opened by a poll of the
 * run. That has happened here before (the comments in `RunActivity.svelte` and
 * `RunDocumentPicker.svelte` say so). A render cannot show it, because a render never toggles
 * anything; what can be checked is the source, as the scan of the components does for markup that
 * loads or navigates (`text-safety.test.ts`).
 */
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { startTags, withoutComments } from './source';

const RUN = fileURLToPath(new URL('../../components/run/', import.meta.url));
const MODEL_PICKER = fileURLToPath(new URL('../../components/ModelPicker.svelte', import.meta.url));

/** Every `<details ...>` start tag in some source, whole. */
const detailsTags = (source: string): string[] => startTags(source, 'details');

/**
 * Whether a start tag gives `open` a value from outside the element: `open={value}`, `open="..."`,
 * or the shorthand `{open}`. `bind:open={...}` is the element's state bound to a variable, and
 * `data-open=...` is another attribute altogether.
 */
function opensFromAValue(tag: string): boolean {
	return /(?:^|\s)open\s*=/.test(tag) || /\{\s*open\s*\}/.test(tag);
}

/** `bind:open={state}`, or the shorthand `bind:open` for a variable called `open`. */
const BINDS_OPEN = /\sbind:open(?:=\{|[\s>])/;

describe('the scan for a fold that is told whether to be open', () => {
	it('sees `open={value}`, in any place among the attributes, over one line or several', () => {
		expect(opensFromAValue('<details class="a" open={x}>')).toBe(true);
		expect(opensFromAValue('<details open={x} class="a">')).toBe(true);
		expect(opensFromAValue('<details class="a" open="open">')).toBe(true);
		expect(opensFromAValue('<details class="a" open = {x}>')).toBe(true);
		expect(
			opensFromAValue('<details\n\tclass="a"\n\topen={awaiting || expanded}\n\tdata-x="y"\n>')
		).toBe(true);
		expect(opensFromAValue('<details {open}>')).toBe(true);
	});

	it('lets `bind:open`, another attribute with `open` in its name, and no attribute at all pass', () => {
		expect(opensFromAValue('<details class="a" bind:open={lineOpen}>')).toBe(false);
		expect(opensFromAValue('<details bind:open={x} class="a" data-testid="b">')).toBe(false);
		expect(opensFromAValue('<details class="a" data-open="1" aria-open={x}>')).toBe(false);
		expect(opensFromAValue('<details class="a" on:toggle={onToggle}>')).toBe(false);
		expect(opensFromAValue('<details>')).toBe(false);
	});

	it('reads a start tag whole when an attribute holds a `>`, a quote or a brace', () => {
		const source =
			'<details class="a" data-x={a > b} title="b > c" open={c}><summary>s</summary></details>';
		const [tag] = detailsTags(source);
		expect(tag).toBe('<details class="a" data-x={a > b} title="b > c" open={c}>');
		expect(opensFromAValue(tag)).toBe(true);
		const braces = '<details data-x={ {a: "}"}.a } bind:open={x}>';
		expect(detailsTags(braces)).toEqual([braces]);
		const nested = '<details data-x={ {a: 1}.a > 0 } bind:open={x}><summary>s</summary></details>';
		expect(detailsTags(nested)).toEqual(['<details data-x={ {a: 1}.a > 0 } bind:open={x}>']);
	});

	it('finds every `<details` in a source, and only those', () => {
		const source =
			'<details bind:open={a}><summary>x</summary><details class="inner"></details></details>' +
			'<Detailsish open={x} /><p>details open={x}</p>';
		expect(detailsTags(source)).toEqual(['<details bind:open={a}>', '<details class="inner">']);
	});

	it('ignores a comment that names the pattern it forbids', () => {
		const source = '<!-- never <details open={x}> -->\n<details bind:open={a}></details>';
		expect(detailsTags(withoutComments(source))).toEqual(['<details bind:open={a}>']);
	});
});

describe('every fold in the run panel and the model picker', () => {
	const files = [
		...readdirSync(RUN)
			.filter((name) => name.endsWith('.svelte'))
			.sort()
			.map((name) => `${RUN}${name}`),
		MODEL_PICKER
	];
	const named = (path: string) => path.slice(path.lastIndexOf('/') + 1);

	it('are found, so the checks below look at something', () => {
		const tags = files.flatMap((path) => detailsTags(withoutComments(readFileSync(path, 'utf8'))));
		expect(files.length).toBeGreaterThanOrEqual(20);
		expect(tags.length).toBeGreaterThanOrEqual(15);
		// The lines of the column are bound to state of their own: the plan, the tasks, the answer,
		// the direct answer, a run that stopped before a plan, and the document picker.
		expect(tags.filter((tag) => BINDS_OPEN.test(tag)).length).toBeGreaterThanOrEqual(6);
		for (const name of [
			'RunPlanCard.svelte',
			'RunChildCard.svelte',
			'RunAnswerRow.svelte',
			'RunDirectRow.svelte',
			'RunNoPlanRow.svelte'
		]) {
			const own = detailsTags(withoutComments(readFileSync(`${RUN}${name}`, 'utf8')));
			expect(
				own.some((tag) => BINDS_OPEN.test(tag)),
				`${name} binds its line's open state`
			).toBe(true);
		}
	});

	it.each(files.map((path) => [named(path), path] as const))(
		'%s has no <details> that is given `open={value}`',
		(_name, path) => {
			for (const tag of detailsTags(withoutComments(readFileSync(path, 'utf8')))) {
				expect(opensFromAValue(tag), tag).toBe(false);
			}
		}
	);
});
