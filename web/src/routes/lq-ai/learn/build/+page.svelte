<!--
  /lq-ai/learn/build — "How to Build" contributor page.

  Covers: contribution path, skill authoring (with embedded Skill Format
  Explorer playground), curated mini-PRDs list, roadmap summary, and
  direct GitHub links.
-->

<main class="lq-learn-build-page" data-testid="lq-ai-learn-build-page">
	<header class="lq-page-header">
		<a href="/lq-ai/learn" class="lq-back-link">← Learn</a>
		<h1 class="lq-text-page-h">How to Build</h1>
		<p class="lq-text-body lq-page-intro">
			Everything you need to go from curious to contributor — whether you're a practicing
			attorney, a security engineer, or a developer looking for a well-scoped first PR.
		</p>
	</header>

	<div class="lq-build-sections">

		<!-- 1: Contribution path -->
		<section class="lq-build-section" data-testid="lq-ai-learn-build-section-path">
			<h2 class="lq-section-h">The contribution path</h2>
			<p class="lq-text-body">
				Contributions arrive two ways: GitHub Issues for bug reports and feature requests;
				Pull Requests for code, skill, and documentation contributions. The engineering
				process — DCO sign-off, imperative-mood commit messages, PR template — is in
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/CONTRIBUTING.md" class="lq-link" target="_blank" rel="noopener noreferrer">CONTRIBUTING.md</a>.
				If you're picking up a curated mini-PRD (see below), the mini-PRD's "Definition of
				merged" section is the contract: if the acceptance criteria are checked off and the
				substance review passes, the PR merges. Ambiguities get resolved in writing on the
				issue thread before work begins — not during review.
			</p>
		</section>

		<!-- 2: Skill contribution -->
		<section class="lq-build-section" data-testid="lq-ai-learn-build-section-skill">
			<h2 class="lq-section-h">Want to contribute a skill? Start here.</h2>
			<p class="lq-text-body">
				Skills are the canonical artifact of value in LQ.AI (PRD §7.1). A skill is a
				structured SKILL.md file that captures: a system prompt, an input schema, reference
				documents, and at least one worked example that a practicing attorney can evaluate.
				Skills containing legal substance are not ordinary code contributions — they go
				through an attestation review to ensure accuracy.
			</p>
			<div class="lq-build-steps">
				<div class="lq-build-step">
					<span class="lq-build-step-n">1</span>
					<div>
						<strong>Claim.</strong> File a GitHub issue or comment on an open one.
						A maintainer acknowledges within ~7 days.
					</div>
				</div>
				<div class="lq-build-step">
					<span class="lq-build-step-n">2</span>
					<div>
						<strong>Draft.</strong> Author the SKILL.md, reference files, and at least
						one worked example. The Skill Format Explorer below validates structure
						as you write.
					</div>
				</div>
				<div class="lq-build-step">
					<span class="lq-build-step-n">3</span>
					<div>
						<strong>Attest.</strong> Add a practicing-attorney attestation paragraph to
						the PR description confirming the legal substance. Agents do not attest;
						the human contributor is the attesting party.
					</div>
				</div>
				<div class="lq-build-step">
					<span class="lq-build-step-n">4</span>
					<div>
						<strong>Review.</strong> A practicing attorney + an engineer review the PR.
						Both approvals required before merge.
					</div>
				</div>
			</div>
			<div class="lq-build-links">
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/skills/CONTRIBUTING.md" class="lq-link" target="_blank" rel="noopener noreferrer">skills/CONTRIBUTING.md</a>
				<span class="lq-sep">·</span>
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/skill-authoring-guide.md" class="lq-link" target="_blank" rel="noopener noreferrer">docs/skill-authoring-guide.md</a>
				<span class="lq-sep">·</span>
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/contribute/mini-prds/skill-acceptance-tests.md" class="lq-link" target="_blank" rel="noopener noreferrer">skill-acceptance-tests mini-PRD</a>
			</div>

			<div class="lq-playground-label">
				<strong>Try it out: Skill Format Explorer</strong>
				<span class="lq-playground-caption">
					Use this editor to experiment with the SKILL.md format. Validation rules are
					mirrored from the live backend at
					<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/user_skills.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/user_skills.py</a>.
				</span>
			</div>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/skill-format.html"
					title="Skill Format Explorer — SKILL.md editor and validation"
					loading="lazy"
					data-testid="learn-playground-skill-format"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/skill-format.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer"
				>Open full-screen ↗</a>
			</div>
		</section>

		<!-- 3: Mini-PRDs -->
		<section class="lq-build-section" data-testid="lq-ai-learn-build-section-mini-prds">
			<h2 class="lq-section-h">Curated mini-PRDs (shortest-path contributions)</h2>
			<p class="lq-text-body">
				Seven contributions where the foundation is already in source, the gaps are named
				in source, and the path to merge is short. Each mini-PRD includes explicit
				acceptance criteria and a contributor profile so you can decide whether to start
				with the same information the maintainer team has. Full list with effort estimates
				at
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/contribute/EASIEST-CONTRIBUTIONS.md" class="lq-link" target="_blank" rel="noopener noreferrer">docs/contribute/EASIEST-CONTRIBUTIONS.md</a>.
			</p>
			<div class="lq-mini-prd-list">
				<div class="lq-mini-prd">
					<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/contribute/mini-prds/procurement-readiness-pack.md" class="lq-mini-prd-title lq-link" target="_blank" rel="noopener noreferrer">Procurement-Readiness Pack</a>
					<span class="lq-mini-prd-who">In-house counsel / procurement analyst</span>
					<p class="lq-mini-prd-desc">Structured SIG Lite response, vendor questionnaire, and data-handling addendum backed by verified file paths.</p>
				</div>
				<div class="lq-mini-prd">
					<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/contribute/mini-prds/owasp-llm-top10-mapping.md" class="lq-mini-prd-title lq-link" target="_blank" rel="noopener noreferrer">OWASP LLM Top 10 Mapping</a>
					<span class="lq-mini-prd-who">Security-aware engineer</span>
					<p class="lq-mini-prd-desc">Map each OWASP LLM Top 10 risk to the mitigating control in this codebase, with a verification path per item.</p>
				</div>
				<div class="lq-mini-prd">
					<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/contribute/mini-prds/skill-acceptance-tests.md" class="lq-mini-prd-title lq-link" target="_blank" rel="noopener noreferrer">Acceptance Tests for Built-in Skills</a>
					<span class="lq-mini-prd-who">Practicing attorney</span>
					<p class="lq-mini-prd-desc">Author a test suite (worked examples with expected outputs) for one or more of the ten starter skills.</p>
				</div>
				<div class="lq-mini-prd">
					<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/contribute/mini-prds/openssf-scorecard-and-badges.md" class="lq-mini-prd-title lq-link" target="_blank" rel="noopener noreferrer">OpenSSF Scorecard + Best Practices Badges</a>
					<span class="lq-mini-prd-who">Junior-to-mid engineer</span>
					<p class="lq-mini-prd-desc">Run the OpenSSF Scorecard, fix the remediable findings, and add the badges to README.</p>
				</div>
				<div class="lq-mini-prd">
					<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/contribute/mini-prds/air-gap-install-verification.md" class="lq-mini-prd-title lq-link" target="_blank" rel="noopener noreferrer">Air-Gap Install Verification CI Test</a>
					<span class="lq-mini-prd-who">Mid engineer with Docker networking</span>
					<p class="lq-mini-prd-desc">Add a CI job that brings up the full stack with network egress blocked, then runs the smoke suite.</p>
				</div>
				<div class="lq-mini-prd">
					<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/contribute/mini-prds/nist-ai-rmf-profile.md" class="lq-mini-prd-title lq-link" target="_blank" rel="noopener noreferrer">NIST AI RMF 1.0 Profile Mapping</a>
					<span class="lq-mini-prd-who">AI-governance / compliance professional</span>
					<p class="lq-mini-prd-desc">Map LQ.AI's risk controls to the NIST AI RMF 1.0 Govern / Map / Measure / Manage functions.</p>
				</div>
				<div class="lq-mini-prd">
					<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/contribute/mini-prds/reverse-proxy-tls-deployment-recipes.md" class="lq-mini-prd-title lq-link" target="_blank" rel="noopener noreferrer">Reverse-Proxy + TLS Deployment Recipes</a>
					<span class="lq-mini-prd-who">Junior-to-mid DevOps</span>
					<p class="lq-mini-prd-desc">Tested nginx and Caddy recipes for putting LQ.AI behind a reverse proxy with TLS termination.</p>
				</div>
			</div>
		</section>

		<!-- 3b: Dev-facing visualizations -->
		<section class="lq-build-section" data-testid="lq-ai-learn-build-section-dev-viz">
			<h2 class="lq-section-h">Before you open a PR: what must pass, and how to trace it</h2>
			<p class="lq-text-body">
				Two interactive maps help you ship a change that merges cleanly. The test landscape shows
				every gate a PR must clear before merge — unit, integration, end-to-end, lint, type-check,
				and coverage — and where each one lives. The observability trace shows the OpenTelemetry
				span tree a single chat-send produces, so you can see exactly where to add instrumentation
				for a new surface.
			</p>
			<div class="lq-build-links">
				<a href="/learn/playgrounds/test-landscape.html" class="lq-link" target="_blank" rel="noopener noreferrer">Test landscape: what must pass before merge ↗</a>
				<span class="lq-sep">·</span>
				<a href="/learn/playgrounds/otel-eval.html" class="lq-link" target="_blank" rel="noopener noreferrer">Observability trace explorer ↗</a>
				<span class="lq-sep">·</span>
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/observability.md" class="lq-link" target="_blank" rel="noopener noreferrer">docs/observability.md</a>
			</div>
		</section>

		<!-- 3c: Anatomy of an aligned agentic flow (M4) -->
		<section class="lq-build-section" data-testid="lq-ai-learn-build-section-agentic-flow">
			<h2 class="lq-section-h">Anatomy of an aligned agentic flow (M4)</h2>
			<p class="lq-text-body">
				<strong>Shipped in M4.</strong> When you contribute an autonomous flow — a single agent that
				acts without a human approving each step — transparency moves from "you can read the prompt" to "you
				can audit the behavior." Four obligations make a flow aligned. The authoritative how-to is the
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/LQVern/agentic-flow-alignment-guide.md" class="lq-link" target="_blank" rel="noopener noreferrer">agentic-flow-alignment-guide.md</a>;
				this is the condensed checklist.
			</p>
			<div class="lq-build-steps">
				<div class="lq-build-step">
					<span class="lq-build-step-n">1</span>
					<div>
						<strong>One chokepoint.</strong> Every tool call goes through the single
						<code>guarded_tool_call</code> chokepoint — no tool bypasses it. A new tool gets the brakes
						and telemetry for free and cannot route around them.
					</div>
				</div>
				<div class="lq-build-step">
					<span class="lq-build-step-n">2</span>
					<div>
						<strong>Brakes before the tool runs.</strong> R5 (halt-state read), R6 (phase-grant check),
						and R4 (cost-cap projection) are all checked <em>before</em> the tool executes — in that order.
					</div>
				</div>
				<div class="lq-build-step">
					<span class="lq-build-step-n">3</span>
					<div>
						<strong>Observable + audited, counts only.</strong> Emit the <code>autonomous.execute</code>
						+ <code>autonomous.tool_call</code> spans and closed-enum audit rows (phase_transition
						/ tool_call / halted / cost_cap_reached / completed). Attributes carry counts, types, IDs, and
						costs only — never raw entity values, document text, prompt bodies, or model responses.
					</div>
				</div>
				<div class="lq-build-step">
					<span class="lq-build-step-n">4</span>
					<div>
						<strong>A user-readable receipt.</strong> Every run produces a receipt that says what the agent
						did and why — every tool call, the inputs seen (counts/types/IDs), cost, phase, and gates passed —
						readable by the user, not just the operator.
					</div>
				</div>
			</div>
			<div class="lq-build-links">
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/LQVern/agentic-flow-alignment-guide.md" class="lq-link" target="_blank" rel="noopener noreferrer">Building aligned agentic flows — the contributor guide ↗</a>
				<span class="lq-sep">·</span>
				<a href="/learn/playgrounds/autonomous-flow.html" class="lq-link" target="_blank" rel="noopener noreferrer">Autonomous flow playground ↗</a>
			</div>
		</section>

		<!-- 4: Roadmap -->
		<section class="lq-build-section" data-testid="lq-ai-learn-build-section-roadmap">
			<h2 class="lq-section-h">The roadmap</h2>
			<p class="lq-text-body">
				LQ.AI follows a milestone-based roadmap. M1 shipped the foundation; M2 and M3 each added a
				named capability layer on top. M1, M2, M3, and the M4 Autonomous Layer are all shipped; the
				Contract Relationship graph remains deferred future work.
			</p>
			<div class="lq-roadmap-list">
				<div class="lq-roadmap-item lq-roadmap-item--shipped">
					<div class="lq-roadmap-pill">M1</div>
					<div>
						<strong>Foundation.</strong> Self-hostable conversational AI on ten starter
						skills. Chat, matters, skills (capture / fork / author), knowledge bases,
						saved prompts, receipts, tier enforcement, audit log, GDPR export/deletion.
						Three provider adapters: Anthropic, OpenAI, Ollama.
					</div>
				</div>
				<div class="lq-roadmap-item lq-roadmap-item--shipped">
					<div class="lq-roadmap-pill">M2</div>
					<div>
						<strong>Citation Engine + Anonymization Layer.</strong>
						Character-level citation verification and personal-data pseudonymization
						before inference, plus the Azure OpenAI provider adapter.
					</div>
				</div>
				<div class="lq-roadmap-item lq-roadmap-item--shipped">
					<div class="lq-roadmap-pill">M3</div>
					<div>
						<strong>Capability surfaces + integrations.</strong> Playbooks, Tabular Review,
						Slack/Teams intake bridges, OpenTelemetry observability, and the Microsoft Word
						add-in (Office.js — plumbing only at v0.3.0; the in-pane feature surface is deferred).
					</div>
				</div>
				<div class="lq-roadmap-item lq-roadmap-item--shipped">
					<div class="lq-roadmap-pill">M4</div>
					<div>
						<strong>Autonomous Layer.</strong> Multi-step agent execution with
						verifiable receipts (opt-in, off by default).
					</div>
				</div>
				<div class="lq-roadmap-item">
					<div class="lq-roadmap-pill lq-roadmap-pill--future">Future</div>
					<div>
						<strong>Contract Relationship graph.</strong> Deferred future work — not yet built.
					</div>
				</div>
			</div>
			<p class="lq-text-body lq-roadmap-note">
				Full deferred-enhancement list with wire-format specs for contributor-ready items:
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md#9-deferred-enhancements-and-identified-future-work" class="lq-link" target="_blank" rel="noopener noreferrer">PRD §9</a>.
			</p>
		</section>

		<!-- 5: GitHub links -->
		<section class="lq-build-section" data-testid="lq-ai-learn-build-section-github">
			<h2 class="lq-section-h">GitHub</h2>
			<div class="lq-github-links">
				<a href="https://github.com/LegalQuants/lq-ai" class="lq-github-link" target="_blank" rel="noopener noreferrer">
					<span class="lq-github-link-icon">📦</span>
					<div>
						<strong>Repository</strong>
						<span>github.com/LegalQuants/lq-ai</span>
					</div>
				</a>
				<a href="https://github.com/LegalQuants/lq-ai/issues" class="lq-github-link" target="_blank" rel="noopener noreferrer">
					<span class="lq-github-link-icon">🐛</span>
					<div>
						<strong>Issues</strong>
						<span>Bug reports + feature requests</span>
					</div>
				</a>
				<a href="https://github.com/LegalQuants/lq-ai/pulls" class="lq-github-link" target="_blank" rel="noopener noreferrer">
					<span class="lq-github-link-icon">🔀</span>
					<div>
						<strong>Pull Requests</strong>
						<span>Active contributions in review</span>
					</div>
				</a>
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/SECURITY.md" class="lq-github-link" target="_blank" rel="noopener noreferrer">
					<span class="lq-github-link-icon">🔒</span>
					<div>
						<strong>Security Policy</strong>
						<span>Responsible disclosure process</span>
					</div>
				</a>
				<a href="https://github.com/LegalQuants/lq-ai/blob/main/CODE_OF_CONDUCT.md" class="lq-github-link" target="_blank" rel="noopener noreferrer">
					<span class="lq-github-link-icon">📜</span>
					<div>
						<strong>Code of Conduct</strong>
						<span>Community standards</span>
					</div>
				</a>
			</div>
		</section>

	</div>
</main>

<style>
	.lq-learn-build-page {
		padding: var(--lq-space-6);
		max-width: 800px;
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
		max-width: 64ch;
		line-height: 1.6;
	}

	.lq-build-sections {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.lq-build-section {
		padding: var(--lq-space-6) 0;
		border-bottom: 1px solid var(--lq-border);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4);
	}

	.lq-build-section:last-child {
		border-bottom: none;
	}

	.lq-section-h {
		font-size: 16px;
		font-weight: 600;
		color: var(--lq-text);
		margin: 0;
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

	.lq-sep {
		color: var(--lq-text-tertiary);
	}

	/* Skill contribution steps */
	.lq-build-steps {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.lq-build-step {
		display: flex;
		gap: var(--lq-space-3);
		align-items: flex-start;
		font-size: 14px;
		line-height: 1.5;
	}

	.lq-build-step-n {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--lq-accent-soft);
		border: 1px solid var(--lq-accent-border);
		color: var(--lq-accent);
		font-size: 12px;
		font-weight: 600;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		margin-top: 1px;
	}

	.lq-build-links {
		display: flex;
		gap: var(--lq-space-2);
		flex-wrap: wrap;
		align-items: center;
		font-size: 13px;
	}

	/* Playground */
	.lq-playground-label {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.lq-playground-label strong {
		font-size: 14px;
		color: var(--lq-text);
	}

	.lq-playground-caption {
		font-size: 13px;
		color: var(--lq-text-secondary);
		line-height: 1.5;
	}

	.lq-playground-wrap {
		border-radius: var(--lq-radius-lg);
		overflow: hidden;
	}

	.lq-playground-foot {
		display: flex;
		justify-content: flex-start;
	}

	.lq-fullscreen-link {
		font-size: 13px;
		font-weight: 500;
	}

	/* Mini-PRD list */
	.lq-mini-prd-list {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.lq-mini-prd {
		padding: var(--lq-space-4);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-canvas);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.lq-mini-prd-title {
		font-size: 14px;
		font-weight: 600;
	}

	.lq-mini-prd-who {
		font-size: 12px;
		color: var(--lq-text-secondary);
	}

	.lq-mini-prd-desc {
		margin: 0;
		font-size: 13px;
		color: var(--lq-text-secondary);
		line-height: 1.4;
	}

	/* Roadmap */
	.lq-roadmap-list {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.lq-roadmap-item {
		display: flex;
		gap: var(--lq-space-3);
		align-items: flex-start;
		font-size: 14px;
		line-height: 1.5;
		color: var(--lq-text-secondary);
	}

	.lq-roadmap-item--shipped {
		color: var(--lq-text);
	}

	.lq-roadmap-pill {
		padding: 2px 10px;
		border-radius: var(--lq-radius-pill);
		font-size: 11px;
		font-weight: 600;
		white-space: nowrap;
		flex-shrink: 0;
		margin-top: 3px;
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
	}

	.lq-roadmap-pill--future {
		background: var(--lq-inset);
		color: var(--lq-text-tertiary);
		border-color: var(--lq-border);
	}

	.lq-roadmap-note {
		color: var(--lq-text-secondary);
		margin-top: var(--lq-space-2);
	}

	/* GitHub links */
	.lq-github-links {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.lq-github-link {
		display: flex;
		align-items: center;
		gap: var(--lq-space-3);
		padding: var(--lq-space-3) var(--lq-space-4);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		background: var(--lq-canvas);
		text-decoration: none;
		color: var(--lq-text);
		font-size: 14px;
		transition: border-color 0.15s ease, background 0.1s ease;
	}

	.lq-github-link:hover {
		border-color: var(--lq-accent);
		background: var(--lq-inset);
	}

	.lq-github-link-icon {
		font-size: 18px;
		line-height: 1;
		flex-shrink: 0;
	}

	.lq-github-link div {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.lq-github-link span {
		font-size: 12px;
		color: var(--lq-text-secondary);
	}
</style>
