<!--
  /lq-ai/learn/use — "How to Use" feature tour.

  Sections covering every user-facing capability across M1–M4. Each section has:
  - A heading
  - A plain-language description
  - A <details> foldout linking to the relevant source file paths, E2E
    test, and audit-log action name so a critic can verify the claim.

  File paths link to GitHub: https://github.com/LegalQuants/lq-ai/blob/main/<path>
-->

<main class="lq-learn-use-page" data-testid="lq-ai-learn-use-page">
	<header class="lq-page-header">
		<a href="/lq-ai/learn" class="lq-back-link">← Learn</a>
		<h1 class="lq-text-page-h">How to Use LQ.AI</h1>
		<p class="lq-text-body lq-page-intro">
			A plain-language tour of every user-facing feature across M1–M4. Each section names the
			file paths and test that exercise the behavior described, so you can verify any claim
			against the source. The M4 Autonomous Layer surfaces in the web app as the autonomous
			dashboard (<a href="/lq-ai/autonomous" class="lq-link">Autonomous</a>) plus an opt-in
			toggle in settings (off by default).
		</p>
	</header>

	<div class="lq-use-sections">

		<!-- 1 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-send">
			<h2 class="lq-section-h">1. Send a message</h2>
			<p class="lq-text-body">
				Type or paste into the composer and press Enter (or Shift+Enter for a newline).
				Every reply is appended to the same conversation thread; you can scroll up to see
				the full history. Conversations are persisted server-side and retrievable via
				<a href="/lq-ai/chats" class="lq-link">Chats</a>. Multi-turn context is preserved
				across browser sessions.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/chats.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/chats.py</a>
						— chat CRUD and message persistence.
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/chat.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/chat.cy.ts</a>
					</p>
					<p><strong>Audit action:</strong> <code>chat.message.send</code></p>
				</div>
			</details>
		</section>

		<!-- 2 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-skill-invoke">
			<h2 class="lq-section-h">2. Use a built-in skill</h2>
			<p class="lq-text-body">
				In the composer, type <code>/</code> followed by a skill alias (for example
				<code>/nda-review</code>). A picker appears showing matching skills; select one and
				press Enter. The skill's system prompt, input schema, and reference files are
				assembled and sent to the model — the full assembled prompt is visible in the
				receipts drawer. Ten starter skills ship with M1:
				NDA Review, MSA Review — SaaS, MSA Review — Commercial Purchase,
				DPA Checklist Review, Vendor Privacy Policy First Pass, Contract QA,
				Action Items from Client Alert, Comms Improver, Enhance Prompt (an optional
					prompt-rewriting pre-step), and Skill Creator (a meta-skill for building new skills).
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/src/lib/lq-ai/components/SkillComposerPicker.svelte" class="lq-link" target="_blank" rel="noopener noreferrer">web/src/lib/lq-ai/components/SkillComposerPicker.svelte</a>
						— slash picker UI.
					</p>
					<p><strong>Skills corpus:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/skills/" class="lq-link" target="_blank" rel="noopener noreferrer">skills/</a>
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/wave-d2-skill-creator.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/wave-d2-skill-creator.cy.ts</a>
						Test 4
					</p>
					<p><strong>Audit action:</strong> <code>skill.invoked</code></p>
				</div>
			</details>
		</section>

		<!-- 3 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-capture">
			<h2 class="lq-section-h">3. Capture a chat reply as a skill</h2>
			<p class="lq-text-body">
				Under any assistant message, a <strong>📝 Capture</strong> button opens the Skill
				Wizard with the reply pre-filled as the seed content. You give it a name, add input
				variables or examples if needed, and save. The new skill is immediately available
				via <code>/</code> in the composer and visible in <a href="/lq-ai/skills" class="lq-link">Skills</a>.
				This is the fastest path from "that response was useful" to "I can reproduce it on
				demand."
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/src/lib/lq-ai/components/SkillWizard.svelte" class="lq-link" target="_blank" rel="noopener noreferrer">web/src/lib/lq-ai/components/SkillWizard.svelte</a>
						— wizard component (pre-fill path).
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/wave-d2-skill-creator.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/wave-d2-skill-creator.cy.ts</a>
						Test 1
					</p>
					<p><strong>Audit action:</strong> <code>skill.created</code></p>
				</div>
			</details>
		</section>

		<!-- 4 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-fork">
			<h2 class="lq-section-h">4. Fork a built-in skill</h2>
			<p class="lq-text-body">
				On any skill detail page, <strong>Fork as my own</strong> creates a personal copy
				under your account. You can edit the system prompt, swap reference files, change the
				input schema, or rename the alias without affecting the canonical version. Forked
				skills version independently from the original.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/user_skills.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/user_skills.py</a>
						— fork endpoint.
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/wave-d2-skill-creator.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/wave-d2-skill-creator.cy.ts</a>
						Test 3
					</p>
					<p><strong>Audit action:</strong> <code>skill.forked</code></p>
				</div>
			</details>
		</section>

		<!-- 5 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-wizard">
			<h2 class="lq-section-h">5. Author a skill from scratch</h2>
			<p class="lq-text-body">
				Navigate to <a href="/lq-ai/skills" class="lq-link">Skills</a> and press
				<strong>+ New skill</strong>. The Skill Wizard walks through: name + alias, system
				prompt, input variables, reference files, and at least one worked example. The
				wizard validates structure against the SKILL.md schema before saving. The finished
				skill is stored as a SKILL.md-formatted record in the database and is immediately
				available via slash invocation.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/src/lib/lq-ai/components/SkillWizard.svelte" class="lq-link" target="_blank" rel="noopener noreferrer">web/src/lib/lq-ai/components/SkillWizard.svelte</a>
					</p>
					<p><strong>Schema spec:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/skill-authoring-guide.md" class="lq-link" target="_blank" rel="noopener noreferrer">docs/skill-authoring-guide.md</a>
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/wave-d2-skill-creator.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/wave-d2-skill-creator.cy.ts</a>
						Test 2
					</p>
					<p><strong>Audit action:</strong> <code>skill.created</code></p>
				</div>
			</details>
		</section>

		<!-- 6 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-kb">
			<h2 class="lq-section-h">6. Attach a knowledge base to a chat</h2>
			<p class="lq-text-body">
				In the composer, press the <strong>📎</strong> button to open the KB attach modal.
				Select one or more knowledge bases from the list. Once attached, each message in
				that conversation retrieves relevant chunks from the KB via hybrid retrieval (vector
				similarity + full-text search) and appends them to the model context. You can also
				attach KBs at the matter level so they are automatically available in all chats
				under that matter.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/knowledge_bases.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/knowledge_bases.py</a>;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/pipeline/ingest.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/pipeline/ingest.py</a>
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/wave-d1-power-features.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/wave-d1-power-features.cy.ts</a>
						Test 2
					</p>
					<p><strong>Audit action:</strong> <code>kb.attached</code></p>
				</div>
			</details>
		</section>

		<!-- 7 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-saved-prompts">
			<h2 class="lq-section-h">7. Use a saved prompt</h2>
			<p class="lq-text-body">
				<a href="/lq-ai/saved-prompts" class="lq-link">Saved Prompts</a> is a personal
				library of reusable prompt fragments — shorter than a full skill, longer than typing
				the same thing every time. Press <strong>Use in chat</strong> on any saved prompt to
				pre-populate the composer with its text. You can also insert from the saved-prompts
				side panel inside any chat. Prompt text is carried via sessionStorage, not a URL
				parameter, so it stays out of server logs and browser history.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/saved_prompts.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/saved_prompts.py</a>;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/src/routes/lq-ai/saved-prompts/+page.svelte" class="lq-link" target="_blank" rel="noopener noreferrer">web/src/routes/lq-ai/saved-prompts/+page.svelte</a>
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/wave-m1-final-surfaces.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/wave-m1-final-surfaces.cy.ts</a>
						Test 1
					</p>
					<p><strong>Audit action:</strong> <code>saved_prompt.used</code></p>
				</div>
			</details>
		</section>

		<!-- 8 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-receipts">
			<h2 class="lq-section-h">8. Read receipts</h2>
			<p class="lq-text-body">
				Every model response has a provenance record. Press the <strong>📜</strong> button
				in the composer toolbar to open the receipts drawer. Each receipt entry shows: the
				request timestamp, the model and provider used, the tier in effect, the full
				assembled prompt (including any skill system prompt and KB chunks), and — when a
				skill was invoked — "via slash command /&lt;alias&gt;". Receipts are read-only audit
				artifacts; they cannot be edited or deleted through the UI.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/chat_receipts.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/chat_receipts.py</a>
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/wave-d1-power-features.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/wave-d1-power-features.cy.ts</a>
						Test 4;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/wave-m1-final-surfaces.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">wave-m1-final-surfaces.cy.ts</a>
						Test 3
					</p>
					<p><strong>Audit action:</strong> <code>receipt.viewed</code></p>
				</div>
			</details>
		</section>

		<!-- 9 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-tier">
			<h2 class="lq-section-h">9. Privileged matter + admin override</h2>
			<p class="lq-text-body">
				When a matter is flagged as privileged, the Inference Gateway enforces a tier floor.
				Requests below that floor are refused with a clear explanation — not a generic error.
				Admins can issue a just-in-time override for a specific session; the override is
				logged as an admin action and visible in the audit log. The tier system has five
				levels (Tiers 1–5); Tier 1 is a local Ollama model that never makes an outbound
				call.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/gateway/app/tier_floor.py" class="lq-link" target="_blank" rel="noopener noreferrer">gateway/app/tier_floor.py</a>
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/wave-d1-power-features.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/wave-d1-power-features.cy.ts</a>
						Test 3 + Test 5
					</p>
					<p><strong>Audit action:</strong> <code>inference.tier_floor_overridden</code></p>
				</div>
			</details>
		</section>

		<!-- 10 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-gdpr">
			<h2 class="lq-section-h">10. Export your data / delete your account</h2>
			<p class="lq-text-body">
				GDPR-aligned export and deletion are runnable today. From Settings, request a
				data export — the backend packages your chat history, skills, saved prompts, and
				knowledge base metadata as a JSON archive and delivers it as a download. Account
				deletion removes your data from the primary database; the deletion job runs
				asynchronously and produces an audit record confirming completion.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/workers/user_export.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/workers/user_export.py</a>;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/workers/user_deletion.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/workers/user_deletion.py</a>;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/users.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/users.py</a>
					</p>
					<p><strong>Audit action:</strong> <code>user.export.requested</code>, <code>user.deleted</code></p>
				</div>
			</details>
		</section>

		<!-- 11 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-citations">
			<h2 class="lq-section-h">11. Read verified citations</h2>
			<p class="lq-text-body">
				When a model reply quotes a source in the form <code>"&lt;quote&gt;" (Source: [N])</code>,
				the Citation Engine verifies each quote against the cited source before it counts. Verified
				quotes render as a green chip in the chat message; quotes the model emitted but that could
				not be matched render as a grey <code>[unverified]</code> chip. There are four chip states —
				verified by exact match, verified by tolerant match, verified by paraphrase judge, and
				unverified — so you see not just whether a citation checked out but how strong the match was.
				Click a verified chip to jump to the matched span in the source.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/citation/verification.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/citation/verification.py</a>
						— four-stage cascade;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/src/lib/lq-ai/components/M2Citations.svelte" class="lq-link" target="_blank" rel="noopener noreferrer">web/src/lib/lq-ai/components/M2Citations.svelte</a>
						— chip rendering.
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/m2-c2-citation-states.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/m2-c2-citation-states.cy.ts</a>
					</p>
				</div>
			</details>
		</section>

		<!-- 12 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-playbooks">
			<h2 class="lq-section-h">12. Run a playbook against a document</h2>
			<p class="lq-text-body">
				A playbook codifies your organization's standard positions on common contract issues. From
				<a href="/lq-ai/playbooks" class="lq-link">Playbooks</a>, pick a playbook, choose the document
				to review, preview the cost, and run it. Execution walks each position through a four-node
				cascade — retrieve the matching clause, classify it against your standard, draft a redline
				where it deviates, and compile the result. Each position lands on one of four verdicts so you
				can triage at a glance. Completed runs are saved and re-openable from
				<a href="/lq-ai/playbook-executions" class="lq-link">playbook executions</a>.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/playbooks/nodes.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/playbooks/nodes.py</a>
						— cascade nodes;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/playbooks.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/playbooks.py</a>
						— endpoints.
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/m3-a4-playbook-execution.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/m3-a4-playbook-execution.cy.ts</a>
					</p>
					<p><strong>Audit action:</strong> <code>playbook.created</code>, <code>playbook.updated</code>, <code>playbook.deleted</code></p>
				</div>
			</details>
		</section>

		<!-- 13 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-tabular">
			<h2 class="lq-section-h">13. Compare many documents in a grid</h2>
			<p class="lq-text-body">
				Tabular Review asks the same set of questions across a set of documents and lays the answers
				out in a grid — one row per document, one column per question. From
				<a href="/lq-ai/tabular" class="lq-link">Tabular Review</a>, a four-step wizard collects the
				documents, the questions, and a cost preview, then runs the extraction. Each cell is grounded
				in the chunks the model cited; click a cell to open its citation drawer. Finished grids export
				to XLSX or CSV.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/tabular/nodes.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/tabular/nodes.py</a>
						— extraction nodes;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/tabular.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/tabular.py</a>
						— endpoints + export.
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/m3-c-tabular-review.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/m3-c-tabular-review.cy.ts</a>
					</p>
					<p><strong>Audit action:</strong> <code>tabular.execution_started</code>, <code>tabular.execution_exported</code></p>
				</div>
			</details>
		</section>

		<!-- 14 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-word-addin">
			<h2 class="lq-section-h">14. Word add-in (plumbing only at v0.3.0)</h2>
			<p class="lq-text-body">
				The Microsoft Word add-in is an Office.js task pane that installs against your own deployment.
				At v0.3.0, only the plumbing has shipped: an admin generates a per-deployment manifest, the
				operator sideloads the unsigned manifest (Microsoft 365 warns about the unsigned package —
				expected), the pane completes OAuth against the deployment, and a version handshake confirms
				compatibility. The in-pane feature surface — chat, skills, playbooks — is deferred (DE-287),
				and a signed distribution package is community-led (DE-295). We call this out plainly rather
				than implying the editor experience is finished.
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/word_addin.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/word_addin.py</a>;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/word-addin.md" class="lq-link" target="_blank" rel="noopener noreferrer">docs/word-addin.md</a>
					</p>
					<p><strong>E2E test:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/web/cypress/e2e/m3-b2-word-addin-oauth.cy.ts" class="lq-link" target="_blank" rel="noopener noreferrer">web/cypress/e2e/m3-b2-word-addin-oauth.cy.ts</a>
					</p>
				</div>
			</details>
		</section>

		<!-- 15 -->
		<section class="lq-use-section" data-testid="lq-ai-learn-use-section-intake-bridges">
			<h2 class="lq-section-h">15. Intake bridges: Slack + Teams (admin)</h2>
			<p class="lq-text-body">
				Intake bridges let a legal team take in requests from Slack and Microsoft Teams. This is an
				admin-facing surface: from <a href="/lq-ai/admin/intake-bridges" class="lq-link">Admin →
				Intake bridges</a>, an administrator connects a workspace over OAuth, lists the configured
				bridges, and soft-deletes ones that are no longer needed. The bridge services run as separate
				deployments. Honest state: the admin shell and backend persistence have shipped; end-to-end
				OAuth against live Slack and Teams workspaces is not yet validated in CI (DE-312).
			</p>
			<details class="lq-verify">
				<summary class="lq-verify-summary">Dig deeper / verify</summary>
				<div class="lq-verify-body">
					<p><strong>Source:</strong>
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/api/admin_intake_bridges.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/api/admin_intake_bridges.py</a>;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/slack-bridge/" class="lq-link" target="_blank" rel="noopener noreferrer">slack-bridge/</a>;
						<a href="https://github.com/LegalQuants/lq-ai/blob/main/teams-bridge/" class="lq-link" target="_blank" rel="noopener noreferrer">teams-bridge/</a>
					</p>
				</div>
			</details>
		</section>

	</div>

	<footer class="lq-use-footer">
		<p class="lq-text-body">
			<a href="/lq-ai/learn/how" class="lq-link">Want to see how this all fits together?</a>
			— Twelve interactive playgrounds that show the system from request to response.
		</p>
		<p class="lq-text-body">
			For the full shipped/deferred capability catalog, read
			<a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/HONEST-STATE.md" class="lq-link" target="_blank" rel="noopener noreferrer">docs/HONEST-STATE.md</a>.
		</p>
	</footer>
</main>

<style>
	.lq-learn-use-page {
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

	.lq-use-sections {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.lq-use-section {
		padding: var(--lq-space-6) 0;
		border-bottom: 1px solid var(--lq-border);
	}

	.lq-use-section:last-child {
		border-bottom: none;
	}

	.lq-section-h {
		font-size: 16px;
		font-weight: 600;
		color: var(--lq-text);
		margin: 0 0 var(--lq-space-3) 0;
	}

	.lq-text-body {
		margin: 0 0 var(--lq-space-3) 0;
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

	code {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-sm);
		padding: 1px 5px;
		font-size: 12px;
		font-family: monospace;
	}

	.lq-verify {
		margin-top: var(--lq-space-3);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		overflow: hidden;
	}

	.lq-verify-summary {
		padding: var(--lq-space-2) var(--lq-space-3);
		cursor: pointer;
		font-size: 12px;
		font-weight: 500;
		color: var(--lq-text-secondary);
		background: var(--lq-inset);
		list-style: none;
		user-select: none;
	}

	.lq-verify-summary::-webkit-details-marker {
		display: none;
	}

	.lq-verify-summary::before {
		content: '▶ ';
		font-size: 10px;
	}

	details[open] .lq-verify-summary::before {
		content: '▼ ';
	}

	.lq-verify-summary:hover {
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
	}

	.lq-verify-body {
		padding: var(--lq-space-3);
		background: var(--lq-canvas);
		border-top: 1px solid var(--lq-border);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.lq-verify-body p {
		margin: 0;
		font-size: 13px;
		color: var(--lq-text-secondary);
		line-height: 1.5;
	}

	.lq-use-footer {
		padding: var(--lq-space-6) 0;
		border-top: 1px solid var(--lq-border);
		margin-top: var(--lq-space-4);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.lq-use-footer .lq-text-body {
		color: var(--lq-text-secondary);
	}
</style>
