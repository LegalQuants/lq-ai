/**
 * Keyboard handling for `ChatListDrawer`, kept apart so it can be tested
 * without a DOM: Escape closes an open sheet and stops there, so it does not
 * also close a sidebar behind it.
 */
export function drawerKeydown(
	event: Pick<KeyboardEvent, 'key' | 'preventDefault' | 'stopPropagation'>,
	open: boolean,
	close: () => void
): boolean {
	if (!open || event.key !== 'Escape') return false;
	event.preventDefault();
	event.stopPropagation();
	close();
	return true;
}

const FOCUSABLE = 'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * The first control in the sheet a person can see and reach: rendered
 * (it has a layout box) and not disabled. A hidden control, such as the
 * matter list toggle that only shows on a matter page, is skipped.
 */
export function firstVisibleFocusable(
	root: Pick<ParentNode, 'querySelectorAll'> | null | undefined
): HTMLElement | null {
	if (!root) return null;
	for (const el of Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))) {
		if ((el as HTMLButtonElement).disabled) continue;
		if (el.getClientRects().length === 0) continue;
		return el;
	}
	return null;
}
