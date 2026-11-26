/// <reference types="cypress" />

const sheet = '[data-testid="lq-chat-list-sheet"]';
const globalLink = 'a[data-nav-id="all-chats"]';
const project = { id: 'matter-1', name: 'Review matter', updated_at: '2026-01-01' };

function visitFixture(route = '/lq-ai/chats?id=existing', beforeVisit = () => {}) {
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
		project_id: id === 'existing' ? project.id : null,
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
			if (path === '/api/v1/chats') {
				const scope = new URL(req.url).searchParams.get('project_id');
				return req.reply(page(scope ? chats.filter((c) => c.project_id === scope) : chats));
			}
			if (path === '/api/v1/projects') return req.reply([project]);
			if (path === '/api/v1/projects/matter-1') return req.reply(project);
			if (path === '/api/v1/playbooks') return req.reply([]);
			if (path === '/api/v1/skills') return req.reply([]);
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
	beforeVisit();
	cy.visit(route, {
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
		visitFixture();
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

it('opens the full list through the Home card on a compact screen', () => {
	cy.viewport(390, 844);
	visitFixture('/lq-ai');
	cy.intercept('GET', '**/api/v1/skills', { statusCode: 503, body: {} });
	cy.get('[data-testid="lq-ai-recent-activity"]').contains('a', 'View all chats').click();
	cy.get(sheet).contains('button', 'Older conversation').should('be.visible');
	cy.focused().should('have.attr', 'data-testid', 'lq-ai-new-chat-btn');
});

it('distinguishes a pending list, a failed list and a successful empty list', () => {
	cy.viewport(1440, 900);
	visitFixture('/lq-ai/playbooks');
	cy.get('[data-testid="lq-playbooks-empty"]').should('be.visible');
	let release: () => void;
	const pending = new Cypress.Promise<void>((resolve) => {
		release = resolve;
	});
	cy.intercept({ pathname: '/api/v1/chats', query: { limit: '100' }, times: 1 }, (req) =>
		pending.then(() => req.reply(503, {}))
	);
	cy.get(globalLink).click();
	cy.get(sheet).contains('Loading chats').should('be.visible');
	cy.get(sheet).should('not.contain.text', 'No chats yet');
	cy.then(() => release());
	cy.get(sheet).contains('Could not load chats.').should('be.visible');
	cy.intercept(
		{ pathname: '/api/v1/chats', query: { limit: '100' } },
		{ items: [], next_cursor: null }
	);
	cy.get(sheet).contains('button', 'Retry').click();
	cy.get(sheet).contains('No chats yet').should('be.visible');
});

it('clears the local project filter on a global link and retains the inner reset', () => {
	cy.viewport(1440, 900);
	visitFixture();
	cy.get(sheet).find('[data-testid="lq-ai-project-matter-1"]').click();
	cy.get(sheet).should('not.contain.text', 'Older conversation');
	cy.get(sheet)
		.contains('button', /^All chats$/)
		.click();
	cy.get(sheet).contains('button', 'Older conversation').should('be.visible');
	cy.get(sheet).find('[data-testid="lq-ai-project-matter-1"]').click();
	cy.get(globalLink).click();
	cy.get(sheet).contains('button', 'Older conversation').should('be.visible');
});

for (const route of ['/lq-ai/chats?project_id=matter-1', '/lq-ai/matters/matter-1']) {
	it(`shows only this matter's chats on ${route} and restores unrelated rows on All chats`, () => {
		cy.viewport(390, 844);
		visitFixture(route);
		cy.get('#matter-chats-toggle').click();
		cy.get(sheet).contains('button', 'existing').should('be.visible');
		cy.get(sheet).should('not.contain.text', 'Older conversation');
		cy.get('[data-testid="lq-shell-sidebar-open"]').click();
		cy.get(globalLink).click();
		cy.get(sheet).contains('button', 'Older conversation').should('be.visible').click();
		cy.get('[data-testid="lq-ai-chat-header"]').should('contain.text', 'Older conversation');
	});
}

it('ignores a pending matter list after the global list has loaded', () => {
	cy.viewport(1440, 900);
	let release: () => void;
	const pending = new Cypress.Promise<void>((resolve) => {
		release = resolve;
	});
	visitFixture('/lq-ai/chats?project_id=matter-1', () => {
		cy.intercept({ pathname: '/api/v1/chats', query: { project_id: project.id } }, (req) =>
			pending.then(() => req.reply({ items: [], next_cursor: null }))
		).as('oldList');
	});
	cy.get(sheet).contains('Loading chats').should('be.visible');
	cy.get(globalLink).click();
	cy.get(sheet).contains('button', 'Older conversation').should('be.visible');
	cy.then(() => release());
	cy.wait('@oldList');
	cy.get(sheet).contains('button', 'Older conversation').click();
	cy.get('[data-testid="lq-ai-chat-header"]').should('contain.text', 'Older conversation');
});

it('opens the conversation named by each Home recent chat link', () => {
	cy.viewport(390, 844);
	visitFixture('/lq-ai');
	for (const id of ['existing', 'recent-2']) {
		cy.get('[data-testid="lq-ai-recent-activity"]').contains('a.chat-row', id).click();
		cy.location('search').should('eq', '?id=' + id);
		cy.get('[data-testid="lq-ai-chat-header"]').should('contain.text', id);
		cy.go('back');
	}
});
