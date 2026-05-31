<!--
  /lq-ai/learn/how — "How It Works" visualization page.

  Sixteen interactive playground iframes in narrative order: system map →
  request lifecycle → tier system → skill composition → citation engine →
  anonymization layer → data residency → playbook cascade → tabular review →
  word add-in flow → observability trace → autonomous flow → autonomous
  primitives → KB hybrid retrieval → projects/org tiers → intake bridges. Each
  section has: a heading, a 2-3 sentence framing paragraph, the embedded iframe,
  and an "Open full-screen" link.

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
			Sixteen interactive surfaces. Together they tell the story of how LQ.AI works from request to
			response — the engine, its boundaries, the M3 capability surfaces built on top, and the
			observability trace that ties them together. Each playground links to the source files that
			implement what it shows — if a visualization makes a claim, the linked file is where you verify it.
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
			environment. The next playground addresses that directly.
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
		<p class="lq-transition lq-text-body">
			The seven playgrounds above trace the engine and its boundaries. The final three demonstrate the
			M3 capability surfaces — Playbooks, Tabular Review, and the Word add-in — built on that engine.
		</p>

		<!-- 8: Playbook execution cascade -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-playbook-cascade">
			<h2 class="lq-section-h">8. Reviewing a contract: the Playbook execution cascade</h2>
			<p class="lq-text-body">
				A Playbook codifies an organization's standard positions on common contract issues. Applying
				one runs a four-node LangGraph cascade — retrieve → classify → redline → compile — that walks
				each position, extracts the matching clause, classifies it against the standard, and drafts a
				redline where it deviates. This playground steps through that cascade position-by-position
				against synthetic NDAs. The per-position references are the verbatim matched clause text
				(lexical FTS), not the M2 Citation Engine verification cascade — that integration is deferred.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/playbook-cascade.html"
					title="Playbook executor — 4-node cascade"
					loading="lazy"
					data-testid="learn-playground-playbook-cascade"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/playbook-cascade.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/playbooks/nodes.py"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">api/app/playbooks/nodes.py</a
					>;
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/docs/playbooks.md"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">docs/playbooks.md</a
					>
				</span>
			</div>
		</section>

		<p class="lq-transition lq-text-body">
			A Playbook reviews one contract against many positions. Tabular Review inverts that — many
			contracts against a few questions, in a grid.
		</p>

		<!-- 9: Tabular Review grid -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-tabular-review">
			<h2 class="lq-section-h">9. Comparing many contracts: the Tabular Review grid</h2>
			<p class="lq-text-body">
				Tabular Review extracts the same set of questions across a set of documents and lays the
				answers out in a grid — one row per document, one column per question. Each cell is grounded in
				the chunks the model cited; click a cell to open its citation drawer. This playground renders a
				small grid of synthetic NDAs; the citation drawer shows the same fields the real surface does.
				Per-cell citations are display-only chunk references today (a synthetic citation id), not
				Citation-Engine-resolved provenance.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/tabular-review.html"
					title="Tabular Review — grid + cell citation drawer"
					loading="lazy"
					data-testid="learn-playground-tabular-review"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/tabular-review.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/tabular/nodes.py"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">api/app/tabular/nodes.py</a
					>;
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/docs/tabular-review.md"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">docs/tabular-review.md</a
					>
				</span>
			</div>
		</section>

		<p class="lq-transition lq-text-body">
			Playbooks and Tabular Review run in the web app. The Word add-in brings the deployment into the
			operator's editor — the last playground walks its install and auth flow.
		</p>

		<!-- 10: Word add-in install + auth flow -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-word-addin-flow">
			<h2 class="lq-section-h">10. Into the editor: the Word add-in install + auth flow</h2>
			<p class="lq-text-body">
				The Word add-in is an Office.js task pane installed against the operator's own deployment. This
				playground walks the four-stage flow: admin generates a per-deployment manifest, the operator
				sideloads the unsigned manifest via the Microsoft 365 Admin Center (which warns about the
				unsigned add-in — expected at v0.3.0), the task pane completes OAuth against the deployment, and
				the version handshake confirms compatibility. M3 shipped the plumbing only — the in-pane feature
				surface (chat, skills, playbooks) is deferred (DE-287; M4 closed without it — community-friendly), and the signed distribution package is
				community-led.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/word-addin-flow.html"
					title="Word Add-In — install + auth flow"
					loading="lazy"
					data-testid="learn-playground-word-addin-flow"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/word-addin-flow.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/word_addin.py"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">api/app/api/word_addin.py</a
					>;
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/docs/word-addin.md"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">docs/word-addin.md</a
					>
				</span>
			</div>
		</section>

		<p class="lq-transition lq-text-body">
			Every chat-send, playbook run, and tabular extraction emits a distributed trace. The final
			playground makes the full span hierarchy visible — from the HTTP boundary at the api down
			through inference dispatch, anonymization, and citation verification — so operators can answer
			latency, cost, and data-handling questions from a single trace view.
		</p>

		<!-- 11: OTel trace visualizer -->
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-otel-eval">
			<h2 class="lq-section-h">11. Seeing it all at once: the observability trace</h2>
			<p class="lq-text-body">
				Every chat-send is one OpenTelemetry trace spanning api → gateway → provider, with domain
				spans for citation verification, anonymization, skill dispatch, and inference carrying counts
				and types only — never raw entity values, prompt text, or response content. This playground
				lets you toggle the citation path, anonymization state, workflow type, and provider tier to
				see how the span tree changes, and shows which span attribute answers each of the five
				questions an operator is most likely to ask in production.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/otel-eval.html"
					title="OTel trace — chat-send end to end"
					loading="lazy"
					data-testid="learn-playground-otel-eval"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/otel-eval.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/docs/observability.md"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">docs/observability.md</a
					>;
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/observability_helpers.py"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">api/app/observability_helpers.py</a
					>
				</span>
			</div>
		</section>
		<section class="lq-how-section" data-testid="lq-ai-learn-how-section-autonomous-flow">
			<h2 class="lq-section-h">12. Autonomy you can audit: the Autonomous flow</h2>
			<p class="lq-text-body">
				The Autonomous Layer (M4, shipped) runs a single agent on your
				behalf — on a schedule, or when documents arrive — without you watching each step. Because no
				human approves each action, the agent runs through declared phases behind one brake-checked
				chokepoint, and every run produces an auditable receipt. Step through a session below and trip
				each brake yourself.
			</p>
			<div class="lq-playground-wrap">
				<iframe
					src="/learn/playgrounds/autonomous-flow.html"
					title="Autonomous flow — a single agent, fully audited"
					loading="lazy"
					data-testid="learn-playground-autonomous-flow"
					style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
				></iframe>
			</div>
			<div class="lq-playground-foot">
				<a
					href="/learn/playgrounds/autonomous-flow.html"
					class="lq-link lq-fullscreen-link"
					target="_blank"
					rel="noopener noreferrer">Open full-screen ↗</a
				>
				<span class="lq-source-ref">
					Source:
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/docs/LQVern/agentic-flow-alignment-guide.md"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">agentic-flow-alignment-guide.md</a
					>;
					<a
						href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0013-autonomous-layer-design-influences.md"
						class="lq-link"
						target="_blank"
						rel="noopener noreferrer">ADR 0013</a
					>
				</span>
			</div>
		</section>

			<p class="lq-transition lq-text-body">
				The flow above showed a single session start to finish. But what schedules those sessions, what feeds them documents, and what captures what they learn? The next playground breaks the Autonomous Layer into its four primitives.
			</p>

			<!-- 13: autonomous-primitives -->
			<section class="lq-how-section" data-testid="lq-ai-learn-how-section-autonomous-primitives">
				<h2 class="lq-section-h">13. The four autonomous primitives: watches, schedules, memory, precedent</h2>
				<p class="lq-text-body">
					An autonomous session does not run in isolation — it is wired to four primitives that decide when it runs and what it carries across runs. <strong>Watches</strong> trigger a session when matching documents arrive; <strong>schedules</strong> trigger it on a cron-like cadence; <strong>memory</strong> persists what a session learned so later runs build on it; and the <strong>precedent lifecycle</strong> promotes vetted work product into reusable precedent. This playground steps through each primitive and shows how it feeds the session you saw in playground 12. The Autonomous Layer shipped in M4.
				</p>
				<div class="lq-playground-wrap">
					<iframe
						src="/learn/playgrounds/autonomous-primitives.html"
						title="Autonomous primitives — watches, schedules, memory, precedent"
						loading="lazy"
						data-testid="learn-playground-autonomous-primitives"
						style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
					></iframe>
				</div>
				<div class="lq-playground-foot">
					<a
						href="/learn/playgrounds/autonomous-primitives.html"
						class="lq-link lq-fullscreen-link"
						target="_blank"
						rel="noopener noreferrer">Open full-screen ↗</a
					>
					<span class="lq-source-ref">
						Source:
						<a
							href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/autonomous.py"
							class="lq-link"
							target="_blank"
							rel="noopener noreferrer">api/app/api/autonomous.py</a
						>;
						<a
							href="https://github.com/LegalQuants/lq-ai/blob/main/docs/autonomous-layer.md"
							class="lq-link"
							target="_blank"
							rel="noopener noreferrer">docs/autonomous-layer.md</a
						>
					</span>
				</div>
			</section>

			<p class="lq-transition lq-text-body">
				Every one of these surfaces — chat, playbooks, autonomous sessions — leans on the same retrieval foundation: finding the right knowledge-base chunks for a given query. The next playground opens up how that retrieval actually works.
			</p>

			<!-- 14: kb-hybrid-retrieval -->
			<section class="lq-how-section" data-testid="lq-ai-learn-how-section-kb-hybrid-retrieval">
				<h2 class="lq-section-h">14. Finding the right chunks: knowledge-base hybrid retrieval</h2>
				<p class="lq-text-body">
					When a message needs grounding context, LQ.AI does not rely on vector search alone. It runs <strong>hybrid retrieval</strong>: a lexical full-text-search pass (Postgres FTS) and a vector cosine-similarity pass run in parallel, and their results are fused into a single ranked set so that both exact-term matches and semantically-related passages surface. This playground lets you issue a query against synthetic KB chunks and watch the lexical scores, the vector scores, and the fused ranking that the engine ultimately uses. Knowledge-base retrieval shipped in M1.
				</p>
				<div class="lq-playground-wrap">
					<iframe
						src="/learn/playgrounds/kb-hybrid-retrieval.html"
						title="Knowledge-base hybrid retrieval — lexical + vector, fused"
						loading="lazy"
						data-testid="learn-playground-kb-hybrid-retrieval"
						style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
					></iframe>
				</div>
				<div class="lq-playground-foot">
					<a
						href="/learn/playgrounds/kb-hybrid-retrieval.html"
						class="lq-link lq-fullscreen-link"
						target="_blank"
						rel="noopener noreferrer">Open full-screen ↗</a
					>
					<span class="lq-source-ref">
						Source:
						<a
							href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/knowledge/retrieval.py"
							class="lq-link"
							target="_blank"
							rel="noopener noreferrer">api/app/knowledge/retrieval.py</a
						>;
						<a
							href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/knowledge_bases.py"
							class="lq-link"
							target="_blank"
							rel="noopener noreferrer">api/app/api/knowledge_bases.py</a
						>
					</span>
				</div>
			</section>

			<p class="lq-transition lq-text-body">
				Retrieval finds the right chunks, but the chunks are only part of the context. A matter's organization profile, its attachments, and its privilege and tier settings all shape what a request is allowed to do. The next playground shows that context being assembled.
			</p>

			<!-- 15: projects-org-tiers -->
			<section class="lq-how-section" data-testid="lq-ai-learn-how-section-projects-org-tiers">
				<h2 class="lq-section-h">15. The matter's context: projects, org profile, and tier floors</h2>
				<p class="lq-text-body">
					Every request runs inside a matter (a project), and the matter carries the context that shapes it: the organization profile (the house voice and standard positions), the matter's attachments and knowledge bases, and its privilege flag and tier floor. This playground lets you configure a matter and watch how each of those settings flows into the assembled request — including how a privileged matter or a stricter tier floor narrows which providers the Gateway will permit. Projects, organization profiles, and tier floors shipped in M1.
				</p>
				<div class="lq-playground-wrap">
					<iframe
						src="/learn/playgrounds/projects-org-tiers.html"
						title="Projects, org profile, and tier floors — shaping a request"
						loading="lazy"
						data-testid="learn-playground-projects-org-tiers"
						style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
					></iframe>
				</div>
				<div class="lq-playground-foot">
					<a
						href="/learn/playgrounds/projects-org-tiers.html"
						class="lq-link lq-fullscreen-link"
						target="_blank"
						rel="noopener noreferrer">Open full-screen ↗</a
					>
					<span class="lq-source-ref">
						Source:
						<a
							href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/projects.py"
							class="lq-link"
							target="_blank"
							rel="noopener noreferrer">api/app/api/projects.py</a
						>;
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
				Everything so far has been about work already inside LQ.AI. The last playground covers getting work in — the Slack and Teams intake bridges — and is honest about how much of it is verified today.
			</p>

			<!-- 16: intake-bridges -->
			<section class="lq-how-section" data-testid="lq-ai-learn-how-section-intake-bridges">
				<h2 class="lq-section-h">16. Getting work in: the Slack/Teams intake bridges</h2>
				<p class="lq-text-body">
					The intake bridges let an operator connect a Slack workspace or a Microsoft Teams tenant so that requests can flow into LQ.AI from where the business already works. This playground walks the OAuth install flow and the admin lifecycle (list, soft-delete) for a connected bridge.
				</p>
				<p class="lq-text-body" style="font-size: 13px; color: var(--lq-text-secondary);">
					<strong>Honest partial state:</strong> the backend plumbing and admin lifecycle shipped in M3, but the live OAuth install handshake is unverified against real Slack and Teams tenants (<strong>DE-312</strong>), and the inbound <code>/lq</code> command path is inert — it does not yet dispatch a request (<strong>DE-288</strong>). Treat this surface as scaffolding, not a production-ready intake channel.
				</p>
				<div class="lq-playground-wrap">
					<iframe
						src="/learn/playgrounds/intake-bridges.html"
						title="Slack/Teams intake bridges — OAuth install + admin lifecycle"
						loading="lazy"
						data-testid="learn-playground-intake-bridges"
						style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
					></iframe>
				</div>
				<div class="lq-playground-foot">
					<a
						href="/learn/playgrounds/intake-bridges.html"
						class="lq-link lq-fullscreen-link"
						target="_blank"
						rel="noopener noreferrer">Open full-screen ↗</a
					>
					<span class="lq-source-ref">
						Source:
						<a
							href="https://github.com/LegalQuants/lq-ai/blob/main/docs/intake-bridges.md"
							class="lq-link"
							target="_blank"
							rel="noopener noreferrer">docs/intake-bridges.md</a
						>;
						<a
							href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/admin_intake_bridges.py"
							class="lq-link"
							target="_blank"
							rel="noopener noreferrer">api/app/api/admin_intake_bridges.py</a
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
