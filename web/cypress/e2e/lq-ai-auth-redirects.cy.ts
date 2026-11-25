/// <reference types="cypress" />

describe('client-side redirects from the protected shell', () => {
	const user = {
		id: 'fixture',
		email: 'user@example.test',
		role: 'member',
		must_change_password: true
	};

	function visitHome(status: number) {
		cy.intercept('GET', '**/api/config', { name: 'LQ.AI', features: { enable_websocket: false } });
		cy.intercept('GET', '**/api/v1/auths/', user);
		cy.intercept('GET', '**/api/v1/users/me/preferences', { autonomous_enabled: false });
		cy.intercept('GET', '**/api/v1/users/me', {
			statusCode: status,
			body:
				status === 200
					? user
					: { detail: { code: status === 403 ? 'password_change_required' : 'unauthorized' } }
		});
		cy.intercept('GET', '**/api/v1/projects*', []).as('protectedProjects');
		cy.visit('/lq-ai', {
			onBeforeLoad(win) {
				win.localStorage.setItem('locale', 'en-US');
				win.localStorage.setItem('token', 'fixture');
				win.localStorage.setItem(
					'lq_ai_auth',
					JSON.stringify({
						access_token: 'fixture',
						expires_at: Date.now() + 3600000,
						user: { ...user, must_change_password: false }
					})
				);
			}
		});
	}

	for (const status of [200, 403]) {
		it(`renders the password form after the server requires a change (HTTP ${status})`, () => {
			visitHome(status);
			cy.location('pathname').should('eq', '/lq-ai/change-password');
			cy.get('[data-testid="lq-ai-change-password-form"]').should('be.visible');
			cy.get('[data-testid="lq-shell-sidebar"]').should('not.exist');
			cy.get('@protectedProjects.all').should('have.length', 0);

			cy.intercept('POST', '**/api/v1/auth/change-password', { statusCode: 204 }).as(
				'changePassword'
			);
			cy.get('[data-testid="lq-ai-current-password"]').type('previous-fixture');
			cy.get('[data-testid="lq-ai-new-password"]').type('replacement-fixture');
			cy.get('[data-testid="lq-ai-confirm-password"]').type('replacement-fixture');
			cy.get('[data-testid="lq-ai-change-password-submit"]').click();
			cy.wait('@changePassword');
			cy.location('pathname').should('eq', '/lq-ai/login');
			cy.get('[data-testid="lq-ai-login-email"]').should('be.visible');
			cy.window().then((win) => expect(win.localStorage.getItem('lq_ai_auth')).to.be.null);
			cy.get('@protectedProjects.all').should('have.length', 0);
		});
	}

	it('shows sign-in when the server rejects the session', () => {
		visitHome(401);
		cy.location('pathname').should('eq', '/lq-ai/login');
		cy.get('[data-testid="lq-ai-login-email"]').should('be.visible');
		cy.get('[data-testid="lq-shell-sidebar"]').should('not.exist');
		cy.get('@protectedProjects.all').should('have.length', 0);
	});
});
