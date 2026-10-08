/**
 * Step renderers (ADR 0038 D3).
 *
 * A run's records say what each step was in registry terms: a `kind`, the tool's
 * `label`, the model's own stated `reason`, and a small `summary` of counts and
 * file names. A renderer turns one kind into plain language. Profiles and tools
 * are a registry on the server, so a kind this client has never seen can arrive at
 * any time: it renders through the generic fallback from its `label` (or a
 * humanised kind), the `summary` key/values and the `reason`. A step never throws
 * and never renders as nothing.
 *
 * Every string returned here is plain text. The `reason`, file names and summary
 * values are model- or owner-supplied, so they are returned untouched and the
 * components render them with Svelte interpolation, never as HTML.
 */
import type { RunEffect, StepNote } from '../api/orchestration';
import { formatUsd, formatValue, humanise, own, pluralise } from './format';

export type StepTone = 'done' | 'working' | 'refused' | 'uncertain' | 'closed';

export interface StepView {
	/** The step's kind, or `legacy` for an effect recorded without a step note. */
	kind: string;
	/** True when a renderer is registered for this kind. */
	known: boolean;
	text: string;
	/** Supporting facts, one short line each. */
	facts: string[];
	/** The model's own stated reason for a tool call, if it gave one. */
	reason: string | null;
	tone: StepTone;
	/** What the step cost: the charge, or the amount still reserved. */
	cost: string | null;
}

/** What a renderer returns for one step. */
export interface StepRendering {
	text: string;
	facts?: string[];
}

export type StepRenderer = (step: StepNote, effect: RunEffect) => StepRendering;

type Summary = Record<string, unknown>;

function summaryOf(step: StepNote): Summary {
	const value = step.summary;
	return value && typeof value === 'object' && !Array.isArray(value) ? (value as Summary) : {};
}

function str(summary: Summary, key: string): string | null {
	const value = summary[key];
	return typeof value === 'string' && value !== '' ? value : null;
}

function num(summary: Summary, key: string): number | null {
	const value = summary[key];
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

const REFUSAL_CODES: Record<string, string> = {
	tool_not_granted: 'that tool is not granted to this task',
	document_not_selected: 'the document is not one you selected',
	invalid_arguments: 'the arguments did not match the tool’s schema',
	budget_exhausted: 'the task’s allowance could not fund the call',
	input_limit: 'the result would not fit the task’s remaining input'
};

/** Why a call was refused, in a clause. Unknown codes are shown as words. */
export function refusalText(code: string | null): string {
	if (!code) return 'the call was refused';
	return own(REFUSAL_CODES, code) ?? code.replace(/[_-]+/g, ' ');
}

function noteFacts(summary: Summary): string[] {
	const facts: string[] = [];
	const revision = num(summary, 'revision');
	const size = num(summary, 'size_bytes');
	if (revision !== null) facts.push(`revision ${revision}`);
	if (size !== null) facts.push(pluralise(size, 'byte'));
	return facts;
}

const RENDERERS = new Map<string, StepRenderer>([
	['planning', () => ({ text: 'Asked the model for a plan' })],
	['synthesis', () => ({ text: 'Asked the model to combine the tasks’ answers' })],
	[
		'model_turn',
		(step) => {
			const summary = summaryOf(step);
			const turn = num(summary, 'turn');
			const calls = num(summary, 'tool_calls');
			const finish = str(summary, 'finish_reason');
			const facts: string[] = [];
			if (calls !== null && calls > 0) facts.push(`asked for ${pluralise(calls, 'tool call')}`);
			else if (finish === 'stop') facts.push('wrote its answer');
			else if (finish) facts.push(`finished: ${finish.replace(/_/g, ' ')}`);
			return { text: turn !== null ? `Asked the model (turn ${turn})` : 'Asked the model', facts };
		}
	],
	[
		'document_read',
		(step) => {
			const summary = summaryOf(step);
			const position = num(summary, 'document');
			const filename = str(summary, 'filename');
			const which = position !== null ? `document ${position}` : 'a document';
			const start = num(summary, 'start');
			const end = num(summary, 'end');
			const total = num(summary, 'total_chars');
			const facts: string[] = [];
			if (start !== null && end !== null && total !== null) {
				facts.push(`characters ${start}–${end} of ${total}${summary.truncated === true ? ' (cut short)' : ''}`);
			} else if (summary.truncated === true) {
				facts.push('the read was cut short');
			}
			return { text: `Read ${which}${filename ? ` (${filename})` : ''}`, facts };
		}
	],
	[
		'note_saved',
		(step) => {
			const summary = summaryOf(step);
			const name = str(summary, 'name');
			return { text: `Saved a working note${name ? ` (${name})` : ''}`, facts: noteFacts(summary) };
		}
	],
	[
		'note_read',
		(step) => {
			const summary = summaryOf(step);
			const name = str(summary, 'name');
			return {
				text: `Read back a working note${name ? ` (${name})` : ''}`,
				facts: noteFacts(summary)
			};
		}
	],
	[
		'tool_refused',
		(step) => {
			const code = str(summaryOf(step), 'code');
			const label = typeof step.label === 'string' && step.label.trim() ? step.label.trim() : null;
			return {
				text: label ? `A tool call was refused: ${label}` : 'A tool call was refused',
				facts: [refusalText(code)]
			};
		}
	],
	['notes_started', () => ({ text: 'Started the task’s private notes' })],
	['notes_read', () => ({ text: 'Read the task’s notes' })],
	['notes_updated', () => ({ text: 'Updated the task’s notes' })],
	['findings_saved', () => ({ text: 'Saved the task’s findings' })],
	['findings_read', () => ({ text: 'Read the task’s findings back' })],
	['findings_shared', () => ({ text: 'Shared the task’s findings with the orchestrator' })],
	['findings_collected', () => ({ text: 'Collected a task’s findings' })]
]);

/**
 * Teach the client a step kind. The server's registry may grow faster than this
 * client; a kind with no renderer still shows through the fallback, so this is
 * only for a nicer sentence. Replaces any renderer already registered for `kind`.
 */
export function registerStepRenderer(kind: string, renderer: StepRenderer): void {
	RENDERERS.set(kind, renderer);
}

/** The kinds this client has a sentence for. */
export function knownStepKinds(): string[] {
	return [...RENDERERS.keys()];
}

/** The generic presentation: label or humanised kind, then the summary's key/values. */
function fallbackRendering(step: StepNote): StepRendering {
	const label = typeof step.label === 'string' ? step.label.trim() : '';
	const kind = typeof step.kind === 'string' ? humanise(step.kind) : '';
	const facts = Object.entries(summaryOf(step)).map(
		([key, value]) => `${key.replace(/[_-]+/g, ' ')}: ${formatValue(value)}`
	);
	return { text: label || kind || 'A step was recorded', facts };
}

const LEGACY_BY_KEY: [RegExp, string][] = [
	[/^chat:plan/, 'Asked the model for a plan'],
	[/^demo:notes:create/, 'Started the task’s private notes'],
	[/^demo:notes:read/, 'Read the task’s notes'],
	[/^demo:notes:update/, 'Updated the task’s notes'],
	[/^demo:findings:write/, 'Saved the task’s findings'],
	[/^demo:findings:read/, 'Read the task’s findings back'],
	[/^demo:findings:share/, 'Shared the task’s findings with the orchestrator'],
	[/^demo:collect:/, 'Collected a task’s findings'],
	[/^demo:synthesis/, 'Asked the model to combine the tasks’ answers'],
	[/^demo:topic/, 'Asked the model'],
	[/^topic:t\d+$/, 'Asked the model']
];

const LEGACY_BY_INTENT: Record<string, string> = {
	plan: 'Asked the model for a plan',
	run_skill: 'Asked the model',
	workspace_write: 'Wrote a working file',
	workspace_read: 'Read a working file',
	workspace_share: 'Shared a working file',
	retrieve_chunks: 'Read a document',
	refused: 'A tool call was refused'
};

/** For an effect recorded without a step note: runs from before the registry, and effects that never completed. */
function legacyRendering(effect: RunEffect): StepRendering {
	const key = effect.effect_key ?? '';
	for (const [pattern, text] of LEGACY_BY_KEY) {
		if (pattern.test(key)) return { text };
	}
	const intent = effect.intent ?? '';
	return {
		text: own(LEGACY_BY_INTENT, intent) ?? (humanise(intent) || humanise(key) || 'A step was recorded')
	};
}

function toneOf(effect: RunEffect, kind: string): StepTone {
	if (effect.status === 'uncertain') return 'uncertain';
	if (effect.status === 'closed') return 'closed';
	if (effect.status === 'admitted') return 'working';
	if (kind === 'tool_refused' || effect.outcome === 'tool_refused') return 'refused';
	return 'done';
}

function positive(value: string | number | null | undefined): boolean {
	const parsed = Number(value);
	return value !== null && value !== undefined && Number.isFinite(parsed) && parsed > 0;
}

function costOf(effect: RunEffect): string | null {
	if (effect.status === 'uncertain' || effect.status === 'admitted') {
		return positive(effect.reserved_usd) ? `${formatUsd(effect.reserved_usd)} reserved` : null;
	}
	return positive(effect.charged_usd) ? formatUsd(effect.charged_usd) : null;
}

function statusFact(effect: RunEffect): string | null {
	switch (effect.status) {
		case 'uncertain':
			return 'No confirmed outcome. It will not be retried automatically.';
		case 'closed':
			return 'Closed without an outcome. The reserved amount was charged.';
		case 'admitted':
			return 'In progress';
		default:
			return null;
	}
}

/**
 * Describe one effect in plain language, through the registry.
 *
 * Total: any effect, however malformed its step note, gives a view with
 * non-empty `text`.
 */
export function describeEffect(effect: RunEffect): StepView {
	const note = effect.step;
	const step: StepNote | null =
		note && typeof note === 'object' && typeof note.kind === 'string' ? note : null;
	let kind = 'legacy';
	let known = false;
	let rendering: StepRendering;
	let reason: string | null = null;
	if (step) {
		kind = step.kind;
		reason = typeof step.reason === 'string' && step.reason !== '' ? step.reason : null;
		const renderer = RENDERERS.get(kind);
		if (renderer) {
			try {
				rendering = renderer(step, effect);
				known = true;
			} catch {
				rendering = fallbackRendering(step);
			}
		} else {
			rendering = fallbackRendering(step);
		}
	} else {
		rendering = legacyRendering(effect);
	}
	const facts = [...(rendering.facts ?? [])];
	const modifier = statusFact(effect);
	if (modifier) facts.push(modifier);
	return {
		kind,
		known,
		text: rendering.text.trim() || fallbackRendering(step ?? { kind }).text,
		facts,
		reason,
		tone: toneOf(effect, kind),
		cost: costOf(effect)
	};
}

/** The same, in the order the server recorded them. */
export function describeEffects(effects: RunEffect[] | null | undefined): StepView[] {
	return (effects ?? []).map(describeEffect);
}
