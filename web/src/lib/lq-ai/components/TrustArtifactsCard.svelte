<script lang="ts">
	import LqText from './shared/LqText.svelte';
	import LqTitle from './shared/LqTitle.svelte';
	/**
	 * TrustArtifactsCard — links to procurement-grade in-repo artifacts.
	 *
	 * V2-FALLBACK notes:
	 * - SBOM: not yet generated. Links to docs/security/ directory.
	 *   Replace with CI-published CycloneDX/SPDX artifact URL when available.
	 * - Threat model: docs/security/threat-model.md does not yet exist.
	 *   Links to docs/PRD.md §5 (Security & Compliance) as interim reference.
	 * - Signed releases: links to GitHub releases page (accurate).
	 * - Source code: links to GitHub repo (accurate).
	 */
	const artifacts = [
		{
			label: 'SBOM (Software Bill of Materials)',
			href: 'https://github.com/LegalQuants/lq-ai/tree/main/docs/security',
			external: true,
			// V2-FALLBACK: replace with CycloneDX/SPDX artifact URL when CI publishes it.
			note: 'Directory — machine-readable SBOM ships in a future release pipeline step'
		},
		{
			label: 'Threat model',
			href: 'https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md#5-security--compliance',
			external: true,
			// V2-FALLBACK: replace with docs/security/threat-model.md once authored.
			note: 'See PRD §5 — dedicated threat-model.md is a v1.1+ deliverable'
		},
		{
			label: 'Signed releases',
			href: 'https://github.com/LegalQuants/lq-ai/releases',
			external: true,
			note: null
		},
		{
			label: 'Source code',
			href: 'https://github.com/LegalQuants/lq-ai',
			external: true,
			note: null
		}
	] as const;
</script>

<div class="lq-card">
	<LqTitle order={3} size="16" weight="semibold" tone="primary" class="card-title">Trust artifacts</LqTitle>
	<ul class="artifact-list">
		{#each artifacts as a}
			<li class="artifact-row">
				<div class="artifact-meta">
					<LqText as="a" size="14" tone="accent"
						href={a.href}
						class="artifact-link"
						target={a.external ? '_blank' : undefined}
						rel={a.external ? 'noopener noreferrer' : undefined}
					>
						{a.label}{a.external ? ' ↗' : ''}
					</LqText>
					{#if a.note}
						<LqText as="span" size="12" tone="tertiary" class="artifact-note">{a.note}</LqText>
					{/if}
				</div>
			</li>
		{/each}
	</ul>
	<LqText as="p" size="12" tone="tertiary" class="footer-note">
		Share this page with your GC or procurement team. Every link above points to a verifiable, public artifact.
	</LqText>
</div>

<style>
	.lq-card {
		background: var(--lq-canvas);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.lq-card :global(.card-title) {
		margin: 0;
	}

	.artifact-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.artifact-row {
		padding: var(--lq-space-2) 0;
		border-bottom: 1px dashed var(--lq-border);
	}

	.artifact-row:last-child {
		border-bottom: none;
	}

	.artifact-meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.artifact-meta :global(.artifact-link) {
		text-decoration: none;
	}

	.artifact-meta :global(.artifact-link:hover) {
		text-decoration: underline;
	}

	.lq-card :global(.footer-note) {
		margin: 0;
	}
</style>
