/**
 * Item 1.6 — Matter-intake E2E: describe → session → receipt.
 *
 * Intercept-based (deterministic; no real seed data), mirroring
 * m4-autonomous.cy.ts. Two scenarios:
 *
 *   1. Describe → session → receipt — fill the matter description, pick a
 *      skill, submit; POST /autonomous/run-now carries `query`; the app
 *      navigates to the session receipt page.
 *   2. Validation — submitting without a description surfaces the inline
 *      field error and does NOT fire the run-now endpoint.
 *
 * Auth strategy: lq_ai_auth in localStorage + intercepted /users/me and
 * preferences, exactly as in m4-autonomous.cy.ts.
 *
 * Run:
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/matter-intake.cy.ts'
 */

/// <reference types="cypress" />

const SESSION_ID = 'sess-0016-aaaa-bbbb-cccc-dddddddddddd';
const MATTER_QUERY =
	'Review the Acme NDA for a mutual confidentiality carve-out and flag survival terms longer than 3 years.';

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

const mockSession = {
	id: SESSION_ID,
	user_id: 'u1',
	project_id: null,
	trigger_kind: 'manual' as const,
	trigger_ref: null,
	current_phase: 'intake' as const,
	halt_state: 'running' as const,
	max_cost_usd: '5.00',
	cost_total_usd: '0.00',
	cost_cap_reached: false,
	idle_halt_minutes: 30,
	last_activity_at: '2026-07-25T10:00:00Z',
	status: 'running' as const,
	params: { skill_ref: 'nda-review', query: MATTER_QUERY },
	result: null,
	error: null,
	created_at: '2026-07-25T09:55:00Z',
	updated_at: '2026-07-25T10:00:00Z',
	completed_at: null
};

const mockReceipt = {
	session_id: SESSION_ID,
	trigger_kind: 'manual',
	status: 'running',
	halt_state: 'running',
	current_phase: 'intake',
	cost_total_usd: 0.0,
	max_cost_usd: 5.0,
	cost_cap_reached: false,
	created_at: '2026-07-25T09:55:00Z',
	completed_at: null,
	phase_transitions: [{ to_phase: 'intake', timestamp: '2026-07-25T09:55:01Z' }],
	tool_calls: [],
	terminal_reason: null
};

function setAuthStorage(win: Window): void {
	win.localStorage.setItem(
		'lq_ai_auth',
		JSON.stringify({
			access_token: 'fake-token-1-6',
			refresh_token: null,
			expires_at: Date.now() + 3600 * 1000,
			user: mockUser
		})
	);
	win.localStorage.setItem(
		'lq-ai:preferences-cache',
		JSON.stringify({
			reasoning_visibility: 'disclosure',
			featured_tools: 'prominent',
			workspace_layout: 'three_pane',
			trust_pills: 'labels',
			provenance_pills: 'always',
			autonomous_enabled: true
		})
	);
}

function interceptBaseRequests(): void {
	cy.intercept('GET', '**/api/v1/users/me', { statusCode: 200, body: mockUser }).as('getMe');
	cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
		statusCode: 200,
		body: { default_password_active: false, logs_hint: '' }
	}).as('bootstrapStatus');
	cy.intercept('GET', '**/api/v1/users/me/preferences', {
		statusCode: 200,
		body: {
			reasoning_visibility: 'disclosure',
			featured_tools: 'prominent',
			workspace_layout: 'three_pane',
			trust_pills: 'labels',
			provenance_pills: 'always',
			autonomous_enabled: true
		}
	}).as('getPreferences');
	// Incidental calls the shell/layout may trigger.
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
	cy.intercept('GET', '**/api/v1/autonomous/notifications**', {
		statusCode: 200,
		body: { notifications: [], total_count: 0, limit: 50, offset: 0 }
	}).as('listNotifications');
	// Intake-page picker lists.
	cy.intercept('GET', '**/api/v1/skills**', {
		statusCode: 200,
		body: [{ name: 'nda-review', title: 'NDA Review', description: 'Review an NDA' }]
	}).as('listSkills');
	cy.intercept('GET', '**/api/v1/playbooks**', { statusCode: 200, body: [] }).as('listPlaybooks');
	cy.intercept('GET', '**/api/v1/knowledge-bases**', { statusCode: 200, body: [] }).as('listKbs');
	cy.intercept('GET', '**/api/v1/projects**', { statusCode: 200, body: [] }).as('listProjects');
}

describe('Item 1.6 — Matter intake: describe → session → receipt', () => {
	beforeEach(() => {
		interceptBaseRequests();
	});

	it('1: Fill the description, pick a skill, submit → run-now carries query → receipt page', () => {
		cy.intercept('POST', '**/api/v1/autonomous/run-now', {
			statusCode: 201,
			body: mockSession
		}).as('runNow');

		// The receipt page the intake navigates to issues a GET for the session.
		cy.intercept('GET', `**/api/v1/autonomous/sessions/${SESSION_ID}`, {
			statusCode: 200,
			body: { session: mockSession, receipt: mockReceipt }
		}).as('getSession');

		cy.visit('/lq-ai/autonomous/matters', {
			onBeforeLoad: (win) => setAuthStorage(win)
		});

		// The intake page heading.
		cy.contains('h1', 'Describe your matter', { timeout: 10000 }).should('exist');

		// Describe the matter.
		cy.get('#matter-query').type(MATTER_QUERY, { delay: 0 });

		// Skill is the default target — pick the seeded skill.
		cy.get('select[aria-label="Select skill"]', { timeout: 10000 }).select('nda-review');

		// Submit.
		cy.contains('button', 'Run on this matter').click();

		// The run-now body carries the matter description as `query`.
		cy.wait('@runNow').its('request.body').should('deep.include', {
			query: MATTER_QUERY,
			skill_ref: 'nda-review'
		});

		// On 201 the app navigates to the new session's receipt (plan trace).
		cy.url({ timeout: 10000 }).should('include', `/lq-ai/autonomous/sessions/${SESSION_ID}`);
		cy.contains('h1', 'Session receipt').should('exist');
	});

	it('2: Submitting without a description shows the inline error and does not call run-now', () => {
		let runNowCalled = false;
		cy.intercept('POST', '**/api/v1/autonomous/run-now', () => {
			runNowCalled = true;
		}).as('runNowGuard');

		cy.visit('/lq-ai/autonomous/matters', {
			onBeforeLoad: (win) => setAuthStorage(win)
		});

		cy.contains('h1', 'Describe your matter', { timeout: 10000 }).should('exist');

		// Pick a skill but leave the description blank.
		cy.get('select[aria-label="Select skill"]', { timeout: 10000 }).select('nda-review');
		cy.contains('button', 'Run on this matter').click();

		// Inline field error on the description; endpoint never fired.
		cy.get('[role="alert"]').should('contain', 'Describe the matter');
		cy.url().should('include', '/lq-ai/autonomous/matters');
		cy.then(() => {
			expect(runNowCalled).to.equal(false);
		});
	});
});
