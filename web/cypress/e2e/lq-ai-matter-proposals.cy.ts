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
		cy.intercept('GET', '**/api/v1/models**', { data: [], default_model_id: null });
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

	const chat = {
		id: 'phone-chat',
		owner_id: user.id,
		project_id: A,
		title: 'Phone layout regression chat',
		created_at: '2026-07-01T00:00:00Z',
		updated_at: '2026-07-01T00:00:00Z'
	};

	function activeChat() {
		cy.intercept('GET', '**/api/v1/chats*', { items: [chat], next_cursor: null });
		cy.intercept('GET', '**/api/v1/chats/phone-chat/messages*', {
			items: [],
			next_cursor: null
		});
		cy.intercept('GET', '**/api/v1/chats/phone-chat/run-profiles', {
			statusCode: 404,
			body: { detail: 'Not enabled' }
		});
	}

	function usableComposer(width: number, height: number) {
		for (const id of ['lq-ai-composer-input', 'lq-ai-send-btn']) {
			cy.get(`[data-testid="${id}"]`).should(($control) => {
				const rect = $control[0].getBoundingClientRect();
				expect(rect.left, `${id} left`).to.be.at.least(0);
				expect(rect.right, `${id} right`).to.be.at.most(width);
				expect(rect.top, `${id} top`).to.be.at.least(0);
				expect(rect.bottom, `${id} bottom`).to.be.at.most(height);
				if (id === 'lq-ai-composer-input') expect(rect.width).to.be.at.least(240);
				// Being inside the viewport is insufficient when a parent clips it.
				let parent = $control[0].parentElement;
				while (parent) {
					const style = parent.ownerDocument.defaultView!.getComputedStyle(parent);
					const bounds = parent.getBoundingClientRect();
					if (/(hidden|auto|scroll|clip)/.test(style.overflowX)) {
						expect(rect.left, `${id} clipped left`).to.be.at.least(bounds.left - 1);
						expect(rect.right, `${id} clipped right`).to.be.at.most(bounds.right + 1);
					}
					if (/(hidden|auto|scroll|clip)/.test(style.overflowY)) {
						expect(rect.top, `${id} clipped top`).to.be.at.least(bounds.top - 1);
						expect(rect.bottom, `${id} clipped bottom`).to.be.at.most(bounds.bottom + 1);
					}
					parent = parent.parentElement;
				}
			});
		}
	}

	for (const [width, height] of [
		[320, 740],
		[390, 844],
		[1024, 768],
		[1440, 900]
	]) {
		for (const theme of ['light', 'dark']) {
			for (const optedIn of [false, true]) {
				it(`keeps the active composer usable at ${width}x${height}/${theme}/opt-in=${optedIn}`, () => {
					activeChat();
					cy.intercept('GET', '**/api/v1/users/me/preferences', {
						...prefs,
						autonomous_enabled: optedIn
					});
					const long = { ...proposal('long'), suggested_md: 'Long context\n'.repeat(40) };
					cy.intercept(
						'GET',
						'**/api/v1/autonomous/project-context-proposals*',
						envelope([long, ...Array.from({ length: 49 }, (_, i) => proposal(`phone-${i}`))], 51)
					);
					cy.viewport(1440, 900);
					visitMatter();
					cy.get('[data-testid="lq-ai-chat-phone-chat"]').click();
					cy.get('[data-testid="lq-ai-composer-input"]').should('exist');
					cy.viewport(width, height);
					cy.document().then((doc) => {
						doc.documentElement.classList.remove('light', 'dark');
						doc.documentElement.classList.add(theme);
					});
					if (optedIn) cy.get('.proposal-row').should('have.length', 50);
					else cy.get('.proposal-banner').should('not.exist');
					usableComposer(width, height);
					cy.get('[data-testid="lq-ai-composer-input"]').type('Retained phone draft');
					cy.get('[data-testid="lq-ai-send-btn"]').should('be.enabled');
				});
			}
		}
	}

	it('keeps phone panels accessible and retains the active draft across toggles, Accept and resizing', () => {
		activeChat();
		let rows = [proposal('phone-accept')];
		cy.intercept('GET', '**/api/v1/autonomous/project-context-proposals*', (req) =>
			req.reply(envelope(rows))
		);
		cy.intercept(
			'POST',
			'**/api/v1/autonomous/project-context-proposals/phone-accept/accept',
			(req) => {
				rows = [];
				req.reply({ ...proposal('phone-accept'), state: 'accepted' });
			}
		);
		cy.viewport(390, 844);
		visitMatter();
		cy.get('#matter-details-toggle').focus();
		cy.get('#matter-details-toggle').type('{enter}');
		cy.get('#matter-details-toggle').should('have.attr', 'aria-expanded', 'true');
		cy.contains('h2', 'Matter A').should('be.visible');
		cy.get('#matter-details-toggle').type('{enter}');
		cy.get('#matter-details-toggle').should('have.attr', 'aria-expanded', 'false');
		cy.get('#matter-chats-toggle').click();
		cy.get('[data-testid="lq-ai-chat-phone-chat"]').click();
		cy.get('#matter-chats-toggle').click();
		usableComposer(390, 844);
		cy.get('[data-testid="lq-ai-composer-input"]').type('Keep this draft');
		cy.get('#matter-files-toggle').click();
		cy.get('#matter-files-toggle').should('have.attr', 'aria-expanded', 'true');
		cy.get('[data-testid="lq-ai-upload-btn"]').should('be.visible');
		cy.get('#matter-files-toggle').click();
		cy.get('#matter-chat-options-toggle').click();
		cy.contains('Saved prompts').should('be.visible');
		cy.get('#matter-chat-options-toggle').click();
		cy.get('.proposal-banner')
			.contains('button', /^Accept$/)
			.click();
		cy.get('.proposal-row').should('not.exist');
		cy.get('[data-testid="lq-ai-composer-input"]').should('have.value', 'Keep this draft');
		usableComposer(390, 844);
		cy.viewport(1440, 900);
		cy.get('#matter-details-toggle').should('not.be.visible');
		cy.get('[data-testid="lq-ai-chat-sidebar"]').should('be.visible');
		cy.get('[data-testid="lq-ai-attached-files-panel"]').should('be.visible');
		cy.get('[data-testid="lq-ai-composer-input"]').should('have.value', 'Keep this draft');
	});
});
