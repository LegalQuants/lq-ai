<!--
  /lq-ai/learn — Learn surface landing page.

  Three gateway tiles to the sub-routes, plus a brief intro that frames
  what the surface is and who it is for. Every claim on the sub-pages
  links back to a verifiable file path in source.
-->

<main class="lq-learn-page" data-testid="lq-ai-learn-page">
	<header class="lq-page-header">
		<h1 class="lq-text-page-h">Learn</h1>
		<div class="lq-learn-intro">
			<p class="lq-text-body lq-learn-intro-p">
				A guided introduction to LQ.AI for everyone — practicing attorneys curious about what the
				project does, security and procurement teams evaluating it for deployment, engineers
				exploring the architecture, and anyone considering contributing a skill. The three sections
				below address a different question: what it does, how it works, and how to contribute.
			</p>
			<p class="lq-text-body lq-learn-intro-p">
				Every claim on these pages is backed by a path to verify it in the codebase. If the docs say
				something the code does not do, the code is canonical — please
				<a
					href="https://github.com/LegalQuants/lq-ai/issues"
					class="lq-link"
					target="_blank"
					rel="noopener noreferrer">open an issue</a
				>.
			</p>
		</div>
	</header>

	<div class="lq-learn-grid">
		<a class="lq-learn-card" href="/lq-ai/learn/use" data-testid="lq-ai-learn-card-use">
			<span class="lq-learn-card-icon" aria-hidden="true">📋</span>
			<h2 class="lq-learn-card-title">How to Use</h2>
			<p class="lq-learn-card-desc">
				What every feature does, in plain language. With links to source for every claim.
			</p>
			<span class="lq-learn-card-cta">Explore →</span>
		</a>

		<a class="lq-learn-card" href="/lq-ai/learn/how" data-testid="lq-ai-learn-card-how">
			<span class="lq-learn-card-icon" aria-hidden="true">🔍</span>
			<h2 class="lq-learn-card-title">How It Works</h2>
			<p class="lq-learn-card-desc">
				Interactive playgrounds that show how the system fits together. Click any visualization to
				verify claims against the source.
			</p>
			<span class="lq-learn-card-cta">Explore →</span>
		</a>

		<a class="lq-learn-card" href="/lq-ai/learn/build" data-testid="lq-ai-learn-card-build">
			<span class="lq-learn-card-icon" aria-hidden="true">🔧</span>
			<h2 class="lq-learn-card-title">How to Build</h2>
			<p class="lq-learn-card-desc">
				How to contribute a skill, a mini-PRD, or a bug fix. What's open right now.
			</p>
			<span class="lq-learn-card-cta">Explore →</span>
		</a>

		<a class="lq-learn-card" href="/lq-ai/learn/compare" data-testid="lq-ai-learn-card-compare">
			<span class="lq-learn-card-icon" aria-hidden="true">⚖️</span>
			<h2 class="lq-learn-card-title">How It Compares</h2>
			<p class="lq-learn-card-desc">
				An evidence-linked, vendor-neutral comparison — every capability claim links to the code,
				ADR, or interactive playground that proves it.
			</p>
			<span class="lq-learn-card-cta">Explore →</span>
		</a>
	</div>
</main>

<style>
	.lq-learn-page {
		padding: var(--lq-space-6);
		max-width: 960px;
		margin: 0 auto;
	}

	.lq-page-header {
		margin-bottom: var(--lq-space-6);
	}

	.lq-learn-intro {
		margin-top: var(--lq-space-3);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
		max-width: 68ch;
	}

	.lq-learn-intro-p {
		color: var(--lq-text-secondary);
		line-height: 1.6;
	}

	.lq-link {
		color: var(--lq-accent);
		text-decoration: underline;
	}

	.lq-link:hover {
		opacity: 0.8;
	}

	.lq-learn-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: var(--lq-space-4);
	}

	.lq-learn-card {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
		padding: var(--lq-space-6);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-canvas);
		text-decoration: none;
		color: var(--lq-text);
		transition:
			border-color 0.15s ease,
			box-shadow 0.15s ease;
	}

	.lq-learn-card:hover {
		border-color: var(--lq-accent);
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
	}

	.lq-learn-card:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.lq-learn-card-icon {
		font-size: 28px;
		line-height: 1;
	}

	.lq-learn-card-title {
		margin: 0;
		font-size: 18px;
		font-weight: 600;
		color: var(--lq-text);
	}

	.lq-learn-card-desc {
		margin: 0;
		font-size: 14px;
		color: var(--lq-text-secondary);
		line-height: 1.5;
		flex: 1;
	}

	.lq-learn-card-cta {
		font-size: 14px;
		font-weight: 500;
		color: var(--lq-accent);
		margin-top: var(--lq-space-2);
	}
</style>
