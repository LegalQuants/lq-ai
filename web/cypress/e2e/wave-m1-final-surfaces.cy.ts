/**
 * Wave M1-final — Saved Prompts + Knowledge + Receipts source (Wave 8 T6).
 *
 * Three independent-surface e2e tests for surfaces that landed AFTER the
 * wave-d2 plan was written. They live in a sibling spec rather than
 * wave-d2-skill-creator.cy.ts to keep that file under the 600-700 line
 * threshold flagged by the Task 8.4 code reviewer.
 *
 *   1. Saved Prompt round-trip — create → Use in chat → composer prefilled → send
 *   2. Knowledge — create KB → upload PDF → doc row present (processing/pending/ready)
 *   3. Receipts source — send via slash → receipts drawer shows "via slash command"
 *
 * Run requires a live stack:
 *   docker compose up -d
 *   docker compose exec api python -m app.cli reset-admin-password \
 *     --email admin@lq.ai --password 'LQ-AI-smoke-test-Pw1!' --no-force-change
 *   cd web && npx cypress run --spec 'cypress/e2e/wave-m1-final-surfaces.cy.ts'
 */

/// <reference types="cypress" />

import { login, createSampleMatter, getBearerToken } from '../support/lq-ai-helpers';

const ADMIN_EMAIL = () => Cypress.env('LQAI_ADMIN_EMAIL') || 'admin@lq.ai';
const ADMIN_PASSWORD = () => Cypress.env('LQAI_ADMIN_PASSWORD') || 'LQ-AI-smoke-test-Pw1!';
/** Direct API base — bypasses the SvelteKit web container. */
const API_BASE = () => Cypress.env('LQAI_API_BASE') ?? 'http://localhost:8000';

describe('Wave M1-final — Saved Prompts + Knowledge + Receipts source', () => {
	beforeEach(() => {
		login(ADMIN_EMAIL(), ADMIN_PASSWORD());
	});

	it('Saved Prompt round-trip: create → Use in chat → composer prefilled → send', () => {
		const ts = Date.now();
		const promptName = `M1 Final Test Prompt ${ts}`;
		const promptText = `Summarize the key obligations in this agreement. Timestamp: ${ts}`;

		// ── Create a matter + chat first so activeChatStore is set ───────────
		// The composer on /lq-ai/chats is gated on `{#if activeChat}` in
		// ChatPanel.svelte. The Svelte store persists across SPA navigation, so
		// a prior active chat from the matter workspace stays set when we land
		// on /lq-ai/chats after clicking "Use in chat". Without this step,
		// activeChatStore is null and the composer never mounts.
		// Critically: we use SPA navigation (the left sidebar's "Saved prompts"
		// row) rather than cy.visit() so Svelte stores are NOT reset by a hard
		// reload. cy.visit() resets all module-level Svelte stores including
		// activeChatStore.
		createSampleMatter('Saved Prompt Test Matter');

		// ── Navigate to saved-prompts via the left sidebar (SPA navigation) ──
		// The sidebar's rows are links, so a click is a client-side navigation
		// that preserves Svelte store state. A matter page starts with the
		// sidebar collapsed to its strip, so open it first; "Saved prompts" sits
		// in the Customise group (nav.ts), which opens on click.
		cy.get('[data-testid="lq-shell-sidebar-open"]').click();
		cy.get('[data-testid="lq-shell-sidebar"] button[data-nav-id="customise"]').click();
		cy.get('[data-testid="lq-shell-sidebar"] a[data-nav-id="saved-prompts"]')
			.should('contain.text', 'Saved prompts')
			.click();
		cy.url({ timeout: 10000 }).should('include', '/lq-ai/saved-prompts');
		cy.get('[data-testid="lq-ai-saved-prompts-page"]').should('exist');

		// ── Create a new saved prompt ─────────────────────────────────────────
		cy.get('[data-testid="lq-ai-saved-prompts-new"]').click();
		cy.get('[data-testid="lq-ai-saved-prompt-editor"]').should('exist');
		cy.get('[data-testid="lq-ai-saved-prompt-name"]').type(promptName);
		cy.get('[data-testid="lq-ai-saved-prompt-text"]').type(promptText);

		// Intercept BEFORE the save click.
		cy.intercept('POST', '/api/v1/saved-prompts').as('createPrompt');
		cy.get('[data-testid="lq-ai-saved-prompt-save"]').click();
		cy.wait('@createPrompt').then((interception) => {
			expect(interception.response?.statusCode).to.eq(201);
		});

		// ── The new prompt row renders; find the "Use in chat" button ─────────
		// SavedPromptsPanel renders each prompt row with data-testid
		// `lq-ai-saved-prompt-{id}`, and the insert button within each row
		// uses data-testid `lq-ai-saved-prompt-insert-{id}`. The insertLabel
		// prop is "Use in chat" on the standalone page (set by +page.svelte).
		// We find the row by name text then click the insert button inside it.
		cy.contains('[data-testid^="lq-ai-saved-prompt-"]', promptName, { timeout: 10000 })
			.find('[data-testid^="lq-ai-saved-prompt-insert-"]')
			.first()
			.click();

		// ── Verify navigation to /lq-ai/chats ────────────────────────────────
		// +page.svelte calls goto('/lq-ai/chats') after stashing the text in
		// sessionStorage under 'lq-ai:composer-prefill'.
		cy.url({ timeout: 15000 }).should('include', '/lq-ai/chats');

		// ── Verify the composer is prefilled ─────────────────────────────────
		// ChatPanel reads sessionStorage['lq-ai:composer-prefill'] on mount
		// and populates lq-ai-composer-input, then clears the key.
		// The chat shell uses `overflow: hidden` on the message container,
		// which can cause Cypress to report the composer as not "visible" even
		// when it is accessible and filled. Assert on value only (not
		// visibility) to avoid a layout-clipping false-negative.
		cy.get('[data-testid="lq-ai-composer-input"]', { timeout: 15000 }).should(
			'have.value',
			promptText
		);

		// ── Send the message and verify the request body ─────────────────────
		// Intercept BEFORE click. Use `force: true` to bypass the overflow
		// clipping that can make the button appear non-interactable to Cypress
		// even though it is in a scrollable container the user can reach.
		cy.intercept('POST', '**/messages').as('sendMessage');
		cy.get('[data-testid="lq-ai-send-btn"]').click({ force: true });

		// 60s timeout: real LLM round-trip. Assert request body contains the
		// prompt text. We do not block on the streamed reply.
		cy.wait('@sendMessage', { timeout: 60000 }).then((interception) => {
			const body = interception.request.body as { content?: string };
			expect(body.content ?? '').to.include(String(ts));
		});

		// Wait for assistant reply to confirm the round-trip completes.
		// MessageBubble renders each message with data-testid="lq-ai-message-{id}".
		// The message list has data-testid="lq-ai-message-list". Assert at least
		// 2 message divs (user + assistant). Use an attribute-prefix selector.
		cy.get('[data-testid="lq-ai-message-list"] [data-testid^="lq-ai-message-"]', {
			timeout: 60000
		}).should('have.length.gte', 2);
	});

	it('Knowledge: create KB → upload PDF → ingest reaches ready status', () => {
		const ts = Date.now();
		const kbName = `M1 KB Test ${ts}`;
		const kbDesc = `Cypress fixture KB created at ${ts}`;

		// ── Navigate to knowledge list page ──────────────────────────────────
		cy.visit('/lq-ai/knowledge');
		cy.get('[data-testid="lq-ai-knowledge-page"]').should('exist');

		// ── Click "+ New KB" to reveal the inline create form ────────────────
		cy.get('[data-testid="lq-ai-knowledge-new-btn"]').click();
		cy.get('[data-testid="lq-ai-knowledge-create-form"]').should('exist');

		// ── Fill name + description ───────────────────────────────────────────
		cy.get('[data-testid="lq-ai-knowledge-create-name"]').type(kbName);
		cy.get('[data-testid="lq-ai-knowledge-create-description"]').type(kbDesc);

		// Intercept POST BEFORE submit.
		cy.intercept('POST', '/api/v1/knowledge-bases').as('createKB');
		cy.get('[data-testid="lq-ai-knowledge-create-submit"]').click();
		cy.wait('@createKB').its('response.statusCode').should('eq', 201);

		// ── Click into the newly created KB card ──────────────────────────────
		// After creation, the card appears in the grid. The card is an <a>
		// linking to /lq-ai/knowledge/{id}. Use cy.contains to target our KB.
		cy.contains('[data-testid="lq-ai-knowledge-card"]', kbName, { timeout: 10000 }).click();
		cy.url({ timeout: 10000 }).should('match', /\/lq-ai\/knowledge\/[a-f0-9-]+$/);
		cy.get('[data-testid="lq-ai-knowledge-detail-page"]').should('exist');

		// ── Upload the fixture PDF ────────────────────────────────────────────
		// The upload button calls fileInput.click() — the actual <input type="file">
		// is hidden (.lq-file-input { display: none }). Intercept both the file
		// upload POST and the KB-attach POST before triggering the file selection.
		// The KB-attach intercept (kbAttach) provides better failure diagnostics:
		// when the attach step fails we get a clear assertion failure with the
		// actual status code rather than a timeout.
		cy.intercept('POST', '/api/v1/files').as('uploadFile');
		cy.intercept('POST', '**/knowledge-bases/**/files').as('kbAttach');

		// Select file on the hidden input directly (force: true bypasses display:none).
		cy.get('[data-testid="lq-ai-knowledge-upload-btn"]')
			.closest('section')
			.find('input[type="file"]')
			.selectFile('cypress/fixtures/sample.pdf', { force: true });

		// Wait for the upload POST to land.
		cy.wait('@uploadFile', { timeout: 30000 }).its('response.statusCode').should('eq', 201);

		// Wait for the KB-attach POST to land (detail page polls for ready status
		// then calls attachFileToKB). The endpoint returns 204 No Content on success;
		// asserting here catches backend errors (4xx/5xx) that would otherwise
		// surface as a silent doc-row absence or timeout.
		cy.wait('@kbAttach', { timeout: 60000 }).its('response.statusCode').should('eq', 204);

		// ── Wait for the doc row to appear in the table ───────────────────────
		// The detail page polls for ready status (~1s interval, up to 30s) then
		// calls attachFileToKB. Once attached, load() rerenders the file list.
		// Accept any of: pending, processing, ready (ingest speed varies).
		cy.get('[data-testid="lq-ai-knowledge-doc-row"]', { timeout: 60000 }).should('exist');

		// Verify the filename matches what we uploaded.
		cy.get('[data-testid="lq-ai-knowledge-doc-row"]').should('contain.text', 'sample.pdf');

		// ── Verify status eventually becomes ready (generous timeout for ingest) ──
		// data-doc-status attribute is set on the row by the Svelte template.
		// Poll until the attribute is 'ready'; 60s ceiling per handoff guidance.
		cy.get('[data-testid="lq-ai-knowledge-doc-row"][data-doc-status="ready"]', {
			timeout: 60000
		}).should('exist');
	});

	it('Receipts source: send via slash → receipts drawer shows "via slash command"', () => {
		const ts = Date.now();
		const skillSlug = `m1-receipts-${ts}`;
		const skillTitle = `M1 Receipts ${ts}`;
		const slashAlias = `/m1r${ts}`.slice(0, 33); // backend max 32 chars after /

		// ── Pre-seed the slash skill via direct API call ──────────────────────
		// Same pattern as wave-d2 Test 4.
		getBearerToken((token) => {
			cy.request({
				method: 'POST',
				url: `${API_BASE()}/api/v1/user-skills`,
				headers: { Authorization: `Bearer ${token}` },
				body: {
					scope: 'user',
					slug: skillSlug,
					display_name: skillTitle,
					description: 'Receipts source cypress fixture',
					body: 'respond briefly with "receipt source ok"',
					version: '1.0.0',
					slash_alias: slashAlias
				}
			})
				.its('status')
				.should('eq', 201);
		});

		// ── Create a matter + new chat ────────────────────────────────────────
		createSampleMatter('Receipts Test Matter');

		// ── Type "/" to open slash popover, then pick skill by title ─────────
		cy.get('[data-testid="lq-ai-composer-input"]').first().type('/');
		cy.get('[data-testid="lq-ai-slash-popover-anchor"]', { timeout: 5000 }).should('exist');
		cy.get('[data-testid="lq-ai-slash-popover-anchor"] [role="listbox"]').should('exist');

		// Type a prefix to narrow the autocomplete.
		cy.get('[data-testid="lq-ai-composer-input"]').first().type('m1r');

		// Wait for title to appear in listbox, then click by title for dirty-DB safety.
		cy.get('[data-testid="lq-ai-slash-popover-anchor"] [role="listbox"]')
			.contains(skillTitle, { timeout: 10000 })
			.should('exist');

		cy.get('[data-testid="lq-ai-slash-popover-anchor"]')
			.contains('[role="option"]', skillTitle)
			.click();

		// ── Verify skill pill rendered ────────────────────────────────────────
		cy.get(`[data-testid="lq-ai-skill-detach-${skillSlug}"]`, { timeout: 5000 }).should('exist');

		// ── Send the message ──────────────────────────────────────────────────
		// Intercept BEFORE click. Assert the request carries source:'slash'.
		cy.intercept('POST', '**/messages').as('sendMessage');
		cy.get('[data-testid="lq-ai-composer-input"]').first().type('test prompt for receipts');
		cy.get('[data-testid="lq-ai-send-btn"]').click();

		cy.wait('@sendMessage', { timeout: 60000 })
			.its('request.body.attached_skills')
			.should('deep.include', { slug: skillSlug, source: 'slash' });

		// ── Wait for assistant reply ──────────────────────────────────────────
		// Ensure the round-trip completes so the receipt event is persisted
		// on the backend before we query it via the receipts drawer.
		cy.get('[data-testid="lq-ai-message-capture-inline"]:not([disabled])', { timeout: 90000 })
			.first()
			.should('exist');

		// ── Open receipts drawer ──────────────────────────────────────────────
		cy.intercept('GET', '**/receipts*').as('getReceipts');
		cy.get('[data-testid="lq-ai-receipts-toggle"]').click();

		// Wait for the receipts fetch to land.
		cy.wait('@getReceipts', { timeout: 15000 }).its('response.statusCode').should('eq', 200);

		// ── Assert the skill event shows source as "via slash command" ────────
		// ReceiptsList.svelte eventDescription() for kind='skill' with
		// source='slash' renders:
		//   "Skill applied: <skill_name> (via slash command)"
		// (SOURCE_LABEL['slash'] === 'slash command', rendered as `(via ${src})`).
		cy.contains('[data-testid="receipt-row"]', /via slash command/i, { timeout: 10000 }).should(
			'exist'
		);
	});
});
