/**
 * M3-0.1 / DE-283 — Fresh-install login UX.
 *
 * Verifies that the login screen surfaces an actionable bootstrap-password
 * hint after a failed login attempt against a fresh-install deployment, and
 * stays silent once the operator has rotated.
 *
 * The hint is conditional on `GET /api/v1/admin/bootstrap-status` reporting
 * `default_password_active=true`. We mock that endpoint with `cy.intercept`
 * so each scenario can pin the state explicitly instead of relying on the
 * mutable state of the live stack.
 *
 * Run requires a live stack:
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/m3-0-fresh-install-login.cy.ts'
 *
 * No matter / chat / KB scaffolding is needed — this spec exercises the
 * login surface only.
 */

/// <reference types="cypress" />

const BOOTSTRAP_HINT_COMMAND =
	'docker compose logs api 2>&1 | grep "First-run admin password"';

describe('M3-0.1 / DE-283 — fresh-install login UX', () => {
	it('initial page load shows no bootstrap hint (no 401 yet)', () => {
		// Even with fresh-install state, the hint is gated on a failed login
		// attempt — operators who have credentials shouldn't see it.
		cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
			statusCode: 200,
			body: { default_password_active: true, logs_hint: BOOTSTRAP_HINT_COMMAND }
		}).as('bootstrapStatus');

		cy.visit('/lq-ai/login');
		cy.get('[data-testid="lq-ai-bootstrap-hint"]').should('not.exist');
	});

	it('first 401 against fresh-install state renders the bootstrap hint', () => {
		cy.intercept('POST', '**/api/v1/auth/login', {
			statusCode: 401,
			body: { detail: { code: 'invalid_credentials', message: 'Invalid email or password.' } }
		}).as('login');
		cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
			statusCode: 200,
			body: { default_password_active: true, logs_hint: BOOTSTRAP_HINT_COMMAND }
		}).as('bootstrapStatus');

		cy.visit('/lq-ai/login');
		cy.get('[data-testid="lq-ai-login-email"]').type('admin@lq.ai');
		cy.get('[data-testid="lq-ai-login-password"]').type('wrong-password');
		cy.get('[data-testid="lq-ai-login-submit"]').click();

		cy.wait('@login');
		cy.wait('@bootstrapStatus');

		cy.get('[data-testid="lq-ai-login-error"]').should('be.visible');
		cy.get('[data-testid="lq-ai-bootstrap-hint"]').should('be.visible');
		cy.get('[data-testid="lq-ai-bootstrap-hint-command"]')
			.should('be.visible')
			.and('contain.text', 'docker compose logs api')
			.and('contain.text', 'First-run admin password');
	});

	it('first 401 against rotated deployment does not render the bootstrap hint', () => {
		cy.intercept('POST', '**/api/v1/auth/login', {
			statusCode: 401,
			body: { detail: { code: 'invalid_credentials', message: 'Invalid email or password.' } }
		}).as('login');
		cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
			statusCode: 200,
			body: { default_password_active: false, logs_hint: BOOTSTRAP_HINT_COMMAND }
		}).as('bootstrapStatus');

		cy.visit('/lq-ai/login');
		cy.get('[data-testid="lq-ai-login-email"]').type('admin@lq.ai');
		cy.get('[data-testid="lq-ai-login-password"]').type('still-wrong');
		cy.get('[data-testid="lq-ai-login-submit"]').click();

		cy.wait('@login');
		cy.wait('@bootstrapStatus');

		// Generic 401 surfaces, but the hint stays hidden — the operator has
		// already rotated; surfacing the bootstrap path would be noise.
		cy.get('[data-testid="lq-ai-login-error"]').should('be.visible');
		cy.get('[data-testid="lq-ai-bootstrap-hint"]').should('not.exist');
	});

	it('bootstrap-status probe failure does not mask the generic 401', () => {
		// If the probe itself errors, the login UI must still show the
		// underlying auth error — a hint-fetch failure is not a substitute
		// for telling the operator their credentials were rejected.
		cy.intercept('POST', '**/api/v1/auth/login', {
			statusCode: 401,
			body: { detail: { code: 'invalid_credentials', message: 'Invalid email or password.' } }
		}).as('login');
		cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
			statusCode: 500,
			body: { detail: { code: 'internal_error', message: 'probe failed' } }
		}).as('bootstrapStatus');

		cy.visit('/lq-ai/login');
		cy.get('[data-testid="lq-ai-login-email"]').type('admin@lq.ai');
		cy.get('[data-testid="lq-ai-login-password"]').type('still-wrong');
		cy.get('[data-testid="lq-ai-login-submit"]').click();

		cy.wait('@login');
		cy.wait('@bootstrapStatus');

		cy.get('[data-testid="lq-ai-login-error"]').should('be.visible');
		cy.get('[data-testid="lq-ai-bootstrap-hint"]').should('not.exist');
	});
});
