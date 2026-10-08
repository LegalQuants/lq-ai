/**
 * The plan card's content: what the owner is asked to approve.
 *
 * Approval is consent to this exact plan (ADR 0035 D2, ADR 0038 D4), so the card
 * shows, for every task, the skill and version, the tools it may call, the
 * documents it may read and its budget, and for the plan as a whole the total cap,
 * the root allowance, the deadline and the attempt limit. Approve and Reject act
 * on the revision and hash of the plan shown, never on a later read.
 *
 * Built from the run read alone. Runs recorded before tools and documents existed
 * simply have no tools and no documents to list.
 */
import type {
	OrchestrationChatRun,
	PlanChild,
	PlanDocument,
	RunProgress,
	RunTool
} from '../api/orchestration';
import { formatUsd, humanise, knowledgeBaseNames, namedLineText, type NamedLine } from './format';

/**
 * The line that says which knowledge bases the tasks of a plan may search, or null when there
 * are none (the plan then says nothing of searching). Approving the plan is consent to it, so
 * the card shows it where the plan is decided on, not inside a fold.
 */
export function searchLine(names: readonly string[]): string | null {
	const line = searchLineParts(names);
	return line ? namedLineText(line) : null;
}

/** The same line in pieces, for a component that draws each name by itself (see `NamedLine`). */
export function searchLineParts(names: readonly string[]): NamedLine | null {
	return names.length > 0 ? { lead: 'Tasks may search: ', names: [...names], tail: '.' } : null;
}

export interface PlanDocumentView {
	number: number;
	filename: string;
	/** True when accepting this run attached the file to the matter. */
	addedForRun: boolean;
}

/**
 * What a session is pinned to, with the version the run recorded: a skill reads
 * `contract-qa v1.0.0`, an engine prompt file `new_harness/subagent.v1 (version 1)`.
 */
export function pinnedText(
	pin: { name: string; kind?: string } | null | undefined,
	version: string | null | undefined
): string | null {
	const name = typeof pin?.name === 'string' ? pin.name : '';
	if (!pin || !name) return null;
	const stated = (version ?? '').trim();
	if (!stated) return name;
	return pin.kind === 'prompt' ? `${name} (version ${stated})` : `${name} v${stated}`;
}

/**
 * How a receipt names what instructed a call: "Skill contract-qa v1.0.0" for an installed skill,
 * "Prompt file new_harness/orchestrator.v2" for one of the engine's own prompt files. The pin's
 * kind says which; a pin with none is a skill, as it was before there were prompt files. A prompt
 * file's name already ends with its version, so the version is not said a second time.
 */
export function receiptPin(
	pin: { name: string; version?: string | null; kind?: string } | null | undefined
): string | null {
	const name = typeof pin?.name === 'string' ? pin.name : '';
	if (!pin || !name) return null;
	const noun = pin.kind === 'prompt' ? 'Prompt file' : 'Skill';
	const version = typeof pin.version === 'string' ? pin.version.trim() : '';
	const said = version && !name.endsWith(`.v${version}`);
	return `${noun} ${name}${said ? ` v${version}` : ''}`;
}

/**
 * What the orchestrator is pinned to, named for what it is (a skill or a prompt file),
 * for the receipts. Null when the run has no plan, since the pin is recorded with it.
 */
export function orchestratorPin(
	run: Pick<OrchestrationChatRun, 'planning' | 'tree'>
): { label: string; text: string; digest: string } | null {
	const pin = run.tree?.plan?.root?.skill;
	if (!pin) return null;
	return {
		label: pin.kind === 'prompt' ? 'Orchestrator prompt' : 'Orchestrator skill',
		text: pinnedText(pin, run.planning?.root_skill_version) ?? pin.name,
		digest: pin.digest
	};
}

export interface PlanTaskView {
	/** 1-based, matches the child card's number. */
	index: number;
	topic: string;
	question: string;
	boundaries: string;
	outputContract: string;
	stoppingCondition: string;
	/** The pinned skill and version, e.g. `contract-qa v1.0.0`, or the prompt file the task is pinned to. */
	skill: string;
	/** What `skill` names: an installed skill, or one of the engine's prompt files. */
	skillKind: 'skill' | 'prompt';
	/** Labels of the tools this task may call. */
	tools: string[];
	/** The documents this task may read, numbered as the owner selected them. */
	documents: PlanDocumentView[];
	budget: string;
	/**
	 * How many turns the task may take with tools before one further model call,
	 * without tools, gives its answer; null when it has no tools.
	 */
	turnLimit: number | null;
}

export interface PlanView {
	revision: number;
	planHash: string;
	approved: boolean;
	tasks: PlanTaskView[];
	totalCap: string;
	rootAllowance: string;
	planningAllowance: string | null;
	/** ISO timestamp; format it for display at the edge. */
	deadline: string;
	maxActive: number;
	attemptLimitSeconds: number | null;
	model: string;
	/** What the profile may read, in its own words, when the run read carries it. */
	reads: string | null;
	/** Every document in the plan, numbered. */
	documents: PlanDocumentView[];
	/** "Tasks may search: People policies, Travel.", or null when the tasks may search none. */
	knowledgeBasesLine: string | null;
	/** The same line in pieces, so that each name is drawn by itself; null when the line is. */
	knowledgeBases: NamedLine | null;
	/** What rejecting would keep: the planning charge, as money text. */
	planningCharge: string | null;
}

export type PlanState = 'proposed' | 'approved' | 'rejected';

/** Whether the plan on the card is still a proposal, was approved, or was rejected. */
export function planState(run: Pick<OrchestrationChatRun, 'status' | 'tree'>): PlanState {
	if (run.status === 'rejected') return 'rejected';
	return run.tree?.approved ? 'approved' : 'proposed';
}

/** The sentence beside the Approve button. */
export function approvalSentence(revision: number): string {
	return `Approves revision ${revision} exactly as shown.`;
}

function toolLabels(
	progress: RunProgress | undefined,
	child: PlanChild | undefined,
	dispatchId: string | undefined
): string[] {
	const seen = new Set<string>();
	const labels: string[] = [];
	const add = (name: string, label: string) => {
		if (seen.has(name)) return;
		seen.add(name);
		labels.push(label);
	};
	const granted: RunTool[] =
		progress && (!dispatchId || progress.session_id === dispatchId) ? (progress.tools ?? []) : [];
	for (const tool of granted) add(tool.name, (tool.label ?? '').trim() || humanise(tool.name));
	if (labels.length === 0 && child?.tools) {
		for (const names of Object.values(child.tools)) {
			for (const name of names ?? []) add(name, humanise(name));
		}
	}
	return labels;
}

function documentViews(documents: PlanDocument[] | undefined): PlanDocumentView[] {
	return (documents ?? []).map((doc) => ({
		number: doc.number,
		filename: doc.filename,
		addedForRun: doc.attached_for_run === true
	}));
}

/** The plan card for a run, or null when no plan was proposed. */
export function planView(run: OrchestrationChatRun): PlanView | null {
	const tree = run.tree;
	if (!tree) return null;
	const plan = tree.plan;
	const all = plan.documents ?? run.planning?.documents ?? [];
	const searched = knowledgeBaseNames(plan.knowledge_bases ?? run.planning?.knowledge_bases);
	const byDocumentId = new Map(all.map((doc) => [doc.document_id, doc]));
	const skillVersion = run.planning?.child_skill_version;
	const tasks = plan.children.map((child, position): PlanTaskView => {
		const progress = tree.children?.[position];
		const readable: PlanDocument[] = [];
		for (const id of child.execution?.resources?.document_ids ?? []) {
			const doc = byDocumentId.get(id);
			if (doc) readable.push(doc);
		}
		readable.sort((a, b) => a.number - b.number);
		const pin = child.execution?.skill;
		const tools = toolLabels(progress, child, child.dispatch_id);
		const turns = child.turn_limit ?? progress?.turn_limit ?? 0;
		return {
			index: position + 1,
			topic: child.task.topic,
			question: child.task.question,
			boundaries: child.task.boundaries,
			outputContract: child.task.output_contract,
			stoppingCondition: child.task.stopping_condition,
			skill: pinnedText(pin, skillVersion) ?? 'Skill not recorded',
			skillKind: pin?.kind === 'prompt' ? 'prompt' : 'skill',
			tools,
			documents: documentViews(readable),
			budget: formatUsd(child.budget_usd),
			turnLimit: tools.length > 0 && turns > 0 ? turns : null
		};
	});
	const planning = run.effects?.find(
		(effect) => effect.intent === 'plan' || effect.effect_key?.startsWith('chat:plan')
	);
	return {
		revision: plan.revision,
		planHash: tree.plan_hash,
		approved: tree.approved,
		tasks,
		totalCap: formatUsd(plan.budget_usd),
		rootAllowance: formatUsd(plan.root_allowance_usd),
		planningAllowance: run.planning?.planning_allowance_usd
			? formatUsd(run.planning.planning_allowance_usd)
			: null,
		deadline: plan.deadline,
		maxActive: plan.max_active_children,
		attemptLimitSeconds:
			plan.attempt_timeout_seconds ?? run.planning?.attempt_timeout_seconds ?? null,
		model: run.planning?.model ?? '',
		reads: run.reads ?? null,
		documents: documentViews([...all].sort((a, b) => a.number - b.number)),
		// The plan names them; the intake's list stands in for a plan recorded without one.
		knowledgeBasesLine: searchLine(searched),
		knowledgeBases: searchLineParts(searched),
		planningCharge:
			planning && planning.charged_usd !== null && planning.charged_usd !== undefined
				? formatUsd(planning.charged_usd)
				: null
	};
}
