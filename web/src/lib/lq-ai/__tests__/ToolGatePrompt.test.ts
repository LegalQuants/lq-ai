/**
 * Unit tests for the ToolGatePrompt logic helpers.
 *
 * Mirrors the RefusalMessageBubble pattern: copy/logic helpers are exported
 * from `<script context="module">` and exercised here. The Svelte template is
 * glue — it composes these helpers and wires the approve/deny/connect
 * callbacks (verified by svelte-check + the PR6b visual check). We do not pull
 * in @testing-library/svelte (per CLAUDE.md "Don't add libraries without
 * justification" — no lq-ai component renders under it).
 */
import { describe, expect, it } from 'vitest';
import {
	confirmHeading,
	tierChipLabel,
	connectBody,
	connectButtonLabel
} from '../components/ToolGatePrompt.svelte';

describe('ToolGatePrompt helpers', () => {
	it('confirmHeading flags destructive actions', () => {
		expect(confirmHeading(false)).toBe('Approval needed');
		expect(confirmHeading(true)).toBe('Destructive action — approval needed');
	});

	it('tierChipLabel renders the tier or a dash when unknown', () => {
		expect(tierChipLabel(2)).toBe('tier 2');
		expect(tierChipLabel(null)).toBe('tier —');
	});

	it('connectBody names the server', () => {
		expect(connectBody('files')).toBe('Connect your files account to continue.');
	});

	it('connectButtonLabel names the server', () => {
		expect(connectButtonLabel('files')).toBe('Connect files');
	});
});
