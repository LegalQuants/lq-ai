/**
 * The composer before a run exists: why a profile cannot be chosen, what blocks a new
 * run, which documents can be picked and in what order, when "Propose plan" is enabled,
 * and the request that starts a run.
 *
 * Profiles, documents and the active run are the recorded responses of
 * `GET /chats/{id}/run-profiles` and `GET /chats/{id}/run-documents`.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ActiveRun, ProfileAvailability, RunDocument, RunTool } from '../../api/orchestration';
import { MAX_CHAT_ATTACHED_FILES } from '../../chat/attachedFiles';
import { availableActions } from '../actions';
import {
	ACTIVE_RUN_POLL_MS,
	ADDED_TO_MATTER_NOTE,
	CLOSE_RUN_NOTE,
	MAX_CANDIDATE_FILES,
	MAX_GOAL_CHARS,
	activeRunLabel,
	activeRunStatusText,
	buildStartBody,
	canCloseActiveRun,
	candidateFileIds,
	candidatesSignature,
	documentNote,
	documentNumber,
	documentRows,
	newRequestId,
	proposeBlocker,
	pruneSelection,
	requestFor,
	requestSignature,
	runModeFacts,
	syncActiveRun,
	toggleDocument,
	toolLabelList,
	unavailableReason,
	unreadableReason
} from '../composer';
import { POLL_START_MS } from '../polling';
import { ACTIVE_STATUSES, TERMINAL_STATUSES, UNCERTAIN_EXPLANATION, runHeadline } from '../status';
import { documents, profiles, run } from './fixtures';

/** The profile that reads a fixed document, available. */
const packetProfile = (patch: Partial<ProfileAvailability> = {}): ProfileAvailability => ({
	...structuredClone(profiles('available').profiles[1]),
	...patch
});

/** The profile that reads documents the owner selects, available. */
const selectedProfile = (patch: Partial<ProfileAvailability> = {}): ProfileAvailability => ({
	...structuredClone(profiles('documents').profiles[0]),
	...patch
});

const document = (patch: Partial<RunDocument> = {}): RunDocument => ({
	file_id: 'file-1',
	filename: 'msa.txt',
	mime_type: 'text/plain',
	size_bytes: 100,
	characters: 100,
	attached_to_project: true,
	selectable: true,
	reason: null,
	...patch
});

/** The six recorded files: two readable, four that cannot be read, each for a different reason. */
const RECORDED = documents().documents;
const [MSA, DPA, DOCX, SCAN, BROKEN, IMAGE_ONLY] = RECORDED;

// ---- why a profile cannot be chosen ------------------------------------------------------

const CODES = [
	'operator_disabled',
	'not_configured',
	'autonomous_opt_in_required',
	'project_required',
	'project_not_permitted',
	'route_unavailable',
	'active_run'
] as const;

/** What a person needs to read, by code, so the wording can change but not the substance. */
const SUBSTANCE: Record<(typeof CODES)[number], RegExp> = {
	operator_disabled: /operator has not enabled/i,
	not_configured: /configuration is incomplete/i,
	autonomous_opt_in_required: /Autonomous.*settings/i,
	project_required: /no matter/i,
	project_not_permitted: /demo matter/i,
	route_unavailable: /route.*(protection|pricing)/i,
	active_run: /another run.*still active/i
};

describe('unavailableReason', () => {
	it('is null for a profile that can be chosen, whatever else it carries', () => {
		expect(unavailableReason(packetProfile())).toBeNull();
		expect(unavailableReason(selectedProfile())).toBeNull();
		expect(
			unavailableReason(packetProfile({ reason: 'active_run', reason_text: 'stale' }))
		).toBeNull();
	});

	describe.each(CODES)('%s', (code) => {
		it('shows the server’s own words, trimmed', () => {
			const profile = packetProfile({
				available: false,
				reason: code,
				reason_text: '  The server says exactly this.  '
			});
			expect(unavailableReason(profile)).toBe('The server says exactly this.');
		});

		it('shows a sentence for the code when the server sent none, never the code itself', () => {
			for (const reason_text of [null, undefined, '', '   ']) {
				const text = unavailableReason(
					packetProfile({ available: false, reason: code, reason_text })
				);
				expect(text).toMatch(SUBSTANCE[code]);
				expect(text).toMatch(/^[A-Z].*\.$/);
				expect(text).not.toContain(code);
				expect(text).not.toContain('_');
			}
		});

		it('leaves the profile unchosen and the plan unproposable, with that same reason', () => {
			const profile = packetProfile({ available: false, reason: code, reason_text: null });
			const reason = unavailableReason(profile);
			expect(reason).not.toBeNull();
			// A request that is otherwise complete is still blocked, and says why.
			expect(proposeBlocker({ profile, goal: 'Check the renewal terms', selectedCount: 3 })).toBe(
				reason
			);
		});
	});

	it('gives every code its own sentence', () => {
		const sentences = CODES.map((reason) =>
			unavailableReason(packetProfile({ available: false, reason, reason_text: null }))
		);
		expect(new Set(sentences).size).toBe(CODES.length);
	});

	it('words the codes the same way the recorded server responses do', () => {
		// The recordings carry the server's text for three of the codes.
		const recorded: [string, ProfileAvailability][] = [
			['operator_disabled', profiles('available').profiles[0]],
			['project_required', profiles('no-project').profiles[1]],
			['active_run', profiles('active-run').profiles[1]]
		];
		for (const [code, profile] of recorded) {
			expect(profile.reason).toBe(code);
			expect(unavailableReason({ ...profile, reason_text: null }), code).toBe(profile.reason_text);
		}
	});

	it('degrades to a generic sentence for a code it has never seen, without throwing or echoing it', () => {
		const generic = 'This profile is unavailable right now.';
		for (const reason of [
			'quota_exhausted',
			'<img src=x onerror=alert(1)>',
			'',
			null,
			undefined,
			'constructor',
			'__proto__',
			'toString',
			'hasOwnProperty'
		]) {
			const profile = packetProfile({ available: false, reason, reason_text: null });
			expect(() => unavailableReason(profile), String(reason)).not.toThrow();
			expect(unavailableReason(profile), String(reason)).toBe(generic);
		}
		// A value of the wrong type in the code or the text is not a reason either.
		const odd = { ...packetProfile({ available: false }), reason: 7, reason_text: {} };
		expect(unavailableReason(odd as unknown as ProfileAvailability)).toBe(generic);
	});

	it('prefers the server’s words for a code it has never seen', () => {
		const profile = packetProfile({
			available: false,
			reason: 'quota_exhausted',
			reason_text: 'You have used this month’s allowance.'
		});
		expect(unavailableReason(profile)).toBe('You have used this month’s allowance.');
	});

	it('never disables a profile without a reason, on any recorded read', () => {
		for (const name of ['available', 'active-run', 'uncertain-run', 'no-project', 'documents']) {
			for (const profile of profiles(name).profiles) {
				const reason = unavailableReason(profile);
				expect(reason === null, `${name} ${profile.profile}`).toBe(profile.available);
				if (!profile.available) expect(reason?.length).toBeGreaterThan(0);
			}
		}
	});
});

// ---- the run that blocks a new one ---------------------------------------------------------

describe('activeRunLabel', () => {
	const active = (patch: Partial<ActiveRun> = {}): ActiveRun => ({
		root_id: 'root-1',
		status: 'running',
		profile: 'model_demo_v1',
		chat_id: 'chat-1',
		chat_title: 'Vendor renewal',
		...patch
	});

	it('names the chat the run is in, and says when it is the chat being viewed', () => {
		expect(activeRunLabel(active(), 'chat-2')).toBe('A run is active in Vendor renewal');
		expect(activeRunLabel(active(), 'chat-1')).toBe(
			'A run is active in Vendor renewal (this chat)'
		);
		expect(activeRunLabel(active(), null)).toBe('A run is active in Vendor renewal');
	});

	it('trims the title and copes with a chat that has none', () => {
		expect(activeRunLabel(active({ chat_title: '  Vendor renewal  ' }), 'x')).toBe(
			'A run is active in Vendor renewal'
		);
		for (const chat_title of [null, undefined, '', '   ']) {
			expect(activeRunLabel(active({ chat_title }), 'chat-1')).toBe('A run is active in this chat');
			expect(activeRunLabel(active({ chat_title }), 'chat-2')).toBe(
				'A run is active in another chat'
			);
		}
	});

	it('says so when the run was started outside a chat', () => {
		for (const chat_id of [null, undefined, '']) {
			expect(activeRunLabel(active({ chat_id }), 'chat-1')).toBe(
				'A run you started outside a chat is active'
			);
		}
	});

	it('reads the recorded active runs', () => {
		const planning = profiles('active-run');
		expect(activeRunLabel(planning.active_run!, planning.chat_id)).toBe(
			'A run is active in Explain payment, renewal and termination questions independently.'
		);
		// The same run, seen from the chat it is in.
		expect(activeRunLabel(planning.active_run!, planning.active_run!.chat_id ?? null)).toMatch(
			/\(this chat\)$/
		);
		const uncertain = profiles('uncertain-run');
		expect(activeRunLabel(uncertain.active_run!, uncertain.chat_id)).toBe(
			'A run is active in A request whose planning call times out. (this chat)'
		);
	});
});

describe('activeRunStatusText', () => {
	it('says in a few words where each active run is', () => {
		expect(activeRunStatusText('planning')).toBe('Proposing a plan');
		expect(activeRunStatusText('awaiting_approval')).toBe('Waiting for your approval');
		expect(activeRunStatusText('queued')).toBe('Approved, waiting to start');
		expect(activeRunStatusText('running')).toBe('Tasks are running');
		expect(activeRunStatusText('waiting_children')).toBe('Tasks are running');
	});

	it('says an uncertain run in the same words as the thread does', () => {
		expect(activeRunStatusText('uncertain')).toBe(
			runHeadline({ status: 'uncertain', stop_reason: null })
		);
	});

	it('has words for every active status and never shows a raw code', () => {
		for (const status of ACTIVE_STATUSES) {
			const text = activeRunStatusText(status);
			expect(text.length, status).toBeGreaterThan(0);
			expect(text, status).not.toContain('_');
		}
		expect(activeRunStatusText('paused_for_review')).toBe('Paused for review');
	});
});

describe('canCloseActiveRun', () => {
	it('closes only an uncertain run, and agrees with the actions the thread offers', () => {
		for (const status of [...ACTIVE_STATUSES, ...TERMINAL_STATUSES, 'something_new']) {
			const close = canCloseActiveRun({ root_id: 'r', status, profile: 'p' });
			expect(close, status).toBe(status === 'uncertain');
			expect(close, status).toBe(availableActions({ status, stop_reason: null }).close);
		}
	});
});

describe('syncActiveRun', () => {
	const read = profiles('active-run');
	const active = read.active_run!;

	it('takes the active run’s status from a read of that same run, and changes nothing else', () => {
		const synced = syncActiveRun(read, { root_id: active.root_id, status: 'awaiting_approval' });
		expect(synced.active_run).toEqual({ ...active, status: 'awaiting_approval' });
		expect(synced.profiles).toBe(read.profiles);
		expect(synced.chat_id).toBe(read.chat_id);
		expect(synced.project_id).toBe(read.project_id);
	});

	it('does not change the read it was given', () => {
		const before = structuredClone(read);
		syncActiveRun(read, { root_id: active.root_id, status: 'running' });
		expect(read).toEqual(before);
	});

	it('hands back the very same object when there is nothing to change', () => {
		// The status is already what the run says.
		expect(syncActiveRun(read, { root_id: active.root_id, status: active.status })).toBe(read);
		// A read of some other run says nothing about this one.
		expect(syncActiveRun(read, { root_id: 'some-other-run', status: 'completed' })).toBe(read);
		// No run holds the allowance, so there is no notice to keep current.
		const none = profiles('available');
		expect(syncActiveRun(none, { root_id: active.root_id, status: 'running' })).toBe(none);
	});

	it('drops the notice when the run has ended and no longer holds the allowance', () => {
		for (const status of ['completed', 'rejected', 'halted', 'failed', 'expired', 'closed']) {
			const synced = syncActiveRun(read, { root_id: active.root_id, status });
			expect(synced.active_run, status).toBeNull();
			expect(synced.profiles, status).toBe(read.profiles);
		}
		expect(read.active_run).toEqual(active);
	});

	it('follows a run into the uncertain state, where it can be closed, and names where it is', () => {
		const synced = syncActiveRun(read, { root_id: active.root_id, status: 'uncertain' });
		expect(canCloseActiveRun(synced.active_run!)).toBe(true);
		expect(activeRunStatusText(synced.active_run!.status)).toBe(
			runHeadline({ status: 'uncertain', stop_reason: null })
		);
		expect(canCloseActiveRun(active)).toBe(false);
	});

	it('is read again on a slow interval, slower than the thread follows its own run', () => {
		expect(ACTIVE_RUN_POLL_MS).toBeGreaterThanOrEqual(POLL_START_MS);
		expect(Number.isInteger(ACTIVE_RUN_POLL_MS)).toBe(true);
	});
});

describe('CLOSE_RUN_NOTE', () => {
	it('says what closing does, the same three things the thread says', () => {
		for (const text of [CLOSE_RUN_NOTE, UNCERTAIN_EXPLANATION]) {
			expect(text).toMatch(/charges? (the|that) unresolved\s+reservation/);
			expect(text).toMatch(/retries nothing/);
			expect(text).toMatch(/another run/);
		}
	});
});

// ---- run mode ----------------------------------------------------------------------------------

describe('toolLabelList', () => {
	const tool = (name: string, label: string): RunTool => ({
		name,
		label,
		phase: 'analysis',
		registered: true
	});

	it('lists the labels the profile gives, in its order', () => {
		expect(toolLabelList(profiles('available').profiles[1].tools)).toEqual([
			'Read a selected document',
			'Read back a working note',
			'Save a working note'
		]);
	});

	it('lists a tool once, in the place it first appears', () => {
		expect(
			toolLabelList([
				tool('a', 'Alpha'),
				tool('b', 'Beta'),
				tool('a', 'Alpha again'),
				tool('c', 'Gamma')
			])
		).toEqual(['Alpha', 'Beta', 'Gamma']);
	});

	it('names a tool with no label from its own name', () => {
		expect(toolLabelList([tool('read_document', '')])).toEqual(['Read document']);
	});

	it('does so for a label of only spaces, or no label at all, and trims one it keeps', () => {
		for (const label of [' ', '   ', '\t\n', ' ']) {
			expect(toolLabelList([tool('read_document', label)]), JSON.stringify(label)).toEqual([
				'Read document'
			]);
		}
		for (const label of [undefined, null]) {
			const noLabel = { name: 'save_note', label, phase: 'analysis' } as unknown as RunTool;
			expect(toolLabelList([noLabel]), String(label)).toEqual(['Save note']);
		}
		expect(toolLabelList([tool('read_document', '  Read a selected document  ')])).toEqual([
			'Read a selected document'
		]);
	});

	it('is empty when there are no tools', () => {
		expect(toolLabelList(null)).toEqual([]);
		expect(toolLabelList(undefined)).toEqual([]);
		expect(toolLabelList([])).toEqual([]);
	});
});

describe('runModeFacts', () => {
	it('lists what a fixed-document run will use and may spend, before anything is sent', () => {
		expect(runModeFacts(profiles('available').profiles[1])).toEqual([
			{ label: 'Model', value: 'selected/native' },
			{ label: 'Total cap', value: '$2.00' },
			{ label: 'Planning allowance', value: '$0.2478' },
			{ label: 'Per-task allowance', value: '$0.7434' },
			{ label: 'Maximum tasks', value: '2' },
			{ label: 'Attempt limit', value: '2 minutes per attempt' },
			{ label: 'Tool turns per task', value: 'up to 2, then one answer' }
		]);
	});

	it('lists the same for a run on selected documents, with its own figures', () => {
		const facts = Object.fromEntries(
			runModeFacts(selectedProfile()).map((f) => [f.label, f.value])
		);
		expect(facts).toEqual({
			Model: 'selected/native',
			'Total cap': '$10.00',
			'Planning allowance': '$0.5781',
			'Per-task allowance': '$3.4686',
			'Maximum tasks': '2',
			'Attempt limit': '5 minutes per attempt',
			'Tool turns per task': 'up to 5, then one answer'
		});
	});

	it('leaves out what the server has not priced instead of showing it as zero', () => {
		// The recorded unavailable profiles carry no model, cap, allowance or attempt limit.
		const unpriced = [profiles('available').profiles[0], profiles('no-project').profiles[1]];
		for (const profile of unpriced) {
			expect(profile.budget_usd).toBeNull();
			const facts = runModeFacts(profile);
			expect(facts.map((f) => f.label)).toEqual(['Tool turns per task']);
			for (const fact of facts) expect(fact.value).not.toMatch(/\$0\.00|—|null|undefined|NaN/);
		}
	});

	it('leaves out a task count, attempt limit or turn limit of zero', () => {
		const facts = runModeFacts(
			packetProfile({ max_children: 0, attempt_timeout_seconds: 0, child_turn_limit: 0 })
		);
		expect(facts.map((f) => f.label)).not.toContain('Maximum tasks');
		expect(facts.map((f) => f.label)).not.toContain('Attempt limit');
		expect(facts.map((f) => f.label)).not.toContain('Tool turns per task');
	});
});

// ---- documents --------------------------------------------------------------------------------

describe('unreadableReason', () => {
	it('is null for a file that can be selected', () => {
		expect(unreadableReason(MSA)).toBeNull();
		expect(unreadableReason(DPA)).toBeNull();
		expect(unreadableReason(document({ reason: 'not_ingested' }))).toBeNull();
	});

	it('says why each recorded file cannot be read, each in its own words', () => {
		const reasons = [DOCX, SCAN, BROKEN, IMAGE_ONLY].map((doc) => unreadableReason(doc));
		expect(reasons).toEqual([
			expect.stringMatching(/type of file cannot be read.*PDF with text, plain text and Markdown/),
			expect.stringMatching(/Not processed yet/),
			expect.stringMatching(/Processing failed/),
			expect.stringMatching(/No text could be extracted/)
		]);
		expect(new Set(reasons).size).toBe(4);
	});

	it('never leaves a file that cannot be read without a reason', () => {
		for (const reason of [undefined, null, '', 'something_new']) {
			const text = unreadableReason(document({ selectable: false, reason }));
			expect(text, String(reason)).toMatch(/^This file cannot be read in a run/);
		}
		expect(unreadableReason(document({ selectable: false, reason: null }))).toBe(
			'This file cannot be read in a run.'
		);
	});

	it('shows a code it has never seen as words, not as a code', () => {
		expect(unreadableReason(document({ selectable: false, reason: 'password_protected' }))).toBe(
			'This file cannot be read in a run (password protected).'
		);
		expect(unreadableReason(document({ selectable: false, reason: 'too-large' }))).toBe(
			'This file cannot be read in a run (too large).'
		);
	});

	it('does not mistake an object property for a reason it knows', () => {
		for (const reason of ['constructor', 'toString', '__proto__', 'hasOwnProperty']) {
			const text = unreadableReason(document({ selectable: false, reason }));
			expect(text, reason).toMatch(/^This file cannot be read in a run \(/);
			expect(text, reason).not.toMatch(/function|native code|\[object/);
		}
	});
});

describe('documentNote', () => {
	it('says a readable file that is not in the matter will be added when the plan is proposed', () => {
		expect(documentNote(DPA)).toBe(ADDED_TO_MATTER_NOTE);
		expect(documentNote(MSA)).toBeNull();
	});

	it('has no note for a file that cannot be selected, in the matter or not', () => {
		expect(documentNote(document({ selectable: false, attached_to_project: false }))).toBeNull();
		expect(documentNote(DOCX)).toBeNull();
	});
});

describe('toggleDocument', () => {
	it('adds a file at the end, so the selection order is the numbering', () => {
		let selected: string[] = [];
		for (const id of ['c', 'a', 'b']) selected = toggleDocument(selected, id, 8);
		expect(selected).toEqual(['c', 'a', 'b']);
	});

	it('removes a file that is selected, and the later ones move up', () => {
		const selected = toggleDocument(['c', 'a', 'b'], 'a', 8);
		expect(selected).toEqual(['c', 'b']);
		expect(documentNumber(selected, 'b')).toBe(2);
	});

	it('stops adding at the limit, but still lets a selected file be removed', () => {
		const full = ['a', 'b'];
		expect(toggleDocument(full, 'c', 2)).toEqual(['a', 'b']);
		expect(toggleDocument(full, 'a', 2)).toEqual(['b']);
		expect(toggleDocument([], 'a', 0)).toEqual([]);
	});

	it('does not change the selection it was given', () => {
		const selected = ['a', 'b'];
		toggleDocument(selected, 'c', 8);
		toggleDocument(selected, 'a', 8);
		expect(selected).toEqual(['a', 'b']);
	});
});

describe('documentNumber', () => {
	it('is the 1-based place in the selection, or null', () => {
		expect(documentNumber(['x', 'y'], 'x')).toBe(1);
		expect(documentNumber(['x', 'y'], 'y')).toBe(2);
		expect(documentNumber(['x', 'y'], 'z')).toBeNull();
		expect(documentNumber([], 'x')).toBeNull();
	});
});

describe('documentRows', () => {
	it('lists every file in the picker, in the list’s order, with the ones that cannot be read disabled and why', () => {
		const rows = documentRows(RECORDED, [], 8);
		expect(rows.map((row) => row.filename)).toEqual([
			'msa.txt',
			'dpa.md',
			'draft.docx',
			'scan.pdf',
			'broken.pdf',
			'image-only.pdf'
		]);
		expect(rows.map((row) => row.disabled)).toEqual([false, false, true, true, true, true]);
		for (const row of rows.slice(2))
			expect(row.reason, row.filename).toBe(unreadableReason(RECORDED[rows.indexOf(row)]));
		for (const row of rows.slice(0, 2)) expect(row.reason).toBeNull();
		expect(rows.every((row) => !row.checked && row.number === null)).toBe(true);
	});

	it('numbers a file by its place in the selection, not by its place in the list', () => {
		const rows = documentRows(RECORDED, [DPA.file_id, MSA.file_id], 8);
		expect(rows.map((row) => row.number)).toEqual([2, 1, null, null, null, null]);
		expect(rows.map((row) => row.checked)).toEqual([true, true, false, false, false, false]);
	});

	it('numbers the documents the way the server numbers them in the plan', () => {
		// Selecting msa.txt then dpa.md: the recorded plan numbers them 1 and 2 and says dpa.md was added.
		const plan = run('documents.awaiting-approval').tree!.plan.documents!;
		const selected = [MSA.file_id, DPA.file_id];
		const rows = documentRows(RECORDED, selected, 8);
		for (const doc of plan) {
			const row = rows.find((candidate) => candidate.fileId === doc.file_id);
			expect(row?.number, doc.filename).toBe(doc.number);
			expect(row?.filename).toBe(doc.filename);
			expect(row?.note !== null, `${doc.filename} added for run`).toBe(doc.attached_for_run);
		}
	});

	it('notes the file that will be added to the matter, and only that one', () => {
		const rows = documentRows(RECORDED, [], 8);
		expect(rows.map((row) => row.note)).toEqual([
			null,
			ADDED_TO_MATTER_NOTE,
			null,
			null,
			null,
			null
		]);
	});

	it('at the limit, disables the files not yet chosen but keeps the chosen ones free to be removed', () => {
		const rows = documentRows(RECORDED, [MSA.file_id], 1);
		const dpa = rows.find((row) => row.filename === 'dpa.md')!;
		expect(dpa.disabled).toBe(true);
		expect(dpa.reason).toBe('Up to 1 document can be selected.');
		const msa = rows.find((row) => row.filename === 'msa.txt')!;
		expect(msa.disabled).toBe(false);
		expect(msa.checked).toBe(true);
		expect(
			documentRows(RECORDED, [MSA.file_id, DPA.file_id], 2)
				.filter((r) => r.checked)
				.every((r) => !r.disabled)
		).toBe(true);
		expect(
			documentRows(RECORDED, [], 8).find((row) => row.filename === 'dpa.md')!.reason
		).toBeNull();
	});

	it('words the limit in the plural, and keeps a file’s own reason over the limit', () => {
		const rows = documentRows(RECORDED, [MSA.file_id, DPA.file_id], 2);
		expect(rows.find((row) => row.filename === 'draft.docx')!.reason).toBe(unreadableReason(DOCX));
		const more = documentRows(
			[MSA, DPA, document({ file_id: 'third', filename: 'third.md' })],
			[MSA.file_id, DPA.file_id],
			2
		);
		expect(more[2].reason).toBe('Up to 2 documents can be selected.');
	});

	it('works on an empty list', () => {
		expect(documentRows([], [], 8)).toEqual([]);
	});
});

describe('pruneSelection', () => {
	it('keeps what is still listed and readable, in the order it was chosen', () => {
		expect(pruneSelection([DPA.file_id, MSA.file_id], RECORDED)).toEqual([
			DPA.file_id,
			MSA.file_id
		]);
	});

	it('drops a file that is no longer listed or can no longer be read', () => {
		expect(pruneSelection([MSA.file_id, 'gone', DOCX.file_id, DPA.file_id], RECORDED)).toEqual([
			MSA.file_id,
			DPA.file_id
		]);
		expect(pruneSelection([MSA.file_id], [])).toEqual([]);
	});

	it('does not change the selection it was given', () => {
		const selected = [MSA.file_id, 'gone'];
		pruneSelection(selected, RECORDED);
		expect(selected).toEqual([MSA.file_id, 'gone']);
	});
});

describe('selecting documents for a run, step by step', () => {
	it('follows the owner from an empty picker to a request the server accepts', () => {
		const max = documents().max_documents;
		expect(max).toBe(8);
		let selected: string[] = [];
		// Reading the list for a profile that needs documents: nothing selected, so nothing to propose.
		const profile = selectedProfile();
		expect(
			proposeBlocker({ profile, goal: 'Compare the two', selectedCount: selected.length })
		).toBe('Select at least one document for this run.');
		selected = toggleDocument(selected, DPA.file_id, max);
		selected = toggleDocument(selected, MSA.file_id, max);
		expect(
			proposeBlocker({ profile, goal: 'Compare the two', selectedCount: selected.length })
		).toBeNull();
		// The list is read again and a file has become unreadable.
		const refreshed = RECORDED.map((doc) =>
			doc.file_id === DPA.file_id ? { ...doc, selectable: false, reason: 'not_ingested' } : doc
		);
		selected = pruneSelection(selected, refreshed);
		expect(selected).toEqual([MSA.file_id]);
		const body = buildStartBody({
			requestId: 'req',
			profile,
			goal: 'Compare the two',
			fileIds: selected
		});
		expect(body.file_ids).toEqual([MSA.file_id]);
	});
});

describe('candidateFileIds and candidatesSignature', () => {
	const files = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `file-${i}` }));

	it('can name every file a chat is allowed to have attached, so none is left out of the picker', () => {
		expect(MAX_CANDIDATE_FILES).toBeGreaterThanOrEqual(MAX_CHAT_ATTACHED_FILES);
		expect(candidateFileIds(files(MAX_CHAT_ATTACHED_FILES))).toHaveLength(MAX_CHAT_ATTACHED_FILES);
	});

	it('names at most the number of candidates one read accepts, in the chat’s order', () => {
		// The API refuses more than 16 `file_id` values in one `run-documents` read.
		expect(MAX_CANDIDATE_FILES).toBe(16);
		expect(candidateFileIds(files(3))).toEqual(['file-0', 'file-1', 'file-2']);
		const many = candidateFileIds(files(40));
		expect(many).toHaveLength(MAX_CANDIDATE_FILES);
		expect(many[0]).toBe('file-0');
		expect(many[15]).toBe('file-15');
		expect(candidateFileIds([])).toEqual([]);
	});

	it('changes when a file is added, removed or finishes processing, and not otherwise', () => {
		const a = [{ id: 'a', ingestion_status: 'pending' }];
		const base = candidatesSignature(a);
		expect(candidatesSignature(structuredClone(a))).toBe(base);
		expect(candidatesSignature([...a, { id: 'b', ingestion_status: 'pending' }])).not.toBe(base);
		expect(candidatesSignature([])).not.toBe(base);
		expect(candidatesSignature([{ id: 'a', ingestion_status: 'ingested' }])).not.toBe(base);
		expect(candidatesSignature([{ id: 'b', ingestion_status: 'pending' }])).not.toBe(base);
	});

	it('does not need an ingestion status', () => {
		expect(candidatesSignature([{ id: 'a' }, { id: 'b' }])).toBe('a:,b:');
		expect(candidatesSignature([])).toBe('');
	});
});

// ---- proposing the plan ---------------------------------------------------------------------------

describe('proposeBlocker', () => {
	const goal = 'Explain payment and renewal.';

	it('enables the action when there is a profile that can be used and a request', () => {
		expect(proposeBlocker({ profile: packetProfile(), goal, selectedCount: 0 })).toBeNull();
		expect(proposeBlocker({ profile: selectedProfile(), goal, selectedCount: 1 })).toBeNull();
		expect(proposeBlocker({ profile: selectedProfile(), goal, selectedCount: 8 })).toBeNull();
	});

	it('asks for a profile first', () => {
		expect(proposeBlocker({ profile: null, goal, selectedCount: 0 })).toBe(
			'Choose what to run first.'
		);
		expect(proposeBlocker({ profile: null, goal: '', selectedCount: 0 })).toBe(
			'Choose what to run first.'
		);
	});

	it('asks for a request, and does not count blank space as one', () => {
		for (const text of ['', ' ', '\n\t  \n']) {
			expect(proposeBlocker({ profile: packetProfile(), goal: text, selectedCount: 0 })).toBe(
				'Describe what the run should examine.'
			);
		}
	});

	it('limits the request to what the API accepts, counted after trimming', () => {
		expect(MAX_GOAL_CHARS).toBe(4096);
		const limit = (text: string) =>
			proposeBlocker({ profile: packetProfile(), goal: text, selectedCount: 0 });
		expect(limit('x'.repeat(4096))).toBeNull();
		expect(limit(`  ${'x'.repeat(4096)}  `)).toBeNull();
		expect(limit('x'.repeat(4097))).toBe('The request is limited to 4,096 characters.');
	});

	it('wants a document for a profile that reads a selection, and not for one that reads a fixed document', () => {
		const need = (profile: ProfileAvailability, selectedCount: number) =>
			proposeBlocker({ profile, goal, selectedCount });
		expect(need(selectedProfile(), 0)).toBe('Select at least one document for this run.');
		expect(need(selectedProfile(), 1)).toBeNull();
		expect(need(packetProfile(), 0)).toBeNull();
	});

	it('blocks a profile that stopped being available while it was chosen, with the profile’s reason', () => {
		const profile = selectedProfile({ available: false, reason: 'active_run', reason_text: null });
		expect(proposeBlocker({ profile, goal, selectedCount: 2 })).toBe(unavailableReason(profile));
	});

	it('reports the first thing in the way: the profile, its availability, the request, then the documents', () => {
		const unavailable = selectedProfile({
			available: false,
			reason: 'operator_disabled',
			reason_text: null
		});
		expect(proposeBlocker({ profile: unavailable, goal: '', selectedCount: 0 })).toBe(
			unavailableReason(unavailable)
		);
		expect(proposeBlocker({ profile: selectedProfile(), goal: '', selectedCount: 0 })).toBe(
			'Describe what the run should examine.'
		);
		expect(
			proposeBlocker({ profile: selectedProfile(), goal: 'x'.repeat(5000), selectedCount: 0 })
		).toMatch(/limited to 4,096/);
	});
});

// ---- the request that starts a run -----------------------------------------------------------------

describe('requestSignature', () => {
	const parts = {
		chatId: 'chat-1',
		profile: 'model_demo_v1',
		goal: 'Explain.',
		fileIds: ['a', 'b']
	};

	it('is the same for the same request, however the goal is padded', () => {
		expect(requestSignature({ ...parts, goal: '  Explain.\n' })).toBe(requestSignature(parts));
		expect(requestSignature({ ...parts, fileIds: [...parts.fileIds] })).toBe(
			requestSignature(parts)
		);
	});

	it('differs when anything the server would treat as a different request differs', () => {
		const base = requestSignature(parts);
		expect(requestSignature({ ...parts, chatId: 'chat-2' })).not.toBe(base);
		expect(requestSignature({ ...parts, profile: 'contract_qa_documents_v1' })).not.toBe(base);
		expect(requestSignature({ ...parts, goal: 'Explain more.' })).not.toBe(base);
		expect(requestSignature({ ...parts, fileIds: ['a'] })).not.toBe(base);
		// The order is the numbering, so it is part of the request.
		expect(requestSignature({ ...parts, fileIds: ['b', 'a'] })).not.toBe(base);
	});

	it('keeps the parts apart, so two different requests cannot share a signature', () => {
		const one = requestSignature({ chatId: 'a', profile: 'b|c', goal: 'd', fileIds: [] });
		const two = requestSignature({ chatId: 'a', profile: 'b', goal: 'c|d', fileIds: [] });
		const three = requestSignature({ chatId: 'a","b', profile: 'c', goal: 'd', fileIds: [] });
		const four = requestSignature({ chatId: 'a', profile: 'b","c', goal: 'd', fileIds: [] });
		expect(new Set([one, two, three, four]).size).toBe(4);
	});
});

describe('requestFor', () => {
	const counter = () => {
		let n = 0;
		return { make: () => `id-${(n += 1)}`, calls: () => n };
	};

	it('makes an id for a first request', () => {
		const ids = counter();
		expect(requestFor(null, 'sig-1', ids.make)).toEqual({ id: 'id-1', signature: 'sig-1' });
	});

	it('keeps the id while the same request is retried, so a lost response cannot start a second run', () => {
		const ids = counter();
		const first = requestFor(null, 'sig-1', ids.make);
		const retry = requestFor(first, 'sig-1', ids.make);
		const again = requestFor(retry, 'sig-1', ids.make);
		expect(retry).toBe(first);
		expect(again.id).toBe('id-1');
		expect(ids.calls()).toBe(1);
	});

	it('makes a new id as soon as the request changes, since the server refuses an id reused with different input', () => {
		const ids = counter();
		const first = requestFor(null, 'sig-1', ids.make);
		const changed = requestFor(first, 'sig-2', ids.make);
		expect(changed.id).toBe('id-2');
		expect(changed.signature).toBe('sig-2');
		// Changing it back is a different request again, not a return to the first.
		expect(requestFor(changed, 'sig-1', ids.make).id).toBe('id-3');
	});

	it('plays out a lost response, an edited goal and a success', () => {
		const ids = counter();
		const sign = (goal: string) =>
			requestSignature({ chatId: 'c', profile: 'model_demo_v1', goal, fileIds: [] });
		let pending = requestFor(null, sign('Explain the renewal.'), ids.make);
		const firstAttempt = pending.id;
		// The response was lost; the owner presses Propose plan again.
		pending = requestFor(pending, sign('Explain the renewal.'), ids.make);
		expect(pending.id).toBe(firstAttempt);
		// The owner edits the goal before trying again: a different request, a different id.
		pending = requestFor(pending, sign('Explain the renewal and notice.'), ids.make);
		expect(pending.id).not.toBe(firstAttempt);
		// After a success the panel forgets the request (`null`), so the next run gets its own id.
		const next = requestFor(null, sign('Explain the renewal and notice.'), ids.make);
		expect(next.id).not.toBe(pending.id);
	});
});

describe('newRequestId', () => {
	const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('is a version 4 UUID, which is what the API accepts as a request id', () => {
		expect(newRequestId()).toMatch(UUID_V4);
	});

	it('is a different id every time', () => {
		expect(new Set(Array.from({ length: 200 }, newRequestId)).size).toBe(200);
	});

	it('uses the browser’s own generator when it has one', () => {
		vi.stubGlobal('crypto', { randomUUID: () => '11111111-2222-4333-8444-555555555555' });
		expect(newRequestId()).toBe('11111111-2222-4333-8444-555555555555');
	});

	it('builds a valid id from random bytes on a page served without a secure context', () => {
		// No randomUUID: only getRandomValues. All-ones bytes make the version and variant bits visible.
		vi.stubGlobal('crypto', {
			getRandomValues: (bytes: Uint8Array) => {
				bytes.fill(0xff);
				return bytes;
			}
		});
		expect(newRequestId()).toBe('ffffffff-ffff-4fff-bfff-ffffffffffff');
		vi.stubGlobal('crypto', {
			getRandomValues: (bytes: Uint8Array) => {
				bytes.fill(0);
				return bytes;
			}
		});
		expect(newRequestId()).toBe('00000000-0000-4000-8000-000000000000');
	});

	it('still makes a valid, varying id with no crypto at all', () => {
		vi.stubGlobal('crypto', undefined);
		const ids = Array.from({ length: 100 }, newRequestId);
		for (const id of ids) expect(id).toMatch(UUID_V4);
		expect(new Set(ids).size).toBe(100);
	});
});

describe('buildStartBody', () => {
	it('sends a profile that reads selected documents the owner’s selection, in order', () => {
		const fileIds = [DPA.file_id, MSA.file_id];
		const body = buildStartBody({
			requestId: 'req-1',
			profile: selectedProfile(),
			goal: '  Explain payment.  ',
			fileIds
		});
		expect(body).toEqual({
			request_id: 'req-1',
			profile: 'contract_qa_documents_v1',
			goal: 'Explain payment.',
			file_ids: [DPA.file_id, MSA.file_id]
		});
		// A copy: changing the selection afterwards does not change a request already built.
		expect(body.file_ids).not.toBe(fileIds);
	});

	it('sends a profile that reads a fixed document no file ids, because the server refuses them', () => {
		const body = buildStartBody({
			requestId: 'req-2',
			profile: packetProfile(),
			goal: 'Explain payment.',
			fileIds: [MSA.file_id]
		});
		expect(body).toEqual({
			request_id: 'req-2',
			profile: 'model_demo_v1',
			goal: 'Explain payment.'
		});
		expect('file_ids' in body).toBe(false);
	});

	it('carries only the fields the API accepts, and serialises without gaps', () => {
		for (const profile of [packetProfile(), selectedProfile()]) {
			const body = buildStartBody({ requestId: 'r', profile, goal: 'g', fileIds: ['f'] });
			expect(
				Object.keys(body).every((key) =>
					['request_id', 'profile', 'goal', 'file_ids'].includes(key)
				)
			).toBe(true);
			expect(JSON.parse(JSON.stringify(body))).toEqual(body);
		}
	});
});
