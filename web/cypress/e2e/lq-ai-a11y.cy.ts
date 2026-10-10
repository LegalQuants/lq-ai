/// <reference types="cypress" />
import {
	compareFindings,
	fingerprint,
	type Baseline,
	type Finding,
	type Impact
} from '../support/a11y-gate';
import { states, viewports, themes } from '../support/a11y-states';

const user = {
	id: 'a11y-user',
	name: 'Accessibility fixture',
	display_name: 'Accessibility fixture',
	email: 'fixture@example.invalid',
	is_admin: true,
	role: 'admin',
	mfa_enabled: false,
	must_change_password: false,
	created_at: '2026-01-01T00:00:00Z'
};
const preferences = {
	reasoning_visibility: 'disclosure',
	featured_tools: 'prominent',
	workspace_layout: 'three_pane',
	trust_pills: 'labels',
	provenance_pills: 'always',
	autonomous_enabled: false
};
function fixtures() {
	const reads: Record<string, unknown> = {
		'/api/config': { name: 'LQ.AI', features: { enable_websocket: false } },
		'/api/version': { version: '0.11.0' },
		'/api/v1/auths': user,
		'/api/v1/users/me': user,
		'/api/v1/users/me/preferences': preferences,
		'/api/v1/admin/bootstrap-status': { default_password_active: false, logs_hint: '' },
		'/api/v1/projects': [],
		'/api/v1/chats': { items: [], next_cursor: null },
		'/api/v1/knowledge-bases': [],
		'/api/v1/user-skills': [],
		'/api/v1/skills': [],
		'/api/v1/saved-prompts': [],
		'/api/v1/teams': [],
		'/api/v1/autonomous/notifications': { notifications: [], total_count: 0, limit: 50, offset: 0 },
		'/api/v1/users/user/settings': { ui: {} },
		'/api/v1/models': { data: [] }
	};
	cy.intercept('**/api/**', (req) => {
		const path = new URL(req.url).pathname.replace(/\/$/, '');
		if (req.method === 'GET' && Object.hasOwn(reads, path))
			req.reply({ statusCode: 200, body: reads[path] });
		else if (req.method === 'POST' && path === '/api/v1/auths/update/timezone')
			req.reply({ statusCode: 204 });
		else {
			req.reply({ statusCode: 500, body: { detail: 'Unexpected accessibility fixture request' } });
			throw new Error(`Unexpected API request: ${req.method} ${path}`);
		}
	});
}
describe('DE-232 exact accessibility gate (source credit: @SaifAlYounan #437)', () => {
	for (const state of states)
		for (const viewport of viewports)
			for (const theme of themes) {
				const id = `${state.id}/${viewport.id}/${theme}`;
				it(id, () => {
					fixtures();
					cy.viewport(viewport.width, viewport.height);
					cy.visit(state.path, {
						onBeforeLoad(win) {
							win.localStorage.clear();
							win.localStorage.setItem('locale', 'en-US');
							win.localStorage.setItem('theme', theme);
							win.localStorage.setItem('token', 'synthetic-a11y-token');
							if (state.id !== 'login')
								win.localStorage.setItem(
									'lq_ai_auth',
									JSON.stringify({
										access_token: 'synthetic-a11y-token',
										refresh_token: null,
										expires_at: Date.now() + 3600000,
										user
									})
								);
							win.localStorage.setItem('lq-ai:preferences-cache', JSON.stringify(preferences));
						}
					});
					cy.location('pathname').should('eq', state.path);
					if ('ready' in state) cy.get(state.ready, { timeout: 15000 }).should('be.visible');
					if ('heading' in state)
						cy.contains('h1,h2', state.heading, { timeout: 15000 }).should('be.visible');
					if ('dialog' in state) {
						cy.contains('button', '+ New matter').first().click();
						cy.get('[role="dialog"]').should('be.visible');
					}
					cy.document().then(async (doc) => {
						await doc.fonts.ready;
					});
					if (Cypress.env('injectViolation') && id === 'login/desktop/light')
						cy.document().then((doc) => {
							const button = doc.createElement('button');
							button.id = 'a11y-negative-probe';
							doc.querySelector('#lq-main')!.append(button);
						});
					cy.injectAxe();
					cy.window()
						.then(
							(win) =>
								new Cypress.Promise<import('axe-core').AxeResults>((resolve, reject) => {
									const axe = (win as unknown as { axe: typeof import('axe-core') }).axe;
									axe.run(
										docBody(win),
										{
											runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] }
										},
										(error, result) => {
											if (error) reject(error);
											else resolve(result);
										}
									);
								})
						)
						.then((result) => {
							const grouped = new Map<string, Finding>();
							for (const violation of result.violations)
								for (const node of violation.nodes) {
									const f: Finding = {
										state: id,
										rule: violation.id,
										impact: (violation.impact ?? 'unknown') as Impact,
										target: node.target,
										count: 1
									};
									const key = fingerprint(f),
										previous = grouped.get(key);
									grouped.set(key, { ...f, count: (previous?.count ?? 0) + 1 });
								}
							const findings = [...grouped.values()];
							return cy
								.task('a11y:record', {
									state: id,
									findings,
									incompleteRules: result.incomplete.map((x) => x.id)
								})
								.then(() => {
									if (!Cypress.env('captureBaseline'))
										cy.fixture<Baseline>('a11y-baseline.json').then((baseline) => {
											// Compare this state's exceptions only; global stale/coverage checks run after the suite.
											const comparison = compareFindings(findings, {
												...baseline,
												entries: baseline.entries.filter((f) => f.state === id)
											});
											expect(comparison.regressions, `new violations in ${id}`).to.deep.equal([]);
										});
								});
						});
				});
			}
});
function docBody(win: Window) {
	return win.document.body;
}
