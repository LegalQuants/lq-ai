/**
 * Unit tests for AttachedSkillPill helpers (Wave D.2, Task 3.2).
 *
 * Convention note: this codebase does not install @testing-library/svelte
 * (see AttachKBModal.test.ts and EnhancePromptExpansion.test.ts — both
 * explicitly call this out). CLAUDE.md forbids adding libraries without
 * justification. So we follow the established pattern: the .svelte file
 * exports its pure logic from <script context="module">, and we exercise
 * those helpers here. The template is glue.
 *
 * Coverage:
 *   - removeAriaLabel(title)   → "Remove <title>"  (a11y contract)
 *   - displayIcon(icon|null)   → the skill's own icon, or null (the pill draws the Tabler fallback)
 *   - handleRemove(skill, onRemove) → invokes callback with slug
 */
import { describe, expect, it, vi } from 'vitest';
import {
	removeAriaLabel,
	displayIcon,
	handleRemove
} from '../components/AttachedSkillPill.svelte';

describe('AttachedSkillPill helpers', () => {
	it('removeAriaLabel formats a "Remove <title>" string', () => {
		expect(removeAriaLabel('NDA Review')).toBe('Remove NDA Review');
		expect(removeAriaLabel('MSA Review (SaaS)')).toBe('Remove MSA Review (SaaS)');
	});

	it('displayIcon returns the provided icon when truthy', () => {
		expect(displayIcon('🛡️')).toBe('🛡️');
		expect(displayIcon('A')).toBe('A');
	});

	it('displayIcon returns null when missing, so the pill draws its Tabler fallback', () => {
		expect(displayIcon(null)).toBeNull();
		expect(displayIcon(undefined)).toBeNull();
		expect(displayIcon('')).toBeNull();
	});

	it('handleRemove invokes the callback with the skill slug', () => {
		const onRemove = vi.fn();
		handleRemove({ slug: 'nda-review', title: 'NDA Review' }, onRemove);
		expect(onRemove).toHaveBeenCalledTimes(1);
		expect(onRemove).toHaveBeenCalledWith('nda-review');
	});

	it('handleRemove is a no-op when callback is undefined', () => {
		expect(() =>
			handleRemove({ slug: 'nda-review', title: 'NDA Review' }, undefined)
		).not.toThrow();
	});
});
