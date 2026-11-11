<script context="module" lang="ts">
	/**
	 * Pure helpers exported for unit tests. The Svelte template below composes
	 * these — keeping the logic out of the template lets us validate it
	 * without @testing-library/svelte (per CLAUDE.md "Don't add libraries
	 * without justification"; mirrors the AttachKBModal / NewMatterModal
	 * pattern).
	 */

	/** Heading copy for the refusal banner — substitutes the enforced tier. */
	export function refusalHeading(enforcedTier: string): string {
		return `Refused at ${enforcedTier}-floor`;
	}

	/**
	 * Body copy templated with both the originally-requested and the policy-
	 * enforced tier so the operator can see exactly what was refused and
	 * why. Phrasing is per PRD/spec §7.4 — "kept your work in privileged-
	 * only providers" frames the refusal as a guard, not a failure.
	 */
	export function refusalBody(requestedTier: string, enforcedTier: string): string {
		return (
			`This task was about to route to a ${requestedTier} tier provider, ` +
			`but your firm's policy enforces ${enforcedTier}-floor for this matter. ` +
			`We refused to keep your work in privileged-only providers.`
		);
	}

	/**
	 * Override is admin-only at M1. Per-user `override_tier_floor` capability
	 * is deferred to v1.1+ (see inferenceOverride.ts comments). Members and
	 * viewers see only Re-run + Why.
	 */
	export function showOverrideButton(role: 'admin' | 'member' | 'viewer'): boolean {
		return role === 'admin';
	}
</script>

<script lang="ts">
	import { IconShield, IconLock, IconFileText } from '@tabler/icons-svelte';
	import type { Message } from '../types';
	// Note: refusalHeading / refusalBody / showOverrideButton are declared in
	// the module-context script above; Svelte merges the two blocks at
	// compile time so re-importing them here would duplicate-identifier
	// under svelte-check (mirrors the AttachKBModal pattern).

	/**
	 * Refusal message bubble (kind='refusal').
	 *
	 * Amber-tinted inline message rendered in the chat stream when the
	 * Inference Gateway refused a routing because the requested tier was
	 * below the firm's policy floor for the matter. No provider call was
	 * made — there is no provider pill — but the refusal is audited
	 * (📜 audited) and labeled with the tier mismatch (🔒).
	 *
	 * The bubble surfaces three operator actions:
	 * - Re-run at {enforcedTier}-floor (primary)
	 * - Override for this turn (secondary, admin only — fires the T14
	 *   confirmation modal; calls overrideTierFloor() from T9)
	 * - Why am I seeing this? (tertiary — opens the explainer panel)
	 */
	export let message: Message;
	export let currentUserRole: 'admin' | 'member' | 'viewer' = 'member';
	export let onRerun: () => void = () => {};
	export let onOverrideRequested: () => void = () => {};
	export let onExplainerRequested: () => void = () => {};

	// `requested_tier` / `enforced_tier` are not on the canonical Message
	// type yet (kind='refusal' is a v1.1+ extension; types.ts contract test
	// pins only the canonical shape). Cast through `any` to read them
	// without forcing a contract-test churn; defaults preserve render when
	// upstream omits them.
	$: requestedTier =
		(message as unknown as { requested_tier?: string }).requested_tier ?? 'standard';
	$: enforcedTier =
		(message as unknown as { enforced_tier?: string }).enforced_tier ?? 'privileged';
</script>

<div class="refusal-bubble" data-testid="refusal-bubble">
	<div class="header">
		<span class="shield" aria-hidden="true"
			><IconShield size={16} stroke={1.75} aria-hidden="true" /></span
		>
		<strong>{refusalHeading(enforcedTier)}</strong>
	</div>
	<p class="body">{refusalBody(requestedTier, enforcedTier)}</p>
	<div class="actions">
		<button type="button" class="primary" on:click={onRerun}>
			Re-run at {enforcedTier}-floor
		</button>
		{#if showOverrideButton(currentUserRole)}
			<button
				type="button"
				class="secondary"
				data-testid="override-button"
				on:click={onOverrideRequested}
			>
				Override for this turn*
			</button>
		{/if}
		<button type="button" class="tertiary" on:click={onExplainerRequested}>
			Why am I seeing this?
		</button>
	</div>
	<div class="pills">
		<span
			class="pill pill-tier"
			data-testid="pill-tier-mismatch"
			title="Tier mismatch — your matter's policy required a stronger inference tier than the one this request would have routed to. The Inference Gateway refused before any provider call was made. Click 'Why am I seeing this?' for the full explanation."
		>
			<IconLock size={12} stroke={1.75} aria-hidden="true" /> tier mismatch (requested {requestedTier},
			enforced {enforcedTier})
		</span>
		<span
			class="pill pill-audited"
			data-testid="pill-audited"
			title="Audited — the refusal was recorded to the audit log with the requested tier, the enforced tier, and the policy basis. Admins can review this in the audit log surface."
		>
			<IconFileText size={12} stroke={1.75} aria-hidden="true" /> audited
		</span>
	</div>
</div>

<style>
	.refusal-bubble {
		background: var(--lq-inset);
		border: 1px solid var(--lq-governance-border);
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
	.shield {
		font-size: 16px;
	}
	strong {
		color: var(--lq-governance);
	}
	.body {
		font-size: 13px;
		color: var(--lq-text);
		line-height: 1.5;
		margin: 0 0 10px 0;
	}
	.actions {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		margin-bottom: 8px;
	}
	.primary {
		background: var(--lq-accent);
		color: var(--lq-on-accent);
		border: 0;
		padding: 4px 10px;
		border-radius: var(--lq-radius-pill);
		cursor: pointer;
		font-size: 12px;
	}
	.secondary {
		background: var(--lq-canvas);
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent);
		padding: 4px 10px;
		border-radius: var(--lq-radius-pill);
		cursor: pointer;
		font-size: 12px;
	}
	.tertiary {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 0;
		padding: 4px 10px;
		cursor: pointer;
		font-size: 12px;
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
		background: var(--lq-surface-muted);
		color: var(--lq-governance);
	}
	.pill-audited {
		background: var(--lq-surface-muted);
		color: var(--lq-text-secondary);
	}
</style>
