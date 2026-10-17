/**
 * What the owner can do with a run in a given state.
 *
 * The server stays the authority (a stale click is refused with 409); this only
 * decides which controls to show.
 */
import { isActiveStatus, type RunLike } from './status';

export interface RunActions {
	/** Approve the exact plan shown. Only while a plan awaits approval. */
	approve: boolean;
	/** Reject the plan shown. Only while a plan awaits approval. */
	reject: boolean;
	/** Stop the run. Stays available for as long as the run holds the owner's allowance. */
	halt: boolean;
	/** Close an uncertain run: charge the unresolved reservation and free the allowance. */
	close: boolean;
}

export function availableActions(run: RunLike): RunActions {
	const awaiting = run.status === 'awaiting_approval' && !!run.tree && run.tree.approved === false;
	return {
		approve: awaiting,
		reject: awaiting,
		halt: isActiveStatus(run.status),
		close: run.status === 'uncertain'
	};
}
