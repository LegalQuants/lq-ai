/// <reference types="cypress" />

const user = {
	id: 'skill-owner',
	email: 'skills@example.com',
	display_name: 'Skill owner',
	role: 'member',
	is_admin: false,
	mfa_enabled: false,
	must_change_password: false
};
const saved = {
	id: '00000000-0000-4000-8000-000000000071',
	skill_name: 'saved-notes-demo',
	project_id: null,
	project_name: null,
	format_version: 1,
	files: [
		{
			name: 'notes.md',
			revision: '00000000-0000-4000-8000-000000000072',
			size_bytes: 20,
			updated_at: '2026-09-14T00:00:00Z'
		}
	]
};
const base = '**/api/v1/skill-workspaces';

function setup() {
	cy.intercept('http://127.0.0.1:8080/**', { statusCode: 404, body: {} });
	cy.intercept('GET', '**/api/config', {
		body: { name: 'LQ.AI', default_locale: 'en-US', features: { enable_websocket: false } }
	});
	cy.intercept('**/api/v1/**', { statusCode: 404, body: {} });
	cy.intercept('GET', '**/api/v1/users/me', { body: user });
	cy.intercept('GET', '**/api/v1/users/me/preferences', { body: { autonomous_enabled: false } });
	cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
		body: { default_password_active: false, logs_hint: '' }
	});
	cy.intercept('GET', '**/api/v1/chats**', { body: { items: [], next_cursor: null } });
	for (const path of ['projects', 'skills', 'user-skills', 'teams', 'saved-prompts'])
		cy.intercept('GET', `**/api/v1/${path}**`, { body: [] });
	cy.intercept('GET', '**/api/v1/autonomous/notifications**', {
		body: { notifications: [], total_count: 0 }
	});
	return (win: Window) => {
		win.localStorage.setItem(
			'lq_ai_auth',
			JSON.stringify({
				access_token: 'fixture',
				refresh_token: null,
				expires_at: Date.now() + 3600000,
				user
			})
		);
	};
}

describe('Optional saved skill work', () => {
	it('reads escaped text and allows owner reset while autonomous execution is off', () => {
		const onBeforeLoad = setup();
		let rows = [saved];
		cy.intercept('GET', `${base}?*`, (req) => req.reply(rows)).as('list');
		cy.intercept('GET', `${base}/${saved.id}/files/notes.md`, {
			body: {
				...saved.files[0],
				content: '<script>window.skillInjected = true</script>Private notes'
			}
		}).as('read');
		cy.intercept('DELETE', `${base}/${saved.id}`, (req) => {
			rows = [];
			req.reply({ statusCode: 204 });
		}).as('reset');
		cy.visit('/lq-ai/skills/workspaces', { onBeforeLoad });
		cy.wait('@list');
		cy.contains('Personal workspace');
		cy.contains('button', 'notes.md').click();
		cy.wait('@read');
		cy.get('[aria-label="Saved file preview"] pre').should('contain.text', '<script>');
		cy.window().its('skillInjected').should('not.exist');
		cy.on('window:confirm', () => true);
		cy.contains('button', 'Delete saved work').click();
		cy.wait('@reset');
		cy.wait('@list');
		cy.contains('No skill has saved work yet.');
		cy.get('[aria-label="Saved file preview"]').should('not.exist');
	});

	it('shows read failure and preserves saved work after a refused reset', () => {
		const onBeforeLoad = setup();
		cy.intercept('GET', `${base}?*`, { body: [saved] });
		cy.intercept('GET', `${base}/${saved.id}/files/notes.md`, { statusCode: 404, body: {} });
		cy.intercept('DELETE', `${base}/${saved.id}`, { statusCode: 503, body: {} });
		cy.visit('/lq-ai/skills/workspaces', { onBeforeLoad });
		cy.contains('button', 'notes.md').click();
		cy.get('[role="alert"]').should('contain.text', 'could not be loaded');
		cy.on('window:confirm', () => true);
		cy.contains('button', 'Delete saved work').click();
		cy.get('[role="alert"]').should('contain.text', 'could not be deleted');
		cy.contains('button', 'notes.md');
	});

	it('makes bundled source readable without executing its contents', () => {
		const onBeforeLoad = setup();
		cy.intercept('GET', '**/api/v1/skills/saved-notes-demo', {
			body: {
				name: 'saved-notes-demo',
				title: 'Saved notes demo',
				version: '0.1.0',
				scope: 'builtin',
				source: 'built-in',
				description: 'Technical helper',
				content_yaml: 'name: saved-notes-demo',
				content_md: 'Use saved notes.',
				script_files: [
					{
						path: 'scripts/summarize_notes.py',
						content: 'print("<script>window.skillInjected = true</script>")'
					}
				]
			}
		});
		cy.intercept('GET', '**/api/v1/skills/saved-notes-demo/inputs', {
			body: { name: 'saved-notes-demo', required: [], optional: [] }
		});
		cy.visit('/lq-ai/skills/saved-notes-demo', { onBeforeLoad });
		cy.contains('button', 'View source').click();
		cy.contains('summary', 'scripts/summarize_notes.py').click();
		cy.contains('pre', 'window.skillInjected').should('be.visible');
		cy.window().its('skillInjected').should('not.exist');
	});
});
