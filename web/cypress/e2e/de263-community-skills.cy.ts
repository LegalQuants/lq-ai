/**
 * 3.8 / DE-263 — Community skill installer admin UI happy path.
 *
 * Covers the operator flow on /lq-ai/admin/community-skills:
 *
 *   1. Visit with an admin auth state → catalog list renders with the
 *      source line (submodule path + short sha) and attestation states
 *      shown honestly per row.
 *   2. Search narrows the list.
 *   3. "Review" opens the detail panel with the FULL SKILL.md
 *      frontmatter + body (transparency: the work product is reviewed
 *      before install) and the install provenance ref.
 *   4. "Install" → confirm dialog → POST install → success banner with
 *      the provenance ref; the list reloads with installed=true and the
 *      button flips to a disabled "Installed".
 *
 * All API responses are mocked via cy.intercept so the spec runs
 * against a live SvelteKit dev server without requiring an initialized
 * skills/community submodule or any particular DB state. Mocked shapes
 * mirror the wire shapes in `api/app/api/community_skills.py`.
 *
 * Run:
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/de263-community-skills.cy.ts'
 */

/// <reference types="cypress" />

const SHA = 'abc123def4567890abc123def4567890abc123de';

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

const leaseReview = {
	slug: 'lease-review',
	title: 'Lease Review',
	description: 'First-pass review of commercial leases.',
	version: '1.2.0',
	author: 'Jane Attorney',
	tags: ['real-estate', 'review'],
	jurisdiction: 'us',
	attested_by: 'Jane Attorney, NY Bar #12345',
	installed: false,
	body_preview: 'You are reviewing a commercial lease…'
};

const ndaTriage = {
	slug: 'nda-triage',
	title: 'NDA Triage',
	description: 'Quick triage pass over inbound NDAs.',
	version: '0.9.0',
	author: null,
	tags: ['nda'],
	jurisdiction: null,
	attested_by: null,
	installed: false,
	body_preview: 'Triage the NDA…'
};

const catalogBody = (items: unknown[]) => ({
	items,
	source: {
		path: '/app/skills/community/skills',
		sha: SHA,
		submodule_present: true,
		operator_hint: null
	},
	load_errors: []
});

const leaseReviewDetail = {
	...leaseReview,
	output_format: 'report',
	minimum_inference_tier: null,
	content_yaml: 'name: lease-review\ndescription: First-pass review of commercial leases.',
	content_md: '# Lease review\n\nYou are reviewing a commercial lease…',
	install_ref: `lq-skills:lease-review@${SHA}`
};

const installedRow = {
	id: 'us-1',
	scope: 'user',
	owner_user_id: 'u1',
	owner_team_id: null,
	slug: 'lease-review',
	display_name: 'Lease Review',
	description: 'First-pass review of commercial leases.',
	version: '1.2.0',
	tags: ['real-estate', 'review'],
	frontmatter_extra: { jurisdiction: 'us', output_format: 'report' },
	body: '# Lease review\n\nYou are reviewing a commercial lease…',
	slash_alias: null,
	forked_from: `lq-skills:lease-review@${SHA}`,
	archived_at: null,
	created_at: '2026-07-25T00:00:00Z',
	updated_at: '2026-07-25T00:00:00Z'
};

function setAuthStorage(win: Window): void {
	win.localStorage.setItem(
		'lq_ai_auth',
		JSON.stringify({
			access_token: 'fake-token-de263',
			refresh_token: null,
			expires_at: Date.now() + 3600 * 1000,
			user: mockUser
		})
	);
}

function interceptBaseRequests(): void {
	cy.intercept('GET', '**/api/v1/users/me', { statusCode: 200, body: mockUser }).as('getMe');
	cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
		statusCode: 200,
		body: { default_password_active: false, logs_hint: '' }
	}).as('bootstrapStatus');
	cy.intercept('GET', '**/api/v1/users/me/preferences', { statusCode: 200, body: {} }).as(
		'getPreferences'
	);
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
	cy.intercept('GET', '**/api/v1/skills**', { statusCode: 200, body: [] }).as('listSkills');
}

describe('DE-263 — community skill installer happy path', () => {
	it('lists, searches, reviews the full SKILL.md, and installs with confirm', () => {
		interceptBaseRequests();

		// First load: neither skill installed yet.
		cy.intercept('GET', '**/api/v1/admin/community-skills', {
			statusCode: 200,
			body: catalogBody([leaseReview, ndaTriage])
		}).as('listCatalog');

		cy.visit('/lq-ai/admin/community-skills', {
			onBeforeLoad: (win) => setAuthStorage(win)
		});
		cy.wait('@listCatalog');

		// 1. Catalog renders with source line + honest attestation states.
		cy.contains('h1', 'Community skills').should('exist');
		cy.contains('code', SHA.slice(0, 12)).should('exist');
		cy.contains('td', 'Attested at source repo by: Jane Attorney, NY Bar #12345').should('exist');
		cy.contains('td', 'No attestation declared in SKILL.md').should('exist');

		// 2. Search narrows the list.
		cy.get('input[type="search"]').type('lease');
		cy.contains('.skill-title', 'Lease Review').should('exist');
		cy.contains('.skill-title', 'NDA Triage').should('not.exist');
		cy.get('input[type="search"]').clear();

		// 3. Review opens the full SKILL.md detail.
		cy.intercept('GET', '**/api/v1/admin/community-skills/lease-review', {
			statusCode: 200,
			body: leaseReviewDetail
		}).as('getDetail');
		cy.contains('tr', 'Lease Review').contains('button', 'Review').click();
		cy.wait('@getDetail');
		cy.contains('h3', 'SKILL.md frontmatter').should('exist');
		cy.contains('pre', 'name: lease-review').should('exist');
		cy.contains('pre', 'You are reviewing a commercial lease…').should('exist');
		cy.contains('code', `lq-skills:lease-review@${SHA}`).should('exist');

		// 4. Install with confirm → success banner → installed state.
		cy.intercept('POST', '**/api/v1/admin/community-skills/lease-review/install', {
			statusCode: 201,
			body: installedRow
		}).as('install');
		// Reload after install returns the row as installed.
		cy.intercept('GET', '**/api/v1/admin/community-skills', {
			statusCode: 200,
			body: catalogBody([{ ...leaseReview, installed: true }, ndaTriage])
		}).as('listCatalogAfter');

		cy.on('window:confirm', (message) => {
			expect(message).to.contain('Install community skill "Lease Review"');
			expect(message).to.contain(`lq-skills:lease-review@${SHA}`);
			return true;
		});
		cy.contains('button', 'Install').click();
		cy.wait('@install');
		cy.wait('@listCatalogAfter');

		cy.contains('[role="status"]', 'Installed "Lease Review"').should('exist');
		cy.contains('.installed-badge', 'Installed').should('exist');
	});
});
