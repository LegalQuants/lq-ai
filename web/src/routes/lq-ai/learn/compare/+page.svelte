<!--
  /lq-ai/learn/compare — "How It Compares" condensed vendor-neutral comparison.

  This page is condensed highlights, not a second full matrix. The canonical,
  evidence-linked 14-row comparison lives at docs/comparison.md — this page
  pulls 8 of the most load-bearing rows, links each to its interactive
  playground and its ADR/code, and points prominently at the full document.

  Comparison axis: verifiability, not capability. The "proprietary category"
  column never asserts the category lacks a capability — only that whatever
  it claims is closed-source and so cannot be independently verified or
  forked by the user who has to rely on it. No vendor is named anywhere on
  this page.
-->

<main class="lq-learn-compare-page" data-testid="lq-ai-learn-compare-page">
	<header class="lq-page-header">
		<a href="/lq-ai/learn" class="lq-back-link">← Learn</a>
		<h1 class="lq-text-page-h">How It Compares</h1>
		<p class="lq-text-body lq-page-intro">
			A category of proprietary legal-tech products has begun describing its AI output as
			"fiduciary-grade" — verified, trustworthy, defensible. That's the right bar. Where this
			comparison differs is the axis it measures on: <strong>verifiability, not capability.</strong>
			No vendor is named below — the "proprietary category" column states one fact, consistently: whatever
			it claims, it is closed-source, so the claim cannot be independently checked or forked by the user
			relying on it. Every LQ.AI row below resolves to a design record, a source file, and an interactive
			playground you can drive yourself.
		</p>
	</header>

	<section class="lq-compare-truths" data-testid="lq-ai-learn-compare-truths">
		<h2 class="lq-section-h">The three fundamental truths</h2>
		<div class="lq-truths-grid">
			<div class="lq-truth-card">
				<h3 class="lq-truth-h">1. Demonstrable vs. asserted</h3>
				<p class="lq-text-body">
					Every LQ.AI checkmark resolves to a clickable artifact — an ADR, the source file that
					implements it, and a playground that lets you drive the logic yourself. A proprietary
					product's equivalent checkmark is a marketing or support-page claim; there is no file you
					are allowed to open to check it. The difference isn't effort — it's that only one side
					lets you look.
				</p>
			</div>
			<div class="lq-truth-card">
				<h3 class="lq-truth-h">2. Show-the-work vs. trust-us</h3>
				<p class="lq-text-body">
					An opaque "this citation is good law" or "this output is verified" verdict is
					architecturally un-inspectable in a closed system — there is no mechanism by which a user
					could ever see the reasoning, only the label. LQ.AI's citation and treatment layers derive
					their verdicts from passages the system actually read and expose the derivation itself,
					not just the label.
				</p>
			</div>
			<div class="lq-truth-card">
				<h3 class="lq-truth-h">3. Named accountability vs. committee-anonymized</h3>
				<p class="lq-text-body">
					Legal work product built into a proprietary tool does not disclose a named individual
					accountable for it — responsibility diffuses across an anonymous process, as far as a user
					can see. Every LQ.AI skill that touches legal substance carries a named
					practicing-attorney attestation as a condition of merge — a real person's name is on the
					work.
				</p>
			</div>
		</div>
	</section>

	<section class="lq-compare-matrix" data-testid="lq-ai-learn-compare-matrix">
		<h2 class="lq-section-h">Highlight matrix</h2>
		<p class="lq-text-body">
			Eight of the fourteen rows in the full comparison — the ones most people ask about first. Each
			links to its interactive playground and its ADR/source. Where LQ.AI's own capability is
			partial or roadmapped, the caveat is stated inline, not buried.
		</p>
		<div class="lq-table-wrap">
			<table class="lq-compare-table">
				<thead>
					<tr>
						<th>Capability</th>
						<th>LQ.AI — verifiable (proof)</th>
						<th>Proprietary category — closed → not user-verifiable</th>
					</tr>
				</thead>
				<tbody>
					<tr>
						<td>Derive-don't-assert citation verification (4-stage cascade)</td>
						<td>
							<a
								href="/learn/playgrounds/citation-engine-cascade.html"
								class="lq-link"
								target="_blank"
								rel="noopener">playground</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">ADR 0018</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/citation/verification.py"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">verification.py</a
							>
						</td>
						<td>
							May claim verified citations; the verification logic is not published, so the claim
							cannot be audited or reproduced by the user.
						</td>
					</tr>
					<tr>
						<td>
							Citation Ledger — every source read, id/offset only, no raw payload stored (P3)
						</td>
						<td>
							<a
								href="/learn/playgrounds/citation-ledger.html"
								class="lq-link"
								target="_blank"
								rel="noopener">playground</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">ADR 0018</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/citation/ledger.py"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">ledger.py</a
							>
						</td>
						<td>
							May claim a source trail exists; its structure, retention, and payload-handling
							guarantees are not disclosed.
						</td>
					</tr>
					<tr>
						<td>
							Fiduciary-grade gate (PASS / SUPPORTED / FAIL, recomputed live)
							<p class="lq-caveat">
								<strong>Caveat:</strong> chat/autonomous verdict-tier parity is open (<strong
									>DE-370</strong
								>
								/ <strong>DE-371</strong>).
							</p>
						</td>
						<td>
							<a
								href="/learn/playgrounds/fiduciary-gate.html"
								class="lq-link"
								target="_blank"
								rel="noopener">playground</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">ADR 0018</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/citation/gate.py"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">gate.py</a
							>
						</td>
						<td>
							May claim a "verified" or "fiduciary-grade" badge; the gate's verdict logic and tier
							definitions are not published.
						</td>
					</tr>
					<tr>
						<td>
							Derived validity/treatment signal ("derived, not editorial")
							<p class="lq-caveat">
								<strong>Caveat:</strong> a derived signal from citing opinions actually read under a bounded
								budget — not an authoritative citator.
							</p>
						</td>
						<td>
							<a
								href="/learn/playgrounds/treatment-layer.html"
								class="lq-link"
								target="_blank"
								rel="noopener">playground</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0019-transparent-validity-treatment-layer.md"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">ADR 0019</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/citation/treatment.py"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">treatment.py</a
							>
						</td>
						<td>
							May offer an editorial good-law/bad-law verdict; the editorial process and reviewer
							identity behind it are not disclosed.
						</td>
					</tr>
					<tr>
						<td>
							Free primary-authority retrieve-and-verify (CourtListener / GovInfo / EDGAR / EUR-Lex)
							<p class="lq-caveat">
								<strong>Caveat:</strong> EUR-Lex is get-by-CELEX only today — no full-text search (<strong
									>DE-374</strong
								>) or treaty CELEX formats (<strong>DE-375</strong>).
							</p>
						</td>
						<td>
							<a
								href="/learn/playgrounds/authority-sources.html"
								class="lq-link"
								target="_blank"
								rel="noopener">playground</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0021-content-source-registry-and-free-source-expansion.md"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">ADR 0021</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/research/registry.py"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">registry.py</a
							>
						</td>
						<td>
							May aggregate primary authority from licensed feeds; the sourcing and licensing chain
							is not visible to the user.
						</td>
					</tr>
					<tr>
						<td>
							Governed agentic matter sessions (plan → act → observe → replan brakes)
							<p class="lq-caveat">
								<strong>Caveat:</strong> no dedicated matter-intake UI yet — reuses the existing autonomous
								session UI rather than a purpose-built "describe your matter" flow.
							</p>
						</td>
						<td>
							<a
								href="/learn/playgrounds/matter-session-flow.html"
								class="lq-link"
								target="_blank"
								rel="noopener">playground</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0020-governed-agentic-legal-matter-sessions.md"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">ADR 0020</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/autonomous/planner.py"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">planner.py</a
							>
						</td>
						<td>
							May offer an "agentic" research or drafting mode; the governing brakes and their
							enforcement points are not published.
						</td>
					</tr>
					<tr>
						<td>Single audited egress boundary (tier-gated, per-call audit)</td>
						<td>
							<a
								href="/learn/playgrounds/governed-tool-flow.html"
								class="lq-link"
								target="_blank"
								rel="noopener">playground</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0014-gateway-egress-boundary-for-tool-providers.md"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">ADR 0014</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0015-governed-tool-calling-model.md"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">ADR 0015</a
							>
						</td>
						<td>
							May claim governed or audited tool use; the egress boundary's implementation and audit
							granularity are not published.
						</td>
					</tr>
					<tr>
						<td>Data residency — self-hosted / BYOK / air-gapped</td>
						<td>
							<a
								href="/learn/playgrounds/data-residency.html"
								class="lq-link"
								target="_blank"
								rel="noopener">playground</a
							>
							·
							<a
								href="https://github.com/LegalQuants/lq-ai/blob/main/docs/architecture.md"
								class="lq-link"
								target="_blank"
								rel="noopener noreferrer">architecture.md</a
							>
						</td>
						<td>
							May claim data residency, private-cloud, or on-prem options; the actual deployment
							architecture and where data flows are not independently verifiable or auditable by the
							user.
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</section>

	<div class="lq-compare-callout" data-testid="lq-ai-learn-compare-callout">
		<p class="lq-text-body">
			<strong>Full evidence-linked comparison + verification paths →</strong>
			<a
				href="https://github.com/LegalQuants/lq-ai/blob/main/docs/comparison.md"
				class="lq-link"
				target="_blank"
				rel="noopener noreferrer">docs/comparison.md</a
			>
			— all 14 rows, the honest-caveats section, and how to verify the comparison yourself.
		</p>
	</div>

	<footer class="lq-how-footer">
		<p class="lq-text-body">
			<a href="/lq-ai/learn/how" class="lq-link">See it work →</a>
			— the How It Works page walks the interactive playgrounds linked above in narrative order.
		</p>
		<p class="lq-text-body">
			Don't take this page's word for it either. Read
			<a
				href="https://github.com/LegalQuants/lq-ai/blob/main/docs/HONEST-STATE.md"
				class="lq-link"
				target="_blank"
				rel="noopener noreferrer">HONEST-STATE.md</a
			>, the canonical claims-vs-reality document this comparison is built from.
		</p>
	</footer>
</main>

<style>
	.lq-learn-compare-page {
		padding: var(--lq-space-6);
		max-width: 960px;
		margin: 0 auto;
	}

	.lq-back-link {
		display: inline-block;
		font-size: 13px;
		color: var(--lq-text-secondary);
		text-decoration: none;
		margin-bottom: var(--lq-space-3);
	}

	.lq-back-link:hover {
		color: var(--lq-accent);
	}

	.lq-page-header {
		margin-bottom: var(--lq-space-6);
	}

	.lq-page-intro {
		color: var(--lq-text-secondary);
		margin-top: var(--lq-space-2);
		max-width: 72ch;
		line-height: 1.6;
	}

	.lq-section-h {
		font-size: 16px;
		font-weight: 600;
		color: var(--lq-text);
		margin: 0 0 var(--lq-space-3) 0;
	}

	.lq-text-body {
		margin: 0;
		font-size: 14px;
		line-height: 1.6;
		color: var(--lq-text);
	}

	.lq-link {
		color: var(--lq-accent);
		text-decoration: underline;
	}

	.lq-link:hover {
		opacity: 0.8;
	}

	.lq-compare-truths {
		margin-bottom: var(--lq-space-8);
	}

	.lq-truths-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
		gap: var(--lq-space-4);
	}

	.lq-truth-card {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
		padding: var(--lq-space-4);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-canvas);
	}

	.lq-truth-h {
		margin: 0;
		font-size: 14px;
		font-weight: 600;
		color: var(--lq-text);
	}

	.lq-compare-matrix {
		margin-bottom: var(--lq-space-6);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.lq-table-wrap {
		overflow-x: auto;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
	}

	.lq-compare-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}

	.lq-compare-table th,
	.lq-compare-table td {
		text-align: left;
		vertical-align: top;
		padding: var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
		line-height: 1.5;
	}

	.lq-compare-table th {
		background: var(--lq-inset);
		font-weight: 600;
		color: var(--lq-text);
		white-space: nowrap;
	}

	.lq-compare-table td {
		color: var(--lq-text-secondary);
	}

	.lq-compare-table td:first-child {
		color: var(--lq-text);
		font-weight: 500;
	}

	.lq-compare-table tbody tr:last-child td {
		border-bottom: none;
	}

	.lq-caveat {
		margin: var(--lq-space-2) 0 0 0;
		font-size: 12px;
		font-weight: 400;
		font-style: italic;
		color: var(--lq-text-tertiary);
	}

	.lq-compare-callout {
		padding: var(--lq-space-4);
		border: 1px solid var(--lq-accent);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-inset);
		margin-bottom: var(--lq-space-6);
	}

	.lq-how-footer {
		padding: var(--lq-space-6) 0;
		border-top: 1px solid var(--lq-border);
		margin-top: var(--lq-space-6);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.lq-how-footer .lq-text-body {
		color: var(--lq-text-secondary);
	}
</style>
