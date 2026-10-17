/// <reference types="cypress" />

// The lq-ai- prefix selects the existing LQ.AI support setup (no upstream signup).
// Fully intercepted regressions: no backend writes, provider keys or real login.
const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';
const user = {
	id: 'user',
	email: 'test@example.test',
	display_name: 'Test',
	is_admin: true,
	role: 'admin',
	must_change_password: false,
	mfa_enabled: false
};
const prefs = {
	reasoning_visibility: 'disclosure',
	featured_tools: 'prominent',
	workspace_layout: 'three_pane',
	trust_pills: 'labels',
	provenance_pills: 'always',
	autonomous_enabled: true
};
const project = (id: string) => ({
	id,
	name: id === A ? 'Matter A' : 'Matter B',
	slug: id,
	owner_id: 'user',
	description: '',
	privileged: false,
	minimum_inference_tier: null,
	attached_file_ids: [],
	attached_skill_names: [],
	archived_at: null,
	created_at: '2026-07-01T00:00:00Z',
	updated_at: '2026-07-01T00:00:00Z'
});
const proposal = (id: string, project_id = A) => ({
	id,
	project_id,
	user_id: 'user',
	precedent_id: 'precedent',
	suggested_md: `Context ${id}`,
	state: 'proposed',
	accepted_at: null,
	rejected_at: null,
	created_at: '2026-07-01T00:00:00Z',
	updated_at: '2026-07-01T00:00:00Z'
});
const envelope = (rows: ReturnType<typeof proposal>[], total_count = rows.length, offset = 0) => ({
	proposals: rows,
	total_count,
	offset,
	limit: 50
});

function visitMatter() {
	cy.visit(`/lq-ai/matters/${A}`, {
		onBeforeLoad(win) {
			win.localStorage.setItem('token', 'fake-inbox-token');
			win.localStorage.setItem('locale', 'en-US');
			win.localStorage.setItem(
				'lq_ai_auth',
				JSON.stringify({
					access_token: 'fake-inbox-token',
					refresh_token: null,
					expires_at: Date.now() + 3600000,
					user
				})
			);
			win.localStorage.setItem('lq-ai:preferences-cache', JSON.stringify(prefs));
		}
	});
}

function navigateToB() {
	// A normal same-origin link exercises SvelteKit's client navigation, not cy.visit.
	cy.document().then((doc) => {
		const link = doc.createElement('a');
		link.href = `/lq-ai/matters/${B}`;
		link.id = 'test-matter-b';
		link.textContent = 'Open Matter B';
		doc.body.appendChild(link);
	});
	cy.get('#test-matter-b').click();
	cy.location('pathname').should('eq', `/lq-ai/matters/${B}`);
}

describe('DE-323 Matter proposal inbox regressions', () => {
	beforeEach(() => {
		cy.intercept('GET', '**/api/config', { name: 'LQ.AI', features: { enable_websocket: false } });
		cy.intercept('GET', '**/api/v1/auths/', {
			id: 'user',
			name: 'Test',
			email: user.email,
			role: 'admin'
		});
		cy.intercept('GET', '**/api/v1/users/me', user);
		cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
			default_password_active: false,
			logs_hint: ''
		});
		cy.intercept('GET', '**/api/v1/users/me/preferences', prefs).as('preferences');
		cy.intercept('GET', '**/api/v1/projects*', [project(A), project(B)]);
		cy.intercept('GET', '**/api/v1/projects/*', (req) =>
			req.reply(project(req.url.split('/').pop()!))
		);
		cy.intercept('GET', '**/api/v1/chats**', { items: [], next_cursor: null });
		cy.intercept('GET', '**/api/v1/skills**', []);
		cy.intercept('GET', '**/api/v1/user-skills**', []);
		cy.intercept('GET', '**/api/v1/teams**', []);
		cy.intercept('GET', '**/api/v1/saved-prompts**', []);
		cy.intercept('GET', '**/api/v1/knowledge-bases**', []);
		cy.intercept('GET', '**/api/v1/models**', { models: [] });
		cy.intercept('GET', '**/api/v1/autonomous/notifications**', {
			notifications: [],
			total_count: 0,
			limit: 50,
			offset: 0
		});
	});

	it('does not render A proposals after navigating to B while A list is pending', () => {
		let requestedA = false;
		cy.intercept('GET', '**/api/v1/autonomous/project-context-proposals*', (req) => {
			if (new URL(req.url).searchParams.get('project_id') === A) {
				requestedA = true;
				req.reply({ delay: 1500, body: envelope([proposal('old-A')]) });
			} else req.reply(envelope([proposal('new-B', B)]));
		}).as('proposals');
		visitMatter();
		cy.wrap(null).should(() => expect(requestedA).to.eq(true));
		navigateToB();
		cy.get('section[aria-label="Context proposals"]').should('contain', 'Context new-B');
		cy.wait('@proposals');
		cy.wait('@proposals');
		cy.get('section[aria-label="Context proposals"]').should('not.contain', 'Context old-A');
		cy.contains('h2', 'Matter B').should('exist');
	});

	it('does not refresh B or show A feedback when an A action finishes after navigation', () => {
		cy.intercept('GET', '**/api/v1/autonomous/project-context-proposals*', (req) => {
			const id = new URL(req.url).searchParams.get('project_id')!;
			req.reply(envelope([proposal(id === A ? 'old-A' : 'new-B', id)]));
		});
		cy.intercept('POST', '**/api/v1/autonomous/project-context-proposals/old-A/accept', {
			delay: 1200,
			body: { ...proposal('old-A'), state: 'accepted' }
		}).as('acceptA');
		visitMatter();
		cy.get('section[aria-label="Context proposals"]')
			.contains('button', /^Accept$/)
			.click();
		navigateToB();
		cy.wait('@acceptA');
		cy.get('section[aria-label="Context proposals"]')
			.should('contain', 'Context new-B')
			.and('not.contain', 'Added to matter context');
		cy.contains('h2', 'Matter B').should('exist');
	});

	it('hides the inbox after preference failure despite cached opt-in and a readable list', () => {
		let listCalls = 0;
		cy.intercept('GET', '**/api/v1/users/me/preferences', { statusCode: 503, body: {} }).as(
			'failedPreferences'
		);
		cy.intercept('GET', '**/api/v1/autonomous/project-context-proposals*', (req) => {
			++listCalls;
			req.reply(envelope([proposal('a')]));
		});
		visitMatter();
		cy.wait('@failedPreferences');
		cy.get('[data-testid="lq-ai-chat-shell"]').should('exist');
		cy.get('section[aria-label="Context proposals"]').should('not.exist');
		cy.then(() => expect(listCalls).to.eq(0));
	});

	it('shows the true 51-row count, pages, then refills after an accept', () => {
		let rows = Array.from({ length: 51 }, (_, i) => proposal(`p${i}`));
		cy.intercept('GET', '**/api/v1/autonomous/project-context-proposals*', (req) => {
			const query = new URL(req.url).searchParams;
			const offset = Number(query.get('offset'));
			req.reply(envelope(rows.slice(offset, offset + 50), rows.length, offset));
		}).as('list');
		cy.intercept('POST', '**/api/v1/autonomous/project-context-proposals/p0/accept', (req) => {
			rows = rows.filter((row) => row.id !== 'p0');
			req.reply({ ...proposal('p0'), state: 'accepted' });
		});
		visitMatter();
		cy.get('.proposal-banner-count').should('contain', '51 pending').and('contain', 'showing 50');
		cy.contains('button', 'Load more proposals').click();
		cy.get('.proposal-row').should('have.length', 51);
		cy.get('.proposal-row')
			.first()
			.contains('button', /^Accept$/)
			.click();
		cy.get('.proposal-banner-count').should('contain', '50 pending');
		cy.get('.proposal-row').should('have.length', 50);
		cy.get('section[aria-label="Context proposals"]').should('contain', 'Context p50');
		cy.get('.proposal-text').should('not.contain.text', 'Context p0');
	});
});
