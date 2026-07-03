/** referenced-files Phase 2 — FilePickerDropdown row-disable logic. */
import { describe, expect, it } from 'vitest';

import { rowDisabled } from '../components/FilePickerDropdown.svelte';
import type { ReferencedFile } from '../files/referenceable';

function ref(ready: boolean): ReferencedFile {
	return { id: '1', filename: 'a.pdf', ready };
}

describe('rowDisabled', () => {
	it('disables non-ready rows regardless of selection state', () => {
		expect(rowDisabled(ref(false), false, false)).toBe(true);
		expect(rowDisabled(ref(false), true, true)).toBe(true);
	});

	it('disables unselected rows at the cap', () => {
		expect(rowDisabled(ref(true), false, true)).toBe(true);
	});

	it('keeps SELECTED rows enabled at the cap so they can be unchecked', () => {
		expect(rowDisabled(ref(true), true, true)).toBe(false);
	});

	it('enables ready rows below the cap', () => {
		expect(rowDisabled(ref(true), false, false)).toBe(false);
	});
});
