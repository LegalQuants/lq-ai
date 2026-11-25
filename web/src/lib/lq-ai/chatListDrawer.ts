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

type Sheet = Pick<ParentNode, 'querySelectorAll'> | null | undefined;

function visibleControls(root: Sheet): HTMLElement[] {
	return Array.from(root?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []).filter(
		(el) => el.tabIndex >= 0 && !(el as HTMLButtonElement).disabled && el.getClientRects().length > 0
	);
}

export function firstVisibleFocusable(root: Sheet): HTMLElement | null {
	return visibleControls(root)[0] ?? null;
}

/** Let the browser traverse the list, wrapping at the two ends of an open sheet. */
export function wrapSheetTab(event: KeyboardEvent, root: Sheet, open: boolean): void {
	if (!open || event.key !== 'Tab') return;
	const controls = visibleControls(root);
	const first = controls[0];
	const last = controls[controls.length - 1];
	if (!first || event.target !== (event.shiftKey ? first : last)) return;
	event.preventDefault();
	(event.shiftKey ? last : first).focus();
}
