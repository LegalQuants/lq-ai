/**
 * The composer before a run exists: why a profile cannot be chosen, what blocks a new
 * run, which documents can be picked and in what order, when Send is enabled beside New harness,
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
	ANSWERS_DIRECTLY_TEXT,
	answersDirectly,
	CLOSE_RUN_NOTE,
	DEFAULT_MAX_DOCUMENTS,
	KNOWLEDGE_SEARCH_TOOL,
	MAX_CANDIDATE_FILES,
	MAX_GOAL_CHARS,
	MAX_RUN_KNOWLEDGE_BASES,
	NOT_PSEUDONYMIZED_TEXT,
	PSEUDONYMIZED_TEXT,
	SUMMARY_NAMES,
	activeRunLabel,
	activeRunStatusText,
	answersDirectlyText,
	buildStartBody,
	canCloseActiveRun,
	candidateFileIds,
	candidatesSignature,
	defaultDocumentSelection,
	documentNote,
	documentNumber,
	documentRows,
	documentsReadSignature,
	documentsSummary,
	spendSummary,
	instructionRows,
	knowledgeBasesLine,
	knowledgeBasesLineParts,
	matterTermsNote,
	minDocuments,
	newRequestId,
	pickerEmpty,
	pickerHelp,
	proposeBlocker,
	pruneSelection,
	pseudonymizationText,
	requestFor,
	requestSignature,
	sendWording,
	routeText,
	runModeFacts,
	searchesKnowledgeBases,
	syncActiveRun,
	takesDocuments,
	toggleDocument,
	toolLabelList,
	toolsOffered,
	unavailableReason,
	unreadableReason
} from '../composer';
import { namedLineText } from '../format';
import { POLL_START_MS } from '../polling';
import { ACTIVE_STATUSES, TERMINAL_STATUSES, UNCERTAIN_EXPLANATION, runHeadline } from '../status';
import { documents, profiles, run } from './fixtures';

/** The profile that reads a fixed document, available. */
const packetProfile = (patch: Partial<ProfileAvailability> = {}): ProfileAvailability => ({
	...structuredClone(profiles('available').profiles[0]),
	...patch
});

/** New harness as the server records it: documents optional (none to eight), available. */
const harnessProfile = (patch: Partial<ProfileAvailability> = {}): ProfileAvailability => ({
	...structuredClone(profiles('documents').profiles[1]),
	...patch
});

/**
 * A profile that needs at least one document. No recording has one: the one profile that
 * takes documents, New harness, takes them as the owner likes. So this is New harness
 * patched the way the API documents a profile that needs one (`selected`, `min_documents: 1`).
 */
const selectedProfile = (patch: Partial<ProfileAvailability> = {}): ProfileAvailability =>
	harnessProfile({ documents: 'selected', min_documents: 1, ...patch });

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
	'role_read_only',
	'chat_archived',
	'project_required',
	'project_unavailable',
	'project_not_permitted',
	'route_unavailable',
	'active_run'
] as const;

/** What a person needs to read, by code, so the wording can change but not the substance. */
const SUBSTANCE: Record<(typeof CODES)[number], RegExp> = {
	operator_disabled: /operator has not enabled/i,
	not_configured: /configuration is incomplete/i,
	autonomous_opt_in_required: /Autonomous.*settings/i,
	role_read_only: /read-only.*cannot start a run/i,
	chat_archived: /chat is archived/i,
	project_required: /no matter/i,
	project_unavailable: /matter.*not available/i,
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
		// The recordings carry the server's text for three of the codes. It names the profile
		// ("The operator has not enabled New harness."), so the fallback does too: a profile is
		// described the same way whether or not the server's own words arrived.
		const recorded: [string, ProfileAvailability][] = [
			['operator_disabled', profiles('available').profiles[1]],
			['project_required', profiles('harness-no-project').profiles[0]],
			['active_run', profiles('active-run').profiles[0]]
		];
		for (const [code, profile] of recorded) {
			expect(profile.reason).toBe(code);
			expect(unavailableReason({ ...profile, reason_text: null }), code).toBe(profile.reason_text);
		}
	});

	it('names the profile in the sentences that are about it, and says "this profile" when it has no title', () => {
		const named = (reason: string, title: string) =>
			unavailableReason(packetProfile({ available: false, reason, reason_text: null, title }));
		expect(named('operator_disabled', 'New harness')).toBe(
			'The operator has not enabled New harness.'
		);
		expect(named('not_configured', 'New harness')).toBe(
			'The operator has enabled New harness but its configuration is incomplete.'
		);
		expect(named('project_required', 'New harness')).toBe(
			'New harness starts from a chat inside a matter. This chat has no matter.'
		);
		expect(named('project_not_permitted', 'New harness')).toBe(
			'The operator has limited New harness to a dedicated demo matter.'
		);
		for (const title of ['', '   ']) {
			expect(named('operator_disabled', title)).toBe('The operator has not enabled this profile.');
			expect(named('project_required', title)).toMatch(/^This profile starts from a chat/);
		}
	});

	it('says in a chat that is archived, or whose matter is not available, that it cannot start a run', () => {
		expect(
			unavailableReason(
				packetProfile({ available: false, reason: 'chat_archived', reason_text: null })
			)
		).toBe('This chat is archived, so it cannot start a run.');
		expect(
			unavailableReason(
				packetProfile({ available: false, reason: 'project_unavailable', reason_text: null })
			)
		).toBe('The matter this chat belongs to is not available, so it cannot start a run.');
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
		for (const name of [
			'available',
			'active-run',
			'uncertain-run',
			'no-project',
			'documents',
			'harness-no-project'
		]) {
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
		expect(activeRunStatusText('planning')).toBe('Reading the request');
		expect(activeRunStatusText('awaiting_approval')).toBe('Waiting for your approval');
		expect(activeRunStatusText('queued')).toBe('Approved, waiting to start');
		expect(activeRunStatusText('running')).toBe('Tasks are running');
		expect(activeRunStatusText('waiting_children')).toBe('Tasks are running');
	});

	it('says a run that is planning is being read, which is true whether or not the model may answer instead of proposing a plan', () => {
		const text = activeRunStatusText('planning');
		expect(text).not.toMatch(/propos|plan/i);
		// The notice has no terms to tell the two modes apart, so it says what neither contradicts.
		expect(text).toBe('Reading the request');
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
			'Save a working note',
			"Search the matter's knowledge bases"
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

describe('the tools the strip lists for the tasks of a run', () => {
	const harness = profiles('harness').profiles[1];
	const withKnowledgeBases = documents('knowledge-bases');
	const names = (tools: RunTool[]) => tools.map((tool) => tool.name);

	it('lists the search of the matter’s knowledge bases where the read lists some, in the profile’s order', () => {
		expect(names(harness.tools)).toEqual([
			'read_document',
			'read_note',
			'save_note',
			KNOWLEDGE_SEARCH_TOOL
		]);
		expect(searchesKnowledgeBases(withKnowledgeBases)).toBe(true);
		expect(toolsOffered(harness.tools, withKnowledgeBases)).toEqual(harness.tools);
		expect(toolLabelList(toolsOffered(harness.tools, withKnowledgeBases))).toContain(
			"Search the matter's knowledge bases"
		);
	});

	it('leaves it out where the read lists none: outside a matter, and in a matter with none attached', () => {
		for (const name of ['list', 'after-run', 'no-project']) {
			const read = documents(name);
			expect(searchesKnowledgeBases(read), name).toBe(false);
			expect(names(toolsOffered(harness.tools, read)), name).toEqual([
				'read_document',
				'read_note',
				'save_note'
			]);
		}
		expect(names(toolsOffered(harness.tools, { knowledge_bases: [] }))).not.toContain(
			KNOWLEDGE_SEARCH_TOOL
		);
	});

	it('leaves it out until the read has come back, or from a server that does not say', () => {
		for (const read of [null, undefined, {}, { knowledge_bases: undefined }]) {
			expect(searchesKnowledgeBases(read), JSON.stringify(read)).toBe(false);
			expect(names(toolsOffered(harness.tools, read)), JSON.stringify(read)).not.toContain(
				KNOWLEDGE_SEARCH_TOOL
			);
		}
	});

	it('takes nothing else away, and does not touch the profile’s own list', () => {
		const before = structuredClone(harness.tools);
		const offered = toolsOffered(harness.tools, null);
		expect(offered).toHaveLength(harness.tools.length - 1);
		for (const tool of offered) expect(harness.tools).toContain(tool);
		expect(harness.tools).toEqual(before);
		// A profile that never had the tool is listed as it is, however the read stands.
		const demo = profiles('harness').profiles[0];
		expect(toolsOffered(demo.tools, null)).toEqual(demo.tools);
		expect(toolsOffered(demo.tools, withKnowledgeBases)).toEqual(demo.tools);
		expect(toolsOffered(null, withKnowledgeBases)).toEqual([]);
		expect(toolsOffered(undefined, null)).toEqual([]);
	});

	it('leaves out the read of a document where the profile’s documents are optional and none is selected', () => {
		expect(harness.documents).toBe('optional');
		const none = toolsOffered(harness.tools, withKnowledgeBases, {
			policy: harness.documents,
			count: 0
		});
		expect(names(none)).toEqual(['read_note', 'save_note', KNOWLEDGE_SEARCH_TOOL]);
		expect(toolLabelList(none)).not.toContain('Read a selected document');
		// With one selected it is listed, as the profile lists it.
		for (const count of [1, 8]) {
			expect(
				toolsOffered(harness.tools, withKnowledgeBases, { policy: harness.documents, count }),
				String(count)
			).toEqual(harness.tools);
		}
	});

	it('leaves out both at once where there is nothing to read and nothing to search', () => {
		const offered = toolsOffered(harness.tools, documents('no-project'), {
			policy: 'optional',
			count: 0
		});
		expect(names(offered)).toEqual(['read_note', 'save_note']);
	});

	it('leaves the read of a document where the profile needs a selection, or reads a fixed packet', () => {
		// A run that needs a document cannot start without one, and a packet is always read.
		for (const policy of ['selected', 'packet'] as const) {
			expect(
				names(toolsOffered(harness.tools, withKnowledgeBases, { policy, count: 0 })),
				policy
			).toContain('read_document');
		}
		const packet = profiles('harness').profiles[0];
		expect(packet.documents).toBe('packet');
		expect(
			toolsOffered(packet.tools, null, { policy: packet.documents, count: 0 }),
			'the recorded packet profile'
		).toEqual(packet.tools);
	});

	it('lists the read of a document while it is not known what is selected', () => {
		expect(names(toolsOffered(harness.tools, withKnowledgeBases))).toContain('read_document');
		expect(names(toolsOffered(harness.tools, withKnowledgeBases, null))).toContain('read_document');
	});

	it('takes only the read of a document away, and does not touch the profile’s own list', () => {
		const before = structuredClone(harness.tools);
		const offered = toolsOffered(harness.tools, withKnowledgeBases, {
			policy: 'optional',
			count: 0
		});
		expect(offered).toHaveLength(harness.tools.length - 1);
		for (const tool of offered) expect(harness.tools).toContain(tool);
		expect(harness.tools).toEqual(before);
	});

	it('counts a knowledge base with a name, and not one with nothing in it', () => {
		const blank = { knowledge_bases: [{ knowledge_base_id: 'a', name: '  ' }] };
		expect(searchesKnowledgeBases(blank)).toBe(false);
		const named = { knowledge_bases: [{ knowledge_base_id: 'a', name: 'Travel' }] };
		expect(searchesKnowledgeBases(named)).toBe(true);
		// The line that names the knowledge bases and the tool that searches them agree.
		for (const read of [blank, named, withKnowledgeBases, documents('list'), null]) {
			expect(searchesKnowledgeBases(read), JSON.stringify(read)).toBe(
				knowledgeBasesLine(read) !== null
			);
		}
	});
});

describe('runModeFacts', () => {
	it('lists what a fixed-document run will use and may spend, before anything is sent', () => {
		expect(runModeFacts(profiles('available').profiles[0])).toEqual([
			// The route is the model and, once it is priced, the inference tier it resolves to.
			{ label: 'Route', value: 'selected/native · inference tier 1' },
			{ label: 'Total cap', value: '$2.00' },
			{ label: 'Planning allowance', value: '$0.2478' },
			{ label: 'Per-task allowance', value: '$0.7434' },
			{ label: 'Maximum tasks', value: '2' },
			{ label: 'Attempt limit', value: '2 minutes per attempt' },
			{ label: 'Tool turns per task', value: 'up to 2, then one answer' }
		]);
	});

	it('lists the same for New harness, with its own figures', () => {
		const facts = Object.fromEntries(runModeFacts(harnessProfile()).map((f) => [f.label, f.value]));
		expect(facts).toEqual({
			Route: 'selected/native · inference tier 1',
			'Total cap': '$10.00',
			'Planning allowance': '$0.5781',
			'Per-task allowance': '$3.4686',
			'Maximum tasks': '2',
			'Attempt limit': '5 minutes per attempt',
			'Tool turns per task': 'up to 5, then one answer'
		});
	});

	it('leaves out what the server has not priced instead of showing it as zero', () => {
		// The recorded unavailable profiles carry no model, tier, cap, allowance or attempt limit.
		const unpriced = [
			profiles('available').profiles[1],
			profiles('harness-no-project').profiles[0]
		];
		for (const profile of unpriced) {
			expect(profile.budget_usd).toBeNull();
			expect(profile.routed_tier).toBeNull();
			const facts = runModeFacts(profile);
			expect(facts.map((f) => f.label)).toEqual(['Tool turns per task']);
			for (const fact of facts) expect(fact.value).not.toMatch(/\$0\.00|—|null|undefined|NaN/);
		}
	});

	it('says the reasoning effort when the operator set one, and nothing when it did not', () => {
		expect(runModeFacts(harnessProfile()).map((f) => f.label)).not.toContain('Reasoning effort');
		for (const reasoning_effort of [null, undefined, '', '  ']) {
			expect(
				runModeFacts(harnessProfile({ reasoning_effort })).map((f) => f.label),
				String(reasoning_effort)
			).not.toContain('Reasoning effort');
		}
		const facts = runModeFacts(harnessProfile({ reasoning_effort: ' high ' }));
		expect(facts.find((f) => f.label === 'Reasoning effort')?.value).toBe('high');
		// Right after the route it belongs to.
		expect(facts.map((f) => f.label).slice(0, 2)).toEqual(['Route', 'Reasoning effort']);
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

describe('the route a run is pinned to', () => {
	it('is the model and the inference tier it resolves to', () => {
		expect(routeText(harnessProfile())).toBe('selected/native · inference tier 1');
		expect(routeText(harnessProfile({ routed_tier: 3 }))).toBe(
			'selected/native · inference tier 3'
		);
	});

	it('is the model alone until the route is priced, the tier alone if only that is stated, and nothing otherwise', () => {
		expect(routeText(harnessProfile({ routed_tier: null }))).toBe('selected/native');
		expect(routeText(harnessProfile({ routed_tier: undefined, model: '  ' }))).toBeNull();
		expect(routeText(harnessProfile({ model: null, routed_tier: 2 }))).toBe('inference tier 2');
		expect(routeText(harnessProfile({ model: null, routed_tier: null }))).toBeNull();
		// A tier of 0 is a tier.
		expect(routeText(harnessProfile({ routed_tier: 0 }))).toBe(
			'selected/native · inference tier 0'
		);
	});
});

describe('what the route does to the text', () => {
	it('says what is replaced with placeholders when the gateway pseudonymizes, and what is not', () => {
		const text = pseudonymizationText(harnessProfile({ pseudonymized: true }))!;
		expect(text).toBe(PSEUDONYMIZED_TEXT);
		expect(text).toContain(
			'the gateway replaces what it recognises as a personal name or an identifier'
		);
		// A placeholder the gateway did not assign cannot be turned back, so the plan is refused: said before the run,
		// right after the sentence that says placeholders are put back, where it qualifies it.
		expect(text).toContain(
			'and puts it back in what the model writes. That includes the plan. A plan that still carries a placeholder, one the gateway did not assign, is refused and nothing runs. It does not recognise everything'
		);
		// What a task reads goes the same way: the gateway rewrites it like the request.
		expect(text).toContain('the plan and what a task reads');
		// It must not read as a guarantee (docs/security/anonymization.md): the layer misses
		// things silently, and organisation names are never replaced (PRD DE-397).
		expect(text).toContain('It does not recognise everything, and a miss is not reported.');
		expect(text).toContain('Organisation names are not replaced.');
		// Neither of the two sentences the person read before the gateway rewrote what a task
		// reads is left: document text no longer goes as written, and a task's notes and
		// stated reasons no longer show a placeholder (the gateway restores them).
		expect(text).not.toContain('is sent as written');
		expect(text).not.toContain('so that its quotations can be checked');
		expect(text).not.toContain('may show a placeholder');
		expect(text).not.toMatch(/before text leaves|all names|every name|always/i);
	});

	it('says the text goes as written when it does not, and why', () => {
		expect(pseudonymizationText(harnessProfile({ pseudonymized: false }))).toBe(
			"Text is sent to the model as written: the operator's setting applies no pseudonymization at this route's tier."
		);
		expect(NOT_PSEUDONYMIZED_TEXT).toMatch(/no pseudonymization/);
	});

	it('says nothing while the route is not priced, rather than guessing either way', () => {
		for (const pseudonymized of [null, undefined]) {
			expect(pseudonymizationText(harnessProfile({ pseudonymized }))).toBeNull();
		}
		// The recorded unavailable profile has no word on it.
		expect(pseudonymizationText(profiles('available').profiles[1])).toBeNull();
	});
});

describe('whether the profile answers by itself, as the server says', () => {
	it('is true only for the server’s `true`: the recorded New harness, not the demonstration', () => {
		const [demo, harness] = profiles('harness').profiles;
		expect(answersDirectly(harness)).toBe(true);
		expect(answersDirectly(demo)).toBe(false);
	});

	it('is false for a server that does not say, a profile that says no, and anything else', () => {
		for (const value of [undefined, null, false, 'true', 'yes', 1, 0, {}, []]) {
			expect(answersDirectly({ answers_directly: value as boolean }), String(value)).toBe(false);
		}
		expect(answersDirectly({})).toBe(false);
		expect(answersDirectly(null)).toBe(false);
		expect(answersDirectly(undefined)).toBe(false);
	});

	it('takes nothing from the profile’s name, its title or its model', () => {
		const [, harness] = profiles('harness').profiles;
		for (const patch of [
			{ profile: 'direct_answers_v9', title: 'Answers directly', summary: 'answers directly' },
			{ model: 'selected/direct', reads: 'answers directly' }
		]) {
			expect(
				answersDirectly({ ...harness, ...patch, answers_directly: false }),
				JSON.stringify(patch)
			).toBe(false);
			expect(
				answersDirectly({ ...harness, ...patch, answers_directly: undefined }),
				JSON.stringify(patch)
			).toBe(false);
		}
	});

	it('words what Send does by that, and by nothing else', () => {
		expect(sendWording(true).sendTitle).toBe(
			'Makes one model call. It answers a request that needs nothing read, or proposes a plan. No task runs until you approve a plan.'
		);
		expect(sendWording(false).sendTitle).toBe(
			'Asks the model for a plan. Nothing else runs until you approve it.'
		);
		expect(sendWording(true).failure).toBe('Could not send the request.');
		expect(sendWording(false).failure).toBe('Could not ask for a plan.');
		// A wording for one never says what the other says.
		expect(sendWording(true).pickerNote).not.toMatch(/^Plans your request/);
		expect(sendWording(false).pickerNote).not.toMatch(/Answers a request/);
		expect(sendWording(false).pickerTitle).not.toMatch(/answers the request/);
	});

	it('does not claim an approval where there is none, or a check, in any of the wording', () => {
		for (const answers of [true, false]) {
			for (const text of Object.values(sendWording(answers))) {
				expect(text, text).not.toMatch(/\b(verified|confirmed|checked)\b/i);
			}
		}
		// A request answered by itself is not put to the owner for approval, and the wording says
		// that no task runs before a plan is approved, which is true of both.
		expect(sendWording(true).sendTitle).toContain('No task runs until you approve a plan.');
		expect(sendWording(true).pickerTitle).toContain('Tasks run only after you approve the plan.');
	});
});

describe('what the strip says of an answer given without a plan', () => {
	it('says that a request needing nothing read may be answered at once, and that no approval is asked for it', () => {
		const profile = profiles('harness').profiles[1];
		expect(profile.profile).toBe('new_harness_v1');
		expect(profile.answers_directly).toBe(true);
		expect(answersDirectlyText(profile)).toBe(
			'A request that needs nothing read may be answered at once, without a plan. That answer is not put to you for approval.'
		);
		expect(ANSWERS_DIRECTLY_TEXT).toBe(answersDirectlyText(profile));
	});

	it('says nothing for a profile that always plans, or that the server does not say about', () => {
		const demo = profiles('harness').profiles[0];
		expect(demo.answers_directly).toBe(false);
		expect(answersDirectlyText(demo)).toBeNull();
		for (const stated of [undefined, null, 'yes', 1, 0, '']) {
			expect(
				answersDirectlyText({ answers_directly: stated as unknown as boolean }),
				String(stated)
			).toBeNull();
		}
	});

	it('says it of New harness in every recorded read, whether or not it can be used there', () => {
		for (const name of ['harness', 'documents', 'available', 'no-project', 'harness-no-project']) {
			const read = profiles(name);
			const harness = read.profiles.find((profile) => profile.profile === read.composer_profile)!;
			expect(answersDirectlyText(harness), name).toBe(ANSWERS_DIRECTLY_TEXT);
		}
	});

	it('does not claim a check, a source or advice', () => {
		expect(ANSWERS_DIRECTLY_TEXT).not.toMatch(
			/(?<!un)verified|\bchecked\b|\bconfirmed\b|\bcorrect|\baccurate|advice/i
		);
		expect(ANSWERS_DIRECTLY_TEXT).not.toMatch(/[<>_]/);
	});
});

describe('the line about the knowledge bases a task may search', () => {
	const read = documents('knowledge-bases');
	const named = (...names: string[]) => ({
		knowledge_bases: names.map((name, at) => ({ knowledge_base_id: `kb-${at}`, name })),
		knowledge_bases_omitted: 0
	});

	it('names the matter’s knowledge bases, in the order the server lists them', () => {
		expect(read.knowledge_bases!.map((kb) => kb.name)).toEqual(['People policies', 'Travel']);
		expect(knowledgeBasesLine(read)).toBe(
			"Tasks may search this matter's knowledge bases: People policies, Travel."
		);
		expect(knowledgeBasesLine(named('Only one'))).toBe(
			"Tasks may search this matter's knowledge bases: Only one."
		);
	});

	it('says nothing when there are none: outside a matter, in a matter with none, or from an older server', () => {
		for (const name of ['list', 'after-run', 'no-project']) {
			expect(knowledgeBasesLine(documents(name)), name).toBeNull();
		}
		expect(knowledgeBasesLine(named())).toBeNull();
		expect(knowledgeBasesLine({})).toBeNull();
		expect(knowledgeBasesLine({ knowledge_bases: undefined })).toBeNull();
		expect(knowledgeBasesLine(null)).toBeNull();
		expect(knowledgeBasesLine(undefined)).toBeNull();
		// A name with nothing in it is not a name to show.
		expect(knowledgeBasesLine(named('', '   '))).toBeNull();
		expect(knowledgeBasesLine(named('', 'Travel'))).toBe(
			"Tasks may search this matter's knowledge bases: Travel."
		);
	});

	it('says how many more are attached than a run lists, and that those are not searched', () => {
		expect(MAX_RUN_KNOWLEDGE_BASES).toBe(16);
		const many = { ...named('People policies', 'Travel'), knowledge_bases_omitted: 3 };
		expect(knowledgeBasesLine(many)).toBe(
			"Tasks may search this matter's knowledge bases: People policies, Travel. 3 more attached to this matter are not searched: a run lists at most 16."
		);
	});

	it('words one more in the singular, which the sentence as given does not', () => {
		const one = { ...named('People policies'), knowledge_bases_omitted: 1 };
		expect(knowledgeBasesLine(one)).toBe(
			"Tasks may search this matter's knowledge bases: People policies. 1 more attached to this matter is not searched: a run lists at most 16."
		);
	});

	it('says nothing about omitted ones when none are, or when the count is not a number above zero', () => {
		for (const omitted of [0, -2, Number.NaN, Number.POSITIVE_INFINITY, undefined, null, '3']) {
			expect(
				knowledgeBasesLine({ ...named('Travel'), knowledge_bases_omitted: omitted as number }),
				String(omitted)
			).toBe("Tasks may search this matter's knowledge bases: Travel.");
		}
		// Omitted ones with nothing listed have no line either: the line is about what is searched.
		expect(knowledgeBasesLine({ ...named(), knowledge_bases_omitted: 4 })).toBeNull();
	});

	it('reads a count with a fraction as the whole number it is', () => {
		expect(knowledgeBasesLine({ ...named('Travel'), knowledge_bases_omitted: 2.9 })).toContain(
			' 2 more attached to this matter are not searched'
		);
	});

	it('names no knowledge base that was not listed, and says nothing was picked', () => {
		const line = knowledgeBasesLine(read)!;
		expect(line).not.toMatch(/picked|chose|selected/i);
		for (const kb of read.knowledge_bases!) expect(line).toContain(kb.name);
	});

	it('carries the same line in pieces, one item to a name, for a component that draws each by itself', () => {
		expect(knowledgeBasesLineParts(read)).toEqual({
			lead: "Tasks may search this matter's knowledge bases: ",
			names: ['People policies', 'Travel'],
			tail: '.'
		});
		expect(knowledgeBasesLineParts({ ...read, knowledge_bases_omitted: 3 })).toEqual({
			lead: "Tasks may search this matter's knowledge bases: ",
			names: ['People policies', 'Travel'],
			tail: '. 3 more attached to this matter are not searched: a run lists at most 16.'
		});
		// Where there is no line there are no pieces, and the other way round.
		for (const value of [null, undefined, {}, documents('list'), named(), named('', '  ')]) {
			expect(knowledgeBasesLineParts(value), JSON.stringify(value)).toBeNull();
			expect(knowledgeBasesLine(value), JSON.stringify(value)).toBeNull();
		}
	});

	it('is, put together, the line it carries, in every state the read can be in', () => {
		for (const value of [
			read,
			{ ...read, knowledge_bases_omitted: 1 },
			{ ...read, knowledge_bases_omitted: 4 },
			{ ...read, knowledge_bases_omitted: 2.9 },
			named('Only one'),
			named('Only one', 'and, two')
		]) {
			const parts = knowledgeBasesLineParts(value)!;
			expect(namedLineText(parts), JSON.stringify(value)).toBe(knowledgeBasesLine(value));
		}
	});

	it('keeps each name as one item as it was written, apart from the spaces around it', () => {
		const parts = knowledgeBasesLineParts(named('  Travel, Expenses ', '', '\u202Eevil'))!;
		expect(parts.names).toEqual(['Travel, Expenses', '\u202Eevil']);
		expect(parts.lead).not.toMatch(/[<>]/);
		expect(parts.tail).not.toMatch(/[<>]/);
	});
});

describe('instructionRows', () => {
	it('lists New harness’s two prompt files, labelled by role and version, in the server’s order', () => {
		expect(instructionRows(harnessProfile())).toEqual([
			{
				role: 'orchestrator',
				kind: 'prompt',
				label: 'Orchestrator prompt, version 2',
				name: 'new_harness/orchestrator.v2',
				detail: null
			},
			{
				role: 'sub-agent',
				kind: 'prompt',
				label: 'Sub-agent prompt, version 2',
				name: 'new_harness/subagent.v2',
				detail: null
			}
		]);
	});

	it('names an installed skill as text with its version, so there is nothing to fetch', () => {
		const rows = instructionRows(packetProfile());
		expect(rows).toEqual([
			{
				role: 'orchestrator',
				kind: 'skill',
				label: 'Orchestrator skill',
				name: 'orchestration-chat-demo',
				detail: 'orchestration-chat-demo (version 1.0.0)'
			},
			{
				role: 'sub-agent',
				kind: 'skill',
				label: 'Sub-agent skill',
				name: 'contract-qa',
				detail: 'contract-qa (version 1.0.0)'
			}
		]);
		expect(rows.every((row) => row.kind === 'skill')).toBe(true);
	});

	it('copes with a profile that has not been priced, or an older server that sends none', () => {
		const unpriced = instructionRows(profiles('harness-no-project').profiles[0]);
		expect(unpriced.map((row) => row.label)).toEqual(['Orchestrator skill', 'Sub-agent skill']);
		expect(unpriced.map((row) => row.detail)).toEqual(['orchestration-chat-demo', 'contract-qa']);
		expect(instructionRows(harnessProfile({ instructions: undefined }))).toEqual([]);
		expect(instructionRows(harnessProfile({ instructions: [] }))).toEqual([]);
	});

	it('words a prompt with no version, a role it has not heard of and a nameless entry sensibly', () => {
		const rows = instructionRows(
			harnessProfile({
				instructions: [
					{ role: 'orchestrator', kind: 'prompt', name: 'f/o.v1', version: null },
					{ role: 'reviewer' as 'orchestrator', kind: 'prompt', name: 'f/r.v2', version: '2' },
					{ role: 'sub-agent', kind: 'prompt', name: '', version: '1' }
				]
			})
		);
		expect(rows.map((row) => row.label)).toEqual([
			'Orchestrator prompt',
			'Reviewer prompt, version 2'
		]);
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

	it('lets a matter’s file be picked from a chat that is in no matter', () => {
		// ADR 0038, ruling 4. It was refused as `in_a_matter`; it is now read on the matter’s terms.
		const [inAMatter, loose] = documents('no-project').documents;
		expect(inAMatter).toMatchObject({ selectable: true, reason: null, matters: ['Fixture'] });
		expect(unreadableReason(inAMatter)).toBeNull();
		expect(unreadableReason(loose)).toBeNull();
		// An older server’s reason is still never left without words.
		expect(unreadableReason(document({ selectable: false, reason: 'in_a_matter' }))).toBe(
			'This file cannot be read in a run (in a matter).'
		);
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

	it('in a chat that is in no matter, promises to add nothing and says what a matter’s file brings', () => {
		const { documents: listed, project_id } = documents('no-project');
		expect(project_id).toBeNull();
		// Every file of a chat in no matter is recorded as not attached to one; that is not
		// a promise to add it.
		expect(listed.every((doc) => doc.attached_to_project === false)).toBe(true);
		for (const doc of listed) {
			expect(documentNote(doc, false) ?? '', doc.filename).not.toContain('Will be added');
		}
		const [inAMatter, loose] = listed;
		expect(documentNote(inAMatter, false)).toBe(
			'From the matter “Fixture”. A run that reads it follows its rules.'
		);
		expect(documentNote(loose, false)).toBeNull();
		expect(documentNote(loose, true)).toBe(ADDED_TO_MATTER_NOTE);
		expect(documentNote(DPA, false)).toBeNull();
		// A file that cannot be read has its reason and no note.
		expect(documentNote({ ...inAMatter, selectable: false }, false)).toBeNull();
	});

	it('in a matter, says what another matter’s knowledge-base file brings (ruling 12)', () => {
		const borrowed = document({
			matters: ['Advice'],
			matter_minimum_inference_tier: 2,
			matter_privileged: true
		});
		// Not yet attached here: the terms, then that it will be added.
		expect(documentNote({ ...borrowed, attached_to_project: false })).toBe(
			'From the matter “Advice”. A run that reads it follows its rules as well as this matter’s: ' +
				'inference tier 2 or stronger; privileged, so nothing is pseudonymized. ' +
				ADDED_TO_MATTER_NOTE
		);
		// Already attached: the terms still apply, so a second run is told too.
		expect(documentNote({ ...borrowed, attached_to_project: true })).toBe(
			'From the matter “Advice”. A run that reads it follows its rules as well as this matter’s: ' +
				'inference tier 2 or stronger; privileged, so nothing is pseudonymized.'
		);
		// Outside a matter the same file is described without this matter's rules.
		expect(documentNote(borrowed, false)).not.toContain('this matter');
		expect(documentNote({ ...borrowed, selectable: false })).toBeNull();
	});
});

describe('matterTermsNote', () => {
	// Recorded from the API: one matter sets a floor of 3, another is privileged with a floor of 2.
	const [privileged, floored, loose] = (() => {
		const listed = documents('no-project-terms').documents;
		const named = (filename: string) => listed.find((doc) => doc.filename === filename)!;
		return [named('msa.txt'), named('dpa.md'), named('loose-note.txt')];
	})();

	it('is recorded as the server sends it: every matter named, the lowest floor, privileged if any', () => {
		expect(privileged).toMatchObject({
			selectable: true,
			matters: ['Board advice', 'Fixture', 'Vendor renewal'],
			matter_minimum_inference_tier: 2,
			matter_privileged: true
		});
		expect(floored).toMatchObject({
			matters: ['Fixture', 'Vendor renewal'],
			matter_minimum_inference_tier: 3,
			matter_privileged: false
		});
		expect(loose).toMatchObject({ matters: [], matter_minimum_inference_tier: null });
	});

	it('names the matters and says what a run that reads the file takes on', () => {
		expect(matterTermsNote(privileged)).toBe(
			'From the matters “Board advice”, “Fixture” and “Vendor renewal”. A run that reads it follows their rules: inference tier 2 or stronger; privileged, so nothing is pseudonymized.'
		);
		expect(matterTermsNote(floored)).toBe(
			'From the matters “Fixture” and “Vendor renewal”. A run that reads it follows their rules: inference tier 3 or stronger.'
		);
		expect(matterTermsNote(loose)).toBeNull();
	});

	it('says a privileged matter turns pseudonymization off, because the strip cannot know it', () => {
		const note = matterTermsNote(document({ matters: ['Advice'], matter_privileged: true }));
		expect(note).toBe(
			'From the matter “Advice”. A run that reads it follows its rules: privileged, so nothing is pseudonymized.'
		);
	});

	it('still says so when no matter of the owner’s is named', () => {
		expect(matterTermsNote(document({ matters: [], matter_minimum_inference_tier: 1 }))).toBe(
			'From a matter. A run that reads it follows its rules: inference tier 1 or stronger.'
		);
	});

	it('is null for a file with nothing from a matter, and for fields of the wrong kind', () => {
		for (const fields of [
			{},
			{ matters: [] },
			{ matters: ['  ', ''], matter_minimum_inference_tier: null, matter_privileged: false },
			{ matters: 'Advice', matter_minimum_inference_tier: '2', matter_privileged: 'yes' }
		]) {
			expect(
				matterTermsNote(document(fields as Partial<RunDocument>)),
				JSON.stringify(fields)
			).toBeNull();
		}
	});

	it('shows a matter’s name as the words it is', () => {
		const note = matterTermsNote(document({ matters: ['<b>Acme</b> & "Co"'] }))!;
		expect(note).toContain('“<b>Acme</b> & "Co"”');
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

	it('in a chat that is in no matter, leaves a matter’s file free to pick and notes what it brings', () => {
		const read = documents('no-project');
		const rows = documentRows(read.documents, [], read.max_documents, { inMatter: false });
		const [inAMatter, loose] = rows;
		expect(inAMatter).toMatchObject({ filename: 'msa.txt', disabled: false, reason: null });
		expect(inAMatter.note).toBe(
			'From the matter “Fixture”. A run that reads it follows its rules.'
		);
		expect(loose).toMatchObject({
			filename: 'loose-note.txt',
			disabled: false,
			reason: null,
			note: null
		});
		// Said the other way, a chat in a matter notes the loose file as one it would add.
		expect(documentRows(read.documents, [], read.max_documents)[1].note).toBe(ADDED_TO_MATTER_NOTE);
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

describe('defaultDocumentSelection', () => {
	const afterRun = documents('after-run');
	const [AFTER_MSA, AFTER_DPA] = afterRun.documents;
	const RECORDED_READ = documents();
	const read = (patch: Partial<typeof RECORDED_READ> = {}) => ({ ...RECORDED_READ, ...patch });
	const choose = (
		over: Partial<Parameters<typeof defaultDocumentSelection>[0]> & { read?: typeof RECORDED_READ }
	) =>
		defaultDocumentSelection({
			read: RECORDED_READ,
			attachedFileIds: [],
			selected: [],
			touched: false,
			...over
		});

	it('starts from the documents the last run in the chat read, in that run’s order', () => {
		expect(afterRun.suggested_file_ids).toEqual([AFTER_MSA.file_id, AFTER_DPA.file_id]);
		expect(choose({ read: afterRun })).toEqual([AFTER_MSA.file_id, AFTER_DPA.file_id]);
		const reversed = { ...afterRun, suggested_file_ids: [AFTER_DPA.file_id, AFTER_MSA.file_id] };
		expect(choose({ read: reversed })).toEqual([AFTER_DPA.file_id, AFTER_MSA.file_id]);
	});

	it('then adds the chat’s own attached files that can be read and are not selected yet, in the chat’s order', () => {
		const suggested = read({ suggested_file_ids: [MSA.file_id] });
		// DOCX is attached but cannot be read; MSA is already selected by the suggestion.
		expect(
			choose({ read: suggested, attachedFileIds: [DPA.file_id, DOCX.file_id, MSA.file_id] })
		).toEqual([MSA.file_id, DPA.file_id]);
		// With nothing suggested, the attached files alone make the selection.
		expect(choose({ attachedFileIds: [DPA.file_id, MSA.file_id] })).toEqual([
			DPA.file_id,
			MSA.file_id
		]);
	});

	it('selects nothing from a matter’s files that were not asked for: only the suggestion and the chat’s own files', () => {
		// The list holds the matter's files too; none is the chat's own, so none is selected.
		expect(choose({})).toEqual([]);
		expect(choose({ attachedFileIds: [] })).toEqual([]);
	});

	it('stops at the most one run may read, suggested documents first', () => {
		const many = Array.from({ length: 10 }, (_, i) => ({
			...MSA,
			file_id: `file-${i}`,
			filename: `f${i}.txt`
		}));
		const wide = read({
			documents: many,
			max_documents: 8,
			suggested_file_ids: many.slice(0, 5).map((doc) => doc.file_id)
		});
		const chosen = choose({ read: wide, attachedFileIds: many.slice(5).map((doc) => doc.file_id) });
		expect(chosen).toEqual(many.slice(0, 8).map((doc) => doc.file_id));
		expect(choose({ read: { ...wide, max_documents: 2 } })).toEqual(['file-0', 'file-1']);
		expect(choose({ read: { ...wide, max_documents: 0 } })).toEqual([]);
	});

	it('uses the usual maximum when the read states none, and never goes past it', () => {
		expect(DEFAULT_MAX_DOCUMENTS).toBe(8);
		const many = Array.from({ length: 12 }, (_, i) => ({ ...MSA, file_id: `f-${i}` }));
		const unstated = read({ documents: many, max_documents: Number.NaN });
		expect(
			choose({ read: unstated, attachedFileIds: many.map((doc) => doc.file_id) })
		).toHaveLength(DEFAULT_MAX_DOCUMENTS);
	});

	it('never selects a file that is listed but cannot be read, or one the list does not hold', () => {
		const odd = read({ suggested_file_ids: [DOCX.file_id, 'not-listed', MSA.file_id] });
		expect(choose({ read: odd, attachedFileIds: [SCAN.file_id, 'also-not-listed'] })).toEqual([
			MSA.file_id
		]);
		// A matter’s file can be read from a chat that is in no matter, so it is chosen too.
		const loose = documents('no-project');
		const [inAMatter, looseFile] = loose.documents;
		expect(
			choose({ read: loose, attachedFileIds: [inAMatter.file_id, looseFile.file_id] })
		).toEqual([inAMatter.file_id, looseFile.file_id]);
	});

	it('names a file once, however many ways it was asked for', () => {
		const twice = read({ suggested_file_ids: [MSA.file_id, MSA.file_id] });
		expect(
			choose({ read: twice, attachedFileIds: [MSA.file_id, DPA.file_id, DPA.file_id] })
		).toEqual([MSA.file_id, DPA.file_id]);
	});

	it('is the same when the list is read again before anything is touched, so a refresh does not move it', () => {
		const first = choose({ read: afterRun, attachedFileIds: [AFTER_DPA.file_id] });
		expect(
			choose({ read: afterRun, attachedFileIds: [AFTER_DPA.file_id], selected: first })
		).toEqual(first);
	});

	it('follows the chat’s files while nothing is touched: a file attached since is selected too', () => {
		const before = choose({ read: afterRun });
		const attached = { ...MSA, file_id: 'newly-attached', filename: 'new.txt' };
		const later = { ...afterRun, documents: [...afterRun.documents, attached] };
		expect(choose({ read: later, attachedFileIds: [attached.file_id], selected: before })).toEqual([
			...before,
			'newly-attached'
		]);
	});

	describe('once the person has ticked or unticked anything in this draft', () => {
		it('leaves their selection alone: the suggestion and the attached files no longer count', () => {
			expect(
				choose({
					read: afterRun,
					attachedFileIds: [AFTER_DPA.file_id],
					selected: [AFTER_DPA.file_id],
					touched: true
				})
			).toEqual([AFTER_DPA.file_id]);
		});

		it('keeps an empty selection empty: unticking everything is a choice', () => {
			expect(choose({ read: afterRun, selected: [], touched: true })).toEqual([]);
		});

		it('only drops what can no longer be selected, keeping their order', () => {
			expect(
				choose({
					selected: [DPA.file_id, 'gone', DOCX.file_id, MSA.file_id],
					touched: true
				})
			).toEqual([DPA.file_id, MSA.file_id]);
		});
	});

	it('does not change what it was given', () => {
		const selected = [MSA.file_id];
		const attached = [DPA.file_id];
		const before = structuredClone(RECORDED_READ);
		choose({ attachedFileIds: attached, selected });
		choose({ attachedFileIds: attached, selected, touched: true });
		expect(selected).toEqual([MSA.file_id]);
		expect(attached).toEqual([DPA.file_id]);
		expect(RECORDED_READ).toEqual(before);
	});

	it('works on a read that carries no suggestion at all, as an older server sends it', () => {
		const older = { ...RECORDED_READ } as Partial<typeof RECORDED_READ>;
		delete older.suggested_file_ids;
		expect(choose({ read: older as typeof RECORDED_READ, attachedFileIds: [MSA.file_id] })).toEqual(
			[MSA.file_id]
		);
	});
});

describe('documentsSummary', () => {
	it('says none are selected, and that they are optional, when the profile needs none', () => {
		expect(documentsSummary({ documents: RECORDED, selected: [], min: 0 })).toEqual({
			line: 'Documents · none selected (optional)',
			full: null,
			startsOpen: false
		});
	});

	it('says how many are needed and starts open when the profile needs one and none is selected', () => {
		expect(documentsSummary({ documents: RECORDED, selected: [], min: 1 })).toEqual({
			line: 'Documents · none selected (at least 1 needed)',
			full: null,
			startsOpen: true
		});
	});

	it('names what is selected, in the order the selection numbers it', () => {
		expect(
			documentsSummary({ documents: RECORDED, selected: [MSA.file_id, DPA.file_id], min: 0 })
		).toEqual({ line: 'Documents · 2 selected: msa.txt, dpa.md', full: null, startsOpen: false });
		expect(
			documentsSummary({ documents: RECORDED, selected: [DPA.file_id, MSA.file_id], min: 0 }).line
		).toBe('Documents · 2 selected: dpa.md, msa.txt');
		expect(documentsSummary({ documents: RECORDED, selected: [MSA.file_id], min: 0 }).line).toBe(
			'Documents · 1 selected: msa.txt'
		);
	});

	it('never starts open once something is selected, whatever the profile needs', () => {
		for (const min of [0, 1, 2]) {
			expect(
				documentsSummary({ documents: RECORDED, selected: [MSA.file_id], min }).startsOpen
			).toBe(false);
		}
		expect(documentsSummary({ documents: RECORDED, selected: [], min: 2 })).toMatchObject({
			line: 'Documents · none selected (at least 2 needed)',
			startsOpen: true
		});
	});

	it('spells out the first few names and counts the rest, with every name for a hover title', () => {
		const files = Array.from({ length: 6 }, (_, i) => ({
			...MSA,
			file_id: `f${i}`,
			filename: `n${i}.md`
		}));
		const summary = documentsSummary({
			documents: files,
			selected: files.map((f) => f.file_id),
			min: 0
		});
		expect(SUMMARY_NAMES).toBe(3);
		expect(summary.line).toBe('Documents · 6 selected: n0.md, n1.md, n2.md and 3 more');
		expect(summary.full).toBe('n0.md, n1.md, n2.md, n3.md, n4.md, n5.md');
		// Exactly as many as it spells out leaves nothing to count.
		const three = documentsSummary({ documents: files, selected: ['f0', 'f1', 'f2'], min: 0 });
		expect(three.line).toBe('Documents · 3 selected: n0.md, n1.md, n2.md');
		expect(three.full).toBeNull();
	});

	it('counts a selected file the list does not hold, without naming it', () => {
		expect(documentsSummary({ documents: RECORDED, selected: ['gone'], min: 0 }).line).toBe(
			'Documents · 1 selected'
		);
		expect(
			documentsSummary({ documents: RECORDED, selected: [MSA.file_id, 'gone'], min: 0 }).line
		).toBe('Documents · 2 selected: msa.txt');
	});

	it('hands a file name back untouched', () => {
		const hostile = '<img src=x onerror=alert(1)>.txt';
		const files = [{ ...MSA, filename: hostile }];
		expect(documentsSummary({ documents: files, selected: [MSA.file_id], min: 0 }).line).toBe(
			`Documents · 1 selected: ${hostile}`
		);
	});
});

describe('what the picker says around its list', () => {
	it('says how many it may read, how they are numbered, and that none is allowed when none is needed', () => {
		const optional = pickerHelp({ max: 8, min: 0 });
		expect(optional).toMatch(/Pick up to 8 documents the run may read/);
		expect(optional).toMatch(/numbered in the order you pick them/);
		expect(optional).toMatch(/With none selected, the run reads no document\./);
		const needed = pickerHelp({ max: 1, min: 1 });
		expect(needed).toMatch(/Pick up to 1 document the run may read/);
		expect(needed).not.toMatch(/With none selected/);
	});

	it('never names a matter in its sentence, since the chat may be in none', () => {
		for (const min of [0, 1]) expect(pickerHelp({ max: 8, min })).not.toMatch(/matter/i);
	});

	it('says where files come from, and names a matter only when the chat is in one', () => {
		expect(pickerEmpty(true)).toBe(
			'No documents yet. Attach a file to this chat, or add files to the matter, then refresh the list.'
		);
		expect(pickerEmpty(false)).toBe(
			'No documents yet. Attach a file to this chat, then refresh the list.'
		);
		expect(pickerEmpty(false)).not.toMatch(/matter/i);
	});
});

describe('how many documents a profile needs, and whether it takes any', () => {
	it('is what the server states', () => {
		expect(minDocuments(harnessProfile())).toBe(0);
		expect(minDocuments(selectedProfile())).toBe(1);
		expect(minDocuments(harnessProfile({ min_documents: 2 }))).toBe(2);
	});

	it('is one for a profile that reads a selection, and none otherwise, from a server that does not say', () => {
		const older = (documents: ProfileAvailability['documents']) => {
			const profile: Partial<ProfileAvailability> = { ...harnessProfile({ documents }) };
			delete profile.min_documents;
			return profile as ProfileAvailability;
		};
		expect(minDocuments(older('selected'))).toBe(1);
		expect(minDocuments(older('optional'))).toBe(0);
		expect(minDocuments(older('packet'))).toBe(0);
	});

	it('reads a figure that is not a whole number of zero or more as the nearest that is', () => {
		expect(minDocuments(harnessProfile({ min_documents: -3 }))).toBe(0);
		expect(minDocuments(harnessProfile({ min_documents: 1.9 }))).toBe(1);
		expect(minDocuments(harnessProfile({ documents: 'selected', min_documents: Number.NaN }))).toBe(
			1
		);
	});

	it('takes documents for a selection or an optional one, and not for a fixed document', () => {
		expect(takesDocuments(selectedProfile())).toBe(true);
		expect(takesDocuments(harnessProfile())).toBe(true);
		expect(takesDocuments(packetProfile())).toBe(false);
		expect(takesDocuments(null)).toBe(false);
		expect(takesDocuments(undefined)).toBe(false);
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

	it('lets the owner of New harness send with none, and with some, and sends what they picked', () => {
		const profile = harnessProfile();
		const goal = 'Shorten that.';
		let selected: string[] = [];
		// Nothing picked is a request the server accepts: the run reads no document.
		expect(proposeBlocker({ profile, goal, selectedCount: selected.length })).toBeNull();
		expect(buildStartBody({ requestId: 'req', profile, goal, fileIds: selected }).file_ids).toEqual(
			[]
		);
		selected = toggleDocument(selected, MSA.file_id, documents().max_documents);
		expect(proposeBlocker({ profile, goal, selectedCount: selected.length })).toBeNull();
		expect(buildStartBody({ requestId: 'req', profile, goal, fileIds: selected }).file_ids).toEqual(
			[MSA.file_id]
		);
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

describe('documentsReadSignature', () => {
	const files = [{ id: 'a', ingestion_status: 'pending' }];

	it('changes when a knowledge base is attached to the matter or detached from it, so the line naming them is read again', () => {
		const base = documentsReadSignature(files, ['kb-1']);
		expect(documentsReadSignature(files, ['kb-1', 'kb-2'])).not.toBe(base);
		expect(documentsReadSignature(files, [])).not.toBe(base);
		expect(documentsReadSignature(files, ['kb-2'])).not.toBe(base);
	});

	it('changes when a file does, as the candidates’ signature does', () => {
		const base = documentsReadSignature(files, ['kb-1']);
		expect(documentsReadSignature([...files, { id: 'b' }], ['kb-1'])).not.toBe(base);
		expect(documentsReadSignature([{ id: 'a', ingestion_status: 'ingested' }], ['kb-1'])).not.toBe(
			base
		);
	});

	it('does not change for the same knowledge bases listed in another order, or for an unchanged read', () => {
		const base = documentsReadSignature(files, ['kb-1', 'kb-2']);
		expect(documentsReadSignature(files, ['kb-2', 'kb-1'])).toBe(base);
		expect(documentsReadSignature(structuredClone(files), [...['kb-1', 'kb-2']])).toBe(base);
	});

	it('is the same for a chat outside a matter however it is asked: it has none attached', () => {
		const none = documentsReadSignature(files, []);
		expect(documentsReadSignature(files, null)).toBe(none);
		expect(documentsReadSignature(files, undefined)).toBe(none);
	});

	it('does not reorder the list it was given', () => {
		const ids = ['kb-2', 'kb-1'];
		documentsReadSignature(files, ids);
		expect(ids).toEqual(['kb-2', 'kb-1']);
	});
});

// ---- proposing the plan ---------------------------------------------------------------------------

describe('the document line when the list could not be read', () => {
	it('says so on the closed line, with what is still selected', () => {
		const none = documentsSummary({ documents: [], selected: [], min: 0, error: 'HTTP 500' });
		expect(none.line).toBe('Documents · the list could not be read. Open to try again.');
		const kept = documentsSummary({
			documents: RECORDED,
			selected: [RECORDED[0].file_id],
			min: 0,
			error: 'HTTP 500'
		});
		expect(kept.line).toBe(
			'Documents · the list could not be read · 1 selected. Open to try again.'
		);
		// It never reads as an ordinary empty selection.
		expect(none.line).not.toContain('none selected');
	});

	it('says the list is being read while a retry is on its way, and the usual line after', () => {
		expect(
			documentsSummary({ documents: [], selected: [], min: 0, error: 'HTTP 500', loading: true })
				.line
		).toBe('Documents · reading the list…');
		expect(documentsSummary({ documents: RECORDED, selected: [], min: 0, error: null }).line).toBe(
			'Documents · none selected (optional)'
		);
	});
});

describe('a candidate that only another matter holds', () => {
	it('has its own reason, which says what the owner can do', () => {
		const doc: RunDocument = {
			...RECORDED[0],
			selectable: false,
			reason: 'in_another_matter'
		};
		const reason = unreadableReason(doc)!;
		expect(reason).toContain('belongs to another matter');
		expect(reason).toContain('Add it to this matter yourself');
	});
});

describe('what the strip says a request may spend', () => {
	it('gives the total cap and the most the planning call may cost', () => {
		expect(spendSummary({ budget_usd: '10.0000', planning_allowance_usd: '0.5781' })).toEqual([
			'total cap $10.00',
			'planning up to $0.5781'
		]);
	});

	it('says a route priced at zero costs nothing, instead of "up to $0.00"', () => {
		const lines = spendSummary({ budget_usd: '5.0000', planning_allowance_usd: '0.0000' });
		expect(lines).toEqual(['total cap $5.00', 'no charge at this route’s rates']);
		expect(lines.join(' ')).not.toContain('$0.00');
	});

	it('leaves out what the server has not priced', () => {
		expect(spendSummary({ budget_usd: null, planning_allowance_usd: null })).toEqual([]);
		expect(spendSummary({ budget_usd: '5.0000', planning_allowance_usd: undefined })).toEqual([
			'total cap $5.00'
		]);
	});
});

describe('the document line while the list is being read', () => {
	it('says the list is being read, not that nothing is selected', () => {
		const summary = documentsSummary({ documents: [], selected: [], min: 0, loading: true });
		expect(summary.line).toBe('Documents · reading the list…');
		expect(summary.startsOpen).toBe(false);
	});

	it('says what is selected as soon as there is a list, loading again or not', () => {
		const listed = RECORDED;
		const first = listed.find((doc) => doc.selectable)!;
		for (const loading of [true, false]) {
			expect(
				documentsSummary({ documents: listed, selected: [first.file_id], min: 0, loading }).line
			).toBe(`Documents · 1 selected: ${first.filename}`);
			expect(documentsSummary({ documents: listed, selected: [], min: 0, loading }).line).toBe(
				'Documents · none selected (optional)'
			);
		}
	});
});

describe('proposeBlocker', () => {
	const goal = 'Explain payment and renewal.';

	it('enables the action when there is a profile that can be used and a request', () => {
		expect(proposeBlocker({ profile: packetProfile(), goal, selectedCount: 0 })).toBeNull();
		expect(proposeBlocker({ profile: selectedProfile(), goal, selectedCount: 1 })).toBeNull();
		expect(proposeBlocker({ profile: selectedProfile(), goal, selectedCount: 8 })).toBeNull();
	});

	it('asks for a profile first', () => {
		expect(proposeBlocker({ profile: null, goal, selectedCount: 0 })).toBe(
			'Choose New harness in the model picker first.'
		);
		expect(proposeBlocker({ profile: null, goal: '', selectedCount: 0 })).toBe(
			'Choose New harness in the model picker first.'
		);
	});

	it('asks for a request, and does not count blank space as one', () => {
		for (const text of ['', ' ', '\n\t  \n']) {
			expect(proposeBlocker({ profile: packetProfile(), goal: text, selectedCount: 0 })).toBe(
				'Type your request.'
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

	it('wants a document for a profile that needs one, and not for one that reads a fixed document', () => {
		const need = (profile: ProfileAvailability, selectedCount: number) =>
			proposeBlocker({ profile, goal, selectedCount });
		expect(need(selectedProfile(), 0)).toBe('Select at least one document for this run.');
		expect(need(selectedProfile(), 1)).toBeNull();
		expect(need(packetProfile(), 0)).toBeNull();
	});

	it('wants as many documents as the profile states, which for New harness is none', () => {
		const need = (profile: ProfileAvailability, selectedCount: number) =>
			proposeBlocker({ profile, goal, selectedCount });
		// Changed on purpose: it used to want one whenever the profile read selected documents.
		// New harness takes documents as the owner likes, so none selected is sendable.
		expect(harnessProfile().documents).toBe('optional');
		expect(harnessProfile().min_documents).toBe(0);
		expect(need(harnessProfile(), 0)).toBeNull();
		expect(need(harnessProfile(), 1)).toBeNull();
		expect(need(harnessProfile(), 8)).toBeNull();
		// One stated: one is needed. Two stated: two.
		const one = harnessProfile({ min_documents: 1 });
		expect(need(one, 0)).toBe('Select at least one document for this run.');
		expect(need(one, 1)).toBeNull();
		const two = harnessProfile({ min_documents: 2 });
		expect(need(two, 1)).toBe('Select at least 2 documents for this run.');
		expect(need(two, 2)).toBeNull();
	});

	it('keeps the old rule for a server that does not state how many it needs', () => {
		const older = (documents: ProfileAvailability['documents']) => {
			const profile: Partial<ProfileAvailability> = { ...harnessProfile({ documents }) };
			delete profile.min_documents;
			return profile as ProfileAvailability;
		};
		expect(proposeBlocker({ profile: older('selected'), goal, selectedCount: 0 })).toBe(
			'Select at least one document for this run.'
		);
		expect(proposeBlocker({ profile: older('selected'), goal, selectedCount: 1 })).toBeNull();
		expect(proposeBlocker({ profile: older('optional'), goal, selectedCount: 0 })).toBeNull();
	});

	it('does not ask for a document before it asks for a request or a usable profile', () => {
		expect(
			proposeBlocker({ profile: harnessProfile({ min_documents: 1 }), goal: '', selectedCount: 0 })
		).toBe('Type your request.');
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
			'Type your request.'
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
		expect(requestSignature({ ...parts, profile: 'new_harness_v1' })).not.toBe(base);
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
		// The response was lost; the owner presses Send again.
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
			profile: 'new_harness_v1',
			goal: 'Explain payment.',
			file_ids: [DPA.file_id, MSA.file_id]
		});
		// A copy: changing the selection afterwards does not change a request already built.
		expect(body.file_ids).not.toBe(fileIds);
	});

	it('sends a profile that takes documents as the owner likes the list too, empty or not', () => {
		const optional = harnessProfile();
		expect(optional.documents).toBe('optional');
		expect(buildStartBody({ requestId: 'r', profile: optional, goal: 'g', fileIds: [] })).toEqual({
			request_id: 'r',
			profile: 'new_harness_v1',
			goal: 'g',
			file_ids: []
		});
		expect(
			buildStartBody({ requestId: 'r', profile: optional, goal: 'g', fileIds: [MSA.file_id] })
				.file_ids
		).toEqual([MSA.file_id]);
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
