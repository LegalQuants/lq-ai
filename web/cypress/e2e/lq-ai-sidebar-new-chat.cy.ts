/// <reference types="cypress" />

function visitExistingChat() {
	const user = {
		id: 'user',
		name: 'Test',
		email: 'user@example.test',
		role: 'member',
		must_change_password: false
	};
	const chat = (id: string) => ({
		id,
		title: id,
		owner_id: user.id,
		project_id: null,
		created_at: '2026-01-01',
		updated_at: '2026-01-01'
	});
	const chats = [
		chat('existing'),
		...Array.from({ length: 8 }, (_, i) => chat(`recent-${i}`)),
		{ ...chat('Older conversation'), updated_at: '2025-01-01' }
	];
	const page = (items: unknown[]) => ({ items, next_cursor: null });

	cy.intercept('**/api/**', (req) => {
		const path = new URL(req.url).pathname.replace(/\/$/, '');
		if (req.method === 'POST' && path === '/api/v1/chats') {
			expect(req.body.project_id).to.equal(null);
			const created = chat('fresh');
			chats.unshift(created);
			req.alias = 'createChat';
			return req.reply(201, created);
		}
		if (req.method === 'GET') {
			if (path === '/api/config')
				return req.reply({ name: 'LQ.AI', features: { enable_websocket: false } });
			if (['/api/v1/users/me', '/api/v1/auths'].includes(path)) return req.reply(user);
			if (path === '/api/v1/users/me/preferences') return req.reply({ autonomous_enabled: false });
			if (path === '/api/v1/chats') return req.reply(page(chats));
			if (path === '/api/v1/chats/existing/messages')
				return req.reply(
					page([
						{
							id: 'old-message',
							chat_id: 'existing',
							role: 'user',
							content: 'Old conversation',
							created_at: '2026-01-01'
						}
					])
				);
			if (path === '/api/v1/chats/fresh/messages') return req.reply(page([]));
			if (path === '/api/v1/models') return req.reply({ data: [] });
			if (path === '/api/v1/admin/bootstrap-status')
				return req.reply({ default_password_active: false });
			if (
				[
					'/api/v1/projects',
					'/api/v1/skills',
					'/api/v1/user-skills',
					'/api/v1/saved-prompts',
					'/api/v1/teams',
					'/api/v1/knowledge-bases'
				].includes(path)
			)
				return req.reply([]);
		}
		return req.reply(404, {});
	});
	cy.visit('/lq-ai/chats?id=existing', {
		onBeforeLoad(win) {
			win.localStorage.setItem('token', 'test-token');
			win.localStorage.setItem('locale', 'en-US');
			win.localStorage.setItem(
				'lq_ai_auth',
				JSON.stringify({ access_token: 'test-token', expires_at: Date.now() + 3600000, user })
			);
		}
	});
}

for (const width of [390, 1440]) {
	it(`starts a fresh chat and reveals the full chat list at ${width}px`, () => {
		cy.viewport(width, 844);
		const narrow = width === 390;
		function openShell() {
			if (narrow) cy.get('[data-testid="lq-shell-sidebar-open"]').click();
		}
		visitExistingChat();
		cy.contains('Old conversation').should('be.visible');
		cy.get('[data-testid="lq-ai-composer-input"]').type('Unsent draft');
		if (narrow)
			cy.get('[data-testid="lq-chat-list-toggle"]').should('have.attr', 'aria-expanded', 'false');
		openShell();
		cy.get('[data-nav-id="new"]').click();
		cy.wait('@createChat');
		cy.location('search').should('eq', '?id=fresh');
		cy.get('[data-testid="lq-ai-chat-header"]').should('contain.text', 'fresh');
		cy.get('[data-testid="lq-ai-composer-input"]').should('have.value', '');
		cy.contains('Old conversation').should('not.exist');
		function openAllChats() {
			openShell();
			cy.get('[data-testid="lq-shell-sidebar"]').should('not.contain.text', 'Older conversation');
			cy.get('a[data-nav-id="all-chats"]').click();
			cy.location('search').should('eq', '');
			cy.get('[data-testid="lq-chat-list-sheet"]')
				.contains('Older conversation')
				.should('be.visible');
			cy.focused().should('have.attr', 'data-testid', 'lq-ai-new-chat-btn');
			cy.get('@createChat.all').should('have.length', 1);
		}

		openAllChats(); // From the selected new chat.
		if (narrow) {
			cy.focused().trigger('keydown', { key: 'Escape' });
			cy.get('[data-testid="lq-chat-list-sheet"]').should('not.be.visible');
			cy.focused().should('have.attr', 'data-testid', 'lq-chat-list-toggle');
			openAllChats(); // From the same bare route after dismissing the drawer.

			// A new tab follows the native link without an in-page click.
			cy.visit('/lq-ai/chats?view=all');
			cy.get('[data-testid="lq-chat-list-sheet"]')
				.contains('Older conversation')
				.should('be.visible');
			cy.focused().should('have.attr', 'data-testid', 'lq-ai-new-chat-btn');
			cy.location('search').should('eq', '');
			cy.visit('/lq-ai/chats');
			cy.get('[data-testid="lq-chat-list-toggle"]').should('have.attr', 'aria-expanded', 'false');
		}
	});
}
