/// <reference types="cypress" />

import { rejectUnexpectedApiRequests } from '../support/mocked-api';

const chat = { id: 'review', title: 'Notice review', project_id: null, archived_at: null };
const user = { id: 'owner', display_name: 'Reviewer', role: 'admin', must_change_password: false };
const toggle = '#chat-list-toggle';
const notice = '[data-testid="lq-ai-run-active-notice"]';

describe('Phone Chats in the sidebar shell', () => {
	it('keeps the list reachable and the uncertainty notice readable after choosing a chat', () => {
		rejectUnexpectedApiRequests();
		cy.intercept('GET', '**/api/config', {
			body: { name: 'LQ.AI', features: { enable_websocket: false } }
		});
		cy.intercept('GET', '**/api/version', { body: { version: 'test' } });
		cy.intercept('GET', '**/api/v1/users/me', { body: user });
		cy.intercept('GET', '**/api/v1/users/me/preferences', { body: { autonomous_enabled: false } });
		cy.intercept('GET', '**/api/v1/chats*', { body: { items: [chat], next_cursor: null } });
		cy.intercept('GET', '**/api/v1/saved-prompts*', { body: [] });
		cy.intercept('GET', '**/api/v1/chats/review/ledger*', {
			body: { chat_id: chat.id, entries: [], gates: [] }
		});
		cy.intercept('GET', '**/api/v1/projects*', { body: [] });
		cy.intercept('GET', '**/api/v1/models*', { body: { data: [] } });
		cy.intercept('GET', '**/api/v1/skills*', { body: [] });
		cy.intercept('GET', '**/api/v1/skills/autocomplete*', { body: [] });
		cy.intercept('GET', '**/api/v1/chats/review/messages*', {
			body: { items: [], next_cursor: null }
		});
		cy.intercept('GET', '**/api/v1/chats/review/run-profiles*', {
			body: {
				chat_id: chat.id,
				project_id: null,
				profiles: [],
				active_run: {
					root_id: 'run',
					profile: 'review',
					status: 'uncertain',
					chat_id: chat.id,
					chat_title: chat.title
				}
			}
		});

		cy.viewport(390, 844);
		cy.visit('/lq-ai/chats', {
			onBeforeLoad(win) {
				win.localStorage.setItem('lq-ai.shell', 'sidebar');
				win.localStorage.setItem(
					'lq_ai_auth',
					JSON.stringify({
						user,
						access_token: 'fixture',
						expires_at: Date.now() + 3600000
					})
				);
			}
		});
		cy.get(toggle).should('have.attr', 'aria-expanded', 'false');
		cy.get(toggle).focus().type('{enter}');
		cy.contains('#chat-list-content button', chat.title).focus().type('{enter}');
		cy.get(toggle).should('be.focused').and('have.attr', 'aria-expanded', 'false');
		cy.contains(notice + ' .line', 'a provider call has no confirmed outcome').should(($line) => {
			const el = $line[0];
			const rect = el.getBoundingClientRect();
			expect(rect.left).to.be.at.least(0);
			expect(rect.right).to.be.at.most(390);
			expect(rect.top).to.be.at.least(0);
			expect(rect.bottom).to.be.at.most(844);
			expect(rect.width).to.be.greaterThan(200);
			expect(rect.height / parseFloat(getComputedStyle(el).lineHeight)).to.be.at.most(4);
		});
		cy.get(toggle).click();
		cy.contains('#chat-list-content button', chat.title).should('be.visible');
		cy.get(toggle).click();
		cy.get(notice).should('be.visible');
	});
});
