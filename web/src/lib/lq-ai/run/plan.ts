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
import { formatUsd, humanise } from './format';

export interface PlanDocumentView {
	number: number;
	filename: string;
	/** True when accepting this run attached the file to the matter. */
	addedForRun: boolean;
}

export interface PlanTaskView {
	/** 1-based, matches the child card's number. */
	index: number;
	topic: string;
	question: string;
	boundaries: string;
	outputContract: string;
	stoppingCondition: string;
	/** The pinned skill and version, e.g. `contract-qa v1.0.0`. */
	skill: string;
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
		const skillName = child.execution?.skill?.name;
		const tools = toolLabels(progress, child, child.dispatch_id);
		const turns = child.turn_limit ?? progress?.turn_limit ?? 0;
		return {
			index: position + 1,
			topic: child.task.topic,
			question: child.task.question,
			boundaries: child.task.boundaries,
			outputContract: child.task.output_contract,
			stoppingCondition: child.task.stopping_condition,
			skill: skillName ? (skillVersion ? `${skillName} v${skillVersion}` : skillName) : 'Skill not recorded',
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
		attemptLimitSeconds: plan.attempt_timeout_seconds ?? run.planning?.attempt_timeout_seconds ?? null,
		model: run.planning?.model ?? '',
		reads: run.reads ?? null,
		documents: documentViews([...all].sort((a, b) => a.number - b.number)),
		planningCharge:
			planning && planning.charged_usd !== null && planning.charged_usd !== undefined
				? formatUsd(planning.charged_usd)
				: null
	};
}
