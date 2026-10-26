import { writable } from 'svelte/store';
import { pendingProposalsFor, removeProposal } from './proposal-helpers';
import type {
	ProjectContextProposalRead,
	ProjectContextProposalListResponse
} from '$lib/lq-ai/api/autonomous';

type Proposal = ProjectContextProposalRead;
type Action = 'accepting' | 'rejecting';

export interface ProposalInboxState {
	enabled: boolean;
	proposals: Proposal[];
	totalCount: number;
	nextOffset: number;
	loading: boolean;
	loadingMore: boolean;
	pending: Record<string, Action>;
	error: string | null;
	success: string | null;
}

interface InboxDependencies {
	// Must read the server: the shared initializer silently retains cached opt-in.
	getOptIn: () => Promise<boolean>;
	list: (
		matterId: string,
		limit: number,
		offset: number
	) => Promise<ProjectContextProposalListResponse>;
	accept: (id: string) => Promise<unknown>;
	reject: (id: string) => Promise<unknown>;
	onAccepted: (matterId: string, isCurrent: () => boolean) => Promise<void>;
}

const PAGE_SIZE = 50;
const initialState = (): ProposalInboxState => ({
	enabled: false,
	proposals: [],
	totalCount: 0,
	nextOffset: 0,
	loading: false,
	loadingMore: false,
	pending: {},
	error: null,
	success: null
});

/** Owns the asynchronous inbox lifecycle rather than just its display helpers. */
export function createProposalInbox(deps: InboxDependencies) {
	let state = initialState();
	const store = writable(state);
	let matterId: string | null = null;
	let generation = 0;
	let listTicket = 0;
	const update = (changes: Partial<ProposalInboxState>) => {
		state = { ...state, ...changes };
		store.set(state);
	};
	const current = (id: string, token: number) => matterId === id && generation === token;

	async function readPage(id: string, token: number, append = false): Promise<void> {
		if (!current(id, token)) return;
		const ticket = ++listTicket;
		const offset = append ? state.nextOffset : 0;
		update({ loading: !append, loadingMore: append });
		try {
			const response = await deps.list(id, PAGE_SIZE, offset);
			if (!current(id, token) || ticket !== listTicket) return;
			const rows = pendingProposalsFor(response.proposals, id);
			const combined = append ? [...state.proposals, ...rows] : rows;
			update({
				proposals: [...new Map(combined.map((row) => [row.id, row])).values()],
				totalCount: response.total_count,
				nextOffset: response.offset + response.proposals.length,
				loading: false,
				loadingMore: false
			});
		} catch {
			if (!current(id, token) || ticket !== listTicket) return;
			// An optional inbox outage must not replace the Matter workspace.
			update({
				loading: false,
				loadingMore: false,
				error:
					append || state.success ? 'Could not refresh context proposals. Please try again.' : null
			});
		}
	}

	async function setMatter(id: string): Promise<void> {
		const token = ++generation;
		++listTicket;
		matterId = id;
		state = initialState();
		store.set(state);
		try {
			const enabled = await deps.getOptIn();
			if (!current(id, token) || !enabled) return;
			update({ enabled: true });
			await readPage(id, token);
		} catch {
			// No fresh opt-in result means no inbox, even when cache says yes.
		}
	}

	async function act(proposalId: string, action: Action): Promise<void> {
		const id = matterId;
		const token = generation;
		if (
			!id ||
			!state.enabled ||
			state.pending[proposalId] ||
			!state.proposals.some((row) => row.id === proposalId && row.project_id === id)
		)
			return;
		// A list started before this mutation must not restore a resolved row.
		++listTicket;
		update({
			pending: { ...state.pending, [proposalId]: action },
			loading: false,
			loadingMore: false,
			error: null,
			success: null
		});
		try {
			await (action === 'accepting' ? deps.accept(proposalId) : deps.reject(proposalId));
			if (!current(id, token)) return;
			update({
				proposals: removeProposal(state.proposals, proposalId),
				totalCount: Math.max(0, state.totalCount - 1),
				success: action === 'accepting' ? 'Added to matter context.' : 'Proposal rejected.'
			});
			if (action === 'accepting') {
				try {
					await deps.onAccepted(id, () => current(id, token));
				} catch {
					if (current(id, token))
						update({
							error: 'Context was added, but the matter could not be refreshed. Please reload it.'
						});
				}
			}
			// Resolving rows shifts the dataset: refill offset zero, not the old next page.
			await readPage(id, token);
		} catch {
			if (current(id, token))
				update({
					error:
						action === 'accepting'
							? 'Accept failed. Please try again.'
							: 'Reject failed. Please try again.'
				});
		} finally {
			if (current(id, token)) {
				const pending = { ...state.pending };
				delete pending[proposalId];
				update({ pending });
			}
		}
	}

	return {
		subscribe: store.subscribe,
		setMatter,
		accept: (id: string) => act(id, 'accepting'),
		reject: (id: string) => act(id, 'rejecting'),
		loadMore: async () => {
			if (
				!matterId ||
				!state.enabled ||
				state.loading ||
				state.loadingMore ||
				Object.keys(state.pending).length ||
				state.nextOffset >= state.totalCount
			)
				return;
			update({ error: null });
			await readPage(matterId, generation, true);
		},
		destroy: () => {
			++generation;
			++listTicket;
			matterId = null;
			state = initialState();
			store.set(state);
		}
	};
}
