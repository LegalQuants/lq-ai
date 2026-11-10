/**
 * How a run was set up, and what its model wrote back: which trace and which call a line
 * of the run column is about, the setup a call is shown with, and the replies matched to
 * the steps that made them. Over the traces recorded from the running backend.
 */
import { describe, expect, it } from 'vitest';

import type { SessionTraceRead, TraceCall } from '../../api/orchestration';
import {
	CALL_NOT_MADE,
	CHECK_DIFFERS,
	CHECK_MATCHES,
	CHECK_NOT_RECORDED,
	DIGEST_CHARS,
	NO_REPLY,
	NO_TEXT,
	NO_TEXT_BUT_TOOLS,
	NO_TOOLS,
	OPENING_NOT_REBUILT,
	OPENING_NOT_REBUILT_FOR_SKILL,
	SYSTEM_TEXT_GONE,
	finishedCalls,
	matchTurns,
	replyTo,
	setupView,
	toolView,
	traceCall,
	turnView
} from '../trace';
import { run, trace } from './fixtures';

const PLANNED = trace('root.planned');
const COMPLETED = trace('root.completed');
const DIRECT = trace('root.direct');
const CHILD = trace('child.completed');
const SEARCHING = trace('child.knowledge');
const DELIVERED = run('harness.completed');

const PLAN = traceCall(COMPLETED, 'plan')!;
const COMBINE = traceCall(COMPLETED, 'combine')!;
const TASK = traceCall(CHILD, 'task')!;
const ANSWERED = traceCall(DIRECT, 'plan')!;
const SEARCH_TASK = traceCall(SEARCHING, 'task')!;

/** A copy of a recorded call with a change made to it. */
function called(base: TraceCall, change: (copy: TraceCall) => void): TraceCall {
	const copy = structuredClone(base);
	change(copy);
	return copy;
}

describe('which call of a trace a line is about', () => {
	it('finds that call in a trace, whichever order the calls are in', () => {
		expect(traceCall(COMPLETED, 'plan')?.effect_key).toBe('chat:plan:v1');
		expect(traceCall(COMPLETED, 'combine')?.effect_key).toBe('demo:synthesis:v1');
		expect(traceCall(CHILD, 'task')?.effect_key).toBe('topic:t1');
		const reversed = { ...COMPLETED, calls: [...COMPLETED.calls].reverse() };
		expect(traceCall(reversed, 'plan')?.step).toBe('plan');
		expect(traceCall(reversed, 'combine')?.step).toBe('combine');
	});

	it('finds none for a call that has not been made yet, and none for a line of another session', () => {
		// The run is awaiting approval: the plan was made, the combine step has not been.
		expect(traceCall(PLANNED, 'plan')).not.toBeNull();
		expect(traceCall(PLANNED, 'combine')).toBeNull();
		expect(traceCall(PLANNED, 'task')).toBeNull();
		expect(traceCall(CHILD, 'plan')).toBeNull();
		expect(traceCall(CHILD, 'combine')).toBeNull();
	});

	it('finds none when there is no trace, or one with no calls', () => {
		for (const missing of [null, undefined]) expect(traceCall(missing, 'plan')).toBeNull();
		expect(traceCall({ ...COMPLETED, calls: [] }, 'plan')).toBeNull();
		expect(
			traceCall({ ...COMPLETED, calls: undefined } as unknown as SessionTraceRead, 'plan')
		).toBeNull();
	});
});

describe('how a call was set up', () => {
	it('names the pinned prompt with its version, and the first characters of its digest', () => {
		const view = setupView(PLAN);
		expect(view.system).toBe('System prompt: new_harness/orchestrator.v2 (version 2)');
		expect(DIGEST_CHARS).toBe(12);
		// Read from the recording: a prompt's digest changes whenever its text does.
		expect(view.digest).toBe(PLAN.system.digest.slice(0, 12));
		expect(view.digest).toMatch(/^[0-9a-f]{12}$/);
		expect(view.systemFold).toBe('Show the system prompt');
	});

	it('holds the pinned text, and the opening message, exactly as the trace has them', () => {
		const view = setupView(PLAN);
		expect(view.systemText).toBe(PLAN.system.text);
		expect(view.systemText).toMatch(/^You are New harness, the orchestrator/);
		expect(view.opening).toBe(PLAN.opening);
		// The first call of a run is asked to respond: to plan, to answer, or to ask one question.
		expect(view.opening).toMatch(/^STEP\nRespond\n\nREQUEST\n/);
		expect(setupView(COMBINE).opening).toMatch(/^STEP\nCombine\n\nREQUEST\n/);
	});

	it('says the matching call matches, with no warning', () => {
		expect(PLAN.check).toBe('matches');
		expect(setupView(PLAN).check).toEqual({
			text: "Rebuilt from this run's records. It matches the digest recorded when the call was sent.",
			warn: false
		});
		expect(CHECK_MATCHES).toBe(setupView(PLAN).check!.text);
	});

	it('warns when the rebuilt opening does not match what was sent, and says to treat it as approximate', () => {
		const view = setupView(called(PLAN, (copy) => (copy.check = 'differs')));
		expect(view.check).toEqual({
			text: "Rebuilt from this run's records, but it does not match the digest recorded when the call was sent. Treat it as approximate.",
			warn: true
		});
		expect(CHECK_DIFFERS).toMatch(/Treat it as approximate\.$/);
	});

	it('says no digest was recorded, or that the call has not been made, for a call without one', () => {
		const sent = called(PLAN, (copy) => {
			copy.check = 'not_recorded';
			copy.sent = true;
		});
		expect(setupView(sent).check).toEqual({ text: CHECK_NOT_RECORDED, warn: false });
		expect(CHECK_NOT_RECORDED).toBe('No digest of what was sent was recorded for this call.');
		const unsent = called(PLAN, (copy) => {
			copy.check = 'not_recorded';
			copy.sent = false;
		});
		expect(setupView(unsent).check).toEqual({ text: CALL_NOT_MADE, warn: false });
		expect(CALL_NOT_MADE).toBe('This call has not been made yet.');
	});

	it('says no more about the check when the opening was not rebuilt: the sentences above say why', () => {
		expect(setupView(called(PLAN, (copy) => (copy.check = 'not_rebuilt'))).check).toBeNull();
	});

	it('names a check result it has never seen in words, and says nothing for a blank one', () => {
		expect(
			setupView(called(PLAN, (copy) => ((copy.check as string) = 'half_matched'))).check
		).toEqual({
			text: 'Check result: Half matched.',
			warn: false
		});
		for (const blank of ['', null, undefined]) {
			expect(
				setupView(called(PLAN, (copy) => ((copy.check as unknown) = blank))).check,
				String(blank)
			).toBeNull();
		}
	});

	it('says the pinned text is no longer installed when the trace has none', () => {
		for (const text of [null, undefined]) {
			const view = setupView(called(PLAN, (copy) => (copy.system.text = text)));
			expect(view.systemText).toBeNull();
			// The name, version and digest are still the record of what was pinned.
			expect(view.system).toBe('System prompt: new_harness/orchestrator.v2 (version 2)');
			expect(view.digest).toBe(PLAN.system.digest.slice(0, 12));
		}
		expect(SYSTEM_TEXT_GONE).toBe(
			'The pinned text is no longer installed with this digest, so it cannot be shown.'
		);
		expect(setupView(PLAN).systemMissing).toBe(SYSTEM_TEXT_GONE);
		expect(setupView(called(PLAN, (copy) => (copy.system.text = ''))).systemText).toBe('');
	});

	it('says the opening is not rebuilt for a run instructed by a skill, and otherwise that it could not be', () => {
		const skill = called(PLAN, (copy) => {
			copy.system = {
				kind: 'skill',
				name: 'orchestration-chat-demo',
				version: '1.0.0',
				digest: 'a'.repeat(64),
				text: 'Skill text'
			};
			copy.opening = null;
			copy.check = 'not_rebuilt';
		});
		const view = setupView(skill);
		expect(view.opening).toBeNull();
		expect(view.openingMissing).toBe(
			'The opening message of this call is not rebuilt for a run instructed by a skill.'
		);
		expect(OPENING_NOT_REBUILT_FOR_SKILL).toBe(view.openingMissing);
		expect(view.system).toBe('Skill: orchestration-chat-demo (version 1.0.0)');
		expect(view.systemFold).toBe('Show the skill');
		expect(view.check).toBeNull();
		// A prompt whose opening is missing was not pinned to a skill: do not say it was.
		const prompt = setupView(called(PLAN, (copy) => (copy.opening = null)));
		expect(prompt.openingMissing).toBe(OPENING_NOT_REBUILT);
		expect(prompt.openingMissing).not.toMatch(/skill/);
	});

	it('leaves out a version the trace does not state, and names a system message of a kind it does not know', () => {
		const unversioned = setupView(called(PLAN, (copy) => (copy.system.version = null)));
		expect(unversioned.system).toBe('System prompt: new_harness/orchestrator.v2');
		const strange = setupView(called(PLAN, (copy) => ((copy.system.kind as string) = 'macro')));
		expect(strange.system).toBe('System message: new_harness/orchestrator.v2 (version 2)');
		expect(strange.systemFold).toBe('Show the system prompt');
	});

	it('prints at most the first characters of the digest, and none for a digest that is missing', () => {
		expect(setupView(called(PLAN, (copy) => (copy.system.digest = 'abc'))).digest).toBe('abc');
		for (const digest of ['', null, undefined]) {
			expect(
				setupView(called(PLAN, (copy) => ((copy.system.digest as unknown) = digest))).digest,
				String(digest)
			).toBeNull();
		}
	});

	describe('the tools it offered', () => {
		it('lists each tool’s name and description, with its schema as indented JSON', () => {
			const view = setupView(TASK);
			expect(view.tools.map((tool) => tool.name)).toEqual([
				'read_document',
				'read_note',
				'save_note'
			]);
			expect(view.tools[0].description).toMatch(
				/^Read the text of one document selected for this run/
			);
			const offered = TASK.tools![0] as { function: { parameters: unknown } };
			expect(JSON.parse(view.tools[0].schema!)).toEqual(offered.function.parameters);
			expect(view.tools[0].schema).toMatch(/^\{\n {2}"/);
		});

		it('says none were offered on a call that offered none', () => {
			// The combine call is offered no tool; the first call, which is offered `propose_plan`, is below.
			expect(COMBINE.tools).toEqual([]);
			expect(setupView(COMBINE).tools).toEqual([]);
			expect(setupView(COMBINE).noTools).toBe('No tools were offered on this call.');
			expect(NO_TOOLS).toBe(setupView(COMBINE).noTools);
			expect(setupView(called(COMBINE, (copy) => delete copy.tools)).tools).toEqual([]);
		});

		it('lists propose_plan, with its description and schema, on the first call of a run', () => {
			for (const [label, call] of [
				['a planned run', PLAN],
				['a run answered directly', ANSWERED]
			] as const) {
				const view = setupView(call);
				expect(
					view.tools.map((tool) => tool.name),
					label
				).toEqual(['propose_plan']);
				// The description and the schema are the tool's own, as the provider was sent them: read
				// from the recording, whose wording changes with the tool's, not written out here.
				const offered = call.tools![0] as {
					function: { description: string; parameters: unknown };
				};
				expect(offered.function.description.trim(), label).not.toBe('');
				expect(view.tools[0].description, label).toBe(offered.function.description);
				expect(JSON.parse(view.tools[0].schema!), label).toEqual(offered.function.parameters);
				expect(view.tools[0].schema, label).toContain('"tasks"');
			}
		});

		it('lists search_knowledge_base among a task’s tools when the matter has knowledge bases', () => {
			const view = setupView(SEARCH_TASK);
			expect(view.tools.map((tool) => tool.name)).toEqual([
				'read_note',
				'save_note',
				'search_knowledge_base'
			]);
			expect(view.tools[2].schema).toMatch(/^\{\n {2}"/);
		});

		it('reads a tool in the provider’s shape or flat, and never drops one it cannot read', () => {
			expect(
				toolView({
					type: 'function',
					function: { name: 'a', description: 'Does a.', parameters: { type: 'object' } }
				})
			).toEqual({
				name: 'a',
				description: 'Does a.',
				schema: '{\n  "type": "object"\n}'
			});
			expect(toolView({ name: 'b', description: 'Does b.', parameters: { x: 1 } })).toEqual({
				name: 'b',
				description: 'Does b.',
				schema: '{\n  "x": 1\n}'
			});
			expect(toolView({ name: 'c', input_schema: { y: 2 } }).schema).toBe('{\n  "y": 2\n}');
			for (const odd of [
				null,
				undefined,
				7,
				'text',
				[],
				{},
				{ function: null },
				{ function: { name: '  ' } }
			]) {
				expect(toolView(odd), JSON.stringify(odd)).toEqual({
					name: 'Unnamed tool',
					description: null,
					schema: null
				});
			}
			expect(toolView({ name: 'd', description: '   ' }).description).toBeNull();
		});

		it('gives no schema for one that cannot be written as JSON, rather than throwing', () => {
			expect(() => toolView({ name: 'e', parameters: { big: BigInt(1) } })).not.toThrow();
			expect(toolView({ name: 'e', parameters: { big: BigInt(1) } }).schema).toBeNull();
		});
	});

	it('hands every text a model, a document or the owner wrote back untouched', () => {
		const hostile = '<img src=x onerror=alert(1)>';
		const view = setupView(
			called(TASK, (copy) => {
				copy.system.name = hostile;
				copy.system.text = hostile;
				copy.opening = hostile;
				copy.tools = [
					{
						type: 'function',
						function: { name: hostile, description: hostile, parameters: { [hostile]: hostile } }
					}
				];
			})
		);
		expect(view.system).toContain(hostile);
		expect(view.systemText).toBe(hostile);
		expect(view.opening).toBe(hostile);
		expect(view.tools[0].name).toBe(hostile);
		expect(view.tools[0].description).toBe(hostile);
		expect(JSON.parse(view.tools[0].schema!)).toEqual({ [hostile]: hostile });
	});
});

describe('what the model wrote', () => {
	it('is the text of a reply, as written', () => {
		expect(turnView(COMPLETED.turns[1]).text).toBe(
			'Fees are due "within thirty (30) days" (Source: [1]).'
		);
	});

	it('is a call to propose_plan, with the plan as its arguments and no text, for a plan handed over', () => {
		for (const [label, trace] of [
			['planned', PLANNED],
			['completed', COMPLETED]
		] as const) {
			const turn = trace.turns[0];
			// The recording: the plan is in the call, and the reply has no text of its own.
			expect(turn.text, label).toBe('');
			expect(turn.finish_reason, label).toBe('tool_calls');
			const plan = turnView(turn);
			expect(plan.effectKey, label).toBe('chat:plan:v1');
			expect(plan.text, label).toBeNull();
			expect(plan.empty, label).toBe(NO_TEXT_BUT_TOOLS);
			expect(plan.toolCalls, label).toHaveLength(1);
			expect(plan.toolCalls[0].name, label).toBe('propose_plan');
			// The arguments are exactly what the model wrote, and they are the plan: an object whose
			// one member, tasks, lists them. (What the tasks say is the model's, so it is not pinned.)
			expect(plan.toolCalls[0].arguments, label).toBe(turn.tool_calls![0].arguments);
			const written = JSON.parse(plan.toolCalls[0].arguments) as { tasks: { topic: string }[] };
			expect(Object.keys(written), label).toEqual(['tasks']);
			expect(written.tasks.length, label).toBeGreaterThanOrEqual(1);
			for (const task of written.tasks) expect(typeof task.topic, label).toBe('string');
		}
	});

	it('is the answer itself, with no tool call, for a request the orchestrator answered by itself', () => {
		const [turn] = DIRECT.turns;
		expect(turn.finish_reason).toBe('stop');
		expect(turn.tool_calls).toEqual([]);
		const answer = turnView(turn);
		// The answer is whatever the model wrote, as it wrote it; its wording is not pinned.
		expect(turn.text!.trim()).not.toBe('');
		expect(answer.text).toBe(turn.text);
		expect(answer.empty).toBeNull();
		expect(answer.toolCalls).toEqual([]);
		// The call that made it was offered propose_plan and did not call it.
		expect(setupView(ANSWERED).tools.map((tool) => tool.name)).toEqual(['propose_plan']);
		expect(ANSWERED.effect_key).toBe(turn.effect_key);
	});

	it('is each search a task asked for, by name, with the query it wrote in the arguments', () => {
		const asked = turnView(SEARCHING.turns[0]);
		expect(asked.text).toBeNull();
		expect(asked.empty).toBe(NO_TEXT_BUT_TOOLS);
		expect(asked.toolCalls.map((call) => call.name)).toEqual([
			'search_knowledge_base',
			'search_knowledge_base'
		]);
		// Each call's arguments are exactly what the model wrote: its query and its reason.
		for (const [at, call] of asked.toolCalls.entries()) {
			expect(call.arguments).toBe(SEARCHING.turns[0].tool_calls![at].arguments);
			const written = JSON.parse(call.arguments) as { query: unknown; reason: unknown };
			expect(typeof written.query, `query ${at}`).toBe('string');
			expect((written.query as string).trim(), `query ${at}`).not.toBe('');
			expect(typeof written.reason, `reason ${at}`).toBe('string');
		}
	});

	it('is each tool call by name, with its arguments exactly as the model wrote them', () => {
		const asked = turnView(CHILD.turns[0]);
		expect(asked.text).toBeNull();
		expect(asked.empty).toBe('No text; the model asked for tools.');
		expect(NO_TEXT_BUT_TOOLS).toBe(asked.empty);
		expect(asked.toolCalls).toEqual([
			{ name: 'read_document', arguments: '{"document": 1, "reason": "Read the MSA."}' },
			{
				name: 'save_note',
				arguments:
					'{"name": "note-fees.md", "content": "Fees: 30 days.", "reason": "Keep the term."}'
			}
		]);
	});

	it('does not tidy arguments that are not JSON, or that are broken', () => {
		const turn = turnView({
			effect_key: 'k',
			status: 'completed',
			text: null,
			tool_calls: [{ id: 'c', name: 'read_document', arguments: '{"document": 1,' }]
		});
		expect(turn.toolCalls[0].arguments).toBe('{"document": 1,');
	});

	it('says plainly when a reply has no text and asked for no tool', () => {
		const empty = (status: string, text: string | null | undefined) =>
			turnView({ effect_key: 'k', status, text, tool_calls: [] });
		expect(empty('completed', '')).toMatchObject({ text: null, empty: NO_TEXT });
		expect(empty('completed', '   \n')).toMatchObject({ text: null, empty: NO_TEXT });
		expect(empty('completed', null)).toMatchObject({ text: null, empty: NO_TEXT });
		expect(NO_TEXT).toBe('The model wrote no text.');
		// A call that never got a reply is not the same as one that answered with nothing.
		for (const status of ['admitted', 'uncertain', 'closed']) {
			expect(empty(status, null), status).toMatchObject({ text: null, empty: NO_REPLY });
		}
		expect(NO_REPLY).toBe('No reply was recorded for this call.');
	});

	it('shows text and says nothing in its place', () => {
		const wrote = turnView({ effect_key: 'k', status: 'completed', text: 'Hello', tool_calls: [] });
		expect(wrote).toMatchObject({ text: 'Hello', empty: null });
		const both = turnView({
			effect_key: 'k',
			status: 'completed',
			text: 'Let me look.',
			tool_calls: [{ id: 'c', name: 'read_document', arguments: '{}' }]
		});
		expect(both.text).toBe('Let me look.');
		expect(both.empty).toBeNull();
		expect(both.toolCalls).toHaveLength(1);
	});

	it('copes with a turn that carries no tool calls, a nameless tool call or arguments that are not text', () => {
		const odd = turnView({
			effect_key: 'k',
			status: 'completed',
			tool_calls: [{ id: 'c', name: '', arguments: undefined as unknown as string }]
		});
		expect(odd.toolCalls).toEqual([{ name: 'Unnamed tool call', arguments: '' }]);
		expect(turnView({ effect_key: 'k', status: 'completed', text: 'x' }).toolCalls).toEqual([]);
	});

	it('hands back what the model wrote untouched', () => {
		const hostile = '<script>alert(1)</script>';
		const turn = turnView({
			effect_key: 'k',
			status: 'completed',
			text: hostile,
			tool_calls: [{ id: 'c', name: hostile, arguments: hostile }]
		});
		expect(turn.text).toBe(hostile);
		expect(turn.toolCalls).toEqual([{ name: hostile, arguments: hostile }]);
	});
});

describe('the reply a call got', () => {
	it('is the turn with the call’s effect key', () => {
		// The planning call's reply is its call to propose_plan: no text.
		expect(replyTo(COMPLETED, PLAN)?.text).toBeNull();
		expect(replyTo(COMPLETED, PLAN)?.toolCalls.map((call) => call.name)).toEqual(['propose_plan']);
		expect(replyTo(COMPLETED, COMBINE)?.text).toBe(COMPLETED.turns[1].text);
		// A request answered directly is replied to with text.
		expect(replyTo(DIRECT, ANSWERED)?.text).toBe(DIRECT.turns[0].text);
		expect(replyTo(PLANNED, traceCall(PLANNED, 'plan'))?.effectKey).toBe('chat:plan:v1');
	});

	it('is the task’s first reply for the task call, which holds the call of its first turn', () => {
		expect(replyTo(CHILD, TASK)?.effectKey).toBe('topic:t1');
		expect(replyTo(CHILD, TASK)?.toolCalls).toHaveLength(2);
	});

	it('is none for a call that has no reply yet, no call, or no trace', () => {
		const unanswered = called(PLAN, (copy) => (copy.effect_key = 'chat:plan:v9'));
		expect(replyTo(COMPLETED, unanswered)).toBeNull();
		expect(replyTo(COMPLETED, null)).toBeNull();
		expect(replyTo(null, PLAN)).toBeNull();
		expect(replyTo(undefined, PLAN)).toBeNull();
		expect(
			replyTo({ ...COMPLETED, turns: undefined } as unknown as SessionTraceRead, PLAN)
		).toBeNull();
	});
});

describe('how many model calls a session has finished', () => {
	// An open line reads its trace again when this number grows: there is a reply in the
	// trace that the earlier read does not have.
	const delivered = run('harness.completed');

	it('counts the planning call and the combining call of a delivered run', () => {
		expect(finishedCalls(delivered.tree!.root.effects)).toBe(2);
	});

	it('counts a task’s turns, and none of its reads, notes or shares', () => {
		for (const child of delivered.tree!.children) {
			const effects = child.effects ?? [];
			expect(effects.length).toBeGreaterThan(2);
			expect(finishedCalls(effects)).toBe(2);
		}
	});

	it('does not count a call that was closed or left uncertain before it was charged', () => {
		const uncertain = run('uncertain-child');
		const child = uncertain.tree!.children.find((candidate) =>
			(candidate.effects ?? []).some((effect) => effect.status === 'uncertain')
		)!;
		const charged = (child.effects ?? []).filter((effect) => effect.accounting != null).length;
		expect(finishedCalls(child.effects)).toBe(charged);
		expect(
			(child.effects ?? []).filter((effect) => effect.status === 'uncertain').length
		).toBeGreaterThan(0);
		expect(finishedCalls(run('closed-planning').tree?.root.effects)).toBe(0);
	});

	it('is 0 for a session with no steps yet, listed or not', () => {
		expect(finishedCalls([])).toBe(0);
		expect(finishedCalls(null)).toBe(0);
		expect(finishedCalls(undefined)).toBe(0);
	});
});

describe('matching replies to the steps that made them', () => {
	const effects = DELIVERED.tree!.children[0].effects;

	it('gives a reply to the step whose effect key is the reply’s, and to no other', () => {
		const matched = matchTurns(effects, CHILD);
		expect(matched).toHaveLength(effects.length);
		const keys = effects.filter((_, at) => matched[at] !== null).map((effect) => effect.effect_key);
		expect(keys).toEqual(['topic:t1', 'topic:t2']);
		matched.forEach((turn, at) => {
			if (turn) expect(turn.effectKey).toBe(effects[at].effect_key);
		});
	});

	it('matches both model turns of a task: the one that asked for tools and the one that answered', () => {
		const matched = matchTurns(effects, CHILD).filter((turn) => turn !== null);
		expect(matched.map((turn) => turn!.toolCalls.length)).toEqual([2, 0]);
		expect(matched[1]!.text).toBe('Fees are due "within thirty (30) days" (Source: [1]).');
	});

	it('matches by key alone: the tool calls made in a turn have keys of their own and get nothing', () => {
		const toolSteps = effects.filter((effect) => /^topic:t\d+:c\d+$/.test(effect.effect_key));
		expect(toolSteps.length).toBeGreaterThan(0);
		const matched = matchTurns(effects, CHILD);
		for (const step of toolSteps) expect(matched[effects.indexOf(step)]).toBeNull();
	});

	it('does not depend on the order the steps or the replies are in', () => {
		const shuffled = [...effects].reverse();
		const matched = matchTurns(shuffled, { ...CHILD, turns: [...CHILD.turns].reverse() });
		shuffled.forEach((effect, at) => {
			const turn = matched[at];
			if (turn) expect(turn.effectKey).toBe(effect.effect_key);
		});
		expect(matched.filter(Boolean)).toHaveLength(2);
	});

	it('gives nothing to a step whose key has no reply, whatever kind of step it is', () => {
		const renamed = effects.map((effect) => ({
			...effect,
			effect_key: `${effect.effect_key}:other`
		}));
		expect(matchTurns(renamed, CHILD).every((turn) => turn === null)).toBe(true);
	});

	it('gives nothing yet to a step whose reply is not in the trace read earlier', () => {
		const earlier = { ...CHILD, turns: CHILD.turns.slice(0, 1) };
		const matched = matchTurns(effects, earlier).filter(Boolean);
		expect(matched).toHaveLength(1);
		expect(matched[0]!.effectKey).toBe('topic:t1');
	});

	it('matches only the keys it is limited to, as the answer line does for the combine call', () => {
		const rootEffects = DELIVERED.tree!.root.effects;
		const everything = matchTurns(rootEffects, COMPLETED);
		expect(
			rootEffects.filter((_, at) => everything[at]).map((effect) => effect.effect_key)
		).toEqual(['chat:plan:v1', 'demo:synthesis:v1']);
		const limited = matchTurns(rootEffects, COMPLETED, [COMBINE.effect_key]);
		expect(rootEffects.filter((_, at) => limited[at]).map((effect) => effect.effect_key)).toEqual([
			'demo:synthesis:v1'
		]);
		expect(matchTurns(rootEffects, COMPLETED, [])).toEqual(rootEffects.map(() => null));
	});

	it('uses the first reply when a key turns up twice, and nothing when there is no trace', () => {
		const twice = {
			...CHILD,
			turns: [CHILD.turns[0], { ...CHILD.turns[1], effect_key: CHILD.turns[0].effect_key }]
		};
		const first = matchTurns(effects, twice).find(Boolean);
		expect(first?.toolCalls).toHaveLength(2);
		for (const missing of [null, undefined]) {
			expect(matchTurns(effects, missing).every((turn) => turn === null)).toBe(true);
		}
		expect(matchTurns([], CHILD)).toEqual([]);
	});
});
