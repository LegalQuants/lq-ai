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
 * It cannot see what needs a browser: clicks, the open state of the profile menu, the
 * follower's fetches, DOMPurify.
 */
import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';

import type {
	OrchestrationChatRun,
	ProfileAvailability,
	RunDocument
} from '../../api/orchestration';
import type { Message } from '../../types';
import RunActiveNotice from '../../components/run/RunActiveNotice.svelte';
import RunAnswerNote from '../../components/run/RunAnswerNote.svelte';
import RunDocumentPicker from '../../components/run/RunDocumentPicker.svelte';
import RunMessage from '../../components/run/RunMessage.svelte';
import RunModePanel from '../../components/run/RunModePanel.svelte';
import RunPlanCard from '../../components/run/RunPlanCard.svelte';
import RunProfileMenu from '../../components/run/RunProfileMenu.svelte';
import { unavailableReason } from '../composer';
import { planView } from '../plan';
import { allRuns, documents, legacyRun, profiles, run } from './fixtures';
import { elementsIn } from './hostile';

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
	}
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
		const pair = renderBoth((say) =>
			markup(RunPlanCard, {
				view: planView(worded(awaiting, say)),
				state: 'proposed',
				awaiting: true
			})
		);
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
				markup(RunPlanCard, { view: planView(value), state: 'proposed', awaiting: true }).replace(
					/<!--[\s\S]*?-->/g,
					''
				),
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
			['title', 'summary', 'reads', 'notice', 'model', 'tool', 'reason'],
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

	it('the profile menu’s button, with a hostile profile id and title', () => {
		const pair = renderBoth((say) => {
			const profile: ProfileAvailability = {
				...structuredClone(profiles('available').profiles[1]),
				profile: say('id'),
				title: say('title')
			};
			return markup(RunProfileMenu, { profiles: [profile], selectedId: profile.profile });
		});
		expectOnlyText(pair, ['title'], 'profile menu');
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
		'project_required',
		'project_not_permitted',
		'route_unavailable',
		'active_run'
	];
	const base = profiles('available').profiles[1];

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
				page(markup(RunModePanel, { profile }), `${code} ${reason_text}`).shows(
					`role="alert">${escapeText(reason!)}</p>`
				);
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
			shown.shows('data-testid="lq-ai-run-progress"');
			shown.shows(`data-status="${value.status}"`);
			for (const placeholder of PLACEHOLDERS) shown.hides(placeholder);
		}
	});

	it('shows one stage as the place a run is, unless it is done, and the plan card only for a run that has a plan', () => {
		for (const { label, run: value } of allRuns()) {
			const html = markup(RunMessage, { rootId: value.root_id, mode: 'thread', run: value });
			expect(html.includes('data-testid="lq-ai-run-plan-card"'), label).toBe(value.tree !== null);
			const stages = html.match(/data-state="(?:current|stopped)"/g) ?? [];
			expect(stages, label).toHaveLength(value.status === 'completed' ? 0 : 1);
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
		shown.shows('Approved plan');
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
			shown.hides('lq-ai-run-progress');
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
