/**
 * Composer helpers: what the owner sees and may do before a run exists.
 *
 * Offering New harness in the model picker, reading why it is unavailable, naming the run that is
 * blocking a new one, picking documents, and building the request that starts a
 * run. Pure functions; the chat panel and its run components only render them.
 */
import type {
	ActiveRun,
	InstructionKind,
	ProfileAvailability,
	RunDocument,
	RunDocumentsRead,
	RunProfilesRead,
	RunTool,
	StartRunBody
} from '../api/orchestration';
import {
	formatDuration,
	formatUsd,
	humanise,
	knowledgeBaseNames,
	namedLineText,
	own,
	pluralise,
	type NamedLine
} from './format';
import { isActiveStatus } from './status';

/** The goal is limited to 4,096 characters by the API. */
export const MAX_GOAL_CHARS = 4096;

/** At most this many candidate files can be named in one `run-documents` read. */
export const MAX_CANDIDATE_FILES = 16;

/** The most documents one run may read, when the server states no other figure. */
export const DEFAULT_MAX_DOCUMENTS = 8;

// ---- why a profile is unavailable ------------------------------------------------

/** A profile's title inside a sentence, or "this profile" when it has none. */
function titleOf(profile: Pick<ProfileAvailability, 'title'>): string {
	const title = typeof profile.title === 'string' ? profile.title.trim() : '';
	return title || 'this profile';
}

const capitalised = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);

/**
 * Wording for a reason code the server sent no sentence for. Where the server names the
 * profile ("The operator has not enabled New harness."), so does this, so a profile is
 * described the same way whether or not the server's own words arrived.
 */
const FALLBACK_REASONS: Record<string, (title: string) => string> = {
	operator_disabled: (title) => `The operator has not enabled ${title}.`,
	not_configured: (title) =>
		`The operator has enabled ${title} but its configuration is incomplete.`,
	autonomous_opt_in_required: () => 'Turn on Autonomous in your settings to start a run.',
	chat_archived: () => 'This chat is archived, so it cannot start a run.',
	project_required: (title) =>
		`${capitalised(title)} starts from a chat inside a matter. This chat has no matter.`,
	project_unavailable: () =>
		'The matter this chat belongs to is not available, so it cannot start a run.',
	project_not_permitted: (title) => `The operator has limited ${title} to a dedicated demo matter.`,
	route_unavailable: () => 'The profile’s model route, protection or pricing is unavailable.',
	active_run: () => 'Another run of yours is still active. One run can be active at a time.'
};

/**
 * Why a profile cannot be used here, or null when it can. Uses the server's own
 * words (`reason_text`) and falls back to wording for the reason code, so a
 * profile is never disabled without a reason.
 */
export function unavailableReason(profile: ProfileAvailability): string | null {
	if (profile.available) return null;
	const text = typeof profile.reason_text === 'string' ? profile.reason_text.trim() : '';
	if (text) return text;
	const fallback = own(FALLBACK_REASONS, profile.reason);
	return fallback ? fallback(titleOf(profile)) : 'This profile is unavailable right now.';
}

// ---- New harness, the model picker's experimental entry ---------------------------

/**
 * The id the model picker and the chat's remembered model use for New harness. It
 * is never sent as `MessageCreate.model`: a request made with it starts a run.
 */
export const NEW_HARNESS_ID = 'lq-ai:new-harness';
export const NEW_HARNESS_LABEL = 'New harness';

export interface HarnessOption {
	profile: ProfileAvailability;
	/** `provider/model` the run is pinned to, shown as an alias shows its target. */
	resolves: string | null;
	/**
	 * Why the entry cannot be chosen in this chat, or null. An active run is not
	 * one: the entry stays chosen and Send says why it waits.
	 */
	disabledReason: string | null;
}

/**
 * The picker's New harness entry for this chat, or null when the server offers
 * none. The server names the profile; nothing here picks one.
 */
export function harnessOption(read: RunProfilesRead | null | undefined): HarnessOption | null {
	const id = read?.composer_profile;
	if (!read || !id) return null;
	const profile = read.profiles.find((candidate) => candidate.profile === id);
	if (!profile) return null;
	const waiting = !profile.available && profile.reason === 'active_run';
	return {
		profile,
		resolves: (profile.model ?? '').trim() || null,
		disabledReason: waiting ? null : unavailableReason(profile)
	};
}

/**
 * What the composer is for one chat. Either an ordinary model is the chat's model,
 * or New harness is, in one of three states.
 *
 * `checking` and `unavailable` exist so that a chat whose model is New harness never
 * sends to some other model in its place. While the availability read is still out,
 * has failed, or says New harness cannot be used here, Send waits and says why; the
 * person leaves by choosing another model in the picker.
 */
export type ComposerMode =
	| { kind: 'model' }
	| { kind: 'harness'; state: 'ready'; option: HarnessOption }
	| { kind: 'harness'; state: 'checking'; option: null; reason: string }
	| { kind: 'harness'; state: 'unavailable'; option: HarnessOption | null; reason: string };

export const HARNESS_CHECKING = 'Checking whether New harness can be used in this chat…';
const CHOOSE_ANOTHER = 'Choose another model to send this message.';

/** An error message as a sentence: it ends with a full stop, a question or an exclamation. */
function sentence(text: string): string {
	const trimmed = text.trim();
	return /[.!?…]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

export function composerMode(input: {
	/** The chat's remembered model id, or null when none was chosen. */
	storedModelId: string | null;
	/** The availability read for this chat, or null when there is none. */
	read: RunProfilesRead | null | undefined;
	/** Whether a read for this chat has finished, with or without a result. */
	checked: boolean;
	/** Why the read failed, when it did. */
	error: string | null;
}): ComposerMode {
	if (input.storedModelId !== NEW_HARNESS_ID) return { kind: 'model' };
	const option = harnessOption(input.read);
	if (option && option.disabledReason === null) return { kind: 'harness', state: 'ready', option };
	if (option) {
		return {
			kind: 'harness',
			state: 'unavailable',
			option,
			reason: `${option.disabledReason} ${CHOOSE_ANOTHER}`
		};
	}
	if (!input.checked && !input.error) {
		return { kind: 'harness', state: 'checking', option: null, reason: HARNESS_CHECKING };
	}
	const why = input.error
		? `New harness could not be checked: ${sentence(input.error)}`
		: 'New harness is not offered on this server.';
	return {
		kind: 'harness',
		state: 'unavailable',
		option: null,
		reason: `${why} ${CHOOSE_ANOTHER}`
	};
}

/** Shown when an action that sends an ordinary message again is used beside New harness. */
export const RESEND_NEEDS_MODEL =
	'Choose an ordinary model to send that message again. With New harness chosen, sending starts a run.';

// ---- the run that is blocking a new one ------------------------------------------

/**
 * Names the owner's active run: "A run is active in <chat title>". The title is the
 * chat's own, shown as text. A run in the chat being viewed says so.
 */
export function activeRunLabel(active: ActiveRun, currentChatId: string | null): string {
	if (!active.chat_id) return 'A run you started outside a chat is active';
	const title = typeof active.chat_title === 'string' ? active.chat_title.trim() : '';
	const here = currentChatId !== null && active.chat_id === currentChatId;
	if (title) return `A run is active in ${title}${here ? ' (this chat)' : ''}`;
	return here ? 'A run is active in this chat' : 'A run is active in another chat';
}

/**
 * Where the active run is, in a few words. This notice has no run to read, so no terms: while a run
 * is planning it says what is true of every mode, that the request is being read. (Where the plan
 * is handed over by a tool call the first call may answer instead of proposing one.)
 */
export function activeRunStatusText(status: string): string {
	switch (status) {
		case 'planning':
			return 'Reading the request';
		case 'awaiting_approval':
			return 'Waiting for your approval';
		case 'queued':
			return 'Approved, waiting to start';
		case 'running':
		case 'waiting_children':
			return 'Tasks are running';
		case 'uncertain':
			return 'Uncertain: a provider call has no confirmed outcome';
		default:
			return humanise(status);
	}
}

/** Only an uncertain run can be closed. */
export function canCloseActiveRun(active: ActiveRun): boolean {
	return active.status === 'uncertain';
}

/**
 * How often the composer reads again which run holds the owner's allowance, while
 * one does. A run in another chat has no message in this thread to follow it, so
 * without this the notice would never learn that it moved on or ended.
 */
export const ACTIVE_RUN_POLL_MS = 10000;

/**
 * The availability read, with its active run's status taken from a run read shown
 * in the thread. The run message follows its run closely and the composer reads
 * availability rarely, so the notice would otherwise name an older state than the
 * message beside it. A run that has ended no longer holds the allowance, so its
 * notice goes at once; the composer then reads availability again for the rest.
 * Returns the same object when there is nothing to change; a read of some other
 * run changes nothing.
 */
export function syncActiveRun<T extends { active_run: ActiveRun | null }>(
	profiles: T,
	run: { root_id: string; status: string }
): T {
	const active = profiles.active_run;
	if (!active || active.root_id !== run.root_id || active.status === run.status) return profiles;
	if (!isActiveStatus(run.status)) return { ...profiles, active_run: null };
	return { ...profiles, active_run: { ...active, status: run.status } };
}

/** Said beside every Close run button (ADR 0038 D6). */
export const CLOSE_RUN_NOTE =
	'Closing charges the unresolved reservation, retries nothing, and frees you to start another run.';

// ---- run mode ------------------------------------------------------------------------

export interface RunFact {
	label: string;
	value: string;
}

/** Unique tool labels, in the order the profile lists them. */
export function toolLabelList(tools: RunTool[] | null | undefined): string[] {
	const seen = new Set<string>();
	const labels: string[] = [];
	for (const tool of tools ?? []) {
		if (seen.has(tool.name)) continue;
		seen.add(tool.name);
		labels.push((tool.label ?? '').trim() || humanise(tool.name));
	}
	return labels;
}

/**
 * The route a run is pinned to: the model, and the inference tier it resolves to once
 * the route is priced. Null when the profile states neither.
 */
export function routeText(profile: ProfileAvailability): string | null {
	const model = typeof profile.model === 'string' ? profile.model.trim() : '';
	const tier = profile.routed_tier;
	const parts = [model, typeof tier === 'number' ? `inference tier ${tier}` : ''];
	return parts.filter(Boolean).join(' · ') || null;
}

// This sentence must not read as a guarantee (docs/security/anonymization.md):
// - the layer replaces what it recognises, and a miss is silent;
// - organisation names are not replaced at all (PRD DE-397, measured again on this build).
//   The web cannot see that for itself: it is stated here, and this sentence has to change
//   when DE-397 is resolved;
// - what the gateway rewrites is message text. A tool result is not rewritten, so the
//   text of a document a task reads, and of a passage a search of the knowledge bases
//   returns, goes out as written (PRD Decision M2-1: quotations are checked against the
//   source), and tool-call arguments are not rewritten either;
// - the plan arrives as the arguments of a tool call, where nothing is put back: a plan that
//   carries a placeholder is refused (`plan_has_placeholders`) and nothing runs.
export const PSEUDONYMIZED_TEXT =
	'On the way to the model, the gateway replaces what it recognises as a personal name or ' +
	'an identifier in your request, this chat’s messages and the plan with a placeholder, and ' +
	'puts it back in what the model writes. It cannot put one back in a plan, so a plan that ' +
	'carries a placeholder is refused and nothing runs. It does not recognise everything, and a ' +
	'miss is not reported. Organisation names are not replaced. The text of a document that a task ' +
	'reads, and of a passage that a search returns, is sent as written, so that quotations ' +
	'can be checked. A task’s notes and stated reasons may show a placeholder.';
export const NOT_PSEUDONYMIZED_TEXT =
	"Text is sent to the model as written: the operator's setting applies no pseudonymization at this route's tier.";

/**
 * What the route does to the text on its way to the model, in plain words, or null
 * while the server has not said (the route is not priced yet).
 */
export function pseudonymizationText(profile: ProfileAvailability): string | null {
	if (profile.pseudonymized === true) return PSEUDONYMIZED_TEXT;
	if (profile.pseudonymized === false) return NOT_PSEUDONYMIZED_TEXT;
	return null;
}

/** One role's instruction, as a row of the strip's "System prompts" list. */
export interface InstructionRow {
	role: string;
	kind: InstructionKind;
	/** "Orchestrator prompt, version 1" or "Orchestrator skill". */
	label: string;
	/** For a prompt, the name its text is read by (`new_harness/orchestrator.v1`); for a skill, its name. */
	name: string;
	/** A skill's name and version to print beside the label, with nothing to read; null for a prompt. */
	detail: string | null;
}

const ROLE_WORDS: Record<string, string> = {
	orchestrator: 'Orchestrator',
	'sub-agent': 'Sub-agent'
};

/**
 * What instructs each role of the profile, in the order the server lists them. A prompt
 * can be opened and read; a skill is named and has nothing to fetch here.
 */
export function instructionRows(profile: ProfileAvailability): InstructionRow[] {
	return (profile.instructions ?? [])
		.filter((item) => typeof item.name === 'string' && item.name !== '')
		.map((item) => {
			const role = own(ROLE_WORDS, item.role) ?? (humanise(item.role) || 'Session');
			const version = typeof item.version === 'string' ? item.version.trim() : '';
			if (item.kind === 'prompt') {
				return {
					role: item.role,
					kind: 'prompt' as const,
					label: version ? `${role} prompt, version ${version}` : `${role} prompt`,
					name: item.name,
					detail: null
				};
			}
			return {
				role: item.role,
				kind: 'skill' as const,
				label: `${role} skill`,
				name: item.name,
				detail: version ? `${item.name} (version ${version})` : item.name
			};
		});
}

/**
 * The limits a run in this profile works within, for the composer's run mode: the
 * route (model and inference tier), the reasoning effort when one is set, the total
 * cap, the planning allowance, the per-task allowance, the maximum number of tasks,
 * the attempt limit. A value the server has not priced (an unavailable profile) is left
 * out rather than shown as zero.
 */
export function runModeFacts(profile: ProfileAvailability): RunFact[] {
	const facts: RunFact[] = [];
	const route = routeText(profile);
	if (route) facts.push({ label: 'Route', value: route });
	const effort =
		typeof profile.reasoning_effort === 'string' ? profile.reasoning_effort.trim() : '';
	if (effort) facts.push({ label: 'Reasoning effort', value: effort });
	if (profile.budget_usd) facts.push({ label: 'Total cap', value: formatUsd(profile.budget_usd) });
	if (profile.planning_allowance_usd) {
		facts.push({ label: 'Planning allowance', value: formatUsd(profile.planning_allowance_usd) });
	}
	if (profile.child_allowance_usd) {
		facts.push({ label: 'Per-task allowance', value: formatUsd(profile.child_allowance_usd) });
	}
	if (profile.max_children) {
		facts.push({ label: 'Maximum tasks', value: String(profile.max_children) });
	}
	if (profile.attempt_timeout_seconds) {
		facts.push({
			label: 'Attempt limit',
			value: `${formatDuration(profile.attempt_timeout_seconds)} per attempt`
		});
	}
	if (profile.child_turn_limit > 0) {
		// The limit counts turns in which the task may call tools; one more model call,
		// without tools, gives the answer. Both are in the per-task allowance.
		facts.push({
			label: 'Tool turns per task',
			value: `up to ${profile.child_turn_limit}, then one answer`
		});
	}
	return facts;
}

/**
 * Said in the strip's fold of limits where the orchestrator may answer a request by itself.
 * It is a consent matter, not a footnote: such an answer comes with no plan to approve.
 */
export const ANSWERS_DIRECTLY_TEXT =
	'A request that needs nothing read may be answered at once, without a plan. ' +
	'That answer is not put to you for approval.';

/**
 * Whether the profile's orchestrator may answer a request by itself, as the server says. A server
 * that does not say (an older one) and a profile that says no both mean it always plans: nothing
 * is taken from the profile's name.
 */
export function answersDirectly(
	profile: Pick<ProfileAvailability, 'answers_directly'> | null | undefined
): boolean {
	return profile?.answers_directly === true;
}

/** The sentence for a profile that may answer by itself, or null for one that always plans. */
export function answersDirectlyText(
	profile: Pick<ProfileAvailability, 'answers_directly'>
): string | null {
	return answersDirectly(profile) ? ANSWERS_DIRECTLY_TEXT : null;
}

/**
 * What the screen says, before Send is pressed, of what Send does: on the button, on the model
 * picker's group and entry, and when a send fails without a reason of its own. Where the profile's
 * orchestrator may answer by itself, Send is one model call that answers or proposes a plan, and
 * the wording says so; otherwise Send asks for a plan, as it always did.
 */
export interface SendWording {
	/** The title of the Send button. */
	sendTitle: string;
	/** The title of the model picker's group that holds New harness. */
	pickerTitle: string;
	/** The note under the New harness entry in the model picker. */
	pickerNote: string;
	/** What a failed send says when the error carries no message. */
	failure: string;
}

const WORDING_PLANS: SendWording = {
	sendTitle: 'Asks the model for a plan. Nothing else runs until you approve it.',
	pickerTitle: 'Not a provider model. Send asks for a plan; tasks run only after you approve it.',
	pickerNote: 'Plans your request, then runs tasks you approve.',
	failure: 'Could not ask for a plan.'
};

const WORDING_ANSWERS: SendWording = {
	sendTitle:
		'Makes one model call. It answers a request that needs nothing read, or proposes a plan. No task runs until you approve a plan.',
	pickerTitle:
		'Not a provider model. Send makes one model call that answers the request or proposes a plan. Tasks run only after you approve the plan.',
	pickerNote:
		'Answers a request that needs nothing read. Otherwise plans it, and runs the tasks you approve.',
	failure: 'Could not send the request.'
};

/** The wording for a profile that may answer by itself (`answersDirectly`), or for one that always plans. */
export function sendWording(answers: boolean): SendWording {
	return answers ? WORDING_ANSWERS : WORDING_PLANS;
}

/**
 * What the stand-alone page says about where a run starts and what then happens. The page reads no
 * profile, so it cannot say whether the server's orchestrator answers by itself; this is the wording
 * for one that may, which is what the current New harness does.
 */
export const RUNS_START_FROM_A_CHAT_TEXT =
	'The run then appears in that chat’s thread. A request that needs nothing read is answered there at once. ' +
	'Otherwise you review and approve its plan there and follow its progress.';

// ---- knowledge bases --------------------------------------------------------------------

/** How many knowledge bases one run lists. More attached to a matter than this are not searched. */
export const MAX_RUN_KNOWLEDGE_BASES = 16;

/** The tool a task searches the matter's knowledge bases with. */
export const KNOWLEDGE_SEARCH_TOOL = 'search_knowledge_base';

/**
 * Whether a run started here is offered the search of knowledge bases: the matter has some attached,
 * which the `run-documents` read lists. Outside a matter, and in a matter with none, it is not; nor,
 * until that read has come back, is it known to be.
 */
export function searchesKnowledgeBases(
	read: Pick<RunDocumentsRead, 'knowledge_bases'> | null | undefined
): boolean {
	return knowledgeBaseNames(read?.knowledge_bases).length > 0;
}

/** The tool a task reads one of the selected documents with. */
export const DOCUMENT_READ_TOOL = 'read_document';

/**
 * The tools a task of a run started here may use. The profile lists the same tools for every chat; a
 * run is offered the ones that could do something. The search of knowledge bases only where it has
 * knowledge bases to search, so it is left out of what is shown here where the read lists none, and
 * until it has landed. The read of a document only where it has a document to read: a profile whose
 * documents are optional is offered none for a run with none selected. A profile that needs a
 * selection cannot start without one, and one that reads a fixed packet always reads it, so neither
 * is touched. Where `selected` is not given the selection is not known, and the tool is listed.
 */
export function toolsOffered(
	tools: RunTool[] | null | undefined,
	read: Pick<RunDocumentsRead, 'knowledge_bases'> | null | undefined,
	selected: { policy: ProfileAvailability['documents']; count: number } | null = null
): RunTool[] {
	const searches = searchesKnowledgeBases(read);
	const nothingToRead = selected !== null && selected.policy === 'optional' && selected.count <= 0;
	return (tools ?? []).filter(
		(tool) =>
			(searches || tool.name !== KNOWLEDGE_SEARCH_TOOL) &&
			(!nothingToRead || tool.name !== DOCUMENT_READ_TOOL)
	);
}

/**
 * The line beside the document picker that says which of the matter's knowledge bases a task of
 * a run started here may search, and how many attached ones it leaves out. Null when there is
 * nothing to say: a chat outside a matter, or a matter with none attached. They are not picked:
 * a run lists every one of them, up to the cap, and its plan names them.
 */
export function knowledgeBasesLine(
	read: Pick<RunDocumentsRead, 'knowledge_bases' | 'knowledge_bases_omitted'> | null | undefined
): string | null {
	const line = knowledgeBasesLineParts(read);
	return line ? namedLineText(line) : null;
}

/**
 * The same line in pieces, for the component that draws it: what comes before the names, the names,
 * and what follows them (the end of the sentence, and the count it leaves out). Each name is drawn
 * by itself, so a name with a comma in it cannot pass for two, nor one that reorders text move the
 * names after it.
 */
export function knowledgeBasesLineParts(
	read: Pick<RunDocumentsRead, 'knowledge_bases' | 'knowledge_bases_omitted'> | null | undefined
): NamedLine | null {
	const names = knowledgeBaseNames(read?.knowledge_bases);
	if (names.length === 0) return null;
	const lead = "Tasks may search this matter's knowledge bases: ";
	const stated = read?.knowledge_bases_omitted;
	const omitted = typeof stated === 'number' && Number.isFinite(stated) ? Math.floor(stated) : 0;
	if (omitted <= 0) return { lead, names, tail: '.' };
	const verb = omitted === 1 ? 'is' : 'are';
	return {
		lead,
		names,
		tail: `. ${omitted} more attached to this matter ${verb} not searched: a run lists at most ${MAX_RUN_KNOWLEDGE_BASES}.`
	};
}

// ---- documents ------------------------------------------------------------------------

/** Shown on a file the run will add to the matter when the request is sent. */
export const ADDED_TO_MATTER_NOTE = 'Will be added to this matter when you send the request';

const UNREADABLE_REASONS: Record<string, string> = {
	unsupported_type:
		'This type of file cannot be read in a run. Runs read PDF with text, plain text and Markdown.',
	not_ingested: 'Not processed yet. Wait for it to finish, then refresh the list.',
	ingestion_failed: 'Processing failed, so this file cannot be read.',
	no_text: 'No text could be extracted from this file, for example a scan or an image-only PDF.',
	// Listed from a chat that is in no matter: a matter's file carries that matter's rules.
	in_a_matter:
		'This file belongs to a matter. Start the request from a chat in that matter to use it.',
	// Listed from a chat in one matter: a run does not move a file out of another.
	in_another_matter:
		'This file belongs to another matter. Add it to this matter yourself if this run should read it.'
};

/** Why a file cannot be selected, or null when it can. Never silently empty for a file that cannot. */
export function unreadableReason(doc: RunDocument): string | null {
	if (doc.selectable) return null;
	const known = own(UNREADABLE_REASONS, doc.reason);
	if (known) return known;
	return doc.reason
		? `This file cannot be read in a run (${doc.reason.replace(/[_-]+/g, ' ')}).`
		: 'This file cannot be read in a run.';
}

/**
 * The note for a selectable file that is not yet attached to the matter, else null.
 * A chat in no matter adds nothing to one, so it has no such note for any file.
 */
export function documentNote(doc: RunDocument, inMatter = true): string | null {
	return inMatter && doc.selectable && !doc.attached_to_project ? ADDED_TO_MATTER_NOTE : null;
}

/** Whether a profile takes documents from the owner: a selection it needs, or one it may have. */
export function takesDocuments(
	profile: Pick<ProfileAvailability, 'documents'> | null | undefined
): boolean {
	return profile?.documents === 'selected' || profile?.documents === 'optional';
}

/**
 * The fewest documents a request to this profile may name. The server states it
 * (`min_documents`); an older server that does not still needs one for `selected`.
 */
export function minDocuments(
	profile: Pick<ProfileAvailability, 'documents' | 'min_documents'>
): number {
	const stated = profile.min_documents;
	if (typeof stated === 'number' && Number.isFinite(stated)) return Math.max(0, Math.floor(stated));
	return profile.documents === 'selected' ? 1 : 0;
}

/** Select or deselect a file. Selection order is the numbering; the limit is enforced. */
export function toggleDocument(selected: string[], fileId: string, max: number): string[] {
	if (selected.includes(fileId)) return selected.filter((id) => id !== fileId);
	if (selected.length >= max) return selected;
	return [...selected, fileId];
}

/** 1-based position in the selection, or null when not selected. */
export function documentNumber(selected: string[], fileId: string): number | null {
	const index = selected.indexOf(fileId);
	return index === -1 ? null : index + 1;
}

export interface DocumentRow {
	fileId: string;
	filename: string;
	characters: number;
	number: number | null;
	checked: boolean;
	disabled: boolean;
	/** Why the row cannot be selected, or null. */
	reason: string | null;
	/** An informational note, or null. */
	note: string | null;
}

/**
 * The picker's rows. Unselectable files are listed, disabled, with the reason. A chat in
 * no matter (`inMatter: false`) has no "added to this matter" note on any file.
 */
export function documentRows(
	docs: RunDocument[],
	selected: string[],
	max: number,
	options: { inMatter?: boolean } = {}
): DocumentRow[] {
	const atCap = selected.length >= max;
	const inMatter = options.inMatter !== false;
	return docs.map((doc) => {
		const checked = selected.includes(doc.file_id);
		const unreadable = unreadableReason(doc);
		const capped = !checked && !unreadable && atCap;
		return {
			fileId: doc.file_id,
			filename: doc.filename,
			characters: doc.characters,
			number: documentNumber(selected, doc.file_id),
			checked,
			disabled: unreadable !== null || capped,
			reason:
				unreadable ?? (capped ? `Up to ${pluralise(max, 'document')} can be selected.` : null),
			note: documentNote(doc, inMatter)
		};
	});
}

/** How many file names the picker's closed line spells out before it says "+ n more". */
export const SUMMARY_NAMES = 3;

export interface DocumentsSummary {
	/** The picker's closed line: "Documents · 2 selected: msa.txt, dpa.md". */
	line: string;
	/** Every selected file name, for a hover title, or null when the line already says them all. */
	full: string | null;
	/** Whether the picker starts open: only when a document is needed and none is selected. */
	startsOpen: boolean;
}

/**
 * What a request may spend, for the strip's first line: the total cap, and the most the
 * planning call may cost. A route priced at zero says so, because "planning up to
 * $0.00" reads as a mistake.
 */
export function spendSummary(
	profile: Pick<ProfileAvailability, 'budget_usd' | 'planning_allowance_usd'>
): string[] {
	const parts: string[] = [];
	if (profile.budget_usd) parts.push(`total cap ${formatUsd(profile.budget_usd)}`);
	const planning = profile.planning_allowance_usd;
	if (planning !== null && planning !== undefined && planning !== '') {
		parts.push(
			Number(planning) === 0
				? 'no charge at this route’s rates'
				: `planning up to ${formatUsd(planning)}`
		);
	}
	return parts;
}

/**
 * The picker's closed line. The names are the owner's own file names, in the order the
 * selection numbers them. A profile that needs a document and has none selected says how
 * many it needs and starts open; one that takes them as it likes says "(optional)".
 */
export function documentsSummary(input: {
	documents: RunDocument[];
	selected: string[];
	min: number;
	/** True while the list is being read and nothing is listed yet. */
	loading?: boolean;
	/** Why the last read of the list failed, or null. */
	error?: string | null;
}): DocumentsSummary {
	const { selected } = input;
	if (input.error && !input.loading) {
		// Said on the closed line: the failure is otherwise inside a fold nobody has opened,
		// and the selection a draft starts with was not applied.
		const kept = selected.length > 0 ? ` · ${selected.length} selected` : '';
		return {
			line: `Documents · the list could not be read${kept}. Open to try again.`,
			full: null,
			startsOpen: false
		};
	}
	if (input.loading && input.documents.length === 0 && selected.length === 0) {
		// The default selection is not known until the list is read; do not say "none".
		return { line: 'Documents · reading the list…', full: null, startsOpen: false };
	}
	const startsOpen = input.min > 0 && selected.length === 0;
	if (selected.length === 0) {
		const need = input.min > 0 ? `at least ${input.min} needed` : 'optional';
		return { line: `Documents · none selected (${need})`, full: null, startsOpen };
	}
	const names = selected
		.map((id) => input.documents.find((doc) => doc.file_id === id)?.filename)
		.filter((name): name is string => typeof name === 'string' && name !== '');
	const shownNames = names.slice(0, SUMMARY_NAMES);
	const rest = names.length - shownNames.length;
	const spelled = shownNames.join(', ') + (rest > 0 ? ` and ${rest} more` : '');
	const line = `Documents · ${selected.length} selected${spelled ? `: ${spelled}` : ''}`;
	return { line, full: rest > 0 ? names.join(', ') : null, startsOpen };
}

/** The sentence under the picker's heading. It names no matter: the chat may be in none. */
export function pickerHelp(input: { max: number; min: number }): string {
	const pick =
		`Pick up to ${pluralise(input.max, 'document')} the run may read. They are numbered in the ` +
		'order you pick them; the plan and the answer refer to them by those numbers.';
	return input.min > 0 ? pick : `${pick} With none selected, the run reads no document.`;
}

/** Shown when the list is empty. Says where files come from, and names a matter only if there is one. */
export function pickerEmpty(inMatter: boolean): string {
	return inMatter
		? 'No documents yet. Attach a file to this chat, or add files to the matter, then refresh the list.'
		: 'No documents yet. Attach a file to this chat, then refresh the list.';
}

/**
 * The selection a draft starts with when the document list is read: the documents the
 * last run in this chat read (`suggested_file_ids`, in that run's order), then the
 * chat's own attached files that can be selected, up to the most one run may read.
 * Once the person has ticked or unticked anything in this draft (`touched`) their
 * selection is theirs: it is only pruned of files that are no longer listed or readable.
 */
export function defaultDocumentSelection(input: {
	read: Pick<RunDocumentsRead, 'documents' | 'max_documents' | 'suggested_file_ids'>;
	/** The chat's own attached files, in the chat's order. */
	attachedFileIds: readonly string[];
	/** The selection as it stands. */
	selected: readonly string[];
	touched: boolean;
}): string[] {
	const { read } = input;
	if (input.touched) return pruneSelection([...input.selected], read.documents);
	const usable = new Set(read.documents.filter((doc) => doc.selectable).map((doc) => doc.file_id));
	const stated = read.max_documents;
	const max = Number.isFinite(stated) ? Math.max(0, Math.floor(stated)) : DEFAULT_MAX_DOCUMENTS;
	const chosen: string[] = [];
	for (const id of [...(read.suggested_file_ids ?? []), ...input.attachedFileIds]) {
		if (chosen.length >= max) break;
		if (usable.has(id) && !chosen.includes(id)) chosen.push(id);
	}
	return chosen;
}

/** Keep only selections that are still listed and selectable, in their order. */
export function pruneSelection(selected: string[], docs: RunDocument[]): string[] {
	const usable = new Set(docs.filter((doc) => doc.selectable).map((doc) => doc.file_id));
	return selected.filter((id) => usable.has(id));
}

/** The chat's own attached files, as candidates for `run-documents`. */
export function candidateFileIds(files: { id: string }[]): string[] {
	return files.slice(0, MAX_CANDIDATE_FILES).map((file) => file.id);
}

/** Changes when a candidate is added, removed or changes ingestion status. */
export function candidatesSignature(files: { id: string; ingestion_status?: string }[]): string {
	return files.map((file) => `${file.id}:${file.ingestion_status ?? ''}`).join(',');
}

/**
 * Changes when the document list read for a chat is out of date: a candidate changes (above), or a
 * knowledge base is attached to or detached from the chat's matter. The same read lists the
 * knowledge bases a task may search, so the line that names them is stale until it is read again.
 * The order the matter lists its knowledge bases in does not matter to what is read.
 */
export function documentsReadSignature(
	files: { id: string; ingestion_status?: string }[],
	knowledgeBaseIds: readonly string[] | null | undefined
): string {
	return `${candidatesSignature(files)}|${[...(knowledgeBaseIds ?? [])].sort().join(',')}`;
}

// ---- sending the request ---------------------------------------------------------------

/**
 * Why the request cannot be sent yet, or null when it can. With New harness chosen,
 * Send asks for a plan; this is the sentence under it when it is disabled.
 */
export function proposeBlocker(input: {
	profile: ProfileAvailability | null;
	goal: string;
	selectedCount: number;
}): string | null {
	const { profile } = input;
	if (!profile) return 'Choose New harness in the model picker first.';
	const unavailable = unavailableReason(profile);
	if (unavailable) return unavailable;
	const goal = input.goal.trim();
	if (!goal) return 'Type your request.';
	if (goal.length > MAX_GOAL_CHARS) {
		return `The request is limited to ${MAX_GOAL_CHARS.toLocaleString('en-US')} characters.`;
	}
	// As many documents as the profile needs, which for New harness is none: it plans and
	// answers without one, and says so under the answer.
	const needed = minDocuments(profile);
	if (input.selectedCount < needed) {
		return needed === 1
			? 'Select at least one document for this run.'
			: `Select at least ${pluralise(needed, 'document')} for this run.`;
	}
	return null;
}

export interface PendingRequest {
	id: string;
	signature: string;
}

/** What a request id stands for. The server refuses an id reused with a different request. */
export function requestSignature(parts: {
	chatId: string;
	profile: string;
	goal: string;
	fileIds: string[];
}): string {
	return JSON.stringify([parts.chatId, parts.profile, parts.goal.trim(), parts.fileIds]);
}

/**
 * The request id to send. Kept while the same request is retried, so a retry after
 * a lost response returns the same run instead of starting a second one; replaced
 * as soon as the request itself changes (the server answers 409 to an id reused
 * with different input).
 */
export function requestFor(
	previous: PendingRequest | null,
	signature: string,
	makeId: () => string
): PendingRequest {
	return previous && previous.signature === signature ? previous : { id: makeId(), signature };
}

/** `crypto.randomUUID()`, with a fallback for pages served without a secure context. */
export function newRequestId(): string {
	const api = typeof crypto !== 'undefined' ? crypto : undefined;
	if (api && typeof api.randomUUID === 'function') return api.randomUUID();
	const bytes = new Uint8Array(16);
	if (api && typeof api.getRandomValues === 'function') api.getRandomValues(bytes);
	else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
	bytes[6] = (bytes[6] & 0x0f) | 0x40;
	bytes[8] = (bytes[8] & 0x3f) | 0x80;
	const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * The body of `POST /chats/{chat_id}/runs`. A profile that reads a fixed document
 * is sent no `file_ids` (the server refuses them); one that reads a selection, or
 * takes one if the owner likes, is sent the owner's selection in order (possibly none).
 */
export function buildStartBody(args: {
	requestId: string;
	profile: ProfileAvailability;
	goal: string;
	fileIds: string[];
}): StartRunBody {
	const body: StartRunBody = {
		request_id: args.requestId,
		profile: args.profile.profile,
		goal: args.goal.trim()
	};
	if (takesDocuments(args.profile)) body.file_ids = [...args.fileIds];
	return body;
}
