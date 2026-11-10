/**
 * The helper that reads a component's source for the scans that hold it to a rule: a start tag taken
 * whole, comments left out.
 */
import { describe, expect, it } from 'vitest';

import { startTags, withoutComments } from './source';

describe('startTags', () => {
	it('finds each start tag of the named element, and no other', () => {
		const source =
			'<div><MessageList a={1} /><MessageListItem /><p>MessageList</p><MessageList b="2">x</MessageList></div>';
		expect(startTags(source, 'MessageList')).toEqual([
			'<MessageList a={1} />',
			'<MessageList b="2">'
		]);
		expect(startTags(source, 'p')).toEqual(['<p>']);
		expect(startTags(source, 'Nothing')).toEqual([]);
	});

	it('takes a tag whole over several lines, with a `>` in an expression or a quoted value', () => {
		const source =
			'<Thing\n\ta="x > y"\n\tb={(m) => m.id > 2}\n\tc={{ d: "}" }}\n\tnewHarness={harnessChosen}\n/>\n<p>after</p>';
		const [tag] = startTags(source, 'Thing');
		expect(tag.startsWith('<Thing')).toBe(true);
		expect(tag.endsWith('/>')).toBe(true);
		expect(tag).toContain('newHarness={harnessChosen}');
		expect(tag).not.toContain('after');
	});

	it('does not take a name with a longer name, a namespace or a dash', () => {
		expect(
			startTags('<details-x a /><details:x a /><details.x a /><details a>', 'details')
		).toEqual(['<details a>']);
	});
});

describe('withoutComments', () => {
	it('leaves out markup, block and line comments, and keeps the code around them', () => {
		const source =
			'<!-- <details open={x}> -->\n<details bind:open={a}></details>\n/* open={y} */\n// open={z}\nconst a = 1;';
		const code = withoutComments(source);
		expect(code).not.toContain('open={x}');
		expect(code).not.toContain('open={y}');
		expect(code).not.toContain('open={z}');
		expect(code).toContain('<details bind:open={a}></details>');
		expect(code).toContain('const a = 1;');
	});
});
