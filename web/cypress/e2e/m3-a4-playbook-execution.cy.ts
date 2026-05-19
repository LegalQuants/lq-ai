/**
 * M3-A4 — Playbook execution UI happy path.
 *
 * Covers the full operator flow from login through executing a playbook and
 * viewing the completed result:
 *
 *   1. /lq-ai/login → fill credentials → submit → redirect to /lq-ai
 *   2. /lq-ai/playbooks → see disclaimer banner + table with the 2 NDA built-ins
 *   3. Click Apply on NDA — Mutual → modal opens with cost preview
 *   4. Pick a KB → file picker appears → pick a file
 *   5. Run playbook → 202 pending → redirect to /lq-ai/playbook-executions/{id}
 *   6. First poll shows pending banner; second poll (3s later) shows completed
 *      result with summary + 8 rows
 *   7. Filter by outcome=deviates → 2 rows
 *   8. Expand the first row → "Suggested redline" section visible
 *
 * All API responses are mocked via cy.intercept so the spec runs against a
 * live SvelteKit dev server (`docker compose up -d`) without requiring any
 * particular database state.
 *
 * The mocked response shapes mirror the wire shapes in
 * `api/app/schemas/playbooks.py` and the executor's `_shape_results_payload`
 * (`api/app/playbooks/nodes.py`), pinned by the TS contract test in
 * `web/src/lib/lq-ai/__tests__/types.contract.test.ts`.
 *
 * Run:
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/m3-a4-playbook-execution.cy.ts'
 */

/// <reference types="cypress" />

const PLAYBOOK_ID = 'pb-mutual-nda';
const EXECUTION_ID = 'exec-1';
const KB_ID = 'kb-1';
const FILE_ID = 'file-1';
const DOC_ID = 'doc-1';

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

const mockPlaybook = {
	id: PLAYBOOK_ID,
	name: 'NDA — Mutual',
	contract_type: 'NDA',
	description: 'Mutual NDA playbook covering 8 standard positions.',
	version: '1.0.0',
	created_by: null,
	created_at: '2026-05-18T00:00:00Z',
	updated_at: '2026-05-18T00:00:00Z',
	positions: Array.from({ length: 8 }, (_, i) => ({
		id: `pos-${i + 1}`,
		issue: `Position ${i + 1}`,
		description: '',
		standard_language: 'Standard language here.',
		fallback_tiers: [{ rank: 1, description: 'Fallback A', language: 'Fallback A text.' }],
		redline_strategy: '',
		severity_if_missing: (['critical', 'high', 'medium', 'low'] as const)[i % 4],
		detection_keywords: ['nda'],
		detection_examples: [],
		position_order: i
	}))
};

const mockKnowledgeBase = {
	id: KB_ID,
	name: 'NDA workspace',
	description: null,
	owner_id: 'u1',
	project_id: null,
	hybrid_alpha: 0.5,
	file_count: 1,
	chunk_count: 5,
	archived_at: null,
	created_at: '2026-05-18T00:00:00Z',
	updated_at: '2026-05-18T00:00:00Z'
};

const mockKbFile = {
	id: FILE_ID,
	owner_id: 'u1',
	project_id: null,
	filename: 'sample-nda.pdf',
	mime_type: 'application/pdf',
	size_bytes: 1024,
	hash_sha256: 'abc',
	ingestion_status: 'ready' as const,
	ingest_status: 'ok' as const,
	document_id: DOC_ID,
	page_count: 4,
	character_count: 2000,
	created_at: '2026-05-18T00:00:00Z',
	attached_at: '2026-05-18T00:00:00Z'
};

const mockExecutionPending = {
	id: EXECUTION_ID,
	playbook_id: PLAYBOOK_ID,
	target_document_id: DOC_ID,
	user_id: 'u1',
	project_id: null,
	status: 'pending' as const,
	results: null,
	error: null,
	created_at: '2026-05-18T00:00:00Z',
	completed_at: null
};

const mockExecutionCompleted = {
	...mockExecutionPending,
	status: 'completed' as const,
	completed_at: '2026-05-18T00:01:00Z',
	results: {
		schema_version: 'm3-a2-v1',
		positions: mockPlaybook.positions.map((p, i) => ({
			position_id: p.id,
			issue: p.issue,
			severity_if_missing: p.severity_if_missing,
			verdict: (['matches_standard', 'matches_fallback', 'deviates', 'missing'] as const)[i % 4],
			confidence: 0.9,
			matched_fallback_rank: null,
			cited_chunk_ids: ['chunk-a', 'chunk-b'],
			matched_text: 'The actual clause text from the contract.',
			redline:
				i % 4 === 2
					? {
							old_text: 'old clause',
							new_text: 'new clause',
							justification: 'tighter than fallback'
						}
					: null,
			justification: 'Reason for the verdict.'
		})),
		summary: {
			matches_standard: 2,
			matches_fallback: 2,
			deviates: 2,
			missing: 2
		}
	}
};

describe('M3-A4 — Playbook execution happy path', () => {
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

		// The LQ.AI shell layout re-fetches /users/me on every route mount
		// (auth gate in src/routes/lq-ai/+layout.svelte). Without an intercept
		// the call hits the real backend and returns the real admin user; the
		// mocked user shape keeps the spec self-contained.
		cy.intercept('GET', '**/api/v1/users/me', {
			statusCode: 200,
			body: mockUser
		}).as('getMe');

		// Bootstrap-status probe — defensively intercepted. Only fires on 401
		// today, but pinning prevents flakes if the shell starts probing on
		// page-load in a future change.
		cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
			statusCode: 200,
			body: { default_password_active: false, logs_hint: '' }
		}).as('bootstrapStatus');

		// After login() returns, the shell redirects to /lq-ai (dashboard),
		// whose mounted components fire a handful of side-effect requests
		// (preferences, projects, chats, user-skills, …). Any of those that
		// return 401 against our fake token will trigger `clearSession()` in
		// `api/client.ts`, which redirects us back to /lq-ai/login. We pin
		// each one to an empty success so the dashboard hop is a no-op.
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

		// --- Playbooks list + detail ------------------------------------------
		cy.intercept('GET', '**/api/v1/playbooks', {
			statusCode: 200,
			body: [mockPlaybook, { ...mockPlaybook, id: 'pb-unilateral-nda', name: 'NDA — Unilateral' }]
		}).as('listPlaybooks');

		cy.intercept('GET', `**/api/v1/playbooks/${PLAYBOOK_ID}`, {
			statusCode: 200,
			body: mockPlaybook
		}).as('getPlaybook');

		// --- KB picker + file picker -----------------------------------------
		// The execute modal loads the KB list on mount, then loads files for
		// the chosen KB on change. Both endpoints must be intercepted so the
		// modal's `listKnowledgeBases` / `listKnowledgeBaseFiles` calls don't
		// hit the real backend.
		cy.intercept('GET', '**/api/v1/knowledge-bases**', {
			statusCode: 200,
			body: [mockKnowledgeBase]
		}).as('listKbs');

		cy.intercept('GET', `**/api/v1/knowledge-bases/${KB_ID}/files**`, {
			statusCode: 200,
			body: [mockKbFile]
		}).as('listKbFiles');

		// --- Execute → 202 pending -------------------------------------------
		cy.intercept('POST', `**/api/v1/playbooks/${PLAYBOOK_ID}/execute`, {
			statusCode: 202,
			body: mockExecutionPending
		}).as('executePlaybook');

		// --- Poll: first call → pending, second call → completed -------------
		// The result page schedules a setTimeout(3000) re-poll while the
		// execution is non-terminal. Cypress' default command timeout (4s)
		// covers the gap; the status assertion below adds a 10s safety margin.
		let pollCount = 0;
		cy.intercept('GET', `**/api/v1/playbook-executions/${EXECUTION_ID}`, (req) => {
			pollCount += 1;
			req.reply({
				statusCode: 200,
				body: pollCount === 1 ? mockExecutionPending : mockExecutionCompleted
			});
		}).as('pollExecution');
	});

	it('login → playbooks list → apply → cost preview → KB pick → file pick → confirm → poll twice → completed result + filter + expand', () => {
		// 1. Login via the form. The redirect after a successful login lands
		//    on /lq-ai (the dashboard), so we wait for the URL to leave /login.
		cy.visit('/lq-ai/login');
		cy.get('[data-testid="lq-ai-login-email"]').type('admin@lq.ai');
		cy.get('[data-testid="lq-ai-login-password"]').type('password');
		cy.get('[data-testid="lq-ai-login-submit"]').click();
		cy.wait('@login');
		cy.url({ timeout: 15000 }).should('not.include', '/login');

		// 2. Navigate to /lq-ai/playbooks. The auth gate calls /users/me on
		//    layout mount; the intercept above resolves it.
		cy.visit('/lq-ai/playbooks');
		cy.wait('@listPlaybooks');

		cy.get('[data-testid="lq-playbook-disclaimer"]').should('be.visible');
		cy.get('[data-testid="lq-playbooks-table"]').should('be.visible');
		cy.get('[data-testid="lq-playbook-row"]').should('have.length', 2);

		// 3. Apply on the mutual NDA.
		cy.get(`[data-playbook-id="${PLAYBOOK_ID}"]`).find('[data-testid="lq-playbook-apply"]').click();

		// 4. Modal opens with cost preview.
		cy.get('[data-testid="lq-playbook-execute-modal"]').should('be.visible');
		cy.get('[data-testid="lq-playbook-cost-preview"]').should('contain', '$');
		cy.get('[data-testid="lq-playbook-cost-preview"]').should('contain', '8 positions');

		// 5. KB picker is populated by the listKbs intercept.
		cy.wait('@listKbs');
		cy.get('[data-testid="lq-playbook-execute-kb-picker"]').should('be.visible');
		cy.get('[data-testid="lq-playbook-execute-kb-picker"]').select(KB_ID);

		// 6. File picker mounts once a KB is selected; intercept fires.
		cy.wait('@listKbFiles');
		cy.get('[data-testid="lq-playbook-execute-doc-picker"]').should('be.visible');
		cy.get('[data-testid="lq-playbook-execute-doc-picker"]').select(FILE_ID);

		// 7. Confirm execution.
		cy.get('[data-testid="lq-playbook-execute-confirm"]').should('not.be.disabled').click();
		cy.wait('@executePlaybook');

		// 8. Redirected to the execution result page.
		cy.url({ timeout: 10000 }).should('include', `/lq-ai/playbook-executions/${EXECUTION_ID}`);

		// 9. First poll → pending banner.
		cy.wait('@pollExecution');
		cy.get('[data-testid="lq-pbx-running"]', { timeout: 10000 }).should('be.visible');

		// 10. Second poll (3s later) → completed; summary + table + 8 rows.
		cy.wait('@pollExecution');
		cy.get('[data-testid="lq-pbx-status"]', { timeout: 10000 }).should('contain', 'completed');
		cy.get('[data-testid="lq-pbx-summary"]').should('be.visible');
		cy.get('[data-testid="lq-pbx-table"]').should('be.visible');
		cy.get('[data-testid="lq-pbx-row"]').should('have.length', 8);

		// 11. Filter by outcome=deviates → 2 of 8 rows survive (positions 3
		//     and 7 — index % 4 === 2 in the mock).
		cy.get('[data-testid="lq-pbx-filter-outcome"]').select('deviates');
		cy.get('[data-testid="lq-pbx-row"]').should('have.length', 2);

		// 12. Expand the first row → "Suggested redline" section visible
		//     (the deviates positions in the mock all have a redline payload).
		cy.get('[data-testid="lq-pbx-row"]').first().find('.lq-pbx-chev-btn').click();
		cy.contains('Suggested redline').should('be.visible');
	});
});
