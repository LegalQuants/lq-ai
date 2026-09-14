import { apiRequest } from './client';
import type { Phase } from './autonomous';

export interface TopicOutcome {
	status: 'completed' | 'empty' | 'failed';
	summary: string;
	findings: string[];
	verification: 'unverified';
	failure_code: string | null;
}

export interface RunProgress {
	session_id: string;
	status: string;
	phase: Phase;
	allocation_usd: string;
	spent_usd: string;
	reserved_usd: string;
	outcome: TopicOutcome | null;
	effects: {
		effect_key: string;
		status: string;
		reserved_usd: string;
		charged_usd: string | null;
	}[];
}

export interface OrchestrationTree {
	root_id: string;
	status: string;
	stop_reason: string | null;
	plan_hash: string;
	approved: boolean;
	mode: 'demonstration';
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
	return ['queued', 'running', 'waiting_children'].includes(status);
}
