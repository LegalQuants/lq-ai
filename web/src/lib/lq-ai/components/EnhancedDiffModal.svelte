<script lang="ts">
	/**
	 * EnhancedDiffModal — tap-to-diff popover for the ✨ enhanced pill.
	 *
	 * Wave D.1 T20 follow-on (deferral B). Shown when the operator clicks
	 * the ✨ enhanced provenance pill on a user-message bubble. Side-by-side
	 * "Original" / "Enhanced" panes so the operator can eyeball what the
	 * Enhance Prompt skill changed about their typed prompt.
	 *
	 * Known limit: the original prompt is currently held in-memory by the
	 * chat shell (ChatPanel.enhancementOriginals), keyed by enhanced
	 * content. The server stores only the enhanced text on the user-message
	 * row — so after a page reload the original is no longer recoverable
	 * for a previously-sent enhanced message. We render an "original not
	 * preserved" fallback in that case. Persisting the original alongside
	 * the enhanced send is a v1.1+ candidate (would require a new column
	 * or an interaction-id back-reference into the enhance_prompt_log
	 * table); for M1 the session-scope record is sufficient because
	 * Enhance Prompt is primarily a live-composition affordance.
	 *
	 * Diff rendering is intentionally simple — two stacked text panes with
	 * `white-space: pre-wrap`. A heavier diff (LCS / inline word-highlight
	 * via `diff-match-patch`) is a v1.1+ refinement; the SBOM does not
	 * currently include that dep and adding it for a single operator
	 * inspection surface is not justified per CLAUDE.md guidance.
	 *
	 * Pure display — no backdrop, no Esc/close handling, no dispatched
	 * events. Whatever renders this (a modal, a hover popover) owns the
	 * presentation; this component owns none of it.
	 */
	export let original: string | undefined = undefined;
	export let enhanced: string;
</script>

<div class="diff-panel" data-testid="enhanced-diff-modal">
	<header>
		<h2 id="enhanced-diff-title">✨ Enhance Prompt — original vs. enhanced</h2>
	</header>

	<div class="cols">
		<section>
			<h3>Original</h3>
			{#if original !== undefined && original !== ''}
				<pre data-testid="enhanced-diff-original">{original}</pre>
			{:else}
				<p class="empty" data-testid="enhanced-diff-original-missing">
					Original prompt not preserved — only the enhanced version was
					committed at send time. (Earlier-session originals are not
					currently persisted server-side. v1.1+ refinement candidate.)
				</p>
			{/if}
		</section>

		<section>
			<h3>Enhanced</h3>
			<pre data-testid="enhanced-diff-enhanced">{enhanced}</pre>
		</section>
	</div>
</div>

<style>
	.diff-panel {
		background: #fff;
		border-radius: 8px;
		width: min(900px, 90vw);
		max-height: 80vh;
		display: flex;
		flex-direction: column;
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 14px;
		border-bottom: 1px solid #e5e7eb;
	}
	header h2 {
		font-size: 14px;
		font-weight: 600;
		margin: 0;
		color: #111827;
	}
	.cols {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 12px;
		padding: 12px 14px;
		overflow: auto;
	}
	section {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	section h3 {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		color: #6b7280;
		margin: 0 0 6px 0;
		letter-spacing: 0.04em;
	}
	pre {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 12px;
		line-height: 1.5;
		white-space: pre-wrap;
		word-break: break-word;
		background: #f9fafb;
		border: 1px solid #e5e7eb;
		border-radius: 6px;
		padding: 10px;
		color: #111827;
		margin: 0;
	}
	.empty {
		font-size: 12px;
		color: #6b7280;
		font-style: italic;
		background: #f9fafb;
		border: 1px dashed #d1d5db;
		border-radius: 6px;
		padding: 10px;
		margin: 0;
	}
	@media (max-width: 640px) {
		.cols {
			grid-template-columns: 1fr;
		}
	}
</style>
