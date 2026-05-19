<script lang="ts">
	/**
	 * PlaybookDisclaimerBanner — the standard not-legal-advice posture
	 * for the playbook execution surface, per Decision F (M3-A3 session)
	 * + §5.3 of the M3-A4 plan.
	 *
	 * Renders on both /lq-ai/playbooks and /lq-ai/playbook-executions/[id].
	 * Matches the project's "lean into transparency + disclaim warranties"
	 * posture: built-in playbooks are reasonable starting points drafted
	 * by the maintainer team, NOT legal advice, NOT a substitute for
	 * licensed counsel review.
	 *
	 * Visual: an inset-tinted box (using --lq-inset / --lq-warn tokens)
	 * with a small alert icon, two short sentences, and no dismiss
	 * affordance (this is a persistent posture statement, not a toast).
	 */
</script>

<aside class="lq-playbook-disclaimer" role="note" data-testid="lq-playbook-disclaimer">
	<svg
		class="lq-playbook-disclaimer__icon"
		viewBox="0 0 16 16"
		width="16"
		height="16"
		aria-hidden="true"
	>
		<path
			d="M8 1.5L1 14h14L8 1.5zm0 4.5v4M8 11.5v.5"
			stroke="currentColor"
			stroke-width="1.5"
			stroke-linecap="round"
			fill="none"
		/>
	</svg>
	<div class="lq-playbook-disclaimer__body">
		<strong>Not legal advice.</strong>
		Playbooks codify one reasonable market position. Apply your own professional judgment; review results
		with counsel licensed in the relevant jurisdiction before relying on them.
	</div>
</aside>

<style>
	.lq-playbook-disclaimer {
		display: flex;
		gap: 0.625rem;
		align-items: flex-start;
		padding: 0.75rem 1rem;
		border: 1px solid var(--lq-warn-border, var(--lq-border));
		background: var(--lq-warn-soft, var(--lq-inset));
		color: var(--lq-text-primary);
		border-radius: 0.5rem;
		font-size: 0.875rem;
		line-height: 1.4;
	}

	.lq-playbook-disclaimer__icon {
		flex-shrink: 0;
		color: var(--lq-warn, var(--lq-text-secondary));
		margin-top: 0.125rem;
	}

	.lq-playbook-disclaimer__body strong {
		font-weight: 600;
		margin-right: 0.25rem;
	}
</style>
