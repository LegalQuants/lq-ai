<script lang="ts">
	import LqToneIcon from '$lib/lq-ai/components/shared/LqToneIcon.svelte';
	import { IconSparkles, IconX } from '@tabler/icons-svelte';
	/**
	 * EnhancePromptExpansion — inline expansion panel shown between the composer
	 * and AmbientFooter after the user clicks ✨.
	 *
	 * State machine:
	 *   closed   → nothing shown
	 *   loading  → spinner + "Enhancing…"
	 *   shown    → two-column Original / Enhanced card diff + action buttons
	 *   skipped  → "No expansion needed" message + Got it button
	 *   error    → error message + Try again / Dismiss
	 *
	 * The parent calls `open()` to trigger the API call. Callbacks let the
	 * parent update composerText and handle dismissal without this component
	 * reaching into the DOM.
	 */
	import { enhance, recordOutcome } from '$lib/lq-ai/api/enhancePrompt';
	import TrustPill from './TrustPill.svelte';
	import LqText from './shared/LqText.svelte';

	export let originalText: string;
	export let chatId: string | null = null;
	export let onUseEnhanced: (enhanced: string, interactionId: string) => void = () => undefined;
	export let onEditEnhanced: (enhanced: string, interactionId: string) => void = () => undefined;
	export let onKeepOriginal: (interactionId: string | null) => void = () => undefined;
	export let onDismiss: () => void = () => undefined;

	/**
	 * §7.1 — first-time JIT onboarding strip. Shows once on the user's first
	 * post-enhance shown state and persists dismissal in localStorage so
	 * subsequent enhancements don't re-show it.
	 */
	export const JIT_SEEN_KEY = 'lq_ai_jit_enhance_seen';
	let jitDismissed = readJitSeen();

	function readJitSeen(): boolean {
		try { return localStorage.getItem(JIT_SEEN_KEY) === 'true'; } catch { return false; }
	}
	function dismissJit(): void {
		jitDismissed = true;
		try { localStorage.setItem(JIT_SEEN_KEY, 'true'); } catch {}
	}

	type ExpansionState =
		| { kind: 'closed' }
		| { kind: 'loading'; original: string }
		| { kind: 'shown'; original: string; enhanced: string; reasoning: string[]; preview?: string; interactionId: string; tier: number | null; provider: string | null }
		| { kind: 'skipped'; original: string; skipReason: string; interactionId: string }
		| { kind: 'error'; original: string; message: string };

	let state: ExpansionState = { kind: 'closed' };

	function setOnboardedFlag(): void {
		try { localStorage.setItem('lq-ai:onboarded:enhance', 'true'); } catch {}
	}

	export async function open(): Promise<void> {
		const text = originalText;
		if (!text.trim()) return;
		state = { kind: 'loading', original: text };
		try {
			const res = await enhance({
				raw_input: text,
				chat_id: chatId ?? undefined
			});
			if (res.expansion_applied) {
				state = {
					kind: 'shown',
					original: text,
					enhanced: res.expanded_prompt,
					reasoning: res.reasoning,
					preview: res.preview_to_user,
					interactionId: res.interaction_id,
					tier: res.routed_inference_tier ?? null,
					provider: res.routed_provider ?? null
				};
			} else {
				state = {
					kind: 'skipped',
					original: text,
					skipReason: res.skip_reason ?? 'no reason provided',
					interactionId: res.interaction_id
				};
			}
		} catch (e) {
			const original = (state as { kind: 'loading'; original: string }).original ?? text;
			state = {
				kind: 'error',
				original,
				message: e instanceof Error ? e.message : 'Unknown error'
			};
		}
	}

	async function handleUseEnhanced(): Promise<void> {
		if (state.kind !== 'shown') return;
		const { enhanced, interactionId } = state;
		state = { kind: 'closed' };
		setOnboardedFlag();
		onUseEnhanced(enhanced, interactionId);
		try { await recordOutcome(interactionId, { used: true, edited_before_use: false }); } catch {}
	}

	async function handleEditEnhanced(): Promise<void> {
		if (state.kind !== 'shown') return;
		const { enhanced, interactionId } = state;
		state = { kind: 'closed' };
		setOnboardedFlag();
		onEditEnhanced(enhanced, interactionId);
		try { await recordOutcome(interactionId, { used: true, edited_before_use: true }); } catch {}
	}

	async function handleKeepOriginal(): Promise<void> {
		if (state.kind !== 'shown') return;
		const { interactionId } = state;
		state = { kind: 'closed' };
		setOnboardedFlag();
		onKeepOriginal(interactionId);
		try { await recordOutcome(interactionId, { used: false }); } catch {}
	}

	async function handleSkippedDismiss(): Promise<void> {
		if (state.kind !== 'skipped') return;
		const { interactionId } = state;
		state = { kind: 'closed' };
		setOnboardedFlag();
		onKeepOriginal(interactionId);
		try { await recordOutcome(interactionId, { used: false }); } catch {}
	}

	function handleDismiss(): void {
		const prevState = state;
		state = { kind: 'closed' };
		if (prevState.kind === 'shown') {
			const id = prevState.interactionId;
			try { recordOutcome(id, { used: false }); } catch {}
		}
		onDismiss();
	}

	function handleRetry(): void {
		void open();
	}
</script>

{#if state.kind !== 'closed'}
	<div class="lq-enhance-panel" data-testid="lq-ai-enhance-panel">
		{#if state.kind === 'loading'}
			<div class="lq-enhance-loading" data-testid="lq-ai-enhance-loading">
				<span class="lq-spinner" aria-hidden="true"></span>
				<LqText as="span" size="11" tone="secondary">Enhancing…</LqText>
			</div>
		{:else if state.kind === 'shown'}
			{#if !jitDismissed}
				<div class="lq-enhance-jit" data-testid="lq-ai-enhance-jit">
					<LqText as="span" size="11" tone="secondary" class="lq-enhance-jit-msg">
						<LqToneIcon tone="info" size={12} />
						Tip: Enhance (<IconSparkles size={11} stroke={1.75} aria-hidden="true" />) rewrites your
						prompt so the AI has more to work with. Pick
						<strong>Use enhanced</strong>, tweak with <strong>Edit enhanced</strong>, or
						<strong>Keep original</strong>. (⌘E)
					</LqText>
					<button
						type="button"
						class="lq-btn-ghost lq-enhance-jit-dismiss"
						on:click={dismissJit}
						data-testid="lq-ai-enhance-jit-dismiss"
						aria-label="Dismiss tip"
					>
						Got it
					</button>
				</div>
			{/if}
			<div class="lq-enhance-header">
				<span class="lq-enhance-title">Prompt Enhancement</span>
				<div class="lq-enhance-header-actions">
					{#if state.tier != null}
						<TrustPill variant="tier" label="Tier {state.tier}" />
					{/if}
					<button
						type="button"
						class="lq-btn-ghost lq-enhance-dismiss-x"
						aria-label="Dismiss enhancement"
						on:click={handleDismiss}
					>
						<IconX size={14} stroke={1.75} aria-hidden="true" />
					</button>
				</div>
			</div>

			<div class="lq-enhance-cards">
				<div class="lq-enhance-card lq-enhance-card--original" data-testid="lq-ai-enhance-original">
					<div class="lq-enhance-card-label">Original</div>
					<p class="lq-enhance-card-body">{state.original}</p>
				</div>
				<div class="lq-enhance-card lq-enhance-card--enhanced" data-testid="lq-ai-enhance-enhanced">
					<div class="lq-enhance-card-label">
						Enhanced <IconSparkles size={11} stroke={1.75} aria-hidden="true" />
					</div>
					<p class="lq-enhance-card-body">{state.enhanced}</p>
					{#if state.reasoning.length > 0}
						<ul class="lq-enhance-reasoning">
							{#each state.reasoning as bullet}
								<LqText as="li" size="11" tone="secondary">{bullet}</LqText>
							{/each}
						</ul>
					{/if}
				</div>
			</div>

			<div class="lq-enhance-actions">
				<button
					type="button"
					class="lq-btn-primary"
					on:click={handleUseEnhanced}
					data-testid="lq-ai-enhance-use"
				>
					Use enhanced
				</button>
				<button
					type="button"
					class="lq-btn-secondary"
					on:click={handleEditEnhanced}
					data-testid="lq-ai-enhance-edit"
				>
					Edit enhanced
				</button>
				<button
					type="button"
					class="lq-btn-ghost"
					on:click={handleKeepOriginal}
					data-testid="lq-ai-enhance-keep"
				>
					Keep original
				</button>
			</div>
		{:else if state.kind === 'skipped'}
			<div class="lq-enhance-skipped" data-testid="lq-ai-enhance-skipped">
				<LqText as="span" size="11" tone="secondary">
					No expansion needed — your prompt is already structured. ({state.skipReason})
				</LqText>
				<button
					type="button"
					class="lq-btn-secondary"
					on:click={handleSkippedDismiss}
					data-testid="lq-ai-enhance-skipped-ok"
				>
					Got it
				</button>
			</div>
		{:else if state.kind === 'error'}
			<div class="lq-enhance-error" data-testid="lq-ai-enhance-error">
				<LqText as="span" size="11" tone="danger" class="lq-enhance-error-msg">
					Enhance Prompt failed: {state.message}
				</LqText>
				<div class="lq-enhance-error-actions">
					<button
						type="button"
						class="lq-btn-secondary"
						on:click={handleRetry}
						data-testid="lq-ai-enhance-retry"
					>
						Try again
					</button>
					<button
						type="button"
						class="lq-btn-ghost"
						on:click={handleDismiss}
						data-testid="lq-ai-enhance-error-dismiss"
					>
						Dismiss
					</button>
				</div>
			</div>
		{/if}
	</div>
{/if}

<style>
	@import '../styles/practice.css';

	.lq-enhance-panel {
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-canvas);
		padding: var(--lq-space-3);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.lq-enhance-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.lq-enhance-title {
		font-size: 13px;
		font-weight: 600;
		color: var(--lq-text);
	}

	.lq-enhance-header-actions {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
	}

	.lq-enhance-dismiss-x {
		font-size: 18px;
		line-height: 1;
		padding: 2px 6px;
		color: var(--lq-text-secondary);
	}

	.lq-enhance-cards {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--lq-space-3);
	}

	@media (max-width: 640px) {
		.lq-enhance-cards {
			grid-template-columns: 1fr;
		}
	}

	.lq-enhance-card {
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		background: var(--lq-canvas);
		padding: var(--lq-space-3);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.lq-enhance-card--original {
		opacity: 0.6;
	}

	.lq-enhance-card--enhanced {
		border-color: var(--lq-accent-border);
		background: var(--lq-inset-secure);
	}

	.lq-enhance-card-label {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--lq-text-secondary);
	}

	.lq-enhance-card--enhanced .lq-enhance-card-label {
		color: var(--lq-accent);
	}

	.lq-enhance-card-body {
		font-size: 13px;
		color: var(--lq-text);
		margin: 0;
		white-space: pre-wrap;
		word-break: break-word;
	}

	.lq-enhance-reasoning {
		margin: 0;
		padding-left: var(--lq-space-4);
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.lq-enhance-actions {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
		flex-wrap: wrap;
	}

	.lq-enhance-loading {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
		padding: var(--lq-space-2) 0;
	}

	.lq-spinner {
		display: inline-block;
		width: 14px;
		height: 14px;
		border: 2px solid var(--lq-accent-border);
		border-top-color: var(--lq-accent);
		border-radius: 50%;
		animation: lq-spin 0.7s linear infinite;
	}

	@keyframes lq-spin {
		to { transform: rotate(360deg); }
	}

	.lq-enhance-skipped {
		display: flex;
		align-items: center;
		gap: var(--lq-space-3);
		flex-wrap: wrap;
	}

	.lq-enhance-error {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.lq-enhance-jit {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--lq-space-3);
		padding: var(--lq-space-2) var(--lq-space-3);
		border-radius: var(--lq-radius);
		background: var(--lq-warn-soft);
		border: 1px solid var(--lq-warn-border);
		color: var(--lq-warn);
	}
	.lq-enhance-jit :global(.lq-enhance-jit-msg) { flex: 1; }
	.lq-enhance-jit-dismiss { flex-shrink: 0; }

	.lq-enhance-error-actions {
		display: flex;
		gap: var(--lq-space-2);
	}

	/* Button primitives — match practice palette */
	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius-pill);
		padding: 6px 14px;
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-primary:hover { opacity: 0.85; }
	.lq-btn-primary:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }

	.lq-btn-secondary {
		background: white;
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
		border-radius: var(--lq-radius-pill);
		padding: 6px 12px;
		font-size: 12px;
		cursor: pointer;
	}
	.lq-btn-secondary:hover { background: var(--lq-accent-soft); }
	.lq-btn-secondary:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }

	.lq-btn-ghost {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: 6px 12px;
		font-size: 12px;
		cursor: pointer;
	}
	.lq-btn-ghost:hover { background: var(--lq-inset); }
	.lq-btn-ghost:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }
</style>
