/**
 * M3-C3 — Tabular Review UI happy path.
 *
 * Covers the full operator flow:
 *
 *   1. Login → redirect to /lq-ai
 *   2. /lq-ai/tabular → empty list + "Start new tabular review" CTA
 *   3. Click CTA → /lq-ai/tabular/new (4-step wizard)
 *   4. Step 1 (Documents): pick KB → multi-select 5 files
 *   5. Step 1 Next → Step 2 (Columns)
 *   6. Step 2: pick the contract-snapshot table-mode skill
 *   7. Step 2 Next → Step 3 (Cost preview); intercept fires
 *   8. Step 3 Next → Step 4 (Confirm); cost below $1 so no checkbox gate
 *   9. Step 4 Run → POST /tabular/execute → redirect to /lq-ai/tabular/[id]
 *   10. First poll → pending banner
 *   11. Second poll (3s later) → completed grid (5 rows × 4 cols = 20 cells)
 *   12. Click a populated cell → citation modal opens
 *   13. Close the modal
 *
 * All API responses are mocked via cy.intercept so the spec runs against
 * a live SvelteKit dev server (`docker compose up -d`) without requiring
 * any particular database state. Mocked shapes mirror the wire shapes in
 * `api/app/schemas/tabular.py`.
 *
 * Run:
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/m3-c-tabular-review.cy.ts'
 */

/// <reference types="cypress" />

const EXECUTION_ID = 'tex-1';
const KB_ID = 'kb-1';
const SKILL_NAME = 'contract-snapshot';

const FILE_IDS = ['f1', 'f2', 'f3', 'f4', 'f5'];
const DOC_IDS = ['d1', 'd2', 'd3', 'd4', 'd5'];
const COLUMN_NAMES = ['Term', 'Survival', 'Carveouts', 'Governing Law'];

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

const mockKnowledgeBase = {
	id: KB_ID,
	name: 'Sample NDAs',
	description: null,
	owner_id: 'u1',
	project_id: null,
	hybrid_alpha: 0.5,
	file_count: 5,
	chunk_count: 25,
	archived_at: null,
	created_at: '2026-05-22T00:00:00Z',
	updated_at: '2026-05-22T00:00:00Z'
};

const mockKbFiles = FILE_IDS.map((id, i) => ({
	id,
	owner_id: 'u1',
	project_id: null,
	filename: `sample-nda-${i + 1}.pdf`,
	mime_type: 'application/pdf',
	size_bytes: 1024,
	hash_sha256: `hash-${i}`,
	ingestion_status: 'ready' as const,
	ingest_status: 'ok' as const,
	document_id: DOC_IDS[i],
	page_count: 4,
	character_count: 2000,
	created_at: '2026-05-22T00:00:00Z',
	attached_at: '2026-05-22T00:00:00Z'
}));

const mockSkills = [
	{
		name: SKILL_NAME,
		version: '1.0.0',
		scope: 'builtin' as const,
		title: 'Contract Snapshot',
		description: '4-column NDA snapshot: Term / Survival / Carveouts / Governing Law.',
		output_format: 'table'
	},
	{
		name: 'nda-review',
		version: '1.0.0',
		scope: 'builtin' as const,
		title: 'NDA Review',
		description: 'Standard NDA review playbook.',
		output_format: 'report' // should be filtered out of the table-mode dropdown
	}
];

const mockPreviewResponse = {
	cells_count: 20,
	estimated_tokens: 12000,
	estimated_cost_usd: '0.0500',
	per_tier_breakdown: { tier_2: 20 }
};

const mockExecutionPending = {
	id: EXECUTION_ID,
	user_id: 'u1',
	parent_execution_id: null,
	skill_name: SKILL_NAME,
	status: 'pending' as const,
	document_ids: DOC_IDS,
	columns: COLUMN_NAMES.map((name) => ({ name, query: `What is the ${name}?` })),
	results: null,
	cost_estimate_usd: '0.0500',
	cost_actual_usd: null,
	error_text: null,
	created_at: '2026-05-22T15:00:00Z',
	started_at: null,
	completed_at: null
};

const mockExecutionCompleted = {
	...mockExecutionPending,
	status: 'completed' as const,
	started_at: '2026-05-22T15:00:05Z',
	completed_at: '2026-05-22T15:01:35Z',
	cost_actual_usd: '0.0480',
	results: {
		rows: DOC_IDS.map((docId, i) => ({
			document_id: docId,
			document_name: `sample-nda-${i + 1}.pdf`,
			cells: Object.fromEntries(
				COLUMN_NAMES.map((col, j) => [
					col,
					{
						value: j === 2 && i === 1 ? null : `value-${i}-${j}`, // (Carveouts, NDA 2) → failed
						citations:
							j === 2 && i === 1
								? []
								: [
										{
											citation_id: `cite-${i}-${j}`,
											document_id: docId,
											chunk_id: `chunk-${i}-${j}`,
											confidence: (['high', 'medium', 'low'] as const)[j % 3]
										}
									],
						confidence:
							j === 2 && i === 1 ? ('failed' as const) : (['high', 'medium', 'low'] as const)[j % 3],
						tier_used: j === 2 && i === 1 ? null : 2,
						cost_usd: '0.0024',
						error: j === 2 && i === 1 ? 'no citation found' : null
					}
				])
			)
		}))
	}
};

describe('M3-C3 — Tabular Review happy path', () => {
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

		cy.intercept('GET', '**/api/v1/users/me', { statusCode: 200, body: mockUser }).as('getMe');
		cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
			statusCode: 200,
			body: { default_password_active: false, logs_hint: '' }
		}).as('bootstrapStatus');
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
		cy.intercept('GET', '**/api/v1/teams**', { statusCode: 200, body: [] }).as('listTeams');

		// --- Skills (Step 2 dropdown filters to table-mode) -------------------
		cy.intercept('GET', '**/api/v1/skills**', { statusCode: 200, body: mockSkills }).as(
			'listSkills'
		);

		// --- Tabular endpoints ------------------------------------------------
		cy.intercept('GET', '**/api/v1/tabular/executions', { statusCode: 200, body: [] }).as(
			'listTabular'
		);

		cy.intercept('GET', '**/api/v1/knowledge-bases**', {
			statusCode: 200,
			body: [mockKnowledgeBase]
		}).as('listKbs');

		cy.intercept('GET', `**/api/v1/knowledge-bases/${KB_ID}/files**`, {
			statusCode: 200,
			body: mockKbFiles
		}).as('listKbFiles');

		cy.intercept('POST', '**/api/v1/tabular/preview-cost', {
			statusCode: 200,
			body: mockPreviewResponse
		}).as('previewCost');

		cy.intercept('POST', '**/api/v1/tabular/execute', {
			statusCode: 202,
			body: mockExecutionPending
		}).as('executeTabular');

		// First poll → pending, every subsequent poll → completed.
		let pollCount = 0;
		cy.intercept('GET', `**/api/v1/tabular/executions/${EXECUTION_ID}`, (req) => {
			pollCount += 1;
			req.reply({
				statusCode: 200,
				body: pollCount === 1 ? mockExecutionPending : mockExecutionCompleted
			});
		}).as('pollTabular');
	});

	it('login → empty list → wizard 4 steps → execute → poll twice → completed grid → cell click opens citation modal', () => {
		// 1. Login + dashboard hop.
		cy.visit('/lq-ai/login');
		cy.get('[data-testid="lq-ai-login-email"]').type('admin@lq.ai');
		cy.get('[data-testid="lq-ai-login-password"]').type('password');
		cy.get('[data-testid="lq-ai-login-submit"]').click();
		cy.wait('@login');
		cy.url({ timeout: 15000 }).should('not.include', '/login');

		// 2. Navigate to /lq-ai/tabular — empty list.
		cy.visit('/lq-ai/tabular');
		cy.wait('@listTabular');
		cy.get('[data-testid="lq-tabular-empty"]').should('be.visible');

		// 3. Click "Start new tabular review" CTA → /lq-ai/tabular/new.
		cy.get('[data-testid="lq-tabular-new-cta"]').click();
		cy.url().should('include', '/lq-ai/tabular/new');

		// Wait for the parallel mount fetches to land.
		cy.wait('@listKbs');
		cy.wait('@listSkills');

		// 4. Step 1: pick KB → 5 file checkboxes → multi-select all 5.
		cy.get('[data-testid="lq-tabwiz-steps"]')
			.find('[data-step="documents"][data-active="true"]')
			.should('exist');
		cy.get('[data-testid="lq-tabwiz-kb-select"]').select(KB_ID);
		cy.wait('@listKbFiles');
		cy.get('[data-testid="lq-tabwiz-files"]').should('be.visible');
		cy.get('[data-testid="lq-tabwiz-file-checkbox"]').should('have.length', 5);
		cy.get('[data-testid="lq-tabwiz-file-checkbox"]').each(($el) => {
			cy.wrap($el).check();
		});
		cy.get('[data-testid="lq-tabwiz-doc-count"]').should('contain', '5');

		// 5. Step 1 → Step 2.
		cy.get('[data-testid="lq-tabwiz-next"]').should('not.be.disabled').click();
		cy.get('[data-testid="lq-tabwiz-steps"]')
			.find('[data-step="columns"][data-active="true"]')
			.should('exist');

		// 6. Step 2: skills already loaded; pick contract-snapshot.
		//    Sanity: the dropdown should only contain table-mode skills (1
		//    entry), NOT the nda-review report-mode skill from the mock.
		cy.get('[data-testid="lq-tabwiz-skill-select"]').find('option').should('have.length', 2);
		cy.get('[data-testid="lq-tabwiz-skill-select"]').select(SKILL_NAME);

		// 7. Step 2 → Step 3 (preview fetched).
		cy.get('[data-testid="lq-tabwiz-next"]').should('not.be.disabled').click();
		cy.wait('@previewCost');
		cy.get('[data-testid="lq-tabwiz-steps"]')
			.find('[data-step="preview"][data-active="true"]')
			.should('exist');
		cy.get('[data-testid="lq-tabwiz-preview-cells"]').should('contain', '20');
		cy.get('[data-testid="lq-tabwiz-preview-cost"]').should('contain', '$0.05');

		// 8. Step 3 → Step 4 — cost below $1, no confirmation gate.
		cy.get('[data-testid="lq-tabwiz-next"]').should('not.be.disabled').click();
		cy.get('[data-testid="lq-tabwiz-steps"]')
			.find('[data-step="confirm"][data-active="true"]')
			.should('exist');
		cy.get('[data-testid="lq-tabwiz-confirm-gate"]').should('not.exist');

		// 9. Run → POST /tabular/execute → redirect to result.
		cy.get('[data-testid="lq-tabwiz-next"]').should('not.be.disabled').click();
		cy.wait('@executeTabular');
		cy.url({ timeout: 10000 }).should('include', `/lq-ai/tabular/${EXECUTION_ID}`);

		// 10. First poll → pending banner.
		cy.wait('@pollTabular');
		cy.get('[data-testid="lq-tabres-status"]', { timeout: 10000 }).should('contain', 'Pending');

		// 11. Second poll (3s later) → completed; grid renders 5 rows.
		cy.wait('@pollTabular');
		cy.get('[data-testid="lq-tabres-status"]', { timeout: 10000 }).should('contain', 'Completed');
		cy.get('[data-testid="lq-tabgrid"]').should('be.visible');
		cy.get('[data-testid="lq-tabgrid-row"]').should('have.length', 5);
		cy.get('[data-testid="lq-tabgrid-header"]').should('have.length', 4);

		// Failed cell (Carveouts × sample-nda-2.pdf) should render italic
		// "not found".
		cy.get('[data-testid="lq-tabcell-failed"]').should('have.length', 1);
		cy.get('[data-testid="lq-tabcell-failed"]').should('contain', 'not found');

		// 12. Click a populated cell → citation modal opens.
		cy.get('[data-testid="lq-tabcell"][data-state!="empty"][data-state!="failed"]')
			.first()
			.click();
		cy.get('[data-testid="lq-tabcm"]').should('be.visible');
		cy.get('[data-testid="lq-tabcm-citations"]').should('be.visible');

		// 13. Close the modal (× button).
		cy.get('[data-testid="lq-tabcm-close"]').click();
		cy.get('[data-testid="lq-tabcm"]').should('not.exist');
	});
});
