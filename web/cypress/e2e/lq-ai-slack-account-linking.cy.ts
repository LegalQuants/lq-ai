/// <reference types="cypress" />
/** Browser acceptance of the confirmation/unlink contract. API security and
 * transaction acceptance run against PostgreSQL in test_slack_account_linking.py.
 */
import { rejectUnexpectedApiRequests } from '../support/mocked-api';

const token = 'a'.repeat(43);
const base = '/api/v1/integrations/slack';
const user = {
	id: '11111111-1111-4111-8111-111111111111',
	email: 'alice@example.com',
	display_name: 'Alice',
	is_admin: false,
	role: 'member',
	mfa_enabled: false,
	must_change_password: false,
	created_at: '2026-01-01T00:00:00Z'
};
const preview = {
	team_id: 'T0123',
	team_name: 'Test Legal',
	slack_user_id: 'U111',
	expires_at: '2099-01-01T00:00:00Z'
};
const account = {
	id: '22222222-2222-4222-8222-222222222222',
	...preview,
	created_at: '2026-11-22T00:00:00Z'
};

function visitLink(signedIn = true) {
	cy.visit(`/lq-ai/slack/link#token=${token}`, {
		onBeforeLoad(win) {
			win.sessionStorage.clear();
			win.localStorage.clear();
			if (signedIn)
				win.localStorage.setItem(
					'lq_ai_auth',
					JSON.stringify({
						access_token: 'test-access',
						refresh_token: 'test-refresh',
						expires_at: Date.now() + 3600000,
						user
					})
				);
		}
	});
}

describe('Explicit Slack account linking', () => {
	beforeEach(() => {
		rejectUnexpectedApiRequests();
		cy.intercept('POST', '**/api/v1/auth/refresh', {
			access_token: 'test-access',
			refresh_token: 'test-refresh',
			expires_in: 3600
		});
		cy.intercept('GET', '**/api/config', { name: 'LQ.AI', features: { enable_websocket: false } });
		cy.intercept('GET', '**/api/v1/users/me', user);
		cy.intercept('GET', '**/api/v1/users/me/preferences', { autonomous_enabled: false });
		cy.intercept('POST', `**${base}/link-requests/preview`, (req) => {
			expect(req.body).to.deep.equal({ token });
			req.reply(preview);
		}).as('preview');
		cy.intercept('GET', `**${base}/account-links`, []).as('accounts');
	});

	it('previews without linking and requires an explicit confirmation click', () => {
		let confirmations = 0;
		cy.intercept('POST', `**${base}/link-requests/confirm`, (req) => {
			confirmations++;
			expect(req.body).to.deep.equal({ token });
			expect(req.headers.authorization).to.equal('Bearer test-access');
			req.reply(account);
		}).as('confirm');
		visitLink();
		cy.wait('@preview');
		cy.contains('Test Legal').should('be.visible');
		cy.contains('U111').should('be.visible');
		cy.contains('alice@example.com').should('be.visible');
		cy.location('hash').should('equal', '');
		cy.then(() => expect(confirmations).to.equal(0));
		cy.contains('button', 'Confirm account link').click();
		cy.wait('@confirm');
		cy.contains('Your Slack account is linked.').should('be.visible');
		cy.window().then((win) =>
			expect(win.sessionStorage.getItem('lq_ai_pending_slack_link')).to.equal(null)
		);
	});

	it('resumes the same confirmation after normal sign-in without a token in the login URL', () => {
		cy.intercept('POST', '**/api/v1/auth/login', {
			access_token: 'test-access',
			refresh_token: 'test-refresh',
			expires_in: 3600,
			user
		}).as('login');
		visitLink(false);
		cy.location('pathname').should('equal', '/lq-ai/login');
		cy.location('href').should('not.contain', token);
		cy.get('[data-testid="lq-ai-login-email"]').type('alice@example.com');
		cy.get('[data-testid="lq-ai-login-password"]').type('Test-password-1!');
		cy.contains('button', 'Sign in').click();
		cy.wait('@login');
		cy.wait('@preview');
		cy.contains('button', 'Confirm account link').should('be.visible');
	});

	it('cancels without confirmation and clears the pending link', () => {
		visitLink();
		cy.wait('@preview');
		cy.contains('button', 'Cancel').click();
		cy.location('pathname').should('equal', '/lq-ai/settings/account');
		cy.contains('No Slack accounts linked.').should('be.visible');
		cy.window().then((win) =>
			expect(win.sessionStorage.getItem('lq_ai_pending_slack_link')).to.equal(null)
		);
	});

	it('shows an expired or consumed link without a confirmation control', () => {
		cy.intercept('POST', `**${base}/link-requests/preview`, {
			statusCode: 404,
			body: { detail: { code: 'not_found', message: 'Unavailable' } }
		});
		visitLink();
		cy.contains('[role="alert"]', 'Run /lq help').should('be.visible');
		cy.contains('button', 'Confirm account link').should('not.exist');
	});

	it('does not show success when confirmation is refused', () => {
		cy.intercept('POST', `**${base}/link-requests/confirm`, {
			statusCode: 409,
			body: { detail: { code: 'conflict', message: 'Already linked' } }
		});
		visitLink();
		cy.wait('@preview');
		cy.contains('button', 'Confirm account link').click();
		cy.contains('[role="alert"]', 'Unable to link').should('be.visible');
		cy.contains('Your Slack account is linked.').should('not.exist');
	});

	it('unlinks the selected account from account settings', () => {
		cy.intercept('GET', `**${base}/account-links`, [account]);
		cy.intercept('DELETE', `**${base}/account-links/${account.id}`, { statusCode: 204 }).as(
			'unlink'
		);
		visitLink();
		cy.wait('@preview');
		cy.contains('button', 'Cancel').click();
		cy.contains('button', 'Unlink').click();
		cy.wait('@unlink');
		cy.contains('Slack account unlinked.').should('be.visible');
		cy.contains('No Slack accounts linked.').should('be.visible');
	});
});
