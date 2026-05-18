<!--
  /lq-ai/learn/how — "How It Works" visualization page.

  Seven interactive playground iframes in narrative order: system map →
  request lifecycle → tier system → skill composition → citation engine →
  anonymization layer → data residency. Each section has: a heading, a
  2-3 sentence framing paragraph, the embedded iframe, and an
  "Open full-screen" link.

  Iframes load the static HTML playgrounds at /learn/playgrounds/*.html
  served directly by the web container from web/static/learn/playgrounds/.

  M2-shipped capabilities (Citation Engine 4-stage cascade, Anonymization
  Layer pre/post middleware) have dedicated playgrounds inline. The honest
  validation posture on the Anonymization Layer surfaces in-page and links
  to docs/security/anonymization.md.
-->

<main class="lq-learn-how-page" data-testid="lq-ai-learn-how-page">
	<header class="lq-page-header">
		<a href="/lq-ai/learn" class="lq-back-link">← Learn</a>
		<h1 class="lq-text-page-h">How It Works</h1>
		<p class="lq-text-body lq-page-intro">
			Seven interactive surfaces. Together they tell the story of how LQ.AI works from request to
			response. Each playground links to the source files that implement what it shows — if a
			visualization makes a claim, the linked file is where you verify it.
		</p>
	</header>

	<div class="lq-how-sections">
		<!-- 1: System Architecture -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-architecture">
			<h2 class="lq-section-h">1. The big picture: System Architecture</h2>
			<p class="lq-text-body">
				LQ.AI is three services: the FastAPI backend (<code>api/</code>), the Inference Gateway (<code
					>gateway/</code
				>), and the SvelteKit web frontend (<code>web/</code>). They communicate over HTTP using
				OpenAPI-defined contracts; no service shares in-process code with another. The Gateway is
				the security boundary — the only component that holds provider API keys and makes outbound
				inference calls. This map shows the service topology, the network boundaries, and the trust
				model.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/system-architecture.html"
					title="System Architecture Map"
					loading="lazy"
					data-testid="learn-playground-system-architecture"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/system-architecture.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/docs/architecture.md"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">docs/architecture.md</a
					>
				</span>
			</div>
		</section>

		<p class="lq-transition lq-text-body">
			Every interaction starts at the frontend and travels through the backend to the Gateway. The
			next playground traces that path step by step.
		</p>

		<!-- 2: Request Lifecycle -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-lifecycle">
			<h2 class="lq-section-h">2. A request, end to end: Lifecycle of a chat send</h2>
			<p class="lq-text-body">
				When you press Enter in the composer, the message travels through at least six distinct
				processing stages before the model sees it — and through three more before the response
				reaches your screen. Each stage can add context (skill prompt, KB chunks, tier metadata),
				apply a policy check, or produce an audit record. This playground walks the full path so you
				can see where each transformation happens and which file implements it.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/request-lifecycle.html"
					title="Request Lifecycle — Lifecycle of a chat send"
					loading="lazy"
					data-testid="learn-playground-request-lifecycle"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/request-lifecycle.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/chats.py"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">api/app/api/chats.py</a
					>;
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/gateway/app/router.py"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">gateway/app/router.py</a
					>
				</span>
			</div>
		</section>

		<p class="lq-transition lq-text-body">
			One of the Gateway's most consequential processing steps is tier enforcement — deciding
			whether the requested provider is permitted for the matter's sensitivity level. The next
			playground makes that decision legible.
		</p>

		<!-- 3: Tier System -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-tier">
			<h2 class="lq-section-h">3. The tier system: when the Gateway says no</h2>
			<p class="lq-text-body">
				The Gateway enforces five data-sensitivity tiers (Tier 1 = local / air-gapped, most secure;
				Tier 5 = consumer, least secure). When a request arrives, the Gateway compares the requested
				provider's tier against the matter's configured floor. A floor of Tier N means "require Tier
				N or stronger" — if the provider's tier is weaker (higher-numbered) than the floor, the
				request is refused with a structured error, not a generic 500. This playground lets you set
				a matter context and a model alias and see whether the request would pass or be refused —
				the same logic the Gateway runs at
				<a
					href="https://github.com/LegalQuants/lq-ai/blob/main/gateway/app/tier_floor.py"
					class="lq-link"
					target="_blank"
					rel="noopener noreferrer">gateway/app/tier_floor.py</a
				>.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/tier-system.html"
					title="Tier System — Tier and refusal explorer"
					loading="lazy"
					data-testid="learn-playground-tier-system"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/tier-system.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/gateway/app/tier_floor.py"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">gateway/app/tier_floor.py</a
					>
				</span>
			</div>
		</section>

		<p class="lq-transition lq-text-body">
			If the tier check passes, the Gateway forwards the request. But what exactly does the model
			receive? The next playground disassembles the assembled prompt so you can see each layer.
		</p>

		<!-- 4: Skill Composition -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-skill-composition">
			<h2 class="lq-section-h">4. What the model actually sees: Skill Composition</h2>
			<p class="lq-text-body">
				When a skill is invoked, the final prompt the model receives is an assembly of layers: the
				skill's system prompt, any input variables resolved against the user's message, reference
				file content, KB chunks retrieved for this specific message, and the conversation history.
				This playground lets you toggle each layer on or off and watch the assembled context update
				in real time. The assembly logic lives at
				<a
					href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/pipeline/"
					class="lq-link"
					target="_blank"
					rel="noopener noreferrer">api/app/pipeline/</a
				>.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/skill-composition.html"
					title="Skill Composition — Assembled prompt explorer"
					loading="lazy"
					data-testid="learn-playground-skill-composition"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/skill-composition.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/pipeline/"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">api/app/pipeline/</a
					>
				</span>
			</div>
		</section>

		<p class="lq-transition lq-text-body">
			Once the model responds, the chat surface renders the output — but every citation the model
			emits has to be verified against the source before it counts. The next playground walks the
			4-stage cascade that decides which citations show up as verified, which show up as "verified
			with caveats," and which surface as unverified.
		</p>

		<!-- 5: Citation Engine 4-stage cascade -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-citation-engine">
			<h2 class="lq-section-h">5. Verifying what the model said: Citation Engine cascade</h2>
			<p class="lq-text-body">
				Every <code>"&lt;quote&gt;" (Source: [N])</code> the model emits runs through a four-stage
				verification cascade: exact match → tolerant match → paraphrase judge → optional ensemble.
				The first stage to verify wins; failures cascade. A citation that misses every stage is not
				persisted — its absence is the "unverified" signal the M2-C2 UI consumes. This playground
				lets you pick or craft a (source, quote) pair and watch which stage verifies, what the
				persisted <code>verification_method</code> would be, and how the chat surface would render it.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/citation-engine-cascade.html"
					title="Citation Engine — 4-stage cascade"
					loading="lazy"
					data-testid="learn-playground-citation-engine-cascade"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/citation-engine-cascade.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/citation/verification.py"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">api/app/citation/verification.py</a
					>;
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/docs/citation-engine.md"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">docs/citation-engine.md</a
					>
				</span>
			</div>
		</section>

		<p class="lq-transition lq-text-body">
			The Citation Engine answers "did the model quote the source faithfully" — but a parallel
			question is "what did the model see in the first place?" The Anonymization Layer pseudonymizes
			sensitive entities before any chat content leaves the gateway and rehydrates pseudonyms on the
			return path. The next playground shows the full pipeline.
		</p>

		<!-- 6: Anonymization Layer pre/post middleware -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-anonymization">
			<h2 class="lq-section-h">6. Confidentiality: Anonymization Layer pre/post</h2>
			<p class="lq-text-body">
				The gateway's Anonymization Layer (M2-B3) is pre/post middleware that pseudonymizes detected
				entities (PERSON, ORGANIZATION, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION, US_BANK_NUMBER +
				custom CASE_NUMBER and MATTER_NUMBER) before requests leave for the model provider, and
				rehydrates the pseudonyms on the response. The per-request PseudonymMapper lives in process
				memory only — never persisted, never logged, dropped on function exit. Privileged-project
				chats skip the layer entirely; retrieval-context system messages skip via <code
					>lq_ai_skip_anonymization</code
				> so source quotes reach the model intact for citation grounding. This playground walks the full
				pipeline with toggles for both skip behaviors.
			</p>
			<p class="lq-text-body" style="font-size: 13px; color: var(--lq-text-secondary);">
				<strong>Honest validation posture:</strong> the custom recognizers and middleware
				integration are tested; Presidio default-recognizer recall/precision on legal-document
				corpus specifically is empirically unmeasured —
				<a
					href="https://github.com/LegalQuants/lq-ai/blob/main/docs/security/anonymization.md#whats-validated-vs-whats-unvalidated"
					class="lq-link"
					target="_blank"
					rel="noopener noreferrer"
					>docs/security/anonymization.md §"What's validated vs unvalidated"</a
				>
				for the risk framing and route-to-Tier-1 guidance.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/anonymization-layer.html"
					title="Anonymization Layer — pre/post middleware"
					loading="lazy"
					data-testid="learn-playground-anonymization-layer"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/anonymization-layer.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/gateway/app/anonymization/"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">gateway/app/anonymization/</a
					>;
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/docs/security/anonymization.md"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">docs/security/anonymization.md</a
					>
				</span>
			</div>
		</section>

		<p class="lq-transition lq-text-body">
			Understanding what the model receives answers the "what" — but procurement and security teams
			also need to know where that data is stored and whether it ever leaves the operator's
			environment. The final playground addresses that directly.
		</p>

		<!-- 7: Data Residency -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-data-residency">
			<h2 class="lq-section-h">7. Where your data lives: Data Residency</h2>
			<p class="lq-text-body">
				LQ.AI is self-hosted. By default, all conversation data, knowledge base content, and skill
				definitions stay within the operator's deployment — they never touch LegalQuants
				infrastructure. The only outbound path is the inference call from the Gateway to the chosen
				provider, and only when the matter's tier floor permits it. This map shows every data store,
				every outbound boundary, and which tiers cross each boundary. The Anonymization Layer
				middleware (M2-shipped — see playground 6 above) is one of the controls that crosses this
				surface; this map shows where its pre/post substitution sits relative to every storage and
				egress point in the system.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/data-residency.html"
					title="Data Residency — Where data lives"
					loading="lazy"
					data-testid="learn-playground-data-residency"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/data-residency.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/docs/architecture.md"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">docs/architecture.md</a
					>;
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/gateway/app/router.py"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">gateway/app/router.py</a
					>
				</span>
			</div>
		</section>
	</div>

	<footer class="lq-how-footer">
		<p class="lq-text-body">
			<a href="/lq-ai/learn/build" class="lq-link">Ready to contribute?</a>
			— The build page explains how to contribute a skill, a mini-PRD, or a bug fix.
		</p>
		<p class="lq-text-body">
			Want the architect's view? Read
			<a
				href="https://github.com/LegalQuants/lq-ai/blob/main/docs/architecture.md"
				class="lq-link"
				target="_blank"
				rel="noopener noreferrer">docs/architecture.md</a
			>
			with its Mermaid diagram.
		</p>
	</footer>
</main>

<style>
	.lq-learn-how-page {
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
		max-width: 68ch;
		line-height: 1.6;
	}

	.lq-how-sections {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-8);
	}

	.lq-how-section {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
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

	.lq-transition {
		color: var(--lq-text-secondary);
		font-style: italic;
		padding: var(--lq-space-4) 0;
		border-top: 1px dashed var(--lq-border);
		border-bottom: 1px dashed var(--lq-border);
		margin: 0;
	}

	.lq-link {
		color: var(--lq-accent);
		text-decoration: underline;
	}

	.lq-link:hover {
		opacity: 0.8;
	}

	code {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-sm);
		padding: 1px 5px;
		font-size: 12px;
		font-family: monospace;
	}

	.lq-playground-wrap {
		border-radius: var(--lq-radius-lg);
		overflow: hidden;
	}

	.lq-playground-foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--lq-space-3);
		flex-wrap: wrap;
	}

	.lq-fullscreen-link {
		font-size: 13px;
		font-weight: 500;
	}

	.lq-source-ref {
		font-size: 12px;
		color: var(--lq-text-tertiary);
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
