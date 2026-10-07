import type { Writable } from 'svelte/store';

export const LQ_HOVERCARD_CONTEXT_KEY = Symbol('lq-hovercard');

export interface LqHoverCardContext {
	opened: Writable<boolean>;
	/** The hover-region element — Dropdown reads its rect to position itself
	 *  once it's portaled out (see Dropdown.svelte). */
	anchorEl: Writable<HTMLElement | null>;
	open: () => void;
	scheduleClose: () => void;
}
