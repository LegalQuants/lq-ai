/**
 * M3-B2 — Word add-in OAuth dialog page.
 *
 * Verifies that the standalone OAuth dialog page at
 * `/lq-ai/word-addin/oauth-start`:
 *
 *   1. Renders without the global LQ.AI nav (the layout-reset trick at
 *      `+layout@.svelte` strips the parent layout chain).
 *   2. Loads Office.js and unblocks the sign-in button once Office.onReady
 *      fires.
 *   3. Posts an `oauth-success` payload to the parent via
 *      `Office.context.ui.messageParent` after a successful login.
 *   4. Posts an `oauth-error` payload when the authenticated user must
 *      change their password (Word add-in doesn't have a change-password
 *      UI in M3-B2 — they're redirected to the web app).
 *   5. Surfaces a 401 error inline without messaging the parent.
 *
 * Office.js is mocked via `cy.window` + `cy.stub` so the test runs
 * without an Office host. The dialog page only uses
 * `Office.onReady()` and `Office.context.ui.messageParent()`, so a
 * minimal mock covers both surfaces.
 *
 * Run requires a live stack:
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/m3-b2-word-addin-oauth.cy.ts'
 */

/// <reference types="cypress" />

describe('M3-B2 — Word add-in OAuth dialog page', () => {
	beforeEach(() => {
		// Prevent the real Office.js CDN load from racing the test's mock.
		// We intercept the script request with a no-op response.
		cy.intercept('https://appsforoffice.microsoft.com/lib/1/hosted/office.js', {
			statusCode: 200,
			body: '/* mocked */'
		});
	});

	it('renders the dialog form without the global LQ.AI nav chrome', () => {
		cy.visit('/lq-ai/word-addin/oauth-start', {
			onBeforeLoad: (win) => {
				// Pre-install the Office mock so the page sees it on mount.
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				(win as any).Office = {
					onReady: (cb: () => void) => cb(),
					context: { ui: { messageParent: () => undefined } }
				};
			}
		});

		// The dialog page's own card UI.
		cy.contains('Sign in to LQ.AI').should('be.visible');
		cy.get('input[type="email"]').should('be.visible');
		cy.get('input[type="password"]').should('be.visible');

		// The standard LQ.AI app shell should NOT be present (layout reset).
		cy.get('nav[aria-label="LQ.AI primary navigation"]').should('not.exist');
		cy.get('[data-testid="lq-ai-app-shell"]').should('not.exist');
	});

	it('posts oauth-success to parent on successful login', () => {
		cy.intercept('POST', '**/api/v1/auth/login', {
			statusCode: 200,
			body: {
				access_token: 'test-access',
				token_type: 'Bearer',
				expires_in: 3600,
				refresh_token: 'test-refresh',
				user: {
					id: '11111111-1111-1111-1111-111111111111',
					email: 'alice@example.com',
					display_name: 'Alice',
					is_admin: false,
					role: 'member',
					mfa_enabled: false,
					must_change_password: false,
					created_at: '2026-05-21T00:00:00Z'
				}
			}
		}).as('login');

		cy.visit('/lq-ai/word-addin/oauth-start', {
			onBeforeLoad: (win) => {
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				(win as any).__messageParentCalls = [];
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				(win as any).Office = {
					onReady: (cb: () => void) => cb(),
					context: {
						ui: {
							messageParent: (msg: string) => {
								// eslint-disable-next-line @typescript-eslint/no-explicit-any
								(win as any).__messageParentCalls.push(msg);
							}
						}
					}
				};
			}
		});

		cy.get('input[type="email"]').type('alice@example.com');
		cy.get('input[type="password"]').type('p4ssword!');
		cy.contains('button', 'Sign in').click();

		cy.wait('@login');

		cy.window().its('__messageParentCalls').should('have.length', 1);
		cy.window()
			.its('__messageParentCalls')
			.then((calls: string[]) => {
				const parsed = JSON.parse(calls[0]);
				expect(parsed.type).to.equal('oauth-success');
				expect(parsed.login.access_token).to.equal('test-access');
				expect(parsed.login.user.email).to.equal('alice@example.com');
			});
	});

	it('posts oauth-error when the user must change their password', () => {
		cy.intercept('POST', '**/api/v1/auth/login', {
			statusCode: 200,
			body: {
				access_token: 'test-access',
				token_type: 'Bearer',
				expires_in: 3600,
				refresh_token: 'test-refresh',
				user: {
					id: '11111111-1111-1111-1111-111111111111',
					email: 'admin@lq.ai',
					is_admin: true,
					mfa_enabled: false,
					must_change_password: true,
					created_at: '2026-05-21T00:00:00Z'
				}
			}
		}).as('login');

		cy.visit('/lq-ai/word-addin/oauth-start', {
			onBeforeLoad: (win) => {
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				(win as any).__messageParentCalls = [];
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				(win as any).Office = {
					onReady: (cb: () => void) => cb(),
					context: {
						ui: {
							messageParent: (msg: string) => {
								// eslint-disable-next-line @typescript-eslint/no-explicit-any
								(win as any).__messageParentCalls.push(msg);
							}
						}
					}
				};
			}
		});

		cy.get('input[type="email"]').type('admin@lq.ai');
		cy.get('input[type="password"]').type('default-pw');
		cy.contains('button', 'Sign in').click();

		cy.wait('@login');

		cy.window()
			.its('__messageParentCalls')
			.then((calls: string[]) => {
				expect(calls).to.have.length(1);
				const parsed = JSON.parse(calls[0]);
				expect(parsed.type).to.equal('oauth-error');
				expect(parsed.reason).to.include('change your password');
			});
	});

	it('surfaces 401 inline without messaging the parent', () => {
		cy.intercept('POST', '**/api/v1/auth/login', {
			statusCode: 401,
			body: {
				detail: { code: 'invalid_credentials', message: 'Invalid email or password.' }
			}
		}).as('login');

		cy.visit('/lq-ai/word-addin/oauth-start', {
			onBeforeLoad: (win) => {
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				(win as any).__messageParentCalls = [];
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				(win as any).Office = {
					onReady: (cb: () => void) => cb(),
					context: {
						ui: {
							messageParent: (msg: string) => {
								// eslint-disable-next-line @typescript-eslint/no-explicit-any
								(win as any).__messageParentCalls.push(msg);
							}
						}
					}
				};
			}
		});

		cy.get('input[type="email"]').type('alice@example.com');
		cy.get('input[type="password"]').type('wrong');
		cy.contains('button', 'Sign in').click();

		cy.wait('@login');
		cy.contains('Invalid email or password.').should('be.visible');
		cy.window().its('__messageParentCalls').should('have.length', 0);
	});
});
