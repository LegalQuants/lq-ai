<script context="module" lang="ts">
	/**
	 * Pure copy/logic helpers exported for unit tests. The Svelte template
	 * below composes these — keeping the logic out of the template lets us
	 * validate it without @testing-library/svelte (per CLAUDE.md "Don't add
	 * libraries without justification"; mirrors the RefusalMessageBubble
	 * pattern).
	 */

	/** Heading copy for the confirm card — flags destructive tools up front. */
	export function confirmHeading(destructive: boolean): string {
		return destructive ? 'Destructive action — approval needed' : 'Approval needed';
	}

	/** Chip label for the routed inference/egress tier (`—` when unknown). */
	export function tierChipLabel(tier: number | null): string {
		return tier == null ? 'tier —' : `tier ${tier}`;
	}

	/** Body copy for the connect card — names the MCP server to authorize. */
	export function connectBody(server: string): string {
		return `Connect your ${server} account to continue.`;
	}

	/** Action-button label for the connect card. */
	export function connectButtonLabel(server: string): string {
		return `Connect ${server}`;
	}
</script>

<script lang="ts">
	import type { ToolConfirmationRequiredFrame, McpAuthorizationRequiredFrame } from '../types';
	// Note: confirmHeading / tierChipLabel / connectBody / connectButtonLabel are
	// declared in the module-context script above; Svelte merges the two blocks
	// at compile time so re-importing them here would duplicate-identifier under
	// svelte-check (mirrors the RefusalMessageBubble pattern).

	/**
	 * In-message tool-gate card (PR6b).
	 *
	 * Rendered below an assistant turn when the governed tool-loop pauses:
	 * - `variant='confirm'` — the gateway flagged a tool call that needs the
	 *   user's approval (`tool_confirmation_required`). Surfaces the tool, the
	 *   provider, the routed tier, a destructive marker, and the backend-redacted
	 *   args summary, with Approve / Deny actions that resume the same turn.
	 * - `variant='connect'` — the tool's MCP server needs OAuth
	 *   (`mcp_authorization_required`). Surfaces a single Connect action that
	 *   redirects to the authorize URL (handled by the parent).
	 *
	 * `args_summary` is already redacted/bounded by the backend — it is rendered
	 * as plain text, never `{@html}`.
	 */
	export let variant: 'confirm' | 'connect';
	export let confirm: ToolConfirmationRequiredFrame | null = null;
	export let connect: McpAuthorizationRequiredFrame | null = null;
	export let busy = false;
	export let onApprove: () => void = () => {};
	export let onDeny: () => void = () => {};
	export let onConnect: () => void = () => {};
</script>

{#if variant === 'confirm' && confirm}
	<div class="tool-gate" data-testid="tool-gate-confirm">
		<div class="header">
			<span class="icon" aria-hidden="true">{confirm.destructive ? '⚠️' : '🛡'}</span>
			<strong>{confirmHeading(confirm.destructive)}</strong>
		</div>
		<p class="body">
			This turn wants to run
			<code class="tool">{confirm.tool}</code>
			on <strong>{confirm.provider}</strong>. Approve to let it proceed, or deny to skip it.
		</p>
		<pre class="args" data-testid="tool-gate-args">{confirm.args_summary}</pre>
		<div class="actions">
			<button
				type="button"
				class="primary"
				data-testid="tool-gate-approve"
				disabled={busy}
				on:click={onApprove}
			>
				Approve
			</button>
			<button
				type="button"
				class="secondary"
				data-testid="tool-gate-deny"
				disabled={busy}
				on:click={onDeny}
			>
				Deny
			</button>
		</div>
		<div class="pills">
			<span class="pill pill-tier" data-testid="tool-gate-tier">🔒 {tierChipLabel(confirm.tier)}</span>
			{#if confirm.destructive}
				<span class="pill pill-destructive" data-testid="tool-gate-destructive">⚠️ destructive</span>
			{/if}
			<span class="pill pill-audited">📜 audited</span>
		</div>
	</div>
{:else if variant === 'connect' && connect}
	<div class="tool-gate" data-testid="tool-gate-connect-card">
		<div class="header">
			<span class="icon" aria-hidden="true">🔗</span>
			<strong>Connection needed</strong>
		</div>
		<p class="body">{connectBody(connect.server)}</p>
		<div class="actions">
			<button
				type="button"
				class="primary"
				data-testid="tool-gate-connect"
				disabled={busy}
				on:click={onConnect}
			>
				{connectButtonLabel(connect.server)}
			</button>
		</div>
	</div>
{/if}

<style>
	.tool-gate {
		background: #eef2ff;
		border: 1px solid #6366f1;
		border-radius: 8px;
		padding: 12px;
		margin-bottom: 8px;
	}
	.header {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 8px;
	}
	.icon {
		font-size: 16px;
	}
	strong {
		color: #3730a3;
	}
	.body {
		font-size: 13px;
		color: #312e81;
		line-height: 1.5;
		margin: 0 0 8px 0;
	}
	.tool {
		background: #e0e7ff;
		padding: 1px 5px;
		border-radius: 4px;
		font-size: 12px;
	}
	.args {
		background: #1e1b4b;
		color: #c7d2fe;
		font-size: 11px;
		line-height: 1.4;
		padding: 8px;
		border-radius: 4px;
		margin: 0 0 10px 0;
		overflow-x: auto;
		white-space: pre-wrap;
		word-break: break-word;
	}
	.actions {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		margin-bottom: 8px;
	}
	.primary {
		background: #4338ca;
		color: #fff;
		border: 0;
		padding: 4px 10px;
		border-radius: 4px;
		cursor: pointer;
		font-size: 12px;
	}
	.secondary {
		background: #fff;
		color: #4338ca;
		border: 1px solid #4338ca;
		padding: 4px 10px;
		border-radius: 4px;
		cursor: pointer;
		font-size: 12px;
	}
	.primary:disabled,
	.secondary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.pills {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}
	.pill {
		padding: 2px 6px;
		border-radius: 4px;
		font-size: 10px;
	}
	.pill-tier {
		background: #e0e7ff;
		color: #3730a3;
	}
	.pill-destructive {
		background: #fee2e2;
		color: #991b1b;
	}
	.pill-audited {
		background: #dbeafe;
		color: #1e40af;
	}
</style>
