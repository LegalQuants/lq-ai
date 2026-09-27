import { apiRequest } from './client';
import type { Phase } from './autonomous';

export interface TopicOutcome {
	status: 'completed' | 'empty' | 'failed';
	summary: string;
	findings: string[];
	verification: 'unverified';
	failure_code: string | null;
}

export interface WorkspaceFile {
	session_id: string;
	name: string;
	revision: number;
	digest: string;
	size_bytes: number;
	shared: boolean;
	updated_at: string;
}

export interface RunProgress {
	session_id: string;
	status: string;
	phase: Phase;
	allocation_usd: string;
	spent_usd: string;
	reserved_usd: string;
	outcome: TopicOutcome | null;
	files: WorkspaceFile[];
	effects: {
		effect_key: string;
		status: string;
		reserved_usd: string;
		charged_usd: string | null;
		intent?: string;
		created_at?: string;
		completed_at?: string | null;
		skill?: { name: string; version: string; digest: string } | null;
		accounting?: {
			provider: string;
			model: string;
			basis: string;
			estimated_prompt_tokens: number;
			reported_usage_cost_usd: string;
		} | null;
	}[];
}

export interface OrchestrationTree {
	root_id: string;
	status: string;
	stop_reason: string | null;
	plan_hash: string;
	approved: boolean;
	mode: 'demonstration' | 'model_demo_v1';
	verification: 'unverified';
	plan: {
		revision: number;
		goal: string;
		budget_usd: string;
		root_allowance_usd: string;
		max_active_children: number;
		deadline: string;
		root: { skill: { name: string; digest: string } };
		children: {
			dispatch_id: string;
			budget_usd: string;
			task: {
				topic: string;
				question: string;
				boundaries: string;
				output_contract: string;
				stopping_condition: string;
			};
		}[];
	};
	root: RunProgress;
	children: RunProgress[];
	spent_usd: string;
	reserved_usd: string;
	result: {
		summary: string;
		coverage: 'complete' | 'partial' | 'empty' | 'failed';
		verification: 'unverified';
	} | null;
	partial_summary: string | null;
}

const base = '/autonomous/orchestration';
export const orchestrationApi = {
	capabilities: () =>
		apiRequest<{ enabled: boolean; deployment_children: number | null; live_providers: false }>(
			`${base}/capabilities`
		),
	prepare: (body: {
		project_id: string;
		goal: string;
		topics: string[];
		max_active_children: number;
	}) => apiRequest<OrchestrationTree>(`${base}/plans`, { method: 'POST', body }),
	tree: (id: string, signal?: AbortSignal) =>
		apiRequest<OrchestrationTree>(`${base}/${encodeURIComponent(id)}/tree`, { signal }),
	file: (root: string, session: string, name: string, signal?: AbortSignal) =>
		apiRequest<WorkspaceFile & { content: string }>(
			`${base}/${encodeURIComponent(root)}/files/${encodeURIComponent(session)}/${encodeURIComponent(name)}`,
			{ signal }
		),
	approve: (tree: OrchestrationTree) =>
		apiRequest<OrchestrationTree>(`${base}/${encodeURIComponent(tree.root_id)}/approve`, {
			method: 'POST',
			body: { revision: tree.plan.revision, plan_hash: tree.plan_hash }
		}),
	reject: (tree: OrchestrationTree) =>
		apiRequest<OrchestrationTree>(`${base}/${encodeURIComponent(tree.root_id)}/reject`, {
			method: 'POST',
			body: { revision: tree.plan.revision }
		}),
	halt: (id: string) =>
		apiRequest<OrchestrationTree>(`${base}/${encodeURIComponent(id)}/halt`, { method: 'POST' })
};

export function shouldPollTree(status: string): boolean {
	return ['planning', 'queued', 'running', 'waiting_children'].includes(status);
}

export interface ChatCapabilities {
	enabled: boolean;
	attempt_timeout_seconds?: number;
	profile?: 'model_demo_v1';
	title?: string;
	project_id?: string;
	project_name?: string;
	packet_id?: 'fictional-agreement-v1';
	packet?: string;
	model?: string;
	budget_usd?: string;
	planning_allowance_usd?: string;
	root_allowance_usd?: string;
	child_skill?: string;
	deployment_children?: number;
}

export interface OrchestrationChatRun {
	root_id: string;
	status: string;
	stop_reason: string | null;
	packet: string | null;
	planning: {
		attempt_timeout_seconds: number;
		goal: string;
		model: string;
		budget_usd: string;
		root_allowance_usd: string;
		planning_allowance_usd: string;
		packet_digest: string;
		gateway_revision: string;
		child_skill_version: string;
		root_skill_version: string;
		deadline: string;
	};
	effects: RunProgress['effects'];
	spent_usd: string;
	reserved_usd: string;
	tree: OrchestrationTree | null;
}

export const orchestrationChatApi = {
	capabilities: () => apiRequest<ChatCapabilities>(`${base}/chat-runs`),
	start: (body: { request_id: string; project_id: string; goal: string }) =>
		apiRequest<OrchestrationChatRun>(`${base}/chat-runs`, {
			method: 'POST',
			body: { ...body, profile: 'model_demo_v1', packet_id: 'fictional-agreement-v1' }
		}),
	read: (id: string, signal?: AbortSignal) =>
		apiRequest<OrchestrationChatRun>(`${base}/chat-runs/${encodeURIComponent(id)}`, { signal }),
	halt: (id: string) =>
		apiRequest<OrchestrationChatRun>(`${base}/chat-runs/${encodeURIComponent(id)}/halt`, {
			method: 'POST'
		})
};
