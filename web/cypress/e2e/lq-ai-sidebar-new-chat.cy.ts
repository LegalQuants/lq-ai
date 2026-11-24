/// <reference types="cypress" />

it('starts a fresh conversation from New on the chat route and uses All chats only to navigate', () => {
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
	const chats = [chat('existing')];
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
	cy.contains('Old conversation').should('be.visible');
	cy.get('[data-testid="lq-ai-composer-input"]').type('Unsent draft');
	cy.get('[data-nav-id="new"]').click();
	cy.wait('@createChat');
	cy.location('search').should('eq', '?id=fresh');
	cy.get('[data-testid="lq-ai-chat-header"]').should('contain.text', 'fresh');
	cy.get('[data-testid="lq-ai-composer-input"]').should('have.value', '');
	cy.contains('Old conversation').should('not.exist');
	cy.get('[data-nav-id="all-chats"]').click();
	cy.location('search').should('eq', '');
	cy.get('@createChat.all').should('have.length', 1);
});
