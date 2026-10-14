/**
 * How a run was set up, and what its model wrote back (ADR 0038 D3): the content of the
 * folds under each line of the run column.
 *
 * A session's trace says, for each model call, the system message it was pinned to, the
 * opening message the application sent, the tools it offered and whether the rebuilt
 * opening still matches the digest recorded when the call went out; and for each reply,
 * the text the model wrote and the tool calls it asked for. Everything here turns that
 * read into plain strings and lists for a component to print. The system text, the
 * opening, the tool names and descriptions, the replies and the arguments are all written
 * by a model, a document or the owner: they are returned untouched and shown as text.
 */
import type {
	RunEffect,
	SessionTraceRead,
	TraceCall,
	TraceStepName,
	TraceTurn
} from '../api/orchestration';
import { humanise } from './format';

// ---- which call of a trace a line is about, and whether the trace is up to date ------------

/**
 * How many model calls a session has finished: its steps that carry accounting, which a
 * model call has from the moment it is charged and no other step has. A line's trace is
 * read once, when the line is opened; when this number grows while the line is open, the
 * trace has a reply in it that the read does not, and it is read again.
 */
export function finishedCalls(effects: readonly RunEffect[] | null | undefined): number {
	return (effects ?? []).filter((effect) => effect.accounting != null).length;
}

/** The call of a trace that a line is about, or null when it has not been made yet. */
export function traceCall(
	trace: SessionTraceRead | null | undefined,
	step: TraceStepName
): TraceCall | null {
	return trace?.calls?.find((call) => call.step === step) ?? null;
}

// ---- how the call was set up ---------------------------------------------------------------

export const CALL_NOT_MADE = 'This call has not been made yet.';
export const SYSTEM_TEXT_GONE =
	'The pinned text is no longer installed with this digest, so it cannot be shown.';
export const OPENING_NOT_REBUILT_FOR_SKILL =
	'The opening message of this call is not rebuilt for a run instructed by a skill.';
export const OPENING_NOT_REBUILT = 'The opening message of this call could not be rebuilt.';
export const NO_TOOLS = 'No tools were offered on this call.';
export const CHECK_MATCHES =
	"Rebuilt from this run's records. It matches the digest recorded when the call was sent.";
export const CHECK_DIFFERS =
	"Rebuilt from this run's records, but it does not match the digest recorded when the call was sent. Treat it as approximate.";
export const CHECK_NOT_RECORDED = 'No digest of what was sent was recorded for this call.';

/** How many characters of the pinned digest the fold prints. */
export const DIGEST_CHARS = 12;

export interface ToolView {
	name: string;
	description: string | null;
	/** The tool's JSON schema, pretty-printed, for a nested fold; null when it states none. */
	schema: string | null;
}

export interface SetupView {
	/** "System prompt: new_harness/orchestrator.v1 (version 1)". */
	system: string;
	/** The first characters of the pinned digest, or null. */
	digest: string | null;
	/** What the nested fold that holds the pinned text is called. */
	systemFold: string;
	/** The pinned text, or null when it is no longer installed with that digest. */
	systemText: string | null;
	systemMissing: string;
	/** The opening user message, or null where it is not rebuilt. */
	opening: string | null;
	openingMissing: string;
	tools: ToolView[];
	noTools: string;
	/** One line on whether the rebuilt opening matches what was sent, or null for none. */
	check: { text: string; warn: boolean } | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** A schema as indented JSON text. Never throws: a value that cannot be written gives null. */
function pretty(value: unknown): string | null {
	if (value === undefined) return null;
	try {
		return JSON.stringify(value, null, 2) ?? null;
	} catch {
		return null;
	}
}

/**
 * One offered tool. The provider's shape is `{type, function: {name, description,
 * parameters}}`; a flat `{name, description, parameters}` reads the same. A tool of any
 * other shape is still listed, as an unnamed tool, and never as nothing.
 */
export function toolView(raw: unknown): ToolView {
	const outer = isRecord(raw) ? raw : {};
	const inner = isRecord(outer.function) ? outer.function : outer;
	const name =
		typeof inner.name === 'string' && inner.name.trim() !== '' ? inner.name : 'Unnamed tool';
	const description =
		typeof inner.description === 'string' && inner.description.trim() !== ''
			? inner.description
			: null;
	return { name, description, schema: pretty(inner.parameters ?? inner.input_schema) };
}

function checkLine(call: TraceCall): { text: string; warn: boolean } | null {
	switch (call.check) {
		case 'matches':
			return { text: CHECK_MATCHES, warn: false };
		case 'differs':
			return { text: CHECK_DIFFERS, warn: true };
		case 'not_recorded':
			// Either no digest was kept, or the call has not gone out: say which.
			return { text: call.sent === false ? CALL_NOT_MADE : CHECK_NOT_RECORDED, warn: false };
		case 'not_rebuilt':
			// The sentences about the pinned text and the opening already say why.
			return null;
		default: {
			const word = humanise(String(call.check ?? ''));
			return word ? { text: `Check result: ${word}.`, warn: false } : null;
		}
	}
}

/** What one call was opened with, in plain strings and lists. */
export function setupView(call: TraceCall): SetupView {
	const system = call.system;
	const kind = system?.kind;
	const version = typeof system?.version === 'string' ? system.version.trim() : '';
	const named = `${system?.name ?? ''}${version ? ` (version ${version})` : ''}`;
	const lead = kind === 'prompt' ? 'System prompt' : kind === 'skill' ? 'Skill' : 'System message';
	const digest = typeof system?.digest === 'string' && system.digest ? system.digest : null;
	return {
		system: `${lead}: ${named}`,
		digest: digest ? digest.slice(0, DIGEST_CHARS) : null,
		systemFold: kind === 'skill' ? 'Show the skill' : 'Show the system prompt',
		systemText: typeof system?.text === 'string' ? system.text : null,
		systemMissing: SYSTEM_TEXT_GONE,
		opening: typeof call.opening === 'string' ? call.opening : null,
		openingMissing: kind === 'skill' ? OPENING_NOT_REBUILT_FOR_SKILL : OPENING_NOT_REBUILT,
		tools: (call.tools ?? []).map(toolView),
		noTools: NO_TOOLS,
		check: checkLine(call)
	};
}

// ---- what the model wrote ------------------------------------------------------------------

export const NO_TEXT_BUT_TOOLS = 'No text; the model asked for tools.';
export const NO_TEXT = 'The model wrote no text.';
export const NO_REPLY = 'No reply was recorded for this call.';

export interface TurnView {
	effectKey: string;
	/** What the model wrote, or null when it wrote no text. */
	text: string | null;
	/** What to say in place of text, or null when there is text. */
	empty: string | null;
	/** Each tool call: its name, and its arguments exactly as the model wrote them. */
	toolCalls: { name: string; arguments: string }[];
}

/** One reply of a session, ready to print. */
export function turnView(turn: TraceTurn): TurnView {
	const text = typeof turn.text === 'string' && turn.text.trim() !== '' ? turn.text : null;
	const toolCalls = (turn.tool_calls ?? []).map((call) => ({
		name: typeof call.name === 'string' && call.name !== '' ? call.name : 'Unnamed tool call',
		arguments: typeof call.arguments === 'string' ? call.arguments : ''
	}));
	let empty: string | null = null;
	if (text === null) {
		if (toolCalls.length > 0) empty = NO_TEXT_BUT_TOOLS;
		else empty = turn.status === 'completed' ? NO_TEXT : NO_REPLY;
	}
	return { effectKey: turn.effect_key, text, empty, toolCalls };
}

/** The reply a call got: the turn with the call's effect key, or null when it has none yet. */
export function replyTo(
	trace: SessionTraceRead | null | undefined,
	call: TraceCall | null
): TurnView | null {
	if (!trace || !call) return null;
	const turn = (trace.turns ?? []).find((candidate) => candidate.effect_key === call.effect_key);
	return turn ? turnView(turn) : null;
}

/**
 * For each effect of a session, the reply that effect made: the turn whose effect key is
 * the effect's own, or null. Matched by key alone, so the sentence the step list prints
 * and the fold under it can never be about different calls. `only` limits the match to
 * those keys (the answer line shows the combine call's reply and no other).
 */
export function matchTurns(
	effects: readonly RunEffect[],
	trace: SessionTraceRead | null | undefined,
	only?: readonly string[]
): (TurnView | null)[] {
	const byKey = new Map<string, TraceTurn>();
	for (const turn of trace?.turns ?? []) {
		if (!byKey.has(turn.effect_key)) byKey.set(turn.effect_key, turn);
	}
	return effects.map((effect) => {
		if (only && !only.includes(effect.effect_key)) return null;
		const turn = byKey.get(effect.effect_key);
		return turn ? turnView(turn) : null;
	});
}
