/**
 * The files a run's searches found, as the list under the answer line names them: the number
 * a quotation's `(Source: [N])` marker carries, the file, and the task whose search found it.
 * Over the recorded run whose search found a file, and over recorded runs given sources the way
 * a two-task search would give them.
 */
import { describe, expect, it } from 'vitest';

import type { OrchestrationChatRun, RunSource } from '../../api/orchestration';
import { SOURCES_TITLE, runSources } from '../sources';
import { HOSTILE_STRINGS, expectPlainText } from './hostile';
import { allRuns, legacyRun, run } from './fixtures';

/** The recorded two-task run, given these files as the sources its tasks' searches found. */
function searched(sources: Partial<RunSource>[]): OrchestrationChatRun {
	const copy = structuredClone(run('documents.completed'));
	copy.sources = sources as RunSource[];
	return copy;
}

describe('the list of files a run found', () => {
	it('is titled "Files found by search"', () => {
		expect(SOURCES_TITLE).toBe('Files found by search');
	});

	it('names the recorded file with its source number and the task that found it', () => {
		const recorded = run('knowledge.completed');
		expect(recorded.sources).toHaveLength(1);
		expect(runSources(recorded)).toEqual([
			{
				number: 1,
				filename: 'leave-policy.txt',
				task: 1,
				text: '[1] leave-policy.txt · found by task 1'
			}
		]);
		// The task is the one whose session the source names.
		expect(recorded.sources![0].session_id).toBe(recorded.tree!.children[0].session_id);
	});

	it('numbers a task by its place in the plan, from the session that found the file', () => {
		const [first, second] = run('documents.completed').tree!.children;
		const rows = runSources(
			searched([
				{ number: 27, filename: 'travel-policy.txt', session_id: second.session_id },
				{ number: 3, filename: 'leave-policy.txt', session_id: first.session_id }
			])
		);
		expect(rows.map((row) => row.text)).toEqual([
			'[3] leave-policy.txt · found by task 1',
			'[27] travel-policy.txt · found by task 2'
		]);
		expect(rows.map((row) => row.task)).toEqual([1, 2]);
	});

	it('lists them in the order of their numbers, whatever order the server sent', () => {
		const [first, second] = run('documents.completed').tree!.children;
		const rows = runSources(
			searched([
				{ number: 30, filename: 'c.txt', session_id: second.session_id },
				{ number: 2, filename: 'a.txt', session_id: first.session_id },
				{ number: 12, filename: 'b.txt', session_id: second.session_id }
			])
		);
		expect(rows.map((row) => row.number)).toEqual([2, 12, 30]);
	});

	it('names the plan’s task when the progress of that task has no session of its own yet', () => {
		const value = searched([]);
		const planned = value.tree!.plan.children[1].dispatch_id;
		value.tree!.children = [];
		value.sources = [{ number: 4, filename: 'a.txt', file_id: 'f', session_id: planned }];
		expect(runSources(value)[0].text).toBe('[4] a.txt · found by task 2');
	});

	it('does not say which task when the run does not say, rather than naming one', () => {
		for (const session_id of ['not-a-session-of-this-run', '', undefined]) {
			const [row] = runSources(searched([{ number: 5, filename: 'a.txt', session_id }]));
			expect(row.task, String(session_id)).toBeNull();
			expect(row.text, String(session_id)).toBe('[5] a.txt');
		}
		// Nor with no plan to count the task in.
		const noPlan = searched([{ number: 5, filename: 'a.txt', session_id: 'x' }]);
		noPlan.tree = null;
		expect(runSources(noPlan)[0].text).toBe('[5] a.txt');
	});

	it('is empty where no file was found, and for a run recorded before searches existed', () => {
		expect(runSources(run('knowledge.awaiting-approval'))).toEqual([]);
		expect(runSources(run('direct.completed'))).toEqual([]);
		const unstated = structuredClone(run('knowledge.completed'));
		delete unstated.sources;
		expect(runSources(unstated)).toEqual([]);
		expect(runSources({ sources: null as never, tree: null })).toEqual([]);
		for (const name of ['model-run', 'rejected-run', 'fenced-plan-run'] as const) {
			expect(runSources(legacyRun(name)), name).toEqual([]);
		}
	});

	it('is a list only for the recorded run that found a file', () => {
		const listed = allRuns()
			.filter(({ run: value }) => runSources(value).length > 0)
			.map(({ label }) => label);
		expect(listed).toEqual(['run.knowledge.completed']);
	});

	it('leaves out a source with no usable number or file name, rather than guessing at it', () => {
		const rows = runSources(
			searched([
				{ number: 1, filename: 'ok.txt' },
				{ number: Number.NaN, filename: 'nan.txt' },
				{ number: '2' as unknown as number, filename: 'string.txt' },
				{ number: 3, filename: '' },
				{ number: 4 },
				{ filename: 'unnumbered.txt' },
				null as unknown as RunSource,
				'x' as unknown as RunSource
			])
		);
		expect(rows.map((row) => row.text)).toEqual(['[1] ok.txt']);
	});

	it('hands a file name back as the text it is, whatever it looks like', () => {
		for (const hostile of HOSTILE_STRINGS) {
			const [row] = runSources(searched([{ number: 9, filename: hostile, session_id: 'x' }]));
			expect(row.filename).toBe(hostile);
			expect(row.text).toBe(`[9] ${hostile}`);
			expectPlainText(row.text, hostile, `source row / ${hostile}`);
		}
	});
});
