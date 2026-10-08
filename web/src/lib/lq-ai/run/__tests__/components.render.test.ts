/**
 * The run components rendered to HTML in node, with no DOM.
 *
 * Svelte compiles a component for the server when it is imported under vitest's node
 * environment, so `render` from `svelte/server` gives the markup a person's browser
 * would be sent, with every `$:` statement run and no `onMount`. That is enough to see
 * what the panel says and, for text from a model or a document, that it arrives as
 * text: the same components are rendered twice, once with hostile strings and once with
 * plain ones, and the hostile page must have exactly the same elements and attributes.
 *
 * It cannot see what needs a browser: clicks, the open state of the model picker, the
 * follower's fetches, DOMPurify.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';

import type {
	OrchestrationChatRun,
	ProfileAvailability,
	PromptRead,
	RunDocument,
	RunDocumentsRead,
	SessionTraceRead,
	TraceStepName
} from '../../api/orchestration';
import type { Message } from '../../types';
import RunActiveNotice from '../../components/run/RunActiveNotice.svelte';
import RunAnswerNote from '../../components/run/RunAnswerNote.svelte';
import RunAnswerRow from '../../components/run/RunAnswerRow.svelte';
import RunChildCard from '../../components/run/RunChildCard.svelte';
import RunDirectRow from '../../components/run/RunDirectRow.svelte';
import RunDocumentPicker from '../../components/run/RunDocumentPicker.svelte';
import RunKnowledgeBases from '../../components/run/RunKnowledgeBases.svelte';
import RunMessage from '../../components/run/RunMessage.svelte';
import RunNoPlanRow from '../../components/run/RunNoPlanRow.svelte';
import RunModePanel from '../../components/run/RunModePanel.svelte';
import MessageList from '../../components/MessageList.svelte';
import ModelPicker from '../../components/ModelPicker.svelte';
import RunPlanCard from '../../components/run/RunPlanCard.svelte';
import RunPromptRow from '../../components/run/RunPromptRow.svelte';
import RunSetup from '../../components/run/RunSetup.svelte';
import RunSources from '../../components/run/RunSources.svelte';
import RunWrote from '../../components/run/RunWrote.svelte';
import {
	RUNS_START_FROM_A_CHAT_TEXT,
	answersDirectly,
	sendWording,
	unavailableReason
} from '../composer';
import { DIRECT_NOTE, runActivity } from '../activity';
import { formatUsd } from '../format';
import { IDLE, type Load } from '../load';
import { planView } from '../plan';
import { turnView } from '../trace';
import {
	allRuns,
	documents,
	legacyRun,
	profiles,
	prompt,
	run,
	thread as recordedThread,
	trace,
	whileSearching,
	withRun
} from './fixtures';
import { HOSTILE_STRINGS, elementsIn } from './hostile';
import { startTags, withoutComments } from './source';

// ---- rendering and reading the markup ------------------------------------------------------------

/** The markup of a component, as a string. */
function markup(component: unknown, props: Record<string, unknown>): string {
	return render(component as never, { props: props as never }).body;
}

/** Every element in the markup, with the names (not the values) of its attributes. */
function elements(html: string): string[] {
	return elementsIn(html).map((element) => `${element.tag}[${element.attributes.join(',')}]`);
}

const LOADS_OR_NAVIGATES = [
	'href',
	'src',
	'srcdoc',
	'action',
	'formaction',
	'xlink:href',
	'poster'
];

const escapeText = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;');
const escapeAttribute = (text: string) => escapeText(text).replace(/"/g, '&quot;');
/** Svelte leaves `>` and `'` as they are; if it ever escapes them the checks should not care. */
const settled = (html: string) => html.replace(/&gt;/g, '>').replace(/&#39;|&#x27;/g, "'");

/** Whether `token` is in the markup as text or as an attribute value, escaped. */
function isShown(html: string, token: string): boolean {
	const page = settled(html);
	return page.includes(escapeText(token)) || page.includes(escapeAttribute(token));
}

/** Checks on a page that fail with a short message, not with the whole page. */
function page(html: string, label: string) {
	const found = (what: string | RegExp) =>
		typeof what === 'string' ? html.includes(what) : what.test(html);
	return {
		shows: (what: string | RegExp) =>
			expect(found(what), `${label} shows ${String(what)}`).toBe(true),
		hides: (what: string | RegExp) =>
			expect(found(what), `${label} does not show ${String(what)}`).toBe(false)
	};
}

// ---- hostile and plain text, one for one ---------------------------------------------------------

const SHAPES = [
	(n: number) => `<img src=x onerror=alert(${n})>`,
	(n: number) => `<script>alert(${n})</script>`,
	(n: number) => `[x](javascript:alert(${n}))`,
	(n: number) => `"><svg/onload=alert(${n})>`
];

/** Hands out one string per label: hostile, or plain text of the same kind in the same place. */
class Words {
	readonly given = new Map<string, string>();

	constructor(private readonly hostile: boolean) {}

	of = (label: string): string => {
		const n = this.given.size + 1;
		const text = this.hostile ? SHAPES[n % SHAPES.length](n) : `plain text ${n}`;
		this.given.set(label, text);
		return text;
	};
}

/** A recorded run with the text a model, a document or the owner supplies replaced by `say(label)`. */
function worded(base: OrchestrationChatRun, say: (label: string) => string): OrchestrationChatRun {
	const copy = structuredClone(base);
	copy.planning.goal = say('goal');
	copy.profile_title = say('profile title');
	copy.reads = say('reads');
	copy.profile = say('profile');
	copy.planning.model = say('model');
	copy.planning.child_skill_version = say('skill version');
	copy.planning.root_skill_version = say('orchestrator skill version');
	copy.planning.gateway_revision = say('gateway revision');
	const effects = (list: OrchestrationChatRun['effects'], owner: string) =>
		list.forEach((effect, position) => {
			const at = `${owner} step ${position}`;
			effect.effect_key = say(`${at} key`);
			effect.intent = say(`${at} intent`);
			if (effect.skill) effect.skill.name = say(`${at} skill`);
			if (effect.accounting) {
				effect.accounting.provider = say(`${at} provider`);
				effect.accounting.model = say(`${at} model`);
			}
			if (effect.step) {
				effect.step.reason = say(`${at} reason`);
				effect.step.label = say(`${at} label`);
				for (const key of Object.keys(effect.step.summary ?? {})) {
					if (typeof effect.step.summary?.[key] === 'string')
						effect.step.summary[key] = say(`${at} ${key}`);
				}
				// A search names the owner's files it found, inside a list of its summary.
				const found = effect.step.summary?.sources;
				if (Array.isArray(found)) {
					found.forEach((file, at2) => {
						if (file && typeof file === 'object') {
							(file as { filename?: string }).filename = say(`${at} found ${at2}`);
						}
					});
				}
			}
		});
	effects(copy.effects, 'planning');
	const tree = copy.tree;
	if (tree) {
		tree.plan.root.skill.name = say('orchestrator skill');
		tree.plan.children.forEach((child, position) => {
			child.task = {
				topic: say(`topic ${position}`),
				question: say(`question ${position}`),
				boundaries: say(`boundaries ${position}`),
				output_contract: say(`output contract ${position}`),
				stopping_condition: say(`stopping condition ${position}`)
			};
			child.budget_usd = say(`budget ${position}`);
			if (child.execution?.skill) child.execution.skill.name = say(`skill ${position}`);
		});
		tree.plan.documents?.forEach((doc, position) => (doc.filename = say(`document ${position}`)));
		effects(tree.root.effects, 'orchestrator');
		tree.children.forEach((child, position) => {
			child.tools?.forEach((tool, at) => (tool.label = say(`tool ${position}.${at}`)));
			if (child.outcome) {
				child.outcome.summary = say(`outcome ${position}`);
				child.outcome.findings = child.outcome.findings.map((_, at) =>
					say(`finding ${position}.${at}`)
				);
			}
			child.files.forEach((file, at) => (file.name = say(`file ${position}.${at}`)));
			effects(child.effects, `task ${position}`);
		});
		if (tree.result) tree.result.summary = say('combined answer');
		// The knowledge bases the plan names, which the owner approves it for.
		tree.plan.knowledge_bases?.forEach(
			(kb, position) => (kb.name = say(`knowledge base ${position}`))
		);
	}
	copy.planning.knowledge_bases?.forEach(
		(kb, position) => (kb.name = say(`intake knowledge base ${position}`))
	);
	// The files the run's searches found, which the list under the answer names.
	copy.sources?.forEach((source, position) => (source.filename = say(`source ${position}`)));
	// An answer the orchestrator gave by itself, which the receipt page shows as text.
	if (typeof copy.direct_answer === 'string') copy.direct_answer = say('direct answer');
	if (copy.evidence_result) copy.evidence_result.gate_status = say('gate');
	return copy;
}

/** The same, but for a run that ended without a combined answer, so the overview of what it kept is shown. */
function withOverview(
	base: OrchestrationChatRun,
	say: (label: string) => string
): OrchestrationChatRun {
	const copy = worded(base, say);
	copy.status = 'failed';
	copy.stop_reason = say('stop reason');
	copy.tree!.result = null;
	copy.tree!.partial_summary = say('overview');
	return copy;
}

/** A run whose statuses are not any the client knows, which end up in attributes and class names. */
function withStatuses(
	base: OrchestrationChatRun,
	say: (label: string) => string
): OrchestrationChatRun {
	const copy = worded(base, say);
	copy.status = say('run status');
	copy.tree!.status = say('tree status');
	copy.tree!.children.forEach((child, position) => {
		child.status = say(`task ${position} status`);
		child.effects.forEach(
			(effect, at) => (effect.status = say(`task ${position} step ${at} status`))
		);
	});
	copy.effects.forEach((effect, at) => (effect.status = say(`planning step ${at} status`)));
	return copy;
}

interface Pair {
	hostile: string;
	plain: string;
	words: Words;
}

/** Renders `build(say)` once with hostile text and once with plain text. */
function renderBoth(build: (say: (label: string) => string) => string): Pair {
	const words = new Words(true);
	const hostile = build(words.of);
	const plain = build(new Words(false).of);
	return { hostile, plain, words };
}

/** The hostile page has the elements and attributes of the plain one, and shows each word as text. */
function expectOnlyText(pair: Pair, shown: string[], label: string): void {
	const { hostile, plain, words } = pair;
	expect(elements(hostile), `${label}: the same elements and attributes`).toEqual(elements(plain));
	page(hostile, label).hides(/<(?:img|script|svg|iframe|object|embed|a)\b/i);
	const names = elements(hostile)
		.flatMap((tag) => tag.slice(tag.indexOf('[') + 1, -1).split(','))
		.filter(Boolean);
	expect(
		names.filter((name) => /^on/i.test(name)),
		`${label}: no event handler`
	).toEqual([]);
	expect(
		names.filter((name) => LOADS_OR_NAVIGATES.includes(name.toLowerCase())),
		`${label}: no link or load`
	).toEqual([]);
	page(hostile, label).hides(/(?:href|src|action)\s*=\s*["']?\s*javascript:/i);
	for (const wording of shown) {
		const token = words.given.get(wording);
		expect(token, `${label}: ${wording} was given`).toBeDefined();
		expect(isShown(hostile, token!), `${label}: ${wording} is shown, as text`).toBe(true);
	}
}

describe('the check itself', () => {
	const words = new Words(true);
	const token = words.of('text');
	const plain = '<p class="a" id="b">plain text 1</p>';
	const pairWith = (hostile: string): Pair => ({ hostile, plain, words });

	it('passes text that arrives escaped', () => {
		const hostile = `<p class="a" id="b">${escapeText(token)}</p>`;
		expect(() => expectOnlyText(pairWith(hostile), ['text'], 'escaped')).not.toThrow();
	});

	it('catches text that became an element', () => {
		expect(() =>
			expectOnlyText(pairWith(`<p class="a" id="b">${token}</p>`), ['text'], 'raw')
		).toThrow();
	});

	it('catches an attribute that was broken out of', () => {
		const breakout = `<p class="a" id="b" onmouseover="alert(1)">${escapeText(token)}</p>`;
		expect(() => expectOnlyText(pairWith(breakout), ['text'], 'breakout')).toThrow();
	});

	it('catches a link that was made', () => {
		const link = `<p class="a" id="b" href="javascript:alert(1)">${escapeText(token)}</p>`;
		expect(() => expectOnlyText(pairWith(link), ['text'], 'link')).toThrow();
	});

	it('catches text that is not shown at all', () => {
		expect(() =>
			expectOnlyText(pairWith('<p class="a" id="b">something else</p>'), ['text'], 'missing')
		).toThrow();
	});
});

// ---- the run panel, with hostile text everywhere a run carries it --------------------------------

const DELIVERED = run('documents.completed');

/** What the panel shows of a run that was delivered, in the receipt view. */
const SHOWN_WHEN_DELIVERED = [
	'goal',
	'profile title',
	'profile',
	'model',
	'gateway revision',
	'orchestrator skill',
	// The prompt version the run pinned is part of the heading of a New harness run.
	'orchestrator skill version',
	'topic 0',
	'topic 1',
	'question 0',
	'boundaries 0',
	'output contract 0',
	'stopping condition 0',
	'skill 0',
	'document 0',
	'document 1',
	'reads',
	'tool 0.0',
	'tool 1.1',
	'outcome 0',
	'finding 0.0',
	'file 0.0',
	'combined answer',
	'planning step 0 key',
	'planning step 0 intent',
	'planning step 0 skill',
	'planning step 0 provider',
	'planning step 0 model',
	'gate'
];

describe('the run panel shows text from a model or a document as text', () => {
	it.each(['receipt', 'thread'] as const)('a delivered run, in the %s view', (mode) => {
		const pair = renderBoth((say) =>
			markup(RunMessage, { rootId: DELIVERED.root_id, mode, run: worded(DELIVERED, say) })
		);
		const onlyInReceipts = ['goal', 'combined answer'];
		expectOnlyText(
			pair,
			SHOWN_WHEN_DELIVERED.filter(
				(wording) => mode === 'receipt' || !onlyInReceipts.includes(wording)
			),
			`delivered ${mode}`
		);
	});

	it('a run that ended without a combined answer, with the overview of what it kept', () => {
		const pair = renderBoth((say) =>
			markup(RunMessage, {
				rootId: DELIVERED.root_id,
				mode: 'thread',
				run: withOverview(DELIVERED, say)
			})
		);
		expectOnlyText(pair, ['overview', 'stop reason', 'topic 0', 'outcome 0'], 'overview');
	});

	it('a run whose statuses are not ones the client knows', () => {
		const pair = renderBoth((say) =>
			markup(RunMessage, {
				rootId: DELIVERED.root_id,
				mode: 'receipt',
				run: withStatuses(DELIVERED, say)
			})
		);
		// Statuses go into attributes and class names: they must come out quoted and escaped, which
		// `expectOnlyText` sees as the same attributes on the same elements, none of them new.
		expectOnlyText(pair, ['run status', 'topic 0', 'planning step 0 status'], 'statuses');
		page(pair.hostile, 'statuses').shows(
			`data-status="${escapeAttribute(pair.words.given.get('run status')!)}"`
		);
	});

	it('a run with refused tool calls and markup already in its recorded answers', () => {
		const recorded = run('refusals-and-partial');
		expect(JSON.stringify(recorded)).toContain('<b>Renewal</b>');
		const shown = page(
			markup(RunMessage, { rootId: recorded.root_id, mode: 'receipt', run: recorded }),
			'refusals'
		);
		shown.hides('<b>Renewal</b>');
		shown.shows('&lt;b>Renewal&lt;/b>');
	});

	it('a run awaiting approval, where the plan card offers its buttons', () => {
		const awaiting = run('documents.awaiting-approval');
		const pair = renderBoth((say) =>
			markup(RunMessage, { rootId: awaiting.root_id, mode: 'thread', run: worded(awaiting, say) })
		);
		expectOnlyText(
			pair,
			['topic 0', 'question 1', 'document 1', 'tool 0.0', 'reads', 'model'],
			'awaiting approval'
		);
		page(pair.plain, 'plain').shows('data-testid="lq-ai-run-approve"');
		page(pair.hostile, 'hostile').shows('data-testid="lq-ai-run-approve"');
	});
});

describe('the plan card on its own', () => {
	it('shows what it is asked to approve as text', () => {
		const awaiting = run('documents.awaiting-approval');
		const pair = renderBoth((say) => {
			const value = worded(awaiting, say);
			return markup(RunPlanCard, {
				view: planView(value),
				line: runActivity(value)[0],
				state: 'proposed',
				awaiting: true
			});
		});
		expectOnlyText(
			pair,
			[
				'topic 0',
				'question 0',
				'boundaries 1',
				'output contract 1',
				'stopping condition 1',
				'document 0',
				'tool 1.2',
				'reads',
				'model'
			],
			'plan card'
		);
	});

	describe('says what a task may spend and for how many tool turns, then that one answer follows', () => {
		const card = (value: OrchestrationChatRun, label: string) =>
			page(
				markup(RunPlanCard, {
					view: planView(value),
					line: runActivity(value)[0],
					state: 'proposed',
					awaiting: true
				}).replace(/<!--[\s\S]*?-->/g, ''),
				label
			);

		it('for each task of a recorded plan', () => {
			card(run('documents.awaiting-approval'), 'selected documents').shows(
				/\$3\.4686 · up to 5 tool turns, then one answer/
			);
			card(run('awaiting-approval'), 'fixed document').shows(
				/\$0\.7434 · up to 2 tool turns, then one answer/
			);
		});

		it('in the singular for one turn', () => {
			const one = structuredClone(run('awaiting-approval'));
			one.tree!.plan.children[0].turn_limit = 1;
			card(one, 'one turn').shows(/up to 1 tool turn, then one answer/);
		});

		it('not at all for a task with no tools, which has no tool turns', () => {
			const none = structuredClone(run('awaiting-approval'));
			for (const child of none.tree!.children) child.tools = [];
			for (const child of none.tree!.plan.children) child.tools = {};
			card(none, 'no tools').hides(/tool turns?|then one answer/);
		});
	});
});

// ---- the composer's components ----------------------------------------------------------------------

describe('the composer shows a profile, a file and a run in another chat as text', () => {
	const docs = documents().documents;
	const [readable, unreadable] = [docs[1], docs[2]];

	it('the document picker, with a hostile file name, file id and reason', () => {
		const pair = renderBoth((say) => {
			const rows: RunDocument[] = [
				{ ...readable, file_id: say('readable id'), filename: say('readable name') },
				{
					...unreadable,
					file_id: say('unreadable id'),
					filename: say('unreadable name'),
					reason: say('unreadable reason')
				}
			];
			return markup(RunDocumentPicker, { documents: rows, selected: [rows[0].file_id], max: 8 });
		});
		expectOnlyText(
			pair,
			['readable name', 'unreadable name', 'unreadable reason'],
			'document picker'
		);
		page(pair.hostile, 'document picker').shows('data-number="1"');
	});

	it('the run mode panel, with hostile profile wording, tools and a reason', () => {
		const base = profiles('documents').profiles[0];
		const pair = renderBoth((say) => {
			const profile: ProfileAvailability = {
				...structuredClone(base),
				title: say('title'),
				summary: say('summary'),
				reads: say('reads'),
				planning_notice: say('notice'),
				model: say('model'),
				tools: [{ name: 'a_tool', label: say('tool'), phase: 'analysis' }],
				available: false,
				reason: 'operator_disabled',
				reason_text: say('reason')
			};
			return markup(RunModePanel, { profile });
		});
		expectOnlyText(
			pair,
			['summary', 'reads', 'notice', 'model', 'tool', 'reason'],
			'run mode panel'
		);
	});

	it('the notice naming a run in another chat, with a hostile chat title and status', () => {
		const pair = renderBoth((say) =>
			markup(RunActiveNotice, {
				active: {
					root_id: 'root-1',
					status: say('status'),
					profile: 'p',
					chat_id: say('chat id'),
					chat_title: say('title')
				},
				currentChatId: 'some-other-chat'
			})
		);
		expectOnlyText(pair, ['title', 'status'], 'active notice');
	});

	it('the model picker’s New harness entry, with a hostile label and pinned model', () => {
		const pair = renderBoth((say) =>
			markup(ModelPicker, {
				selectedId: 'lq-ai:new-harness',
				harness: {
					id: 'lq-ai:new-harness',
					label: say('label'),
					resolves: say('model'),
					disabledReason: null
				}
			})
		);
		expectOnlyText(pair, ['label', 'model'], 'model picker');
	});

	it('the model picker’s open list, with a hostile label, pinned model and reason', () => {
		const pair = renderBoth((say) =>
			markup(ModelPicker, {
				open: true,
				selectedId: 'smart',
				models: {
					object: 'list',
					data: [{ id: 'smart', object: 'model', owned_by: 'lq-ai', lq_ai_kind: 'alias' }]
				},
				harness: {
					id: 'lq-ai:new-harness',
					label: say('label'),
					resolves: say('model'),
					disabledReason: say('reason')
				}
			})
		);
		expectOnlyText(pair, ['label', 'model', 'reason'], 'model picker list');
	});

	it('the evidence line, with a hostile gate and kind of evidence', () => {
		const pair = renderBoth((say) =>
			markup(RunAnswerNote, {
				run: {
					evidence: 'citations',
					evidence_result: { gate_status: say('gate'), checked: 3, matched: 2, unmatched: 1 }
				}
			})
		);
		expectOnlyText(pair, ['gate'], 'evidence line');
		const unknownKind = renderBoth((say) =>
			markup(RunAnswerNote, { run: { evidence: say('kind'), evidence_result: null } })
		);
		expectOnlyText(unknownKind, ['kind'], 'unknown evidence kind');
	});
});

// ---- what a person sees ----------------------------------------------------------------------------------

describe('the composer says why a profile cannot be used', () => {
	const CODES = [
		'operator_disabled',
		'not_configured',
		'autonomous_opt_in_required',
		'chat_archived',
		'project_required',
		'project_unavailable',
		'project_not_permitted',
		'route_unavailable',
		'active_run'
	];
	// New harness as recorded where the operator has it on: available, with no reason.
	const base = profiles('documents').profiles[1];

	it.each(CODES)(
		'%s: a profile chosen and then unavailable shows its reason, in the server’s words or ours',
		(code) => {
			for (const reason_text of ['The server’s own sentence.', null]) {
				const profile: ProfileAvailability = {
					...structuredClone(base),
					available: false,
					reason: code,
					reason_text
				};
				const reason = unavailableReason(profile);
				expect(reason).toBeTruthy();
				const shown = page(markup(RunModePanel, { profile }), `${code} ${reason_text}`);
				if (code === 'active_run') {
					// The notice above the strip names the active run; the strip does not repeat it.
					shown.hides('role="alert"');
				} else {
					shown.shows(`role="alert">${escapeText(reason!)}</p>`);
				}
			}
		}
	);

	it('says nothing of the kind about a profile that can be used', () => {
		page(markup(RunModePanel, { profile: structuredClone(base) }), 'available').hides(
			'role="alert"'
		);
	});
});

/** Placeholders a template prints when it is handed a value it did not expect. */
const PLACEHOLDERS = [
	/undefined/,
	/\bNaN\b/,
	/\[object Object\]/,
	/Invalid Date/,
	/>\s*null\s*</,
	/="(?:undefined|null|NaN)"/
];

describe('every recorded run renders as a panel', () => {
	it.each(allRuns().map((entry) => [entry.label, entry.run] as const))('%s', (label, value) => {
		for (const mode of ['thread', 'receipt'] as const) {
			const shown = page(
				markup(RunMessage, { rootId: value.root_id, mode, run: value }),
				`${label} ${mode}`
			);
			shown.shows('data-testid="lq-ai-run-activity"');
			shown.shows(`data-status="${value.status}"`);
			for (const placeholder of PLACEHOLDERS) shown.hides(placeholder);
		}
	});

	it('draws one line per row of the run, in one column, and the plan line only for a run that has a plan', () => {
		for (const { label, run: value } of allRuns()) {
			for (const mode of ['thread', 'receipt'] as const) {
				const html = markup(RunMessage, { rootId: value.root_id, mode, run: value });
				expect(html.includes('data-testid="lq-ai-run-plan-card"'), label).toBe(value.tree !== null);
				const rows = runActivity(value);
				const drawn = [
					...html.matchAll(/<li class="row \w+[^"]*" data-row="(\w+)" data-state="(\w+)"/g)
				];
				expect(
					drawn.map((row) => [row[1], row[2]]),
					`${label} ${mode}`
				).toEqual(rows.map((row) => [row.kind, row.state]));
				// No grid of cards and no side-by-side tasks.
				expect(html, label).not.toContain('class="children');
			}
		}
	});

	it('opens only the plan awaiting approval in the chat, and every line on the receipt page', () => {
		const opened = (html: string) =>
			[...html.matchAll(/<details class="([\w-]+)[^"]*"([^>]*)>/g)]
				.filter((match) => /\bopen\b/.test(match[2]))
				.map((match) => match[1]);
		const awaiting = run('awaiting-approval');
		expect(
			opened(markup(RunMessage, { rootId: awaiting.root_id, mode: 'thread', run: awaiting }))
		).toEqual(['plan']);
		const done = run('completed');
		expect(opened(markup(RunMessage, { rootId: done.root_id, mode: 'thread', run: done }))).toEqual(
			[]
		);
		expect(
			opened(markup(RunMessage, { rootId: done.root_id, mode: 'receipt', run: done }))
		).toEqual(['plan', 'child', 'child', 'answer-row']);
	});
});

describe('the closed lines show a task topic as text', () => {
	it('a hostile topic in a closed line is escaped, in the text and in the hover title', () => {
		const value = run('documents.completed');
		const pair = renderBoth((say) =>
			markup(RunMessage, { rootId: value.root_id, mode: 'thread', run: worded(value, say) })
		);
		expectOnlyText(pair, ['topic 0', 'topic 1'], 'closed task lines');
		const summaries = [...pair.hostile.matchAll(/<summary[^>]*>([\s\S]*?)<\/summary>/g)].map(
			(match) => match[1]
		);
		for (const wording of ['topic 0', 'topic 1']) {
			const token = pair.words.given.get(wording)!;
			expect(
				summaries.some((summary) => isShown(summary, token)),
				`${wording} is in a closed line`
			).toBe(true);
		}
		// A closed line holds the topic and facts from the records; no finding, no summary text.
		for (const wording of ['finding 0.0', 'outcome 0']) {
			const token = pair.words.given.get(wording)!;
			expect(
				summaries.some((summary) => isShown(summary, token)),
				`${wording} is not in a closed line`
			).toBe(false);
		}
	});
});

describe('a task card prints its summary line only when no finding already says it', () => {
	const summaries = (value: OrchestrationChatRun) =>
		(
			markup(RunMessage, { rootId: value.root_id, mode: 'thread', run: value }).match(
				/<p class="summary[ "]/g
			) ?? []
		).length;

	it('not at all, where every finding begins with it (a Markdown answer’s summary is its own first line)', () => {
		for (const name of ['completed', 'documents.completed', 'halted'] as const) {
			expect(summaries(run(name)), name).toBe(0);
		}
	});

	it('for the task that has no findings, which would otherwise say nothing', () => {
		// One task answered, with markup in its summary; the other failed with no findings.
		expect(summaries(run('refusals-and-partial'))).toBe(1);
	});

	it('for each task of a run recorded before findings carried it', () => {
		expect(summaries(legacyRun('model-run'))).toBe(2);
	});
});

describe('the previous release’s runs', () => {
	it('show their plan with no tools and no documents listed, and what the plan did say', () => {
		const recorded = legacyRun('model-run');
		// Without the markers Svelte leaves between the parts of a template.
		const html = markup(RunMessage, {
			rootId: recorded.root_id,
			mode: 'receipt',
			run: recorded
		}).replace(/<!--[\s\S]*?-->/g, '');
		const shown = page(html, 'model-run');
		shown.shows('Plan approved');
		shown.shows('contract-qa v1.0.0');
		shown.shows(/data-testid="lq-ai-run-plan-tools"[^>]*>\s*none\s*</);
		shown.shows(/data-testid="lq-ai-run-plan-documents"[^>]*>\s*none listed\s*</);
		// No evidence fields on these runs: the line says what it always said.
		shown.shows('Model-generated; unverified.');
		shown.hides(/tool turns?|then one answer/);
	});

	it('say a plan that never arrived never arrived', () => {
		for (const name of ['fenced-plan-run', 'truncated-plan-run'] as const) {
			const shown = page(
				markup(RunMessage, {
					rootId: legacyRun(name).root_id,
					mode: 'thread',
					run: legacyRun(name)
				}),
				name
			);
			shown.hides('lq-ai-run-plan-card');
			shown.shows('The model could not produce a usable plan');
		}
	});
});

describe('a message that names no run', () => {
	const unnamed = (patch: Partial<Message>): Message => ({
		id: 'message-1',
		chat_id: 'chat-1',
		role: 'assistant',
		kind: 'run',
		content: '',
		created_at: '2026-10-06T08:55:09Z',
		...patch
	});

	it.each([null, undefined, ''])(
		'with autonomous_session_id %j says so, and shows nothing for a run called "null"',
		(id) => {
			const shown = page(
				markup(RunMessage, { message: unnamed({ autonomous_session_id: id }) }),
				`id ${String(id)}`
			);
			shown.shows('This message is not linked to a run.');
			shown.shows('data-status="loading"');
			shown.hides('lq-ai-run-activity');
			for (const placeholder of PLACEHOLDERS) shown.hides(placeholder);
			shown.hides(/Loading the run/);
			shown.hides(/\bnull\b/);
		}
	);

	it('with no message and no run, says the same', () => {
		page(markup(RunMessage, {}), 'no message').shows('This message is not linked to a run.');
	});

	it('with an id and no run yet, says it is loading', () => {
		const shown = page(
			markup(RunMessage, { message: unnamed({ autonomous_session_id: run('planning').root_id }) }),
			'named'
		);
		shown.shows('Loading the run…');
		shown.hides('not linked');
	});
});

// ---- how a run was set up, and what its model wrote ----------------------------------------------------

const loaded = <T>(value: T): Load<T> => ({ status: 'loaded', value });

/**
 * The markup with the comment markers Svelte leaves between the parts of a template taken
 * out, and the class names it adds to scope a component's styles (`svelte-1abc`), so that
 * a test can ask for `<dt>Route</dt>` and not for whatever hash this build gave the class.
 */
const bare = (html: string): string =>
	html
		.replace(/<!--[\s\S]*?-->/g, '')
		.replace(/\s?svelte-[a-z0-9]+/g, '')
		.replace(/ class=""/g, '');

/** The sentence under an answer that says how far to rely on it. */
function evidenceLine(html: string): string {
	return /data-testid="lq-ai-run-answer-evidence"[^>]*>\s*([^<]*?)\s*</.exec(html)?.[1] ?? '';
}

/** The opening tag of the first element with this test id. */
function tagOf(html: string, testId: string): string {
	return new RegExp(`<[a-z]+[^>]*data-testid="${testId}"[^>]*>`).exec(html)?.[0] ?? '';
}

/** A recorded trace with every text a model, a document or the owner wrote replaced by `say(label)`. */
function wordedTrace(base: SessionTraceRead, say: (label: string) => string): SessionTraceRead {
	const copy = structuredClone(base);
	copy.note = say('note');
	copy.calls.forEach((call, at) => {
		call.system.name = say(`call ${at} system name`);
		call.system.version = say(`call ${at} system version`);
		call.system.digest = say(`call ${at} system digest`);
		call.system.text = say(`call ${at} system text`);
		call.opening = say(`call ${at} opening`);
		call.tools = (call.tools ?? []).map((_, position) => ({
			type: 'function',
			function: {
				name: say(`call ${at} tool ${position} name`),
				description: say(`call ${at} tool ${position} description`),
				parameters: {
					[say(`call ${at} tool ${position} key`)]: say(`call ${at} tool ${position} value`)
				}
			}
		}));
	});
	copy.turns.forEach((turn, at) => {
		turn.text = say(`turn ${at} text`);
		turn.tool_calls = (turn.tool_calls ?? []).map((call, position) => ({
			...call,
			name: say(`turn ${at} call ${position} name`),
			arguments: say(`turn ${at} call ${position} arguments`)
		}));
	});
	return copy;
}

describe('the fold that says how a call was set up', () => {
	const ROOT = trace('root.completed');
	const PLANNED = trace('root.planned');
	const CHILD = trace('child.completed');

	const setup = (state: Load<SessionTraceRead>, step: TraceStepName = 'plan', more = {}) =>
		bare(markup(RunSetup, { rootId: 'root', sessionId: 'session', step, state, ...more }));

	it('is a closed fold, and draws without reading anything: a read starts only on a page, when a line is open', () => {
		const read = vi.fn();
		const html = setup(IDLE, 'plan', { fetchTrace: read, lineOpen: true });
		page(html, 'idle').shows('<summary>How this run was set up</summary>');
		page(html, 'idle').hides('Opening message');
		expect(tagOf(html, 'lq-ai-run-setup')).not.toMatch(/\bopen\b/);
		expect(read).not.toHaveBeenCalled();
	});

	it('says what the planning call was opened with: the pinned prompt, its digest, the opening and the check', () => {
		const html = setup(loaded(ROOT), 'plan');
		const [call] = ROOT.calls;
		const shown = page(html, 'plan setup');
		shown.shows('System prompt: new_harness/orchestrator.v2 (version 2)');
		shown.shows(`<code>${call.system.digest.slice(0, 12)}</code>`);
		shown.shows('<summary>Show the system prompt</summary>');
		shown.shows(escapeText(call.system.text!.slice(0, 80)));
		shown.shows('REQUEST\nExplain payment, renewal and termination questions independently.');
		// The first call is offered one tool, the one that hands the plan over.
		shown.shows('<span class="tool-name">propose_plan</span>');
		// Its description is the tool's own, read from the recording rather than written out here.
		const offered = call.tools![0] as { function: { description: string } };
		expect(offered.function.description.trim()).not.toBe('');
		expect(isShown(html, offered.function.description)).toBe(true);
		expect(html.match(/<summary>Schema<\/summary>/g)).toHaveLength(1);
		shown.hides('No tools were offered on this call.');
		shown.shows(
			"Rebuilt from this run's records. It matches the digest recorded when the call was sent."
		);
		shown.shows(escapeText(ROOT.note!.slice(0, 60)));
		shown.hides('This call has not been made yet.');
		shown.hides('class="check warn"');
		// The full digest is on record, but the line prints only its first characters.
		shown.hides(call.system.digest);
	});

	it('says the same of the combine call from the same trace', () => {
		const html = setup(loaded(ROOT), 'combine');
		page(html, 'combine setup').shows('STEP\nCombine\n\nREQUEST\n');
		page(html, 'combine setup').hides('STEP\nRespond');
		// The combine call is offered no tool. (Its system prompt, which is the same text as the
		// first call's, names `propose_plan`, so the list of tools offered is what is looked at.)
		page(html, 'combine setup').shows('No tools were offered on this call.');
		page(html, 'combine setup').hides('<span class="tool-name">propose_plan</span>');
	});

	it('lists a task’s tools by name and description, each with its schema in a fold of its own', () => {
		const html = setup(loaded(CHILD), 'task');
		const [call] = CHILD.calls;
		const shown = page(html, 'task setup');
		shown.shows('System prompt: new_harness/subagent.v2 (version 2)');
		shown.shows(`<code>${call.system.digest.slice(0, 12)}</code>`);
		for (const name of ['read_document', 'read_note', 'save_note']) {
			shown.shows(`<span class="tool-name">${name}</span>`);
		}
		shown.shows('Read back a working note this task saved earlier.');
		expect(html.match(/<summary>Schema<\/summary>/g)).toHaveLength(3);
		// The schema is JSON text, indented.
		shown.shows('&quot;additionalProperties&quot;: false'.replace(/&quot;/g, '"'));
		shown.hides('No tools were offered');
	});

	it('says a call has not been made yet when the trace does not have it', () => {
		const html = setup(loaded(PLANNED), 'combine');
		page(html, 'combine before it is made').shows('This call has not been made yet.');
		page(html, 'combine before it is made').hides('Opening message');
		page(html, 'combine before it is made').hides(PLANNED.note!.slice(0, 40));
	});

	it('warns, and says to treat it as approximate, when the rebuilt opening does not match what was sent', () => {
		const odd = structuredClone(ROOT);
		odd.calls[0].check = 'differs';
		const html = setup(loaded(odd), 'plan');
		page(html, 'differs').shows('class="check warn"');
		page(html, 'differs').shows('Treat it as approximate.');
		page(html, 'differs').hides('It matches the digest');
	});

	it('says no digest was recorded, or that the call is not made, and says nothing more where it was not rebuilt', () => {
		const state = (check: string, sent: boolean) => {
			const odd = structuredClone(ROOT);
			odd.calls[0].check = check as 'matches';
			odd.calls[0].sent = sent;
			return setup(loaded(odd), 'plan');
		};
		page(state('not_recorded', true), 'not recorded').shows(
			'No digest of what was sent was recorded for this call.'
		);
		page(state('not_recorded', false), 'not sent').shows('This call has not been made yet.');
		const unbuilt = state('not_rebuilt', true);
		expect(tagOf(unbuilt, 'lq-ai-run-setup-check')).toBe('');
	});

	it('says the pinned text is no longer installed, with no fold to open for it', () => {
		const odd = structuredClone(ROOT);
		odd.calls[0].system.text = null;
		const html = setup(loaded(odd), 'plan');
		page(html, 'text gone').shows(
			'The pinned text is no longer installed with this digest, so it cannot be shown.'
		);
		page(html, 'text gone').hides('Show the system prompt');
		page(html, 'text gone').shows('System prompt: new_harness/orchestrator.v2 (version 2)');
	});

	it('says the opening is not rebuilt for a run instructed by a skill, and never says so of a prompt', () => {
		const skilled = structuredClone(ROOT);
		skilled.calls[0].system = {
			kind: 'skill',
			name: 'orchestration-chat-demo',
			version: '1.0.0',
			digest: 'a'.repeat(64),
			text: 'The skill.'
		};
		skilled.calls[0].opening = null;
		skilled.calls[0].check = 'not_rebuilt';
		const html = setup(loaded(skilled), 'plan');
		page(html, 'skill').shows('Skill: orchestration-chat-demo (version 1.0.0)');
		page(html, 'skill').shows('<summary>Show the skill</summary>');
		page(html, 'skill').shows(
			'The opening message of this call is not rebuilt for a run instructed by a skill.'
		);
		const prompted = structuredClone(ROOT);
		prompted.calls[0].opening = null;
		page(setup(loaded(prompted), 'plan'), 'prompt').hides('instructed by a skill');
	});

	it('shows that it is reading, with nothing else yet, and keeps what it has while it reads again', () => {
		const first = setup({ status: 'loading', previous: null }, 'plan');
		page(first, 'reading').shows('role="status"');
		page(first, 'reading').shows('Reading how this call was set up…');
		page(first, 'reading').hides('Opening message');
		const again = setup({ status: 'loading', previous: ROOT }, 'plan');
		page(again, 'reading again').shows('Reading it again…');
		page(again, 'reading again').shows('System prompt: new_harness/orchestrator.v2 (version 2)');
		page(again, 'reading again').hides('Reading how this call was set up…');
	});

	it('says why it could not read, as an alert, and still shows what it had before', () => {
		const failed = setup({ status: 'failed', message: 'The run is gone.', previous: null }, 'plan');
		page(failed, 'failed').shows('role="alert"');
		page(failed, 'failed').shows('Could not read how this call was set up: The run is gone.');
		page(failed, 'failed').hides('Opening message');
		const kept = setup({ status: 'failed', message: 'Timed out', previous: ROOT }, 'plan');
		page(kept, 'failed after a read').shows('Could not read how this call was set up: Timed out');
		page(kept, 'failed after a read').shows('System prompt: new_harness/orchestrator.v2');
	});

	it('shows text a model, a document or the owner wrote as text, for every call of every trace', () => {
		for (const [name, base, step, shown] of [
			[
				'plan',
				ROOT,
				'plan',
				[
					'note',
					'call 0 system name',
					'call 0 system text',
					'call 0 opening',
					'call 0 system version'
				]
			],
			['combine', ROOT, 'combine', ['call 1 system text', 'call 1 opening']],
			[
				'task',
				CHILD,
				'task',
				[
					'note',
					'call 0 system text',
					'call 0 opening',
					'call 0 tool 0 name',
					'call 0 tool 0 description',
					'call 0 tool 1 name',
					'call 0 tool 2 description'
				]
			]
		] as const) {
			const pair = renderBoth((say) =>
				bare(
					markup(RunSetup, {
						rootId: 'root',
						sessionId: 'session',
						step,
						state: loaded(wordedTrace(base, say))
					})
				)
			);
			expectOnlyText(pair, [...shown], `setup fold: ${name}`);
		}
	});

	it('shows a hostile error message and a hostile system version as text', () => {
		const pair = renderBoth((say) =>
			bare(
				markup(RunSetup, {
					rootId: 'root',
					sessionId: 'session',
					step: 'plan',
					state: { status: 'failed', message: say('error'), previous: null }
				})
			)
		);
		expectOnlyText(pair, ['error'], 'setup fold: failed');
	});

	it('shows the conversation the planning call was shown, quoted in its opening as the server quotes it, as text', () => {
		// The server writes each earlier message under "User:" or "Assistant:", every line quoted.
		const thread = run('harness.follow-up.planning').planning.thread!;
		expect(thread.length).toBeGreaterThan(1);
		const quote = (message: { role: string; content: string; cut: boolean }) =>
			`${message.role === 'user' ? 'User' : 'Assistant'}:\n` +
			message.content
				.split('\n')
				.map((line) => (line ? `> ${line}` : '>'))
				.join('\n') +
			(message.cut ? '\n> [This message was cut to fit.]' : '');
		const pair = renderBoth((say) => {
			const messages = thread.map((message, at) => ({
				...message,
				content: say(`thread message ${at}`)
			}));
			const odd = structuredClone(ROOT);
			odd.calls[0].opening = [
				'STEP\nRespond',
				`REQUEST\n${say('request')}`,
				`CONVERSATION SO FAR\n${messages.map(quote).join('\n\n')}`
			].join('\n\n');
			return setup(loaded(odd), 'plan');
		});
		expectOnlyText(
			pair,
			['thread message 0', 'thread message 1', 'request'],
			'conversation in the opening'
		);
	});
});

describe('the fold that says what the model wrote', () => {
	const ROOT = trace('root.completed');
	const CHILD = trace('child.completed');
	const wrote = (turn: Parameters<typeof turnView>[0]) =>
		bare(markup(RunWrote, { turn: turnView(turn) }));

	it('is a closed fold; it shows the text the model wrote, in a block of its own', () => {
		const html = wrote(ROOT.turns[1]);
		expect(tagOf(html, 'lq-ai-run-wrote')).not.toMatch(/\bopen\b/);
		page(html, 'reply').shows('<summary>What the model wrote</summary>');
		page(html, 'reply').shows('Fees are due "within thirty (30) days" (Source: [1]).');
		expect(html).toMatch(/<pre class="text"[^>]*>Fees are due/);
	});

	it('says the model asked for tools when it wrote no text, then names each call with its arguments', () => {
		const html = wrote(CHILD.turns[0]);
		const shown = page(html, 'tool turn');
		shown.shows('No text; the model asked for tools.');
		shown.shows('<p class="name">read_document</p>');
		shown.shows('{"document": 1, "reason": "Read the MSA."}');
		shown.shows('<p class="name">save_note</p>');
		shown.hides('lq-ai-run-wrote-text');
		expect(html.match(/data-testid="lq-ai-run-wrote-call"/g)).toHaveLength(2);
	});

	it('says plainly when there was no text and no tool, or no reply', () => {
		page(wrote({ effect_key: 'k', status: 'completed', text: '', tool_calls: [] }), 'empty').shows(
			'The model wrote no text.'
		);
		page(wrote({ effect_key: 'k', status: 'uncertain', text: null }), 'unanswered').shows(
			'No reply was recorded for this call.'
		);
	});

	it('shows what the model wrote, its tool names and its arguments as text', () => {
		const pair = renderBoth((say) =>
			bare(
				markup(RunWrote, {
					turn: turnView({
						effect_key: 'k',
						status: 'completed',
						text: say('text'),
						tool_calls: [
							{ id: 'a', name: say('first name'), arguments: say('first arguments') },
							{ id: 'b', name: say('second name'), arguments: say('second arguments') }
						]
					})
				})
			)
		);
		expectOnlyText(
			pair,
			['text', 'first name', 'first arguments', 'second name', 'second arguments'],
			'what the model wrote'
		);
	});
});

describe('the lines of the column, with a trace read', () => {
	const DELIVERED = run('harness.completed');
	const AWAITING = run('harness.no-documents.awaiting-approval');
	const ROOT = trace('root.completed');
	const PLANNED = trace('root.planned');
	const CHILD = trace('child.completed');
	const rows = runActivity(DELIVERED);

	const wroteFolds = (html: string) => html.match(/data-testid="lq-ai-run-wrote"/g)?.length ?? 0;
	const setupFolds = (html: string) => html.match(/data-testid="lq-ai-run-setup"/g)?.length ?? 0;

	it('the plan line has a setup fold and the planning call’s reply', () => {
		const html = bare(
			markup(RunPlanCard, {
				view: planView(DELIVERED),
				line: rows[0],
				state: 'approved',
				rootId: DELIVERED.root_id,
				traceState: loaded(ROOT)
			})
		);
		expect(setupFolds(html)).toBe(1);
		expect(wroteFolds(html)).toBe(1);
		// The plan is handed over as a call to `propose_plan`: the model wrote no text, and the
		// plan is the call's arguments, shown exactly as written.
		const [call] = ROOT.turns[0].tool_calls!;
		page(html, 'plan line').shows('No text; the model asked for tools.');
		page(html, 'plan line').shows('<p class="name">propose_plan</p>');
		page(html, 'plan line').shows(escapeText(call.arguments.slice(0, 60)));
		page(html, 'plan line').hides('lq-ai-run-wrote-text');
		// Not the answer's reply, which belongs to the answer line.
		page(html, 'plan line').hides('Fees are due');
	});

	it('the plan line of a run that waits for approval reads the same, from the trace so far', () => {
		const html = bare(
			markup(RunPlanCard, {
				view: planView(AWAITING),
				line: runActivity(AWAITING)[0],
				state: 'proposed',
				awaiting: true,
				rootId: AWAITING.root_id,
				traceState: loaded(PLANNED)
			})
		);
		expect(setupFolds(html)).toBe(1);
		expect(wroteFolds(html)).toBe(1);
		page(html, 'plan awaiting').shows('data-testid="lq-ai-run-approve"');
	});

	it('the plan line has no setup fold, and reads nothing, where it has no run to read', () => {
		const read = vi.fn();
		const html = bare(
			markup(RunPlanCard, {
				view: planView(DELIVERED),
				line: rows[0],
				state: 'approved',
				fetchTrace: read
			})
		);
		expect(setupFolds(html)).toBe(0);
		expect(read).not.toHaveBeenCalled();
	});

	it('a task line has a setup fold, and a reply under each step that was a model’s turn', () => {
		const child = DELIVERED.tree!.children[0];
		const html = bare(
			markup(RunChildCard, {
				rootId: DELIVERED.root_id,
				index: 1,
				topic: rows[1].label,
				skill: 'new_harness/subagent.v1 (version 1)',
				child,
				line: rows[1],
				expanded: true,
				traceState: loaded(CHILD)
			})
		);
		expect(setupFolds(html)).toBe(1);
		expect(wroteFolds(html)).toBe(2);
		page(html, 'task line').shows('<p class="name">read_document</p>');
		page(html, 'task line').shows('Fees are due "within thirty (30) days" (Source: [1]).');
		// Each fold is inside the step that made the reply: its list item holds the step's own words.
		const steps = [...html.matchAll(/<li class="step[^"]*"[\s\S]*?<\/li>/g)].map((m) => m[0]);
		const withReply = steps.filter((step) => step.includes('lq-ai-run-wrote'));
		expect(withReply).toHaveLength(2);
		for (const step of withReply) expect(step).toContain('Asked the model');
	});

	it('a task line shows no reply until the trace has been read', () => {
		const child = DELIVERED.tree!.children[0];
		const props = {
			rootId: DELIVERED.root_id,
			index: 1,
			topic: rows[1].label,
			skill: 's',
			child,
			line: rows[1],
			expanded: true
		};
		expect(wroteFolds(bare(markup(RunChildCard, props)))).toBe(0);
		expect(
			wroteFolds(
				bare(markup(RunChildCard, { ...props, traceState: { status: 'loading', previous: null } }))
			)
		).toBe(0);
		// A reply from before keeps showing while the trace is read again.
		expect(
			wroteFolds(
				bare(markup(RunChildCard, { ...props, traceState: { status: 'loading', previous: CHILD } }))
			)
		).toBe(2);
	});

	it('the answer line has a setup fold and the combine call’s reply, and not the planning reply', () => {
		const html = bare(
			markup(RunAnswerRow, {
				run: DELIVERED,
				line: rows[rows.length - 1],
				expanded: true,
				traceState: loaded(ROOT)
			})
		);
		expect(setupFolds(html)).toBe(1);
		expect(wroteFolds(html)).toBe(1);
		page(html, 'answer line').shows('Fees are due "within thirty (30) days" (Source: [1]).');
		// What the planning call wrote is not on this line: its plan, the arguments of its call to
		// `propose_plan`. (The system prompt, which says what a plan looks like, is in the setup
		// fold of any call, so the plan's own words are the test.)
		const planned = ROOT.turns[0].tool_calls![0].arguments;
		expect(planned.length).toBeGreaterThan(100);
		page(html, 'answer line').hides(escapeText(planned.slice(0, 100)));
		page(html, 'answer line').hides('<p class="name">propose_plan</p>');
		// It sits under the step that asked the model to combine the answers.
		const step = [...html.matchAll(/<li class="step[^"]*"[\s\S]*?<\/li>/g)]
			.map((m) => m[0])
			.find((text) => text.includes('lq-ai-run-wrote'))!;
		expect(step).toContain('Asked the model to combine the tasks’ answers');
	});

	it('the answer line has no reply before the combine call exists', () => {
		const html = bare(
			markup(RunAnswerRow, {
				run: DELIVERED,
				line: rows[rows.length - 1],
				expanded: true,
				traceState: loaded(PLANNED)
			})
		);
		expect(wroteFolds(html)).toBe(0);
		page(html, 'answer line before the combine call').shows('This call has not been made yet.');
	});

	it('shows the replies of every line as text, for a trace full of hostile text', () => {
		const child = DELIVERED.tree!.children[0];
		const pair = renderBoth((say) =>
			bare(
				markup(RunChildCard, {
					rootId: DELIVERED.root_id,
					index: 1,
					topic: 'a task',
					skill: 's',
					child,
					line: rows[1],
					expanded: true,
					traceState: loaded(wordedTrace(CHILD, say))
				})
			)
		);
		expectOnlyText(
			pair,
			['turn 0 call 0 name', 'turn 0 call 0 arguments', 'turn 0 call 1 name', 'turn 1 text'],
			'task line with replies'
		);
	});
});

describe('the run message, with the setup folds under its lines', () => {
	const DELIVERED = run('harness.completed');
	const NONE = run('harness.no-documents.completed');
	const SETUP = 'data-testid="lq-ai-run-setup"';
	const count = (html: string, needle: string) => html.split(needle).length - 1;

	// What this can and cannot show: these are server renders, where `onMount` never runs,
	// so `read` is not called whatever the view. It fails if drawing alone starts a read (the
	// `mounted` guard is dropped). It cannot show what a browser reads: there the receipt
	// view's lines start open and each reads its trace when mounted (see RunSetup).
	it.each(['thread', 'receipt'] as const)(
		'has a setup fold under the plan, each task and the answer in the %s view, closed, and drawing it starts no read',
		(mode) => {
			const read = vi.fn();
			const html = bare(
				markup(RunMessage, { rootId: DELIVERED.root_id, mode, run: DELIVERED, fetchTrace: read })
			);
			expect(count(html, SETUP)).toBe(4);
			for (const tag of html.match(/<details class="setup"[^>]*>/g) ?? []) {
				expect(tag).not.toMatch(/\bopen\b/);
			}
			expect(read).not.toHaveBeenCalled();
		}
	);

	it('has none for a line that is not there: a run still planning has no plan line to open', () => {
		const planning = run('harness.follow-up.planning');
		const html = bare(
			markup(RunMessage, { rootId: planning.root_id, mode: 'thread', run: planning })
		);
		expect(count(html, SETUP)).toBe(0);
	});

	it('opens the same lines as before on the receipt page, and none of the new folds with them', () => {
		const opened = (html: string) =>
			[...html.matchAll(/<details class="([\w-]+)[^"]*"([^>]*)>/g)]
				.filter((match) => /\bopen\b/.test(match[2]))
				.map((match) => match[1]);
		expect(
			opened(markup(RunMessage, { rootId: DELIVERED.root_id, mode: 'receipt', run: DELIVERED }))
		).toEqual(['plan', 'child', 'child', 'answer-row']);
		expect(
			opened(markup(RunMessage, { rootId: DELIVERED.root_id, mode: 'thread', run: DELIVERED }))
		).toEqual([]);
		const awaiting = run('harness.no-documents.awaiting-approval');
		expect(
			opened(markup(RunMessage, { rootId: awaiting.root_id, mode: 'thread', run: awaiting }))
		).toEqual(['plan']);
	});

	describe('the heading', () => {
		const title = (value: OrchestrationChatRun | null) =>
			bare(markup(RunMessage, { rootId: value?.root_id ?? 'x', mode: 'thread', run: value }));

		it('names New harness, its prompt version and its model, with a chip that says it is experimental', () => {
			const html = title(DELIVERED);
			// A space separates the title from the chip, so that the two are not read or
			// copied as one word ("…nativeexperimental").
			page(html, 'New harness heading').shows(
				/data-testid="lq-ai-run-title">New harness v2 → selected\/native <span class="chip[^"]*">experimental<\/span>/
			);
		});

		it('is the profile’s own title for a run instructed by a skill, with no chip', () => {
			const html = title(run('completed'));
			page(html, 'skill heading').shows(
				/data-testid="lq-ai-run-title">Contract Questions Orchestrator</
			);
			page(html, 'skill heading').hides('experimental');
		});

		it('is "Governed run" while the run is being read, with no chip', () => {
			const html = bare(markup(RunMessage, { rootId: 'x', mode: 'thread' }));
			page(html, 'loading heading').shows(/data-testid="lq-ai-run-title">Governed run</);
			page(html, 'loading heading').hides('experimental');
		});
	});

	describe('the note under the answer', () => {
		const note = (value: OrchestrationChatRun) =>
			bare(markup(RunMessage, { rootId: value.root_id, mode: 'receipt', run: value }));

		it('says no documents were selected, that nothing was checked against a source and that it is model-generated', () => {
			const html = note(NONE);
			expect(evidenceLine(html)).toBe(
				'No documents were selected, so nothing in this answer was checked against a source. It is model-generated.'
			);
			// And the closed line for the answer opens with the same first sentence.
			page(html, 'no documents').shows(
				/Answer delivered<\/span><span class="summary-text"> · No documents were selected, so nothing in this answer was checked against a source/
			);
		});

		it('keeps the existing wording for a run that read documents, and for one on a fixed packet', () => {
			expect(evidenceLine(note(DELIVERED))).toBe(
				'1 of 1 checked quotation matched the selected documents.'
			);
			expect(evidenceLine(note(run('completed')))).toBe('Model-generated; unverified.');
			page(note(run('completed')), 'packet').hides('No documents were selected');
		});
	});

	describe('the receipts', () => {
		const receipts = (value: OrchestrationChatRun) =>
			bare(markup(RunMessage, { rootId: value.root_id, mode: 'receipt', run: value }));

		it('names the orchestrator’s prompt as a prompt, and a skill as a skill', () => {
			page(receipts(DELIVERED), 'prompt').shows('<dt>Orchestrator prompt</dt>');
			page(receipts(DELIVERED), 'prompt').shows('new_harness/orchestrator.v2 (version 2)');
			page(receipts(DELIVERED), 'prompt').hides('Orchestrator skill');
			page(receipts(run('completed')), 'skill').shows('<dt>Orchestrator skill</dt>');
			page(receipts(run('completed')), 'skill').shows('orchestration-chat-demo v1.0.0');
		});

		it('names a task’s prompt on the plan card as a system prompt, and a skill as a skill', () => {
			page(receipts(DELIVERED), 'prompt task').shows('<dt>System prompt</dt>');
			page(receipts(DELIVERED), 'prompt task').shows('new_harness/subagent.v2 (version 2)');
			page(receipts(run('completed')), 'skill task').shows('<dt>Skill</dt>');
			page(receipts(run('completed')), 'skill task').shows('contract-qa v1.0.0');
		});
	});

	it('shows text from the conversation the planning call was shown as text, wherever it lands', () => {
		// The thread is part of the planning snapshot. Whatever of it reaches a page does so as text.
		const base = run('harness.no-documents.completed');
		expect(base.planning.thread?.length).toBeGreaterThan(0);
		const pair = renderBoth((say) => {
			const value = structuredClone(base);
			value.planning.thread = value.planning.thread!.map((message, at) => ({
				...message,
				content: say(`thread message ${at}`)
			}));
			return bare(markup(RunMessage, { rootId: value.root_id, mode: 'receipt', run: value }));
		});
		expectOnlyText(pair, [], 'thread');
	});
});

describe('the strip above the composer, in its fold of limits and tools', () => {
	const harness = profiles('documents').profiles[1];
	const strip = (profile: ProfileAvailability, more = {}) =>
		bare(markup(RunModePanel, { profile, ...more }));

	it('says the route: the model and the inference tier', () => {
		page(strip(harness), 'route').shows('<dt>Route</dt>');
		page(strip(harness), 'route').shows('selected/native · inference tier 1');
	});

	it('says in plain words that names and identifiers are replaced, when the route pseudonymizes', () => {
		const html = strip(harness);
		page(html, 'pseudonymized').shows('<dt>Pseudonymization</dt>');
		page(html, 'pseudonymized').shows(
			'the gateway replaces what it recognises as a personal name or an identifier'
		);
		// A plan cannot have a placeholder put back, so the strip says such a plan is refused.
		page(html, 'pseudonymized').shows(
			'It cannot put one back in a plan, so a plan that carries a placeholder is refused and nothing runs.'
		);
		// Not a guarantee: it says what is missed, and what is never replaced.
		page(html, 'pseudonymized').shows(
			'It does not recognise everything, and a miss is not reported.'
		);
		page(html, 'pseudonymized').shows('Organisation names are not replaced.');
		page(html, 'pseudonymized').shows(
			'The text of a document that a task reads, and of a passage that a search returns, is sent as written, so that quotations can be checked.'
		);
		// The sentence the person read before knowledge bases could be searched is gone.
		page(html, 'pseudonymized').hides('so that its quotations can be checked');
	});

	it('says in plain words that text goes as written, and why, when it does not', () => {
		const html = strip({ ...harness, pseudonymized: false });
		page(html, 'not pseudonymized').shows(
			"Text is sent to the model as written: the operator's setting applies no pseudonymization at this route's tier."
		);
		page(html, 'not pseudonymized').hides('replaced with placeholders');
	});

	it('says nothing about pseudonymization, the tier or the effort until the route is priced and one is set', () => {
		const html = strip({
			...harness,
			pseudonymized: null,
			routed_tier: null,
			reasoning_effort: null
		});
		page(html, 'unpriced').hides('Pseudonymization');
		page(html, 'unpriced').hides('inference tier');
		page(html, 'unpriced').hides('Reasoning effort');
		page(html, 'unpriced').shows('selected/native');
	});

	it('says the reasoning effort when the operator set one', () => {
		page(strip({ ...harness, reasoning_effort: 'high' }), 'effort').shows(
			/<dt>Reasoning effort<\/dt>\s*<dd>high<\/dd>/
		);
	});

	it('lists each system prompt by role and version, closed, and reads none of them until it is opened', () => {
		const read = vi.fn();
		const html = strip(harness, { fetchPrompt: read });
		page(html, 'prompts').shows('<dt>System prompts</dt>');
		page(html, 'prompts').shows('<summary>Orchestrator prompt, version 2</summary>');
		page(html, 'prompts').shows('<summary>Sub-agent prompt, version 2</summary>');
		expect(html.match(/data-testid="lq-ai-run-prompt"/g)).toHaveLength(2);
		for (const tag of html.match(/<details class="prompt"[^>]*>/g) ?? []) {
			expect(tag).not.toMatch(/\bopen\b/);
		}
		page(html, 'prompts').hides('lq-ai-run-prompt-text');
		expect(read).not.toHaveBeenCalled();
	});

	it('names a skill as text, with its version, and has nothing to open or read for it', () => {
		const skilled = profiles('documents').profiles[0];
		const read = vi.fn();
		const html = strip(skilled, { fetchPrompt: read });
		page(html, 'skills').shows('Orchestrator skill: orchestration-chat-demo (version 1.0.0)');
		page(html, 'skills').shows('Sub-agent skill: contract-qa (version 1.0.0)');
		// Nothing listed is a prompt, so the list is not called one.
		page(html, 'skills').shows('<dt>Skills</dt>');
		page(html, 'skills').hides('System prompts');
		page(html, 'skills').hides('lq-ai-run-prompt"');
		expect(read).not.toHaveBeenCalled();
	});

	it('has no prompts row at all for a profile that lists none', () => {
		page(strip({ ...harness, instructions: [] }), 'no instructions').hides('System prompts');
	});

	it('shows the route, the effort and the instruction names as text', () => {
		const pair = renderBoth((say) =>
			strip({
				...harness,
				model: say('model'),
				reasoning_effort: say('effort'),
				instructions: [
					{
						role: 'orchestrator',
						kind: 'prompt',
						name: say('prompt name'),
						version: say('version')
					},
					{
						role: 'sub-agent',
						kind: 'skill',
						name: say('skill name'),
						version: say('skill version')
					}
				]
			})
		);
		expectOnlyText(pair, ['model', 'effort', 'skill name', 'skill version', 'version'], 'strip');
	});
});

describe('one system prompt, in the strip', () => {
	const PROMPT = prompt('orchestrator');
	const row = (state: Load<PromptRead>, more = {}) =>
		bare(
			markup(RunPromptRow, {
				name: 'new_harness/orchestrator.v1',
				label: 'Orchestrator prompt, version 1',
				state,
				...more
			})
		);

	it('is a closed fold with its label, and reads nothing until it is opened', () => {
		const read = vi.fn();
		const html = row(IDLE, { fetchPrompt: read });
		page(html, 'idle').shows('<summary>Orchestrator prompt, version 1</summary>');
		expect(tagOf(html, 'lq-ai-run-prompt')).not.toMatch(/\bopen\b/);
		page(html, 'idle').hides('<pre');
		expect(read).not.toHaveBeenCalled();
	});

	it('shows the prompt’s text, wrapping and scrollable, once it has been read', () => {
		const html = row(loaded(PROMPT));
		expect(html).toMatch(
			/<pre class="text"[^>]*data-testid="lq-ai-run-prompt-text"[^>]*>You are New harness/
		);
		page(html, 'loaded').shows(escapeText(PROMPT.text.slice(0, 80)));
		page(html, 'loaded').hides('Loading the prompt');
	});

	it('says that it is loading, and nothing else, until the text arrives', () => {
		const html = row({ status: 'loading', previous: null });
		page(html, 'loading').shows('role="status"');
		page(html, 'loading').shows('Loading the prompt…');
		page(html, 'loading').hides('<pre');
	});

	it('says why it could not be read, as an alert', () => {
		const html = row({ status: 'failed', message: 'Not found', previous: null });
		page(html, 'failed').shows('role="alert"');
		page(html, 'failed').shows('Could not read the prompt: Not found');
		page(html, 'failed').hides('<pre');
	});

	it('shows the prompt’s text as text, and an error as text', () => {
		const text = renderBoth((say) => row(loaded({ ...PROMPT, text: say('text') })));
		expectOnlyText(text, ['text'], 'prompt text');
		const failed = renderBoth((say) =>
			row({ status: 'failed', message: say('error'), previous: null })
		);
		expectOnlyText(failed, ['error'], 'prompt error');
		const label = renderBoth((say) => row(IDLE, { label: say('label') }));
		expectOnlyText(label, ['label'], 'prompt label');
	});
});

describe('the document picker, in one line', () => {
	const docs = documents().documents;
	const [MSA, DPA, DOCX] = docs;
	const picker = (more: Record<string, unknown> = {}) =>
		bare(markup(RunDocumentPicker, { documents: docs, selected: [], max: 8, ...more }));
	const openTag = (html: string) => tagOf(html, 'lq-ai-run-document-picker');

	it('says none are selected, and that they are optional, closed, for a profile that needs none', () => {
		const html = picker({ min: 0 });
		page(html, 'optional').shows('Documents · none selected (optional)');
		expect(openTag(html)).not.toMatch(/\bopen\b/);
	});

	it('names what is selected, in the order it was picked', () => {
		const html = picker({ selected: [MSA.file_id, DPA.file_id] });
		page(html, 'selected').shows('Documents · 2 selected: msa.txt, dpa.md');
		expect(openTag(html)).not.toMatch(/\bopen\b/);
		expect(picker({ selected: [DPA.file_id, MSA.file_id] })).toContain(
			'Documents · 2 selected: dpa.md, msa.txt'
		);
	});

	it('starts open, and says how many it needs, only when a document is needed and none is selected', () => {
		const needed = picker({ min: 1 });
		page(needed, 'needed').shows('Documents · none selected (at least 1 needed)');
		expect(openTag(needed)).toMatch(/\bopen\b/);
		expect(openTag(picker({ min: 1, selected: [MSA.file_id] }))).not.toMatch(/\bopen\b/);
		expect(openTag(picker({ min: 0 }))).not.toMatch(/\bopen\b/);
	});

	it('still lists every file, numbered, with the ones that cannot be read disabled and why', () => {
		const html = picker({ selected: [DPA.file_id] });
		page(html, 'list').shows('data-number="1"');
		page(html, 'list').shows(escapeText(DOCX.filename));
		page(html, 'list').shows('This type of file cannot be read in a run.');
		page(html, 'list').shows('1 of 8 selected');
	});

	it('in a matter, notes the file that will be added to it, and says where files come from when there are none', () => {
		page(picker(), 'matter').shows('Will be added to this matter when you send the request');
		page(picker({ documents: [] }), 'empty matter').shows('or add files to the matter');
	});

	it('in a chat that is in no matter, names no matter in its own words: no note, no sentence', () => {
		const read = documents('no-project');
		const html = picker({
			documents: read.documents,
			inMatter: false,
			selected: [read.documents[1].file_id]
		});
		page(html, 'no matter').hides('Will be added to this matter');
		page(html, 'no matter').hides('add files to the matter');
		// The help sentence and the empty state say nothing of a matter, whatever else is on the page.
		const empty = picker({ documents: [], inMatter: false });
		page(empty, 'no matter, no files').shows(
			'No documents yet. Attach a file to this chat, then refresh the list.'
		);
		expect(empty).not.toMatch(/matter/i);
		// A file of a matter says why it cannot be picked, in the words of the reason, and is disabled.
		page(html, 'no matter').shows(
			'This file belongs to a matter. Start the request from a chat in that matter to use it.'
		);
		const tag = tagOf(html, `lq-ai-run-document-${read.documents[0].file_id}`);
		expect(tag).toContain('data-selected="false"');
		expect(html).toMatch(/<input type="checkbox"[^>]*disabled/);
	});

	it('says the run reads no document when none is selected and none is needed', () => {
		page(picker({ min: 0 }), 'optional help').shows(
			'With none selected, the run reads no document.'
		);
		page(picker({ min: 1 }), 'needed help').hides('With none selected');
	});

	it('shows file names as text, in the line, the hover title and the list', () => {
		const pair = renderBoth((say) => {
			const rows = [
				{ ...MSA, file_id: say('first id'), filename: say('first name') },
				{ ...DPA, file_id: say('second id'), filename: say('second name') },
				{ ...MSA, file_id: say('third id'), filename: say('third name') },
				{ ...MSA, file_id: say('fourth id'), filename: say('fourth name') },
				{ ...MSA, file_id: say('fifth id'), filename: say('fifth name') }
			];
			return picker({ documents: rows, selected: rows.map((doc) => doc.file_id), max: 8 });
		});
		expectOnlyText(pair, ['first name', 'second name', 'third name'], 'picker line');
	});
});

// ---- a request the orchestrator answered by itself -----------------------------------------------------

/** The folds of a markup that are open, by the class of the `<details>`. */
const openFolds = (html: string): string[] =>
	[...html.matchAll(/<details class="([\w-]+)[^"]*"([^>]*)>/g)]
		.filter((match) => /\bopen\b/.test(match[2]))
		.map((match) => match[1]);

describe('a request the orchestrator answered by itself', () => {
	const ANSWERED = run('direct.completed');
	const ROOT = trace('root.direct');
	const message = (mode: 'thread' | 'receipt', value: OrchestrationChatRun = ANSWERED, more = {}) =>
		bare(markup(RunMessage, { rootId: value.root_id, mode, run: value, ...more }));

	it('is one line, with no plan, task or answer line and nothing to approve, reject or halt', () => {
		for (const mode of ['thread', 'receipt'] as const) {
			const html = message(mode);
			const shown = page(html, `answered directly, ${mode}`);
			shown.shows('data-testid="lq-ai-run-direct"');
			shown.hides('lq-ai-run-plan-card');
			shown.hides('lq-ai-run-child-');
			shown.hides('lq-ai-run-answer-row');
			shown.hides('lq-ai-run-approve');
			shown.hides('lq-ai-run-reject');
			shown.hides('lq-ai-run-halt');
			shown.hides('lq-ai-run-close');
			expect(html.match(/<li class="row /g), mode).toHaveLength(1);
			expect(html, mode).toContain('<li class="row direct" data-row="direct" data-state="done">');
		}
	});

	it('is closed in the chat and open on the receipt page, like every other line', () => {
		expect(openFolds(message('thread'))).toEqual([]);
		expect(openFolds(message('receipt'))).toEqual(['direct-row']);
	});

	it('says on its closed line that it was answered directly, with no plan and nothing read, and what it cost', () => {
		const html = message('thread');
		const closed = /<details class="direct-row"[^>]*><summary>([\s\S]*?)<\/summary>/.exec(html)![1];
		expect(closed).toContain('<span class="label">Answered directly</span>');
		expect(closed).toContain('<span class="summary-text"> · no plan · nothing read</span>');
		expect(closed).toContain(`<span class="meta">${formatUsd(ANSWERED.spent_usd)}</span>`);
		// It reads, in order and in one line: Answered directly · no plan · nothing read · <cost>.
		const text = closed.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ');
		expect(text).toContain(
			`(done)Answered directly · no plan · nothing read ${formatUsd(ANSWERED.spent_usd)}`
		);
	});

	it('says in a paragraph first under the line what that means, in the secondary text colour', () => {
		const html = message('thread');
		expect(DIRECT_NOTE).toBe(
			'The orchestrator answered this request by itself. No task ran, nothing was read or searched, and nothing was put to you for approval.'
		);
		page(html, 'direct note').shows(
			`<div class="body"><p class="note" data-testid="lq-ai-run-direct-note">${DIRECT_NOTE}</p>`
		);
		// The colour is the component's own style, which a render does not carry: read it from the source.
		const source = readFileSync(
			fileURLToPath(new URL('../../components/run/RunDirectRow.svelte', import.meta.url)),
			'utf8'
		);
		expect(source).toMatch(/\.note\s*\{[^}]*color:\s*var\(--lq-text-secondary\)/);
	});

	it('has the fold that says how its one call was set up, for the root session and the plan step, and draws without reading', () => {
		const read = vi.fn();
		const html = message('thread', ANSWERED, { fetchTrace: read });
		expect(html.match(/data-testid="lq-ai-run-setup"/g)).toHaveLength(1);
		expect(tagOf(html, 'lq-ai-run-setup')).toContain('data-step="plan"');
		expect(tagOf(html, 'lq-ai-run-setup')).not.toMatch(/\bopen\b/);
		expect(read).not.toHaveBeenCalled();
	});

	it('draws without reading, on the receipt page too, where the line starts open and is read on a page', () => {
		// In the chat the line is closed, so a render of it would read nothing in any case. Here the
		// line starts open, which is where a read starts on a page: a render must not.
		const read = vi.fn();
		const html = message('receipt', ANSWERED, { fetchTrace: read });
		expect(tagOf(html, 'lq-ai-run-direct')).toMatch(/\bopen\b/);
		expect(html.match(/data-testid="lq-ai-run-setup"/g)).toHaveLength(1);
		expect(read).not.toHaveBeenCalled();
		// The row on its own, handed the same stub and drawn open.
		const alone = bare(
			markup(RunDirectRow, {
				run: ANSWERED,
				line: runActivity(ANSWERED)[0],
				expanded: true,
				fetchTrace: read
			})
		);
		expect(tagOf(alone, 'lq-ai-run-direct')).toMatch(/\bopen\b/);
		expect(read).not.toHaveBeenCalled();
	});

	it('shows in that fold what the call was opened with: the prompt, the request, and the tool it was offered', () => {
		const html = bare(
			markup(RunDirectRow, {
				run: ANSWERED,
				line: runActivity(ANSWERED)[0],
				expanded: true,
				traceState: loaded(ROOT)
			})
		);
		const shown = page(html, 'direct setup');
		shown.shows('System prompt: new_harness/orchestrator.v2 (version 2)');
		shown.shows(`STEP\nRespond\n\nREQUEST\n${ANSWERED.planning.goal}`);
		shown.shows('<span class="tool-name">propose_plan</span>');
		shown.shows(
			"Rebuilt from this run's records. It matches the digest recorded when the call was sent."
		);
		shown.hides('class="check warn"');
	});

	it('lists the receipts of that one call, in a fold of their own', () => {
		const html = message('thread');
		expect(ANSWERED.effects).toHaveLength(1);
		expect(tagOf(html, 'lq-ai-run-direct-receipts')).not.toMatch(/\bopen\b/);
		const from = html.indexOf('data-testid="lq-ai-run-direct-receipts"');
		const fold = html.slice(from, html.indexOf('</details>', from));
		expect(fold).toContain('<summary>Receipts</summary>');
		expect(fold.match(/data-testid="lq-ai-run-effect-receipt"/g)).toHaveLength(1);
		expect(fold).toContain('chat:plan:v1');
		expect(fold).toContain(escapeText(ANSWERED.effects[0].skill!.digest));
	});

	it('says in the heading that it is New harness, and under the answer that the orchestrator answered alone', () => {
		page(message('thread'), 'heading').shows(/data-testid="lq-ai-run-title">New harness v2 → /);
		expect(evidenceLine(message('thread'))).toBe(
			'Answered by the orchestrator alone. It read no document and searched nothing for this answer. Model-generated; not checked.'
		);
		expect(evidenceLine(message('thread'))).not.toContain('No documents were selected');
	});

	it('reports the checks, then that it did not read these documents, where its quotations were checked', () => {
		const quoted = structuredClone(ANSWERED);
		quoted.evidence = 'citations';
		quoted.planning.documents = structuredClone(run('documents.completed').planning.documents);
		quoted.evidence_result = {
			gate_status: 'fiduciary_grade',
			checked: 1,
			matched: 1,
			unmatched: 0,
			unresolved: 0,
			unmarked: 0
		};
		expect(evidenceLine(message('thread', quoted))).toBe(
			'1 of 1 checked quotation matched the selected documents. The orchestrator did not read these documents in this run.'
		);
		page(message('thread', quoted), 'quoted').shows('lq-ai-run-answer-evidence');
		page(message('thread', quoted), 'quoted').shows(
			'Open the citation chips and the ledger under the answer to see each result.'
		);
	});

	it('shows the request, the trace and the receipts of the one call as text', () => {
		const pair = renderBoth((say) =>
			bare(
				markup(RunMessage, {
					rootId: ANSWERED.root_id,
					mode: 'receipt',
					run: worded(ANSWERED, say),
					// The receipt page starts the line open and reads its trace; here it is handed in.
					fetchTrace: () => Promise.resolve(wordedTrace(ROOT, say))
				})
			)
		);
		expectOnlyText(
			pair,
			[
				'goal',
				'profile title',
				'model',
				'planning step 0 key',
				'planning step 0 intent',
				'planning step 0 skill',
				'planning step 0 provider'
			],
			'answered directly'
		);
		const trace = renderBoth((say) =>
			bare(
				markup(RunDirectRow, {
					run: ANSWERED,
					line: runActivity(ANSWERED)[0],
					expanded: true,
					traceState: loaded(wordedTrace(ROOT, say))
				})
			)
		);
		expectOnlyText(
			trace,
			[
				'note',
				'call 0 system name',
				'call 0 system text',
				'call 0 opening',
				'call 0 tool 0 name',
				'call 0 tool 0 description'
			],
			'answered directly, its trace'
		);
	});
});

// ---- a run that stopped before it had a plan -------------------------------------------------------------

describe('the plan line of a run that stopped before it had a plan', () => {
	const NAMES = [
		'plan-not-handed-over',
		'plan-has-placeholders',
		'failed-plan',
		'unfunded-plan',
		'uncertain-planning',
		'closed-planning'
	] as const;
	const message = (mode: 'thread' | 'receipt', value: OrchestrationChatRun, more = {}) =>
		bare(markup(RunMessage, { rootId: value.root_id, mode, run: value, ...more }));
	/** The row alone, with a trace handed in. */
	const row = (value: OrchestrationChatRun, more: Record<string, unknown> = {}) =>
		bare(
			markup(RunNoPlanRow, { run: value, line: runActivity(value)[0], expanded: true, ...more })
		);

	it.each(NAMES)(
		'%s: is a fold of its own, closed in the chat and open on the receipt page',
		(name) => {
			const value = run(name);
			for (const mode of ['thread', 'receipt'] as const) {
				const html = message(mode, value);
				const shown = page(html, `${name}, ${mode}`);
				shown.shows('data-testid="lq-ai-run-noplan"');
				shown.hides('lq-ai-run-plan-card');
				shown.hides('lq-ai-run-direct');
				shown.hides('lq-ai-run-approve');
				expect(html.match(/<details class="noplan-row"/g), `${name} ${mode}`).toHaveLength(1);
				expect(openFolds(html), `${name} ${mode}`).toEqual(
					mode === 'receipt' ? ['noplan-row'] : []
				);
			}
		}
	);

	it.each(NAMES)(
		'%s: keeps the closed line it had, and draws the mark that says it opens',
		(name) => {
			const value = run(name);
			const [plan] = runActivity(value);
			const html = message('thread', value);
			const closed = /<details class="noplan-row"[^>]*><summary>([\s\S]*?)<\/summary>/.exec(
				html
			)![1];
			expect(closed).toContain(`<span class="label">${escapeText(plan.label)}</span>`);
			if (plan.summary) expect(closed).toContain(escapeText(plan.summary));
			expect(closed).toContain('class="caret"');
			expect(closed).toMatch(new RegExp(`<span class="line ${plan.state}">`));
		}
	);

	it('says what each of the two new stop reasons says, on the line, as it did before it could be opened', () => {
		const text = (name: (typeof NAMES)[number]) => {
			const html = message('thread', run(name));
			return /<details class="noplan-row"[^>]*><summary>([\s\S]*?)<\/summary>/
				.exec(html)![1]
				.replace(/<[^>]*>/g, '')
				.replace(/\s+/g, ' ');
		};
		expect(text('plan-not-handed-over')).toContain(
			'No plan was produced · The model wrote its plan out as text instead of handing it over, so there is no plan to approve.'
		);
		expect(text('plan-has-placeholders')).toContain(
			'No plan was produced · The plan carried a placeholder that stands for a name or an identifier.'
		);
	});

	it.each(NAMES)(
		'%s: holds how the call was set up, for the root session and the plan step',
		(name) => {
			const html = message('thread', run(name));
			expect(html.match(/data-testid="lq-ai-run-setup"/g), name).toHaveLength(1);
			const tag = tagOf(html, 'lq-ai-run-setup');
			expect(tag).toContain('data-step="plan"');
			expect(tag).not.toMatch(/\bopen\b/);
			page(html, name).shows('<summary>How this run was set up</summary>');
			// The row itself comes before it.
			expect(html.indexOf('lq-ai-run-noplan"')).toBeLessThan(html.indexOf('lq-ai-run-setup'));
		}
	);

	it.each(NAMES)('%s: lists the receipts of its calls, in a fold of their own', (name) => {
		const value = run(name);
		const html = message('thread', value);
		expect(tagOf(html, 'lq-ai-run-noplan-receipts'), name).not.toMatch(/\bopen\b/);
		const from = html.indexOf('data-testid="lq-ai-run-noplan-receipts"');
		const fold = html.slice(from, html.indexOf('</details>', from));
		expect(fold).toContain('<summary>Receipts</summary>');
		expect(fold.match(/data-testid="lq-ai-run-effect-receipt"/g), name).toHaveLength(
			value.effects.length
		);
		expect(fold).toContain(escapeText(value.effects[0].effect_key));
	});

	it('says there are no receipts when the run was stopped before its first call was recorded', () => {
		const none = withRun(run('closed-planning'), { effects: [] });
		const html = message('thread', none);
		page(html, 'no receipts').shows('lq-ai-run-noplan-receipts');
		page(html, 'no receipts').shows('<p class="muted">No receipts yet.</p>');
	});

	it('draws without reading anything, even where the line starts open', () => {
		for (const mode of ['thread', 'receipt'] as const) {
			const read = vi.fn();
			for (const name of NAMES) message(mode, run(name), { fetchTrace: read });
			expect(read, mode).not.toHaveBeenCalled();
		}
		// And the row, drawn open, which is where a read would start if it could.
		const read = vi.fn();
		const html = row(run('plan-not-handed-over'), { fetchTrace: read });
		expect(tagOf(html, 'lq-ai-run-noplan')).toMatch(/\bopen\b/);
		expect(read).not.toHaveBeenCalled();
	});

	it('shows what the model wrote when it wrote the plan out as text, once the trace is in', () => {
		const written = trace('root.direct');
		const value = run('plan-not-handed-over');
		const html = row(value, { traceState: loaded(written) });
		const shown = page(html, 'text instead of a plan');
		shown.shows('data-testid="lq-ai-run-wrote"');
		shown.shows('<summary>What the model wrote</summary>');
		shown.shows(escapeText(written.turns[0].text!.slice(0, 40)));
		// It is the root's plan call that is shown: how it was set up is beside it.
		shown.shows('System prompt: new_harness/orchestrator.v2 (version 2)');
	});

	it('shows the plan the model handed over, with its placeholder, once the trace is in', () => {
		const written = trace('root.planned');
		const html = row(run('plan-has-placeholders'), { traceState: loaded(written) });
		const shown = page(html, 'plan with a placeholder');
		shown.shows('data-testid="lq-ai-run-wrote-call"');
		shown.shows('<p class="name">propose_plan</p>');
		const call = written.turns[0].tool_calls![0];
		shown.shows(escapeText(call.arguments.slice(0, 40)));
	});

	it('shows no "What the model wrote" until the trace is in, or where it holds no reply to the call', () => {
		const reading: Load<SessionTraceRead> = { status: 'loading', previous: null };
		for (const state of [IDLE, reading]) {
			page(row(run('plan-not-handed-over'), { traceState: state }), 'no trace').hides(
				'lq-ai-run-wrote'
			);
		}
		const silent = { ...trace('root.direct'), turns: [] };
		page(
			row(run('plan-not-handed-over'), { traceState: loaded(silent) }),
			'a trace with no reply'
		).hides('lq-ai-run-wrote');
	});

	it('says a read failed beside the fold, where the line is open', () => {
		const failed: Load<SessionTraceRead> = {
			status: 'failed',
			message: 'Orchestration root not found',
			previous: null
		};
		const html = row(run('plan-not-handed-over'), { traceState: failed });
		page(html, 'failed read').shows('data-testid="lq-ai-run-setup-failed"');
		page(html, 'failed read').shows(
			'Could not read how this call was set up: Orchestration root not found'
		);
	});

	it('is a line with nothing to open while the first call is still being answered', () => {
		for (const name of ['planning', 'direct.planning', 'knowledge.planning'] as const) {
			for (const mode of ['thread', 'receipt'] as const) {
				const html = message(mode, run(name));
				page(html, `${name} ${mode}`).hides('lq-ai-run-noplan');
				page(html, `${name} ${mode}`).shows('<div class="static">');
			}
		}
	});

	it('is a line with nothing to open for a run of the earlier demonstration, which has no trace to read', () => {
		const demonstration = withRun(run('plan-not-handed-over'), { profile: 'demonstration' });
		for (const mode of ['thread', 'receipt'] as const) {
			const html = message(mode, demonstration);
			page(html, `demonstration ${mode}`).hides('lq-ai-run-noplan');
			page(html, `demonstration ${mode}`).hides('lq-ai-run-setup');
			page(html, `demonstration ${mode}`).shows('<div class="static">');
			// The words on the line are the same.
			page(html, `demonstration ${mode}`).shows('No plan was produced');
		}
	});

	it('is the plan card, as before, for a run that has a plan', () => {
		for (const name of ['awaiting-approval', 'rejected', 'halted', 'completed'] as const) {
			const html = message('thread', run(name));
			page(html, name).hides('lq-ai-run-noplan');
			page(html, name).shows('data-testid="lq-ai-run-plan-card"');
		}
	});

	it('leaves the line of a run answered by itself as it was', () => {
		const html = message('thread', run('direct.completed'));
		page(html, 'direct').hides('lq-ai-run-noplan');
		page(html, 'direct').shows('data-testid="lq-ai-run-direct"');
	});

	it('is the same fold before and after the owner closes a run left uncertain, so a poll does not swap it', () => {
		// What the render can show of "the reader's choice is kept": the status moves and the fold is
		// the same component in the same place, not another branch. That the open state survives the
		// poll is the browser's to show (the fold binds `open` to a state of its own).
		const uncertain = message('thread', run('uncertain-planning'));
		const closed = message('thread', withRun(run('uncertain-planning'), { status: 'closed' }));
		for (const html of [uncertain, closed]) {
			expect(html.match(/<details class="noplan-row"/g)).toHaveLength(1);
			expect(openFolds(html)).toEqual([]);
		}
	});

	it('shows a model’s reply, its plan, the call’s set-up and the receipts as text', () => {
		const pair = renderBoth((say) =>
			row(worded(run('plan-has-placeholders'), say), {
				traceState: loaded(wordedTrace(trace('root.planned'), say))
			})
		);
		expectOnlyText(
			pair,
			[
				'planning step 0 key',
				'planning step 0 intent',
				'planning step 0 skill',
				'note',
				'call 0 system name',
				'call 0 system text',
				'call 0 opening',
				'call 0 tool 0 name',
				'call 0 tool 0 description',
				'turn 0 text',
				'turn 0 call 0 name',
				'turn 0 call 0 arguments'
			],
			'a run that stopped before a plan'
		);
	});

	it('shows a run’s status and the code of an unfamiliar stop reason as text', () => {
		const pair = renderBoth((say) =>
			message(
				'thread',
				withRun(run('plan-not-handed-over'), { status: 'failed', stop_reason: say('code') })
			)
		);
		expectOnlyText(pair, [], 'an unfamiliar stop reason on a run without a plan');
	});
});

describe('a search that has not settled, in the steps and the receipts of its task', () => {
	const message = (mode: 'thread' | 'receipt', value: OrchestrationChatRun) =>
		bare(markup(RunMessage, { rootId: value.root_id, mode, run: value }));
	const SAYS = [
		['knowledge', 'Searched the knowledge bases'],
		['documents', 'Read a document'],
		['both', 'Read a document or searched the knowledge bases']
	] as const;
	/** The task (the run has only the one): its step lines and its receipts, as markup. */
	const firstTask = (html: string) => {
		const from = html.indexOf('data-testid="lq-ai-run-child-1"');
		expect(from).toBeGreaterThan(-1);
		return html.slice(from);
	};

	it.each(SAYS)(
		'says, in the opened task, what the plan allows when it lists %s: "%s"',
		(lists, said) => {
			for (const status of ['admitted', 'uncertain'] as const) {
				const html = firstTask(message('thread', whileSearching(status, lists)));
				expect(html, `${status} ${lists}`).toContain(`<span class="text">${said}</span>`);
			}
		}
	);

	it.each(SAYS)('says the same on its receipt when the plan lists %s: "%s"', (lists, said) => {
		for (const status of ['admitted', 'uncertain'] as const) {
			const html = firstTask(message('thread', whileSearching(status, lists)));
			expect(html, `${status} ${lists}`).toContain(`<strong>${said}</strong>`);
		}
	});

	it('says an uncertain one has no confirmed outcome, with the search it was named for', () => {
		const html = firstTask(message('thread', whileSearching('uncertain')));
		page(html, 'uncertain search').shows(
			'No confirmed outcome. It will not be retried automatically.'
		);
		page(html, 'uncertain search').hides('Read a document');
	});

	it('does not say "Read a document" of a search in a run that lists only knowledge bases', () => {
		for (const mode of ['thread', 'receipt'] as const) {
			const html = message(mode, whileSearching('uncertain'));
			expect(html, mode).not.toContain('Read a document');
		}
	});

	it('words the closed line of the task for it while it is going', () => {
		const html = message('thread', whileSearching('admitted', 'both'));
		const closed = /<details class="child"[^>]*><summary>([\s\S]*?)<\/summary>/.exec(html)![1];
		expect(closed).toContain('Read a document or searched the knowledge bases…');
	});

	it('leaves a settled search to say what it found, whatever the plan lists', () => {
		const html = message('thread', run('knowledge.completed'));
		page(html, 'settled').shows('Searched the knowledge bases · 1 passage from');
		page(html, 'settled').hides('Read a document or searched');
	});
});

describe('while the first call of a run is being answered', () => {
	const thread = (value: OrchestrationChatRun) =>
		bare(markup(RunMessage, { rootId: value.root_id, mode: 'thread', run: value }));

	it('says it is reading the request on the status and on the plan line, and not that a plan is being proposed', () => {
		for (const name of ['direct.planning', 'knowledge.planning', 'documents.planning'] as const) {
			const html = thread(run(name));
			const shown = page(html, name);
			shown.shows('data-status="planning">Reading your request…</p>');
			shown.shows('<span class="label">Reading your request…</span>');
			shown.hides('Proposing a plan');
			shown.hides('The model is proposing');
			shown.shows(
				'<p class="detail">One model call is reading your request. It will answer, or propose a plan. No task runs until you approve a plan.</p>'
			);
			// Nothing to approve yet, so nothing to open: a plan line that is not a fold.
			shown.hides('lq-ai-run-plan-card');
			shown.hides('lq-ai-run-approve');
			shown.shows('data-testid="lq-ai-run-halt"');
		}
	});

	it('keeps its wording for a run whose intake states no terms', () => {
		const html = thread(run('planning'));
		page(html, 'older planning').shows('data-status="planning">Proposing a plan…</p>');
		page(html, 'older planning').shows('<span class="label">Proposing a plan…</span>');
		page(html, 'older planning').hides('Reading your request');
		page(html, 'older planning').shows('The model is proposing bounded tasks.');
	});
});

describe('a plan the model wrote out as text, and one that carried a placeholder', () => {
	const thread = (value: OrchestrationChatRun) =>
		bare(markup(RunMessage, { rootId: value.root_id, mode: 'thread', run: value }));

	it('says the model wrote its plan out as text, that nothing ran and to send the request again, with no plan to approve', () => {
		const html = thread(run('plan-not-handed-over'));
		const shown = page(html, 'not handed over');
		shown.shows(
			'<p class="detail">The model wrote its plan out as text instead of handing it over, so there is no plan to approve. Nothing ran. Send the request again.</p>'
		);
		shown.shows('data-status="failed">The run failed</p>');
		shown.shows('<li class="row plan" data-row="plan" data-state="stopped">');
		shown.shows('<span class="label">No plan was produced</span>');
		shown.hides('lq-ai-run-plan-card');
		shown.hides('lq-ai-run-approve');
		shown.hides('lq-ai-run-reject');
		shown.hides('lq-ai-run-halt');
	});

	it('says the plan carried a placeholder, why it was refused, that nothing ran and what to try, with no plan to approve', () => {
		const html = thread(run('plan-has-placeholders'));
		const shown = page(html, 'placeholders');
		shown.shows(
			'<p class="detail">The plan carried a placeholder that stands for a name or an identifier. This route is pseudonymized, and a placeholder in a plan cannot be turned back into the real value, so the plan was refused. Nothing ran. Try the request again without the name or identifier.</p>'
		);
		shown.shows('data-status="failed">The run failed</p>');
		// The plan line says it in one sentence, as it does for the other plan failures.
		shown.shows('<li class="row plan" data-row="plan" data-state="stopped">');
		shown.shows('<span class="label">No plan was produced</span>');
		shown.shows(
			'<span class="summary-text"> · The plan carried a placeholder that stands for a name or an identifier.</span>'
		);
		shown.hides('lq-ai-run-plan-card');
		shown.hides('lq-ai-run-approve');
		shown.hides('lq-ai-run-reject');
		shown.hides('lq-ai-run-halt');
	});
});

describe('a stop reason the page has never seen, on a run message', () => {
	const MADE_UP = 'mystery_code';
	const thread = (value: OrchestrationChatRun) =>
		bare(markup(RunMessage, { rootId: value.root_id, mode: 'thread', run: value }));
	const stopped = (name: Parameters<typeof run>[0], status: string, stop_reason: string) => {
		const copy = structuredClone(run(name));
		copy.status = status;
		copy.stop_reason = stop_reason;
		if (copy.tree) copy.tree.status = status;
		return copy;
	};

	it('shows a plan that failed for it as failed, with the code in plain words, on the heading and the plan line', () => {
		const html = thread(stopped('failed-plan', 'failed', MADE_UP));
		const shown = page(html, 'unknown code, failed plan');
		shown.shows('data-status="failed">The run failed</p>');
		shown.shows('<p class="detail">Mystery code.</p>');
		shown.shows('<span class="summary-text"> · Mystery code.</span>');
		// The code as it came is not shown with its underscore, and nothing else is made up.
		shown.hides(MADE_UP);
		shown.hides('lq-ai-run-approve');
	});

	it('shows a halted run as halted, what that says, and then the code in plain words', () => {
		const html = thread(stopped('halted', 'halted', MADE_UP));
		const shown = page(html, 'unknown code, halted');
		shown.shows('data-status="halted">Halted</p>');
		shown.shows(
			'<p class="detail">No combined answer was produced. Task answers and files finished before the halt remain below. Mystery code.</p>'
		);
		// It is not said to be the owner's doing.
		shown.hides('You halted the run');
	});

	it('shows a closed and an expired run the same way', () => {
		const closed = thread(stopped('closed-child', 'closed', MADE_UP));
		page(closed, 'unknown code, closed').shows('data-status="closed">Closed</p>');
		page(closed, 'unknown code, closed').shows('remains below. Mystery code.</p>');
		const expired = thread(stopped('one-child-done', 'expired', MADE_UP));
		page(expired, 'unknown code, expired').shows('The run reached its time limit</p>');
		page(expired, 'unknown code, expired').shows('remains below. Mystery code.</p>');
	});

	it('shows a status it has never seen as words, and the code', () => {
		const html = thread(stopped('failed-plan', 'quarantined', MADE_UP));
		page(html, 'unknown status').shows('data-status="quarantined">Quarantined</p>');
		page(html, 'unknown status').shows('<p class="detail">Mystery code.</p>');
	});

	it('shows the code as text, whatever it looks like', () => {
		const pair = renderBoth((say) => {
			const value = stopped('failed-plan', 'failed', say('stop reason'));
			return thread(value);
		});
		expectOnlyText(pair, ['stop reason'], 'unknown stop reason, failed plan');
		const halted = renderBoth((say) => thread(stopped('halted', 'halted', say('stop reason'))));
		expectOnlyText(halted, ['stop reason'], 'unknown stop reason, halted');
	});
});

// ---- the knowledge bases a task may search -------------------------------------------------------------

describe('the line about the knowledge bases a task may search, beside the document picker', () => {
	const read = documents('knowledge-bases');
	const line = (
		value: Pick<RunDocumentsRead, 'knowledge_bases' | 'knowledge_bases_omitted'> | null
	) => settled(bare(markup(RunKnowledgeBases, { read: value })));

	/** The words of some markup, without its elements. */
	const words = (html: string) => html.replace(/<[^>]*>/g, '');

	it('names them in one line, with a test id', () => {
		const html = line(read);
		expect(html).toMatch(/^<p class="knowledge-bases" data-testid="lq-ai-run-knowledge-bases">/);
		expect(html).toMatch(/<\/p>$/);
		expect(words(html)).toBe(
			"Tasks may search this matter's knowledge bases: People policies, Travel."
		);
	});

	it('adds how many more are attached than a run lists, in the same line', () => {
		const html = line({ ...read, knowledge_bases_omitted: 3 });
		expect(html.match(/data-testid="lq-ai-run-knowledge-bases"/g)).toHaveLength(1);
		expect(words(html)).toBe(
			"Tasks may search this matter's knowledge bases: People policies, Travel. 3 more attached to this matter are not searched: a run lists at most 16."
		);
		expect(html).toMatch(/<\/bdi>\. 3 more attached to this matter are not searched/);
	});

	it('draws each name in an element of its own, separated by a comma and a space', () => {
		const html = line(read);
		expect(html).toContain('<bdi>People policies</bdi>, <bdi>Travel</bdi>.</p>');
		expect(html.match(/<bdi>/g)).toHaveLength(2);
		// The sentence around the names is outside them.
		expect(html).toContain('knowledge bases: <bdi>People policies</bdi>');
	});

	it('keeps a name with a comma in it as one name, and cannot make one name pass for two', () => {
		const comma = {
			knowledge_bases: [{ knowledge_base_id: 'a', name: 'Travel, Expenses' }]
		};
		const two = {
			knowledge_bases: [
				{ knowledge_base_id: 'a', name: 'Travel' },
				{ knowledge_base_id: 'b', name: 'Expenses' }
			]
		};
		// The two read alike as words, and differ in how many names there are.
		expect(words(line(comma))).toBe(words(line(two)));
		expect(line(comma).match(/<bdi>/g)).toHaveLength(1);
		expect(line(two).match(/<bdi>/g)).toHaveLength(2);
		expect(line(comma)).toContain('<bdi>Travel, Expenses</bdi>.</p>');
	});

	it('keeps a name that reorders text inside its own element, with the names around it outside', () => {
		const flip = '‮evil';
		const html = line({
			knowledge_bases: [
				{ knowledge_base_id: 'a', name: 'Travel' },
				{ knowledge_base_id: 'b', name: flip },
				{ knowledge_base_id: 'c', name: 'Expenses' }
			],
			knowledge_bases_omitted: 1
		});
		expect(html).toContain(`<bdi>Travel</bdi>, <bdi>${flip}</bdi>, <bdi>Expenses</bdi>. 1 more`);
		// The reordering character is inside an element that isolates it, and nowhere else.
		expect(html.split(flip)).toHaveLength(2);
	});

	it('is nothing at all when there are none, or the read has not come back', () => {
		for (const none of [documents('list'), documents('no-project'), documents('after-run'), null]) {
			expect(line(none as typeof read | null)).toBe('');
		}
		expect(line({ ...read, knowledge_bases: [] })).toBe('');
	});

	it('is a line of its own, not a fold, and reads nothing', () => {
		const html = line(read);
		page(html, 'line').hides('<details');
		page(html, 'line').hides('<button');
	});

	it('shows the names of the owner’s knowledge bases as text', () => {
		const pair = renderBoth((say) =>
			bare(
				markup(RunKnowledgeBases, {
					read: {
						knowledge_bases: [
							{ knowledge_base_id: say('first id'), name: say('first') },
							{ knowledge_base_id: say('second id'), name: say('second') }
						],
						knowledge_bases_omitted: 2
					}
				})
			)
		);
		expectOnlyText(pair, ['first', 'second'], 'knowledge-base line');
	});
});

describe('the strip, for a profile whose orchestrator may answer without a plan', () => {
	const harness = profiles('harness').profiles[1];
	const strip = (profile: ProfileAvailability) => bare(markup(RunModePanel, { profile }));

	it('says in the fold of limits that a request needing nothing read may be answered at once, and that no approval is asked for it', () => {
		const html = strip(harness);
		page(html, 'answers directly').shows(
			/<dt>Direct answers<\/dt>\s*<dd data-testid="lq-ai-run-mode-answers-directly">A request that needs nothing read may be answered at once, without a plan\. That answer is not put to you for approval\.<\/dd>/
		);
		// It is in the fold of limits and tools, which is closed.
		expect(html.indexOf('lq-ai-run-mode-answers-directly')).toBeGreaterThan(
			html.indexOf('data-testid="lq-ai-run-mode-limits"')
		);
		expect(tagOf(html, 'lq-ai-run-mode-limits')).not.toMatch(/\bopen\b/);
	});

	it('says it once, and nothing of it for a profile that always plans', () => {
		expect(strip(harness).match(/lq-ai-run-mode-answers-directly/g)).toHaveLength(1);
		for (const profile of [
			profiles('harness').profiles[0],
			{ ...harness, answers_directly: false },
			{ ...harness, answers_directly: undefined }
		]) {
			page(strip(profile), 'always plans').hides('lq-ai-run-mode-answers-directly');
			page(strip(profile), 'always plans').hides('Direct answers');
		}
	});

	it('shows the planning notice as the server sent it', () => {
		const html = strip(harness);
		expect(harness.planning_notice).toMatch(
			/either answers a request that needs nothing read, or proposes a plan/
		);
		expect(isShown(html, harness.planning_notice)).toBe(true);
		expect(tagOf(html, 'lq-ai-run-planning-notice')).not.toBe('');
	});
});

describe('the plan card, for a plan whose tasks may search knowledge bases', () => {
	const AWAITING = run('knowledge.awaiting-approval');
	const card = (value: OrchestrationChatRun, more = {}) =>
		bare(
			markup(RunPlanCard, {
				view: planView(value),
				line: runActivity(value)[0],
				state: 'proposed',
				awaiting: true,
				...more
			})
		);

	/** The words of the plan card's line, without its elements. */
	const searchLine = (html: string) => {
		const from = html.indexOf('data-testid="lq-ai-run-plan-knowledge-bases"');
		return html
			.slice(html.indexOf('>', from) + 1, html.indexOf('</p>', from))
			.replace(/<[^>]*>/g, '');
	};

	it('says which, in a line with a test id', () => {
		const html = settled(card(AWAITING));
		page(html, 'plan card').shows(
			'<p class="reads searches" data-testid="lq-ai-run-plan-knowledge-bases">Tasks may search: '
		);
		expect(searchLine(html)).toBe('Tasks may search: People policies, Travel.');
	});

	it('draws each name in an element of its own, separated by a comma and a space', () => {
		const html = settled(card(AWAITING));
		expect(html).toContain('Tasks may search: <bdi>People policies</bdi>, <bdi>Travel</bdi>.</p>');
		const from = html.indexOf('data-testid="lq-ai-run-plan-knowledge-bases"');
		expect(html.slice(from, html.indexOf('</p>', from)).match(/<bdi>/g)).toHaveLength(2);
	});

	it('keeps a name with a comma in it as one name, and one that reorders text inside its element', () => {
		const odd = structuredClone(AWAITING);
		odd.tree!.plan.knowledge_bases = [
			{ knowledge_base_id: 'a', name: 'Travel, Expenses' },
			{ knowledge_base_id: 'b', name: '‮evil' }
		];
		const html = card(odd);
		expect(html).toContain('<bdi>Travel, Expenses</bdi>, <bdi>‮evil</bdi>.</p>');
		expect(html.split('‮')).toHaveLength(2);
	});

	it('puts it on the plan, in no fold of its own, while the plan waits for the owner: open, before the tasks', () => {
		const html = card(AWAITING);
		const at = html.indexOf('data-testid="lq-ai-run-plan-knowledge-bases"');
		expect(at).toBeGreaterThan(-1);
		// The plan's own fold is open while it awaits a decision, and it is the only fold around the line.
		expect(tagOf(html, 'lq-ai-run-plan-card')).toMatch(/\bopen\b/);
		const before = html.slice(0, at);
		expect(
			(before.match(/<details/g) ?? []).length - (before.match(/<\/details>/g) ?? []).length
		).toBe(1);
		// Where the owner reads before they read the tasks they approve.
		expect(at).toBeLessThan(html.indexOf('data-testid="lq-ai-run-plan-task"'));
		page(html, 'awaiting').shows('data-testid="lq-ai-run-approve"');
	});

	it('is there once the plan is approved, and says nothing where the tasks may search none', () => {
		const done = run('knowledge.completed');
		expect(searchLine(card(done, { state: 'approved', awaiting: false }))).toBe(
			'Tasks may search: People policies, Travel.'
		);
		for (const name of [
			'awaiting-approval',
			'documents.awaiting-approval',
			'harness.completed'
		] as const) {
			page(card(run(name)), name).hides('lq-ai-run-plan-knowledge-bases');
			page(card(run(name)), name).hides('Tasks may search');
		}
	});

	it('names the search tool among those a task may call', () => {
		page(settled(card(AWAITING)), 'tools').shows("Search the matter's knowledge bases");
	});

	it('shows the knowledge bases’ names as text', () => {
		const pair = renderBoth((say) => card(worded(AWAITING, say)));
		expectOnlyText(
			pair,
			['knowledge base 0', 'knowledge base 1', 'reads'],
			'plan card knowledge bases'
		);
	});

	it('shows a plan handed over as a call to propose_plan, with hostile arguments, as text', () => {
		const pair = renderBoth((say) =>
			card(worded(AWAITING, say), {
				rootId: AWAITING.root_id,
				traceState: loaded(wordedTrace(trace('root.planned'), say))
			})
		);
		expectOnlyText(
			pair,
			['turn 0 text', 'turn 0 call 0 name', 'turn 0 call 0 arguments', 'call 0 tool 0 name'],
			'plan handed over as a tool call'
		);
	});
});

describe('a task that searched the knowledge bases', () => {
	const DONE = run('knowledge.completed');
	const SEARCHES = trace('child.knowledge');
	const thread = (value: OrchestrationChatRun, mode: 'thread' | 'receipt' = 'thread') =>
		bare(markup(RunMessage, { rootId: value.root_id, mode, run: value }));

	it('says on its closed line how many times it searched, between the documents it read and its model calls', () => {
		const html = thread(DONE);
		const closed = /<details class="child"[^>]*><summary>([\s\S]*?)<\/summary>/.exec(html)![1];
		expect(closed.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ')).toContain(
			`(done)Payments · done · searched 2 times · 2 model calls ${formatUsd(DONE.tree!.children[0].spent_usd)}`
		);
	});

	it('says what each search found as a step of the task, with the model’s stated reason', () => {
		const html = thread(DONE);
		const steps = [
			...html.matchAll(
				/<li class="step[^"]*" data-testid="lq-ai-run-step" data-kind="knowledge_search"[\s\S]*?<\/li>/g
			)
		].map((match) =>
			match[0]
				.replace(/<[^>]*>/g, ' ')
				.replace(/\s+/g, ' ')
				.trim()
		);
		// The reasons are the model's, read from the recording; what the steps say of what was found
		// is the application's.
		const [first, second] = DONE.tree!.children[0].effects.filter(
			(effect) => effect.step?.kind === 'knowledge_search'
		).map((effect) => effect.step!.reason);
		expect(first && second).toBeTruthy();
		expect(steps).toEqual([
			`Searched the knowledge bases · 1 passage from [1] leave-policy.txt The model’s stated reason: ${first}`,
			`Searched the knowledge bases · nothing found The model’s stated reason: ${second}`
		]);
	});

	it('shows the queries the model wrote under "What the model wrote", and not in the step lines', () => {
		const child = DONE.tree!.children[0];
		const html = bare(
			markup(RunChildCard, {
				rootId: DONE.root_id,
				index: 1,
				topic: 'Payments',
				skill: 's',
				child,
				line: runActivity(DONE)[1],
				expanded: true,
				traceState: loaded(SEARCHES)
			})
		);
		page(html, 'task trace').shows('<p class="name">search_knowledge_base</p>');
		// Each query is shown exactly as the model wrote it: the call's arguments, read from the recording.
		const calls = SEARCHES.turns[0].tool_calls!;
		expect(calls).toHaveLength(2);
		const queries = calls.map((call) => (JSON.parse(call.arguments) as { query: string }).query);
		for (const call of calls) expect(isShown(html, call.arguments), call.arguments).toBe(true);
		const stepLines = [
			...html.matchAll(/<span class="text">(Searched the knowledge bases[^<]*)<\/span>/g)
		].map((m) => m[1]);
		expect(stepLines).toHaveLength(2);
		for (const text of stepLines) {
			for (const query of queries) expect(text).not.toContain(query);
		}
	});

	it('says nothing of searching for a task that made no search', () => {
		const none = structuredClone(DONE);
		none.tree!.children[0].effects = none.tree!.children[0].effects.filter(
			(effect) => effect.step?.kind !== 'knowledge_search'
		);
		page(thread(none), 'no search').shows(
			'Payments</span><span class="summary-text"> · done · 2 model calls'
		);
		page(thread(none), 'no search').hides('searched');
	});

	it('shows the owner’s file names and a model’s stated reason, in the step lines, as text', () => {
		expect(DONE.tree!.children[0].effects[3].step?.kind).toBe('knowledge_search');
		const pair = renderBoth((say) => thread(worded(DONE, say)));
		expectOnlyText(
			pair,
			['task 0 step 3 found 0', 'task 0 step 3 reason', 'task 0 step 4 reason'],
			'search steps'
		);
	});
});

describe('the files found by search, under the answer line', () => {
	const DONE = run('knowledge.completed');
	// From the start of the answer's row to the end of the markup: the answer is the last line.
	const answerRow = (html: string) => html.slice(html.indexOf('<li class="row answer"'));
	const thread = (value: OrchestrationChatRun, mode: 'thread' | 'receipt' = 'thread') =>
		bare(markup(RunMessage, { rootId: value.root_id, mode, run: value }));

	it('lists each file with its source number and the task that found it, under a title', () => {
		const html = thread(DONE);
		const shown = page(html, 'sources');
		shown.shows(
			'<section class="sources" aria-label="Files found by search" data-testid="lq-ai-run-sources">'
		);
		shown.shows('<h4 class="title">Files found by search</h4>');
		shown.shows(
			'<li class="source" data-testid="lq-ai-run-source">[1] leave-policy.txt · found by task 1</li>'
		);
	});

	it('is under the answer line, outside its fold, so it is read where the answer is cited', () => {
		const row = answerRow(thread(DONE));
		const at = row.indexOf('data-testid="lq-ai-run-sources"');
		expect(at).toBeGreaterThan(-1);
		const before = row.slice(0, at);
		// Every fold of the line is closed before the list begins.
		expect((before.match(/<details/g) ?? []).length).toBe(
			(before.match(/<\/details>/g) ?? []).length
		);
		expect(before).toContain('data-testid="lq-ai-run-answer-row"');
	});

	it('is there on the receipt page too, and drawn once', () => {
		for (const mode of ['thread', 'receipt'] as const) {
			expect(thread(DONE, mode).match(/data-testid="lq-ai-run-sources"/g), mode).toHaveLength(1);
		}
	});

	it('is not drawn for a run whose searches found no file, or that searched none', () => {
		for (const name of [
			'knowledge.awaiting-approval',
			'completed',
			'documents.completed',
			'direct.completed'
		] as const) {
			page(thread(run(name)), name).hides('lq-ai-run-sources');
			page(thread(run(name)), name).hides('Files found by search');
		}
		const empty = structuredClone(DONE);
		empty.sources = [];
		page(thread(empty), 'empty').hides('lq-ai-run-sources');
	});

	it('is a list, in the order of the source numbers, and says which task found each when there are several', () => {
		const [first, second] = run('documents.completed').tree!.children;
		const several = structuredClone(run('documents.completed'));
		several.sources = [
			{ number: 27, file_id: 'f-27', filename: 'travel-policy.txt', session_id: second.session_id },
			{ number: 3, file_id: 'f-3', filename: 'leave-policy.txt', session_id: first.session_id }
		];
		const items = [...thread(several).matchAll(/<li class="source"[^>]*>([^<]*)<\/li>/g)].map(
			(m) => m[1]
		);
		expect(items).toEqual([
			'[3] leave-policy.txt · found by task 1',
			'[27] travel-policy.txt · found by task 2'
		]);
	});

	it('shows the owner’s file names as text', () => {
		const pair = renderBoth((say) => bare(markup(RunSources, { run: worded(DONE, say) })));
		expectOnlyText(pair, ['source 0'], 'sources list');
	});
});

describe('the evidence line of a run whose search found a file', () => {
	it('says the quotations matched the knowledge-base files they name, in the note and on the closed answer line', () => {
		const html = bare(
			markup(RunMessage, {
				rootId: run('knowledge.completed').root_id,
				mode: 'thread',
				run: run('knowledge.completed')
			})
		);
		expect(evidenceLine(html)).toBe(
			'1 of 1 checked quotation matched the knowledge-base files they name.'
		);
		page(html, 'closed line').shows(
			'Answer delivered</span><span class="summary-text"> · 1 of 1 checked quotation matched the knowledge-base files they name</span>'
		);
		page(html, 'closed line').hides('matched the selected documents');
	});

	it('says the selected documents where documents were selected and no file was found, as it always did', () => {
		const html = bare(
			markup(RunMessage, {
				rootId: run('harness.completed').root_id,
				mode: 'thread',
				run: run('harness.completed')
			})
		);
		expect(evidenceLine(html)).toBe('1 of 1 checked quotation matched the selected documents.');
		page(html, 'documents').hides('knowledge-base files');
	});

	it('says nothing could be checked against the files the searches found, or the documents and the files', () => {
		const files = structuredClone(run('knowledge.completed'));
		files.evidence_result = null;
		expect(
			evidenceLine(bare(markup(RunMessage, { rootId: files.root_id, mode: 'thread', run: files })))
		).toBe(
			'No quotation in this answer could be checked against the knowledge-base files its searches found. Treat it as unverified.'
		);
		const both = structuredClone(files);
		both.planning.documents = structuredClone(run('documents.completed').planning.documents);
		expect(
			evidenceLine(bare(markup(RunMessage, { rootId: both.root_id, mode: 'thread', run: both })))
		).toBe(
			'No quotation in this answer could be checked against the selected documents and knowledge-base files. Treat it as unverified.'
		);
	});
});

// ---- the receipt page of a request the orchestrator answered by itself ---------------------------------

describe('the receipt page of a run the orchestrator answered by itself', () => {
	const ANSWERED = run('direct.completed');
	const receipt = (value: OrchestrationChatRun = ANSWERED) =>
		bare(markup(RunMessage, { rootId: value.root_id, mode: 'receipt', run: value }));

	it('shows the answer itself, as text in a block of its own, which the run read now carries', () => {
		expect(ANSWERED.answered_directly).toBe(true);
		expect(ANSWERED.direct_answer).toBeTruthy();
		const html = receipt();
		page(html, 'receipt').shows('<section class="answer" aria-label="Direct answer">');
		page(html, 'receipt').shows('<h3>Direct answer</h3>');
		// The same block, and the same rendering, as a plan's combined answer: text in a <pre>.
		const block = /<pre class="answer-text">([\s\S]*?)<\/pre>/.exec(html);
		expect(block, 'a block of text').not.toBeNull();
		expect(settled(block![1])).toBe(escapeText(ANSWERED.direct_answer!));
		page(html, 'receipt').hides('Combined answer');
	});

	it('puts it below the column and above the note that says what kind of answer it is', () => {
		const html = receipt();
		const at = (needle: string) => html.indexOf(needle);
		expect(at('data-testid="lq-ai-run-activity"')).toBeGreaterThan(-1);
		expect(at('aria-label="Direct answer"')).toBeGreaterThan(
			at('data-testid="lq-ai-run-activity"')
		);
		expect(at('data-testid="lq-ai-run-answer-evidence"')).toBeGreaterThan(
			at('aria-label="Direct answer"')
		);
		expect(evidenceLine(html)).toBe(
			'Answered by the orchestrator alone. It read no document and searched nothing for this answer. Model-generated; not checked.'
		);
	});

	it('shows nothing of it in the thread, where the answer is the message beneath the run', () => {
		const html = bare(
			markup(RunMessage, { rootId: ANSWERED.root_id, mode: 'thread', run: ANSWERED })
		);
		page(html, 'thread').hides('aria-label="Direct answer"');
		expect(isShown(html, ANSWERED.direct_answer!)).toBe(false);
	});

	it('shows no answer where the read carries none: from an older server, or an empty one', () => {
		for (const stated of [undefined, null, '', '  ']) {
			const value = structuredClone(ANSWERED);
			value.direct_answer = stated;
			page(receipt(value), String(stated)).hides('aria-label="Direct answer"');
			page(receipt(value), String(stated)).hides('<pre class="answer-text">');
		}
	});

	it('shows a plan’s combined answer as it always did, and no direct answer beside it', () => {
		const planned = run('completed');
		const html = receipt(planned);
		page(html, 'planned').shows('<section class="answer" aria-label="Combined answer">');
		page(html, 'planned').hides('Direct answer');
		// A stray field on a run that was not answered directly does not become its answer.
		const stray = structuredClone(planned);
		stray.direct_answer = 'Not an answer.';
		page(receipt(stray), 'stray').hides('Not an answer.');
	});

	it('shows the answer as text, whatever the model wrote', () => {
		const pair = renderBoth((say) => receipt(worded(ANSWERED, say)));
		expectOnlyText(pair, ['direct answer'], 'direct answer, receipt');
		for (const hostile of HOSTILE_STRINGS) {
			const value = structuredClone(ANSWERED);
			value.direct_answer = hostile;
			const html = receipt(value);
			expect(html.match(/<pre class="answer-text">/g), hostile).toHaveLength(1);
			page(html, hostile).hides(/<(?:img|script|iframe|svg)\b/i);
		}
	});
});

// ---- not drawing the answer line before there is a plan --------------------------------------------------

describe('the answer line, while the first call may still answer instead', () => {
	const thread = (value: OrchestrationChatRun) =>
		bare(markup(RunMessage, { rootId: value.root_id, mode: 'thread', run: value }));

	it('is not drawn while the run reads the request: only the plan line is there', () => {
		for (const name of ['direct.planning', 'knowledge.planning', 'documents.planning'] as const) {
			const html = thread(run(name));
			const shown = page(html, name);
			shown.shows('<li class="row plan" data-row="plan" data-state="current">');
			shown.hides('data-row="answer"');
			shown.hides('Combine and deliver the answer');
			expect(html.match(/<li class="row /g), name).toHaveLength(1);
		}
	});

	it('is drawn, not started, once a plan exists', () => {
		const html = thread(run('knowledge.awaiting-approval'));
		page(html, 'awaiting').shows('<li class="row answer" data-row="answer" data-state="pending">');
		page(html, 'awaiting').shows('Combine and deliver the answer');
	});

	it('is drawn, not started, where the plan is written in text, as it always was', () => {
		const html = thread(run('planning'));
		page(html, 'older planning').shows(
			'<li class="row answer" data-row="answer" data-state="pending">'
		);
	});

	it('is drawn, saying it did not run, where the run stopped without a plan', () => {
		const html = thread(run('plan-not-handed-over'));
		page(html, 'stopped').shows('<li class="row answer" data-row="answer" data-state="skipped">');
		page(html, 'stopped').shows('did not run');
	});
});

// ---- the composer's notice of a run that is active ----------------------------------------------------

describe('the notice of a run that is planning, above the composer', () => {
	const notice = (status: string) =>
		bare(
			markup(RunActiveNotice, {
				active: {
					root_id: 'root-1',
					status,
					profile: 'p',
					chat_id: 'chat-1',
					chat_title: 'A chat'
				},
				currentChatId: 'some-other-chat'
			})
		);

	it('says the request is being read, which is true whether or not the model may answer instead of proposing a plan', () => {
		const html = notice('planning');
		page(html, 'planning notice').shows('Reading the request');
		page(html, 'planning notice').hides('Proposing a plan');
	});

	it('says the other states as it did', () => {
		page(notice('awaiting_approval'), 'awaiting').shows('Waiting for your approval');
		page(notice('running'), 'running').shows('Tasks are running');
	});
});

// ---- the first call, and what instructed it, in the steps and receipts ---------------------------------

describe('the first call of a run, in the steps and the receipts', () => {
	const FOR_A_PLAN = 'Asked the model for a plan';
	const HOW_TO_RESPOND = 'Asked the model how to respond';
	const message = (value: OrchestrationChatRun, mode: 'thread' | 'receipt' = 'thread') =>
		bare(markup(RunMessage, { rootId: value.root_id, mode, run: value }));

	it('asks how to respond, in the receipts of a run answered by itself: its line and the run’s own', () => {
		const html = message(run('direct.completed'));
		// The fold of the direct line, and the receipts at the foot of the run.
		expect(html.split(`<strong>${HOW_TO_RESPOND}</strong>`).length - 1).toBe(2);
		page(html, 'direct receipts').hides(FOR_A_PLAN);
	});

	it('asks how to respond, in the steps and receipts of a run whose plan was handed over by a tool call', () => {
		for (const name of [
			'knowledge.completed',
			'harness.completed',
			'documents.completed'
		] as const) {
			const html = message(run(name));
			// The answer line lists the orchestrator's steps; the run's receipts list them again.
			const step =
				/<li class="step[^"]*" data-testid="lq-ai-run-step" data-kind="planning"[\s\S]*?<\/li>/.exec(
					html
				);
			expect(step?.[0], name).toContain(`<span class="text">${HOW_TO_RESPOND}</span>`);
			page(html, name).shows(`<strong>${HOW_TO_RESPOND}</strong>`);
			page(html, name).hides(FOR_A_PLAN);
		}
	});

	it('asks for a plan, as it did, in a run whose intake states no terms', () => {
		const older = run('completed');
		expect(older.planning.terms ?? null).toBeNull();
		const html = message(older);
		page(html, 'older run').shows(`<span class="text">${FOR_A_PLAN}</span>`);
		page(html, 'older run').shows(`<strong>${FOR_A_PLAN}</strong>`);
		page(html, 'older run').hides(HOW_TO_RESPOND);
		for (const name of ['model-run', 'rejected-run'] as const) {
			page(message(legacyRun(name)), name).hides(HOW_TO_RESPOND);
		}
	});

	it('words no task step any differently: only the orchestrator’s first call depends on how the plan is handed over', () => {
		const html = message(run('knowledge.completed'));
		page(html, 'task steps').shows('Asked the model (turn 1)');
		page(html, 'task steps').shows('Asked the model to combine the tasks’ answers');
	});
});

describe('a receipt, for what instructed the call', () => {
	const receipts = (value: OrchestrationChatRun) =>
		bare(markup(RunMessage, { rootId: value.root_id, mode: 'receipt', run: value }));

	it('says "Prompt file" for one of the engine’s prompt files, with its name, and not "Skill"', () => {
		const value = run('knowledge.completed');
		const orchestrator = value.effects.find((effect) => effect.skill)!.skill!;
		const task = value.tree!.children[0].effects.find((effect) => effect.skill)!.skill!;
		const html = receipts(value);
		page(html, 'prompt receipts').shows(`Prompt file ${orchestrator.name}`);
		page(html, 'prompt receipts').shows(`Prompt file ${task.name}`);
		page(html, 'prompt receipts').hides(/Skill new_harness/);
	});

	it('does not say the version twice: the file’s name ends with it already', () => {
		const value = run('knowledge.completed');
		const orchestrator = value.effects.find((effect) => effect.skill)!.skill!;
		const task = value.tree!.children[0].effects.find((effect) => effect.skill)!.skill!;
		for (const pin of [orchestrator, task]) {
			expect(pin.name.endsWith(`.v${pin.version}`), pin.name).toBe(true);
		}
		const html = receipts(value);
		page(html, 'prompt receipts').hides(`${orchestrator.name} v${orchestrator.version}`);
		page(html, 'prompt receipts').hides(`${task.name} v${task.version}`);
	});

	it('says "Skill" for an installed skill, as it did', () => {
		const html = receipts(run('completed'));
		page(html, 'skill receipts').shows('Skill orchestration-chat-demo v1.0.0');
		page(html, 'skill receipts').shows('Skill contract-qa v1.0.0');
		page(html, 'skill receipts').hides('Prompt file');
	});

	it('shows the name and version as text', () => {
		const pair = renderBoth((say) => receipts(worded(run('direct.completed'), say)));
		expectOnlyText(pair, ['planning step 0 skill'], 'receipt pin');
	});
});

// ---- the tools the strip lists ------------------------------------------------------------------------------

// ---- what is said before Send is pressed ---------------------------------------------------------------

/** The source of a component, comments and all. */
const sourceOf = (path: string): string =>
	readFileSync(fileURLToPath(new URL(`../../components/${path}`, import.meta.url)), 'utf8');

describe('what the screen says Send does, before it is pressed', () => {
	const PICKER_PLANS =
		'Not a provider model. Send asks for a plan; tasks run only after you approve it.';
	const PICKER_ANSWERS =
		'Not a provider model. Send makes one model call that answers the request or proposes a plan. Tasks run only after you approve the plan.';
	const NOTE_PLANS = 'Plans your request, then runs tasks you approve.';
	const NOTE_ANSWERS =
		'Answers a request that needs nothing read. Otherwise plans it, and runs the tasks you approve.';
	const SEND_PLANS = 'Asks the model for a plan. Nothing else runs until you approve it.';
	const SEND_ANSWERS =
		'Makes one model call. It answers a request that needs nothing read, or proposes a plan. No task runs until you approve a plan.';
	const harness = profiles('harness').profiles[1];
	const picker = (more: Record<string, unknown> = {}) =>
		settled(
			bare(
				markup(ModelPicker, {
					open: true,
					selectedId: 'smart',
					models: {
						object: 'list',
						data: [{ id: 'smart', object: 'model', owned_by: 'lq-ai', lq_ai_kind: 'alias' }]
					},
					harness: {
						id: 'lq-ai:new-harness',
						label: 'New harness',
						resolves: harness.model,
						disabledReason: null,
						...more
					}
				})
			)
		);
	const groupTitle = (html: string) =>
		/<div class="[^"]*lq-group-label[^"]*" title="([^"]*)">\s*Experimental/.exec(html)?.[1] ?? '';
	const note = (html: string) =>
		/<div class="text-\[11px\] lq-harness-note mt-0\.5">\s*([\s\S]*?)\s*<\/div>/.exec(html)?.[1];

	it('reads the server’s word on the recorded profiles: New harness answers by itself, the demonstration does not', () => {
		expect(harness.profile).toBe('new_harness_v1');
		expect(answersDirectly(harness)).toBe(true);
		expect(answersDirectly(profiles('harness').profiles[0])).toBe(false);
	});

	it('says in the picker that Send makes one call that answers or proposes a plan, where the server says it may answer', () => {
		const html = picker({ answersDirectly: true });
		expect(groupTitle(html)).toBe(PICKER_ANSWERS);
		expect(note(html)).toBe(NOTE_ANSWERS);
		page(html, 'answers').hides('Send asks for a plan');
		page(html, 'answers').hides(NOTE_PLANS);
	});

	it('says what it always said where the profile always plans, or nothing says otherwise', () => {
		for (const more of [
			{ answersDirectly: false },
			{ answersDirectly: undefined },
			{},
			// Nothing but `true` is taken for the server's word.
			{ answersDirectly: 'true' },
			{ answersDirectly: 1 }
		]) {
			const html = picker(more);
			expect(groupTitle(html), JSON.stringify(more)).toBe(PICKER_PLANS);
			expect(note(html), JSON.stringify(more)).toBe(NOTE_PLANS);
			page(html, JSON.stringify(more)).hides('answers a request');
		}
	});

	it('does not choose its words by the profile’s name or the label it is shown under', () => {
		// The same label and model, one profile that answers by itself and one that does not.
		const label = { label: 'New harness', resolves: 'selected/native' };
		expect(note(picker({ ...label, answersDirectly: true }))).toBe(NOTE_ANSWERS);
		expect(note(picker({ ...label, answersDirectly: false }))).toBe(NOTE_PLANS);
		// And a different label does not change which it is.
		expect(note(picker({ label: 'Something else', answersDirectly: true }))).toBe(NOTE_ANSWERS);
		expect(note(picker({ label: 'Something else', answersDirectly: false }))).toBe(NOTE_PLANS);
	});

	it('says why it cannot be chosen where it cannot, in the server’s words, whatever the wording', () => {
		const html = picker({
			answersDirectly: true,
			disabledReason: 'Archived chats cannot start a run.'
		});
		page(html, 'disabled').shows('data-testid="lq-ai-model-picker-harness-reason"');
		page(html, 'disabled').shows('Archived chats cannot start a run.');
		page(html, 'disabled').hides(NOTE_ANSWERS);
		// The group title is still the group's.
		expect(groupTitle(html)).toBe(PICKER_ANSWERS);
	});

	it('words the Send button, and a send that failed with no message, the same way', () => {
		expect(sendWording(true)).toEqual({
			sendTitle: SEND_ANSWERS,
			pickerTitle: PICKER_ANSWERS,
			pickerNote: NOTE_ANSWERS,
			failure: 'Could not send the request.'
		});
		expect(sendWording(false)).toEqual({
			sendTitle: SEND_PLANS,
			pickerTitle: PICKER_PLANS,
			pickerNote: NOTE_PLANS,
			failure: 'Could not ask for a plan.'
		});
	});

	it('says in the composer that Send’s title and the error fallback come from the wording, and nowhere else', () => {
		// ChatPanel is too large to render here; what it can be held to is its source.
		const panel = withoutComments(sourceOf('ChatPanel.svelte'));
		expect(panel).toContain('sendWording(answersDirectly(selectedRunProfile)).sendTitle');
		expect(panel).toContain('sendWording(answersDirectly(profile)).failure');
		for (const old of [SEND_PLANS, 'Could not ask for a plan']) {
			expect(panel, old).not.toContain(old);
		}
		// The picker is told what the server says of the profile behind New harness, and says "no"
		// where there is no profile to ask (the availability read has not come back).
		expect(panel).toMatch(/answersDirectly: answersDirectly\(harness\.profile\)/);
		expect(panel).toMatch(
			/resolves: null,\s*disabledReason: harnessBlock,\s*answersDirectly: false/
		);
		const picker = withoutComments(sourceOf('ModelPicker.svelte'));
		expect(picker).toContain('sendWording(harness?.answersDirectly === true)');
		for (const old of [PICKER_PLANS, NOTE_PLANS]) expect(picker, old).not.toContain(old);
	});

	it('words the stand-alone page for a run that may be answered at once, and says it cannot know', () => {
		expect(RUNS_START_FROM_A_CHAT_TEXT).toBe(
			'The run then appears in that chat’s thread. A request that needs nothing read is answered there at once. Otherwise you review and approve its plan there and follow its progress.'
		);
		// The words of the source, as the page sets them: a line break in a paragraph is a space.
		const source = withoutComments(sourceOf('OrchestrationChat.svelte')).replace(/\s+/g, ' ');
		expect(source).toContain('{RUNS_START_FROM_A_CHAT_TEXT}');
		expect(source).not.toContain('where you review and approve its plan');
		// The first sentence of the paragraph is as it was, and the new ones follow it.
		expect(source).toContain(
			'Open a chat and choose <strong>New harness</strong> in the model picker, then send your request. {RUNS_START_FROM_A_CHAT_TEXT}'
		);
	});
});

describe('the empty thread', () => {
	const HINT =
		'No messages yet. Type a request and send it. New harness answers a request that needs nothing read, and otherwise proposes a plan for you to approve.';
	const OTHER = 'No messages yet. Attach a skill, optionally upload a file, and send a message.';
	const list = (props: Record<string, unknown> = {}) =>
		settled(bare(markup(MessageList, { messages: [], ...props })));
	/** The words of the list, as a person reads them: no elements, one space between words. */
	const words = (html: string) =>
		html
			.replace(/<[^>]*>/g, '')
			.replace(/\s+/g, ' ')
			.trim();

	it('says, with New harness chosen, that it answers a request that needs nothing read and otherwise proposes a plan to approve', () => {
		expect(words(list({ newHarness: true }))).toBe(HINT);
	});

	it('says what it said before, with another model chosen', () => {
		expect(words(list({ newHarness: false }))).toBe(OTHER);
		expect(words(list())).toBe(OTHER);
	});

	it('does not say the one where it says the other', () => {
		page(list({ newHarness: true }), 'new harness').hides('Attach a skill');
		page(list({ newHarness: false }), 'another model').hides('New harness');
		page(list({ newHarness: false }), 'another model').hides('proposes a plan');
	});

	it('keeps a few lines for the thread beside New harness, and nothing is set otherwise', () => {
		expect(list({ newHarness: true })).toContain('style="min-height: 4rem;"');
		expect(list({ newHarness: false })).not.toContain('min-height');
	});

	it('says nothing once there is a message', () => {
		const messages = recordedThread('completed').slice(0, 1);
		for (const newHarness of [true, false]) {
			const html = list({ messages, newHarness });
			page(html, `a message, ${newHarness}`).hides('No messages yet');
			page(html, `a message, ${newHarness}`).shows(escapeText(messages[0].content));
		}
	});

	it('is told by ChatPanel when New harness is the chat’s model, wherever it draws the thread', () => {
		// The panel is too large to render here; what it can be held to is its source.
		const tags = startTags(withoutComments(sourceOf('ChatPanel.svelte')), 'MessageList');
		expect(tags.length).toBeGreaterThanOrEqual(1);
		for (const tag of tags) expect(tag).toContain('newHarness={harnessChosen}');
	});
});

describe('the strip’s list of tools the tasks may use', () => {
	const harness = profiles('harness').profiles[1];
	const SEARCH = "Search the matter's knowledge bases";
	const strip = (more: Record<string, unknown> = {}) =>
		settled(bare(markup(RunModePanel, { profile: harness, ...more })));
	const toolsRow = (html: string) =>
		/<dt>Tools the tasks may use<\/dt>\s*<dd>([\s\S]*?)<\/dd>/.exec(html)?.[1] ?? '';

	it('names the search of the matter’s knowledge bases where the read lists some', () => {
		const row = toolsRow(strip({ documentsRead: documents('knowledge-bases') }));
		expect(row).toBe(
			`Read a selected document, Read back a working note, Save a working note, ${SEARCH}`
		);
	});

	it('leaves it out where the read lists none: outside a matter, and in a matter with none attached', () => {
		for (const name of ['list', 'after-run', 'no-project']) {
			const row = toolsRow(strip({ documentsRead: documents(name) }));
			expect(row, name).toBe(
				'Read a selected document, Read back a working note, Save a working note'
			);
		}
	});

	it('leaves it out until the read has come back', () => {
		for (const more of [{}, { documentsRead: null }]) {
			const row = toolsRow(strip(more));
			expect(row).toBe('Read a selected document, Read back a working note, Save a working note');
			expect(row).not.toContain(SEARCH);
		}
	});

	it('lists a profile that has no such tool as it is, whatever the read says', () => {
		const demo = profiles('harness').profiles[0];
		const row = (read: unknown) =>
			toolsRow(settled(bare(markup(RunModePanel, { profile: demo, documentsRead: read }))));
		expect(row(null)).toBe(row(documents('knowledge-bases')));
		expect(row(null)).not.toContain(SEARCH);
	});

	it('says “none” rather than nothing when the only tool is the one left out', () => {
		const only = {
			...harness,
			tools: harness.tools.filter((tool) => tool.name === 'search_knowledge_base')
		};
		const html = settled(bare(markup(RunModePanel, { profile: only })));
		expect(toolsRow(html).trim()).toBe('none');
	});

	it('leaves out the read of a selected document while no document is selected', () => {
		const row = toolsRow(
			strip({ documentsRead: documents('knowledge-bases'), selectedDocuments: 0 })
		);
		expect(row).toBe(`Read back a working note, Save a working note, ${SEARCH}`);
		expect(row).not.toContain('Read a selected document');
	});

	it('lists it once a document is selected, and while it is not known what is selected', () => {
		for (const more of [{ selectedDocuments: 1 }, { selectedDocuments: 3 }, {}]) {
			const row = toolsRow(strip({ documentsRead: documents('knowledge-bases'), ...more }));
			expect(row, JSON.stringify(more)).toBe(
				`Read a selected document, Read back a working note, Save a working note, ${SEARCH}`
			);
		}
	});

	it('leaves out both when there is nothing to read and nothing to search', () => {
		const row = toolsRow(strip({ documentsRead: documents('list'), selectedDocuments: 0 }));
		expect(row).toBe('Read back a working note, Save a working note');
	});

	it('is told by ChatPanel how many documents are selected, and what the read of the chat lists', () => {
		// The panel is too large to render here; what it can be held to is its source.
		const tags = startTags(withoutComments(sourceOf('ChatPanel.svelte')), 'RunModePanel');
		expect(tags).toHaveLength(1);
		expect(tags[0]).toContain('selectedDocuments={selectedDocumentIds.length}');
		expect(tags[0]).toContain('documentsRead={runDocuments}');
	});

	it('lists the read of a document of a profile that reads a fixed packet, with none selected', () => {
		const packet = profiles('harness').profiles[0];
		const row = toolsRow(
			settled(bare(markup(RunModePanel, { profile: packet, selectedDocuments: 0 })))
		);
		expect(row).toContain('Read a selected document');
	});

	it('says “none” when nothing is left to list', () => {
		const only = {
			...harness,
			tools: harness.tools.filter((tool) => tool.name === 'read_document')
		};
		const html = settled(bare(markup(RunModePanel, { profile: only, selectedDocuments: 0 })));
		expect(toolsRow(html).trim()).toBe('none');
	});
});
