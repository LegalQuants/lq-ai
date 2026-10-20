/// <reference types="cypress" />
import {
	compareFindings,
	fingerprint,
	type Baseline,
	type Finding,
	type Impact
} from '../support/a11y-gate';
import { states, viewports, savedThemePreferences } from '../support/a11y-states';

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
// Opt-in regression probe: simulate a slow cold bootstrap in the failing CI state.
// This delays only the first config response; it never skips a state or an axe rule.
const bootstrapDelayMs = Number(Cypress.env('a11yBootstrapDelayMs') ?? 0);
if (!Number.isInteger(bootstrapDelayMs) || bootstrapDelayMs < 0 || bootstrapDelayMs > 20000)
	throw new Error('a11yBootstrapDelayMs must be an integer between 0 and 20000');

function fixtures(dashboard = false, delayBootstrap = false) {
	let firstConfig = true;
	let releaseActivity!: () => void;
	const activityReady = new Promise<void>((resolve) => {
		releaseActivity = resolve;
	});
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
	const aliases: Record<string, string> = {
		'/api/config': 'a11yConfig',
		'/api/v1/auths': 'a11ySession',
		'/api/v1/users/me': 'a11yUser',
		'/api/v1/user-skills': 'a11yUserSkills',
		'/api/v1/skills': 'a11yBuiltinSkills',
		'/api/v1/teams': 'a11yTeams'
	};
	cy.intercept('**/api/**', async (req) => {
		const path = new URL(req.url).pathname.replace(/\/$/, '');
		// Hold the synthetic reads until loading contrast has been checked, without a timing guess.
		if (dashboard && (path === '/api/v1/chats' || path === '/api/v1/projects')) await activityReady;
		if (req.method === 'GET' && Object.hasOwn(reads, path)) {
			if (aliases[path]) req.alias = aliases[path];
			const delay = delayBootstrap && firstConfig && path === '/api/config' ? bootstrapDelayMs : 0;
			if (path === '/api/config') firstConfig = false;
			req.reply({ statusCode: 200, body: reads[path], delay });
		} else if (req.method === 'POST' && path === '/api/v1/auths/update/timezone')
			req.reply({ statusCode: 204 });
		else {
			req.reply({ statusCode: 500, body: { detail: 'Unexpected accessibility fixture request' } });
			throw new Error(`Unexpected API request: ${req.method} ${path}`);
		}
	});
	return releaseActivity;
}
// The final inventory-key segment records the saved input preference only.
// Assert the actual palette rather than treating a saved dark value as dark UI.
function assertLightOnlyUI() {
	cy.get('html')
		.should('have.class', 'light')
		.and('not.have.class', 'dark')
		.and('not.have.class', 'oled-dark')
		.and('not.have.class', 'her')
		.and('have.css', 'color-scheme', 'light');
	cy.get('meta[name="theme-color"]').should('have.attr', 'content', '#ffffff');
}

describe('DE-232 exact accessibility gate (source credit: @SaifAlYounan #437)', () => {
	for (const state of states)
		for (const viewport of viewports)
			for (const savedTheme of savedThemePreferences) {
				const id = `${state.id}/${viewport.id}/${savedTheme}`;
				it(`${state.id}/${viewport.id}/light UI (saved ${savedTheme})`, () => {
					const releaseActivity = fixtures(state.id === 'dashboard', id === 'skills/desktop/light');
					cy.viewport(viewport.width, viewport.height);
					cy.visit(state.path, {
						onBeforeLoad(win) {
							win.localStorage.clear();
							win.localStorage.setItem('locale', 'en-US');
							win.localStorage.setItem('theme', savedTheme);
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
					// Document load does not mean either shell's async auth gate has mounted its route.
					// Start the DOM-readiness budget after the intercepted bootstrap responses settle.
					const bootstrapTimeout = { requestTimeout: 30000, responseTimeout: 30000 };
					cy.wait(['@a11yConfig', '@a11ySession', '@a11yConfig'], bootstrapTimeout);
					if (state.id !== 'login') cy.wait('@a11yUser', bootstrapTimeout);
					assertLightOnlyUI();
					if ('ready' in state) cy.get(state.ready, { timeout: 15000 }).should('be.visible');
					if ('heading' in state)
						cy.contains('h1,h2', state.heading, { timeout: 15000 }).should('be.visible');
					if (state.id === 'skills') {
						cy.wait(['@a11yUserSkills', '@a11yBuiltinSkills', '@a11yTeams'], bootstrapTimeout);
						cy.contains(
							'[data-testid="lq-ai-user-skills"]',
							"You haven't created any skills yet."
						).should('be.visible');
					}
					if ('dialog' in state) {
						cy.contains('button', '+ New matter').first().click();
						cy.get('[role="dialog"]').should('be.visible');
					}
					if (state.id === 'dashboard') {
						cy.get('[data-testid="lq-ai-recent-activity"] p')
							.filter(':contains("Loading…")')
							.should('have.length', 2)
							.then(($loading) => {
								cy.injectAxe();
								cy.window().then(async (win) => {
									await win.document.fonts.ready;
									const axe = (win as unknown as { axe: typeof import('axe-core') }).axe;
									const result = await axe.run($loading.toArray(), {
										runOnly: { type: 'rule', values: ['color-contrast'] }
									});
									expect(result.violations, `loading text contrast in ${id}`).to.deep.equal([]);
									expect(result.incomplete, `unresolved loading contrast in ${id}`).to.deep.equal(
										[]
									);
									expect(
										result.passes.find((rule) => rule.id === 'color-contrast')?.nodes
									).to.have.length(2);
								});
							});
						cy.then(releaseActivity);
						// A heading does not establish that RecentActivity's async reads have settled.
						// Scanning removed loading nodes can turn their selectors into :root.
						cy.get('[data-testid="lq-ai-recent-activity"]').should(
							'have.attr',
							'aria-busy',
							'false'
						);
					}
					cy.document().then(async (doc) => {
						await doc.fonts.ready;
					});
					assertLightOnlyUI();
					if (Cypress.env('injectViolation') && id === 'login/desktop/light')
						cy.document().then((doc) => {
							const button = doc.createElement('button');
							button.id = 'a11y-negative-probe';
							doc.querySelector('#lq-main')!.append(button);
						});
					cy.injectAxe();
					cy.checkA11y('[data-testid="lq-ai-dual-branding-footer"]', {
						runOnly: { type: 'rule', values: ['color-contrast'] }
					});
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

// The general baseline matrix opts out of autonomous mode, so it never opens
// the DE-324 bell. Check this opt-in surface separately with zero exceptions.
describe('DE-324 populated notification bell accessibility', () => {
	for (const viewport of viewports)
		for (const savedTheme of savedThemePreferences) {
			it(`populated bell/${viewport.id}/light UI (saved ${savedTheme})`, () => {
				fixtures();
				cy.intercept('GET', '**/api/v1/users/me/preferences', {
					...preferences,
					autonomous_enabled: true
				});
				cy.intercept('GET', '**/api/v1/autonomous/notifications**', {
					notifications: Array.from({ length: 10 }, (_, i) => ({
						id: `bell-${i}`,
						user_id: user.id,
						session_id: 'synthetic-session',
						channel: 'in_app',
						title: `Review ${i} completed`,
						body: 'A background review completed. Open the receipt to inspect the result.',
						payload: null,
						read_at: null,
						created_at: '2026-10-17T12:00:00Z',
						updated_at: '2026-10-17T12:00:00Z'
					})),
					total_count: 102,
					limit: 10,
					offset: 0
				});
				cy.viewport(viewport.width, viewport.height);
				cy.visit('/lq-ai/settings/account', {
					onBeforeLoad(win) {
						win.localStorage.clear();
						win.localStorage.setItem('locale', 'en-US');
						win.localStorage.setItem('theme', savedTheme);
						win.localStorage.setItem(
							'lq_ai_auth',
							JSON.stringify({
								access_token: 'synthetic-a11y-token',
								refresh_token: null,
								expires_at: Date.now() + 3600000,
								user
							})
						);
					}
				});
				assertLightOnlyUI();
				cy.get('[data-testid="lq-ai-notification-bell-badge"]').should('have.text', '99+');
				cy.get('[data-testid="lq-ai-notification-bell-trigger"]')
					.should('have.attr', 'aria-label', 'Notifications, 99+ (102 unread)')
					.click();
				cy.get('[data-testid="lq-ai-notification-bell-dropdown"] li.item').should(
					'have.length',
					10
				);
				cy.document().then(async (doc) => {
					await doc.fonts.ready;
				});
				assertLightOnlyUI();
				cy.injectAxe();
				cy.checkA11y('[data-testid="lq-ai-notification-bell"]', {
					runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] }
				});
			});
		}
});
