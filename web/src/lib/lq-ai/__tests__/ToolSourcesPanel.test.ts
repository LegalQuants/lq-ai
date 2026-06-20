/**
 * Unit tests for the ToolSourcesPanel logic helper.
 *
 * Mirrors the ToolGatePrompt / RefusalMessageBubble pattern: the pure helper
 * is exported from `<script context="module">` and exercised here without
 * @testing-library/svelte (per CLAUDE.md "Don't add libraries without
 * justification"). The panel's rendering chrome is validated by svelte-check
 * and the Task 9 visual check.
 */
import { describe, expect, it } from 'vitest';
import { sourcesPillLabel } from '../components/ToolSourcesPanel.svelte';

describe('sourcesPillLabel', () => {
	it('singular vs plural', () => {
		expect(sourcesPillLabel(1)).toBe('1 source consulted');
		expect(sourcesPillLabel(3)).toBe('3 sources consulted');
	});
});
