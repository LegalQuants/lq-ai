/**
 * M3-A6 — Easy Playbook wizard E2E happy path.
 *
 * Covers the full operator flow from login through saving a generated
 * playbook:
 *
 *   1. /lq-ai/login → fill credentials → submit → redirect to /lq-ai
 *   2. /lq-ai/playbooks → click "Generate from prior agreements" CTA
 *   3. /lq-ai/playbooks/easy (Step 1 upload) → pick contract_type, upload 3
 *      stub PDFs, click Generate
 *   4. Step 2 progress → setTimeout-driven poll → first poll returns
 *      pending; cy.tick advances; second poll returns completed with a
 *      draft_playbook
 *   5. Step 3 review → the inline editor surfaces the assembled positions
 *      bound to draft_playbook; edit one position's `issue` field
 *   6. Click Save → POST /playbooks → Step 4 success screen
 *
 * All API responses are mocked via cy.intercept so the spec runs against
 * a live SvelteKit dev server (`docker compose up -d`) without requiring
 * provider keys / the real M3-A6 backend pipeline. The mocked shapes
 * mirror the wire shapes in `api/app/schemas/playbooks.py` and the
 * OpenAPI sketch.
 *
 * The wizard's file-upload step is short-circuited by mocking POST
 * /files to return `document_id` set on the response (the wizard then
 * skips the per-file parse poll loop). That is NOT what the real
 * pipeline does — there `document_id` is null on POST and only flips
 * non-null once the C5 parser runs — but for this UI smoke we want a
 * fast deterministic path through the steps. The real upload→parse
 * timing is covered by the backend integration tests.
 *
 * Run:
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/m3-a6-easy-playbook-wizard.cy.ts'
 */

/// <reference types="cypress" />

const GENERATION_ID = 'gen-1';
const SAVED_PLAYBOOK_ID = 'pb-saved-1';

const mockUser = {
	id: 'u1',
	email: 'admin@lq.ai',
	display_name: 'Admin',
	is_admin: true,
	role: 'admin' as const,
	mfa_enabled: false,
	must_change_password: false,
	created_at: '2026-01-01T00:00:00Z'
};

const mockDraftPlaybook = {
	name: 'Generated NDA Playbook',
	contract_type: 'NDA',
	description: 'Generated from 3 NDAs.',
	version: '0.1.0',
	positions: [
		{
			issue: 'Definition of Confidential Information',
			description: 'How the parties scope what counts as confidential.',
			standard_language: 'Confidential Information means [...]',
			fallback_tiers: [
				{
					rank: 1,
					description: 'Broader scope acceptable',
					language: 'Confidential Information includes [...]'
				}
			],
			redline_strategy: 'Tighten the carve-outs.',
			severity_if_missing: 'high' as const,
			detection_keywords: ['confidential information', 'definition'],
			detection_examples: ['Section 1 of NDA-A'],
			position_order: 0
		},
		{
			issue: 'Term of Confidentiality',
			description: 'How long the confidentiality obligation runs.',
			standard_language: 'The obligations under this Agreement shall continue for three (3) years.',
			fallback_tiers: [
				{ rank: 1, description: '2-year term acceptable', language: 'two (2) years' }
			],
			redline_strategy: 'Cap at 5 years.',
			severity_if_missing: 'medium' as const,
			detection_keywords: ['term', 'years'],
			detection_examples: [],
			position_order: 1
		}
	]
};

const mockSavedPlaybook = {
	id: SAVED_PLAYBOOK_ID,
	name: mockDraftPlaybook.name,
	contract_type: mockDraftPlaybook.contract_type,
	description: mockDraftPlaybook.description,
	version: mockDraftPlaybook.version,
	created_by: mockUser.id,
	created_at: '2026-05-20T00:00:00Z',
	updated_at: '2026-05-20T00:00:00Z',
	positions: mockDraftPlaybook.positions.map((p, i) => ({
		id: `pos-${i + 1}`,
		...p
	}))
};

describe('M3-A6 — Easy Playbook wizard happy path', () => {
	beforeEach(() => {
		// --- Login + post-login gate ------------------------------------------
		cy.intercept('POST', '**/api/v1/auth/login', {
			statusCode: 200,
			body: {
				access_token: 'fake-token',
				token_type: 'Bearer',
				expires_in: 3600,
				user: mockUser
			}
		}).as('login');

		cy.intercept('GET', '**/api/v1/users/me', {
			statusCode: 200,
			body: mockUser
		}).as('getMe');

		cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
			statusCode: 200,
			body: { default_password_active: false, logs_hint: '' }
		}).as('bootstrapStatus');

		// Dashboard side-effect endpoints — pin each to empty success so
		// the post-login hop doesn't trigger clearSession() on a 401.
		cy.intercept('GET', '**/api/v1/users/me/preferences', {
			statusCode: 200,
			body: {
				reasoning_visibility: 'on_request',
				featured_tools: 'inline',
				workspace_layout: 'three_pane',
				trust_pills: 'labels',
				provenance_pills: 'collapsed'
			}
		}).as('getPreferences');
		cy.intercept('GET', '**/api/v1/projects**', { statusCode: 200, body: [] }).as('listProjects');
		cy.intercept('GET', '**/api/v1/chats**', {
			statusCode: 200,
			body: { items: [], next_cursor: null }
		}).as('listChats');
		cy.intercept('GET', '**/api/v1/user-skills**', { statusCode: 200, body: [] }).as(
			'listUserSkills'
		);
		cy.intercept('GET', '**/api/v1/saved-prompts**', { statusCode: 200, body: [] }).as(
			'listSavedPrompts'
		);
		cy.intercept('GET', '**/api/v1/skills**', { statusCode: 200, body: [] }).as('listSkills');
		cy.intercept('GET', '**/api/v1/teams**', { statusCode: 200, body: [] }).as('listTeams');

		// --- Playbooks list (empty so the CTA is the only thing to click) ----
		cy.intercept('GET', '**/api/v1/playbooks', { statusCode: 200, body: [] }).as('listPlaybooks');

		// --- File upload: 3 calls, each returns FileMeta with document_id set
		//     so the wizard's per-file parse-poll loop is skipped. Counter
		//     is in the closure so each call sees a distinct file_id +
		//     document_id (the request order is the upload order in the
		//     wizard's sequential for-loop).
		let uploadCount = 0;
		cy.intercept('POST', '**/api/v1/files', (req) => {
			uploadCount += 1;
			const idx = uploadCount;
			req.reply({
				statusCode: 201,
				body: {
					id: `file-${idx}`,
					owner_id: mockUser.id,
					project_id: null,
					filename: `nda-${idx}.pdf`,
					mime_type: 'application/pdf',
					size_bytes: 1024,
					hash_sha256: `hash-${idx}`,
					ingestion_status: 'ready',
					page_count: 4,
					character_count: 2000,
					document_id: `doc-${idx}`,
					created_at: '2026-05-20T00:00:00Z'
				}
			});
		}).as('uploadFile');

		// --- Easy Playbook generation: POST returns pending; GET poll first
		//     returns running, then completed with draft_playbook.
		cy.intercept('POST', '**/api/v1/playbooks/easy', (req) => {
			req.reply({
				statusCode: 202,
				body: {
					id: GENERATION_ID,
					user_id: mockUser.id,
					contract_type: 'NDA',
					status: 'pending',
					document_ids: ['doc-1', 'doc-2', 'doc-3'],
					draft_playbook: null,
					error_message: null,
					created_at: '2026-05-20T00:00:00Z'
				}
			});
		}).as('startGeneration');

		let pollCount = 0;
		cy.intercept('GET', `**/api/v1/playbooks/easy/${GENERATION_ID}`, (req) => {
			pollCount += 1;
			if (pollCount === 1) {
				req.reply({
					statusCode: 200,
					body: {
						id: GENERATION_ID,
						user_id: mockUser.id,
						contract_type: 'NDA',
						status: 'running',
						document_ids: ['doc-1', 'doc-2', 'doc-3'],
						draft_playbook: null,
						error_message: null,
						created_at: '2026-05-20T00:00:00Z'
					}
				});
			} else {
				req.reply({
					statusCode: 200,
					body: {
						id: GENERATION_ID,
						user_id: mockUser.id,
						contract_type: 'NDA',
						status: 'completed',
						document_ids: ['doc-1', 'doc-2', 'doc-3'],
						draft_playbook: mockDraftPlaybook,
						error_message: null,
						created_at: '2026-05-20T00:00:00Z'
					}
				});
			}
		}).as('pollGeneration');

		// --- Save the playbook -------------------------------------------------
		cy.intercept('POST', '**/api/v1/playbooks', {
			statusCode: 201,
			body: mockSavedPlaybook
		}).as('createPlaybook');
	});

	it('login → playbooks list → CTA → wizard → upload → poll → review + edit → save → success', () => {
		// 1. Login.
		cy.visit('/lq-ai/login');
		cy.get('[data-testid="lq-ai-login-email"]').type('admin@lq.ai');
		cy.get('[data-testid="lq-ai-login-password"]').type('password');
		cy.get('[data-testid="lq-ai-login-submit"]').click();
		cy.wait('@login');
		cy.url({ timeout: 15000 }).should('not.include', '/login');

		// 2. Navigate to /lq-ai/playbooks. The CTA is rendered in the header.
		cy.visit('/lq-ai/playbooks');
		cy.wait('@listPlaybooks');
		cy.get('[data-testid="lq-playbooks-generate-cta"]').should('be.visible').click();

		// 3. Land on the wizard at Step 1.
		cy.url({ timeout: 10000 }).should('include', '/lq-ai/playbooks/easy');
		cy.get('[data-testid="lq-easy-wizard-step-upload"]').should('be.visible');

		// 4. Pick contract type + upload 3 stub PDFs.
		cy.get('#lq-easy-wizard-contract-type').type('NDA');
		cy.get('[data-testid="lq-easy-wizard-file-input"]').selectFile(
			[
				{ contents: 'cypress/fixtures/sample.pdf', fileName: 'nda-1.pdf' },
				{ contents: 'cypress/fixtures/sample.pdf', fileName: 'nda-2.pdf' },
				{ contents: 'cypress/fixtures/sample.pdf', fileName: 'nda-3.pdf' }
			],
			{ force: true }
		);
		cy.get('[data-testid="lq-easy-wizard-file-list"]')
			.find('li')
			.should('have.length', 3);

		// 5. Fake the clock before clicking generate so we can advance the
		//    progress-step setTimeout(5s) poll deterministically.
		cy.clock();

		cy.get('[data-testid="lq-easy-wizard-start"]').click();

		// 6. Three uploads + start generation, in that order.
		cy.wait('@uploadFile');
		cy.wait('@uploadFile');
		cy.wait('@uploadFile');
		cy.wait('@startGeneration');

		// 7. Step 2 progress visible.
		cy.get('[data-testid="lq-easy-wizard-step-progress"]', { timeout: 10000 }).should(
			'be.visible'
		);

		// 8. Advance through the first poll (status='running' → schedule another).
		cy.tick(5_500);
		cy.wait('@pollGeneration');

		// 9. Advance through the second poll (status='completed' → review step).
		cy.tick(5_500);
		cy.wait('@pollGeneration');

		// 10. Step 3 review. Editor renders both positions.
		cy.get('[data-testid="lq-easy-wizard-step-review"]', { timeout: 10000 }).should('be.visible');
		cy.get('[data-testid="lq-playbook-editor"]').should('be.visible');
		cy.get('[data-testid="lq-playbook-editor-position"]').should('have.length', 2);

		// Restore real timers — the rest of the flow is synchronous from the
		// browser's POV (no more setTimeout-driven UI).
		cy.clock().then((clock) => clock.restore());

		// 11. Edit the first position's `issue` field.
		cy.get('[data-testid="lq-playbook-editor-position"]')
			.first()
			.find('input[id$="-issue"]')
			.clear()
			.type('Definition of Confidential Information (edited)');

		// 12. Save.
		cy.get('[data-testid="lq-easy-wizard-save"]').click();
		cy.wait('@createPlaybook').its('request.body.positions.0.issue').should(
			'eq',
			'Definition of Confidential Information (edited)'
		);

		// 13. Step 4 success screen.
		cy.get('[data-testid="lq-easy-wizard-step-approve"]', { timeout: 10000 }).should(
			'be.visible'
		);
		cy.contains('Playbook saved').should('be.visible');
	});
});
