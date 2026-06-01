/**
 * M4-C2 — Autonomous Dashboard E2E.
 *
 * Five scenarios, all intercept-based (deterministic; no real seed data):
 *
 *   1. Opt-in gating  — Autonomous tab absent when disabled; direct visit
 *                       to /lq-ai/autonomous redirects to settings.
 *   2. Receipt + Halt — Sessions list shows a running session with a Halt
 *                       button; receipt page renders a phase node, a tool
 *                       node, and a terminal node; Halt succeeds.
 *   3. Memory keep    — Proposed memory entry renders; Keep action fires the
 *                       POST endpoint and surfaces a success banner.
 *   4. Precedent dismiss — Precedent entry renders; Dismiss fires the POST
 *                          endpoint and surfaces a success banner.
 *   5. Opt-out        — After disabling, the tab disappears and a direct
 *                       visit to /lq-ai/autonomous redirects back to settings.
 *
 * Auth strategy: set lq_ai_auth in localStorage (token + user) before each
 * visit and intercept GET /api/v1/users/me so the layout gate passes. Also
 * intercept the preferences endpoint so the store sees exactly the state
 * each scenario needs. Pattern mirrors m3-c-tabular-review.cy.ts.
 *
 * Run:
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/m4-autonomous.cy.ts'
 */

/// <reference types="cypress" />

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SESSION_ID = 'sess-0001-aaaa-bbbb-cccc-dddddddddddd';
const MEMORY_ID = 'mem-0001-aaaa-bbbb';
const PRECEDENT_ID = 'prec-0001-aaaa-bbbb';

// ---------------------------------------------------------------------------
// Mock shapes
// ---------------------------------------------------------------------------

const mockUser = {
	id: 'u1',
	email: 'admin@lq.ai',
	display_name: 'Admin',
	is_admin: true,
	role: 'admin' as const,
	mfa_enabled: false,
	must_change_password: false,
	created_at: '2026-01-01T00:00:00Z'
};

const mockSession = {
	id: SESSION_ID,
	user_id: 'u1',
	project_id: null,
	trigger_kind: 'manual' as const,
	trigger_ref: null,
	current_phase: 'analysis' as const,
	halt_state: 'running' as const,
	max_cost_usd: '5.00',
	cost_total_usd: '0.12',
	cost_cap_reached: false,
	idle_halt_minutes: 30,
	last_activity_at: '2026-05-27T10:00:00Z',
	status: 'running' as const,
	params: {},
	result: null,
	error: null,
	created_at: '2026-05-27T09:55:00Z',
	updated_at: '2026-05-27T10:00:00Z',
	completed_at: null
};

const mockReceipt = {
	session_id: SESSION_ID,
	trigger_kind: 'manual',
	status: 'running',
	halt_state: 'running',
	current_phase: 'analysis',
	cost_total_usd: 0.12,
	max_cost_usd: 5.0,
	cost_cap_reached: false,
	created_at: '2026-05-27T09:55:00Z',
	completed_at: null,
	phase_transitions: [
		{ to_phase: 'intake', timestamp: '2026-05-27T09:55:01Z' },
		{ to_phase: 'analysis', timestamp: '2026-05-27T09:56:00Z' }
	],
	tool_calls: [
		{
			tool: 'search_kb',
			outcome: 'success',
			timestamp: '2026-05-27T09:56:10Z',
			cost_usd: 0.0025
		}
	],
	terminal_reason: null
};

const mockHaltedSession = { ...mockSession, status: 'halted' as const, halt_state: 'halted' as const };

const mockMemoryEntry = {
	id: MEMORY_ID,
	user_id: 'u1',
	state: 'proposed' as const,
	category: 'counterparty_preference',
	content: 'Acme Corp always prefers Delaware governing law.',
	source_session_id: SESSION_ID,
	kept_at: null,
	deleted_at: null,
	created_at: '2026-05-27T10:00:00Z',
	updated_at: '2026-05-27T10:00:00Z'
};

const mockKeptMemoryEntry = { ...mockMemoryEntry, state: 'kept' as const, kept_at: '2026-05-27T10:01:00Z' };

const mockPrecedentEntry = {
	id: PRECEDENT_ID,
	user_id: 'u1',
	pattern_kind: 'governing_law',
	summary: 'Acme always chooses Delaware in tech-sector deals.',
	observed_count: 4,
	source_session_id: SESSION_ID,
	dismissed_at: null,
	created_at: '2026-05-27T09:00:00Z',
	updated_at: '2026-05-27T09:00:00Z'
};

const mockDismissedPrecedentEntry = {
	...mockPrecedentEntry,
	dismissed_at: '2026-05-27T10:02:00Z'
};

// ---------------------------------------------------------------------------
// Helper: set up auth state in localStorage (called inside cy.visit() via
// cy.window() — but we do it before the visit using cy.then on a stub visit).
//
// Strategy: inject auth into localStorage BEFORE the page loads.
// Cypress supports this via the `onBeforeLoad` option.
// ---------------------------------------------------------------------------

function setAuthStorage(win: Window, opts: { autonomousEnabled: boolean }): void {
	// Auth token — the layout gate checks this to decide whether to call /users/me.
	win.localStorage.setItem(
		'lq_ai_auth',
		JSON.stringify({
			access_token: 'fake-token-m4',
			refresh_token: null,
			expires_at: Date.now() + 3600 * 1000,
			user: mockUser
		})
	);
	// Preferences cache — avoids a flash of "not enabled" while the GET resolves.
	win.localStorage.setItem(
		'lq-ai:preferences-cache',
		JSON.stringify({
			reasoning_visibility: 'disclosure',
			featured_tools: 'prominent',
			workspace_layout: 'three_pane',
			trust_pills: 'labels',
			provenance_pills: 'always',
			autonomous_enabled: opts.autonomousEnabled
		})
	);
}

// ---------------------------------------------------------------------------
// Helper: intercept all the "background" requests every lq-ai page triggers.
// ---------------------------------------------------------------------------

function interceptBaseRequests(autonomousEnabled: boolean): void {
	// Auth gate: the layout calls GET /users/me after finding a token.
	cy.intercept('GET', '**/api/v1/users/me', { statusCode: 200, body: mockUser }).as('getMe');
	// POST login is not used but intercept so CI doesn't accidentally hit real stack.
	cy.intercept('POST', '**/api/v1/auth/login', {
		statusCode: 200,
		body: { access_token: 'fake-token-m4', token_type: 'Bearer', expires_in: 3600, user: mockUser }
	}).as('login');
	cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
		statusCode: 200,
		body: { default_password_active: false, logs_hint: '' }
	}).as('bootstrapStatus');
	cy.intercept('GET', '**/api/v1/users/me/preferences', {
		statusCode: 200,
		body: {
			reasoning_visibility: 'disclosure',
			featured_tools: 'prominent',
			workspace_layout: 'three_pane',
			trust_pills: 'labels',
			provenance_pills: 'always',
			autonomous_enabled: autonomousEnabled
		}
	}).as('getPreferences');
	// Incidental calls the shell/layout may trigger.
	cy.intercept('GET', '**/api/v1/projects**', { statusCode: 200, body: [] }).as('listProjects');
	cy.intercept('GET', '**/api/v1/chats**', {
		statusCode: 200,
		body: { items: [], next_cursor: null }
	}).as('listChats');
	cy.intercept('GET', '**/api/v1/user-skills**', { statusCode: 200, body: [] }).as('listUserSkills');
	cy.intercept('GET', '**/api/v1/saved-prompts**', { statusCode: 200, body: [] }).as('listSavedPrompts');
	cy.intercept('GET', '**/api/v1/teams**', { statusCode: 200, body: [] }).as('listTeams');
	cy.intercept('GET', '**/api/v1/skills**', { statusCode: 200, body: [] }).as('listSkills');
	// Autonomous sub-pages also hit notifications for the unread badge.
	cy.intercept('GET', '**/api/v1/autonomous/notifications**', {
		statusCode: 200,
		body: { notifications: [], total_count: 0, limit: 50, offset: 0 }
	}).as('listNotifications');
}

// ---------------------------------------------------------------------------
// Scenario 1 + 5 — Opt-in gating + opt-out
// ---------------------------------------------------------------------------

describe('M4-C2 — Scenario 1 + 5: opt-in gating and opt-out', () => {
	it('1a: Autonomous tab is NOT present when autonomous_enabled=false', () => {
		interceptBaseRequests(false);

		cy.visit('/lq-ai', {
			onBeforeLoad: (win) => setAuthStorage(win, { autonomousEnabled: false })
		});

		// TopTabBar renders tabs; 'Autonomous' should not appear.
		cy.get('.lq-tabbar', { timeout: 10000 }).should('exist');
		cy.get('.lq-tabbar').contains('button', 'Autonomous').should('not.exist');
	});

	it('1b: Direct visit to /lq-ai/autonomous redirects to /lq-ai/settings/autonomous when opt-in=false', () => {
		interceptBaseRequests(false);

		cy.visit('/lq-ai/autonomous', {
			onBeforeLoad: (win) => setAuthStorage(win, { autonomousEnabled: false })
		});

		// The layout guard calls goto('/lq-ai/settings/autonomous') on mount.
		cy.url({ timeout: 10000 }).should('include', '/lq-ai/settings/autonomous');
	});

	it('1c: After opt-in toggle (PATCH returns enabled=true), Autonomous tab appears', () => {
		interceptBaseRequests(false);

		// Start at settings/autonomous with opt-in disabled.
		cy.visit('/lq-ai/settings/autonomous', {
			onBeforeLoad: (win) => setAuthStorage(win, { autonomousEnabled: false })
		});

		// When the user clicks the toggle, the page calls PATCH preferences.
		// Return enabled=true from PATCH — the store updates optimistically then
		// confirms via the PATCH response.
		cy.intercept('PATCH', '**/api/v1/users/me/preferences', {
			statusCode: 200,
			body: {
				reasoning_visibility: 'disclosure',
				featured_tools: 'prominent',
				workspace_layout: 'three_pane',
				trust_pills: 'labels',
				provenance_pills: 'always',
				autonomous_enabled: true
			}
		}).as('patchPreferences');

		// The checkbox has data-testid="lq-ai-autonomous-enabled-toggle".
		cy.get('[data-testid="lq-ai-autonomous-enabled-toggle"]', { timeout: 10000 }).should('exist');
		cy.get('[data-testid="lq-ai-autonomous-enabled-toggle"]').check();

		cy.wait('@patchPreferences');

		// After the PATCH the preferences store is updated. The TopTabBar is
		// reactive to $preferences.autonomous_enabled. The Autonomous tab should
		// now be present in the tab bar.
		cy.get('.lq-tabbar', { timeout: 10000 }).contains('button', 'Autonomous').should('exist');
	});

	it('5: After opt-out, Autonomous tab disappears and direct visit redirects', () => {
		// Start with opt-in ENABLED.
		interceptBaseRequests(true);

		cy.visit('/lq-ai/settings/autonomous', {
			onBeforeLoad: (win) => setAuthStorage(win, { autonomousEnabled: true })
		});

		// Autonomous tab should be visible right now.
		cy.get('.lq-tabbar', { timeout: 10000 }).contains('button', 'Autonomous').should('exist');

		// Intercept PATCH to return disabled.
		cy.intercept('PATCH', '**/api/v1/users/me/preferences', {
			statusCode: 200,
			body: {
				reasoning_visibility: 'disclosure',
				featured_tools: 'prominent',
				workspace_layout: 'three_pane',
				trust_pills: 'labels',
				provenance_pills: 'always',
				autonomous_enabled: false
			}
		}).as('patchPreferencesOff');

		// Uncheck the toggle.
		cy.get('[data-testid="lq-ai-autonomous-enabled-toggle"]', { timeout: 10000 })
			.should('be.checked')
			.uncheck();

		cy.wait('@patchPreferencesOff');

		// Tab should disappear.
		cy.get('.lq-tabbar').contains('button', 'Autonomous').should('not.exist');

		// Intercept the preferences GET for the next page visit — now returns disabled.
		cy.intercept('GET', '**/api/v1/users/me/preferences', {
			statusCode: 200,
			body: {
				reasoning_visibility: 'disclosure',
				featured_tools: 'prominent',
				workspace_layout: 'three_pane',
				trust_pills: 'labels',
				provenance_pills: 'always',
				autonomous_enabled: false
			}
		}).as('getPreferencesOff');

		// Update the localStorage cache so the next onBeforeLoad sees disabled.
		cy.window().then((win) => {
			win.localStorage.setItem(
				'lq-ai:preferences-cache',
				JSON.stringify({
					reasoning_visibility: 'disclosure',
					featured_tools: 'prominent',
					workspace_layout: 'three_pane',
					trust_pills: 'labels',
					provenance_pills: 'always',
					autonomous_enabled: false
				})
			);
		});

		// Direct visit to /lq-ai/autonomous should redirect to settings.
		cy.visit('/lq-ai/autonomous', {
			onBeforeLoad: (win) => setAuthStorage(win, { autonomousEnabled: false })
		});
		cy.url({ timeout: 10000 }).should('include', '/lq-ai/settings/autonomous');
	});
});

// ---------------------------------------------------------------------------
// Scenario 2 — Receipt + Halt
// ---------------------------------------------------------------------------

describe('M4-C2 — Scenario 2: receipt view and halt', () => {
	beforeEach(() => {
		interceptBaseRequests(true);
	});

	it('2a: Sessions list renders a running session row with a Halt button', () => {
		cy.intercept('GET', '**/api/v1/autonomous/sessions**', {
			statusCode: 200,
			body: {
				sessions: [mockSession],
				total_count: 1,
				limit: 50,
				offset: 0
			}
		}).as('listSessions');

		cy.visit('/lq-ai/autonomous', {
			onBeforeLoad: (win) => setAuthStorage(win, { autonomousEnabled: true })
		});

		cy.wait('@listSessions');

		// The sessions table should render one row with the running session.
		cy.contains('td', 'running').should('exist');
		cy.contains('button', 'Halt').should('exist');
	});

	it('2b: Receipt page renders phase nodes, tool nodes, and terminal node; Halt fires the endpoint', () => {
		// Session detail — running session + receipt with 2 phases + 1 tool.
		cy.intercept('GET', `**/api/v1/autonomous/sessions/${SESSION_ID}`, {
			statusCode: 200,
			body: { session: mockSession, receipt: mockReceipt }
		}).as('getSession');

		// Halt endpoint — returns the halted session.
		cy.intercept('POST', `**/api/v1/autonomous/sessions/${SESSION_ID}/halt`, {
			statusCode: 200,
			body: mockHaltedSession
		}).as('haltSession');

		// After halt, the page re-loads the session — now halted.
		let getCount = 0;
		cy.intercept('GET', `**/api/v1/autonomous/sessions/${SESSION_ID}`, (req) => {
			getCount += 1;
			req.reply({
				statusCode: 200,
				body: getCount === 1
					? { session: mockSession, receipt: mockReceipt }
					: { session: mockHaltedSession, receipt: { ...mockReceipt, status: 'halted', halt_state: 'halted' } }
			});
		}).as('getSessionDynamic');

		cy.visit(`/lq-ai/autonomous/sessions/${SESSION_ID}`, {
			onBeforeLoad: (win) => setAuthStorage(win, { autonomousEnabled: true })
		});

		cy.wait('@getSessionDynamic');

		// The receipt page heading.
		cy.contains('h1', 'Session receipt').should('exist');

		// Phase nodes: 2 phase transitions → 2 .timeline-node--phase elements.
		cy.get('.timeline-node--phase').should('have.length', 2);

		// Tool node: 1 tool call → 1 .timeline-node--tool element.
		cy.get('.timeline-node--tool').should('have.length', 1);
		cy.get('.tool-name').should('contain', 'search_kb');

		// The "Halt session" button should be present for a running session.
		cy.get('button.halt-button').should('exist').and('contain', 'Halt session');

		// Cypress auto-accepts window:confirm — just click the Halt button.
		cy.get('button.halt-button').click();

		cy.wait('@haltSession');

		// After halt, the success banner appears.
		cy.get('[role="status"]', { timeout: 10000 }).should('contain', 'Halt requested');
	});
});

// ---------------------------------------------------------------------------
// Scenario 3 — Memory keep
// ---------------------------------------------------------------------------

describe('M4-C2 — Scenario 3: memory keep', () => {
	beforeEach(() => {
		interceptBaseRequests(true);
	});

	it('3: Proposed memory entry renders; Keep fires POST and success banner appears', () => {
		cy.intercept('GET', '**/api/v1/autonomous/memory**', {
			statusCode: 200,
			body: {
				entries: [mockMemoryEntry],
				total_count: 1,
				limit: 50,
				offset: 0
			}
		}).as('listMemory');

		cy.intercept('POST', `**/api/v1/autonomous/memory/${MEMORY_ID}/keep`, {
			statusCode: 200,
			body: mockKeptMemoryEntry
		}).as('keepMemory');

		cy.visit('/lq-ai/autonomous/memory', {
			onBeforeLoad: (win) => setAuthStorage(win, { autonomousEnabled: true })
		});

		cy.wait('@listMemory');

		// The entry card should render with the memory content.
		cy.contains('Acme Corp always prefers Delaware governing law.').should('exist');

		// Click the "Keep" button (the primary keep, not "Edit & keep").
		cy.contains('button', 'Keep').first().click();

		cy.wait('@keepMemory');

		// Success banner confirms the keep.
		cy.get('[role="status"]', { timeout: 10000 }).should('contain', 'Kept memory entry');
	});
});

// ---------------------------------------------------------------------------
// Scenario 4 — Precedent dismiss
// ---------------------------------------------------------------------------

describe('M4-C2 — Scenario 4: precedent dismiss', () => {
	beforeEach(() => {
		interceptBaseRequests(true);
	});

	it('4: Precedent entry renders; Dismiss fires POST and success banner appears', () => {
		cy.intercept('GET', '**/api/v1/autonomous/precedents**', {
			statusCode: 200,
			body: {
				entries: [mockPrecedentEntry],
				total_count: 1,
				limit: 50,
				offset: 0
			}
		}).as('listPrecedents');

		cy.intercept('POST', `**/api/v1/autonomous/precedents/${PRECEDENT_ID}/dismiss`, {
			statusCode: 200,
			body: mockDismissedPrecedentEntry
		}).as('dismissPrecedent');

		cy.visit('/lq-ai/autonomous/precedents', {
			onBeforeLoad: (win) => setAuthStorage(win, { autonomousEnabled: true })
		});

		cy.wait('@listPrecedents');

		// The precedent entry should render with the summary text.
		cy.contains('Acme always chooses Delaware in tech-sector deals.').should('exist');

		// Cypress auto-accepts window:confirm — click the Dismiss button.
		cy.contains('button', 'Dismiss').click();

		cy.wait('@dismissPrecedent');

		// Success banner.
		cy.get('[role="status"]', { timeout: 10000 }).should('contain', 'Precedent dismissed');
	});
});

// ---------------------------------------------------------------------------
// Scenario 6 — Run now (§4.4): one-off run from the Sessions page
// ---------------------------------------------------------------------------

describe('M4-C2 — Scenario 6: Run now', () => {
	beforeEach(() => {
		interceptBaseRequests(true);
	});

	it('6: Open the Run-now modal, pick a skill, submit → POST run-now → navigate to the receipt', () => {
		// Sessions list starts empty so the page renders with just the header button.
		cy.intercept('GET', '**/api/v1/autonomous/sessions**', {
			statusCode: 200,
			body: { sessions: [], total_count: 0, limit: 50, offset: 0 }
		}).as('listSessions');

		// Picker lists the modal loads on mount / open. The skills list drives the
		// skill <select>; we return one selectable skill.
		cy.intercept('GET', '**/api/v1/skills**', {
			statusCode: 200,
			body: [{ name: 'nda-review', title: 'NDA Review', description: 'Review an NDA' }]
		}).as('listSkillsForRun');
		cy.intercept('GET', '**/api/v1/playbooks**', { statusCode: 200, body: [] }).as('listPlaybooks');
		cy.intercept('GET', '**/api/v1/knowledge-bases**', { statusCode: 200, body: [] }).as('listKbs');

		// run-now → 201 with a freshly created (running) session.
		cy.intercept('POST', '**/api/v1/autonomous/run-now', {
			statusCode: 201,
			body: mockSession
		}).as('runNow');

		// The receipt page the run-now navigates to issues a GET for the session.
		cy.intercept('GET', `**/api/v1/autonomous/sessions/${SESSION_ID}`, {
			statusCode: 200,
			body: { session: mockSession, receipt: mockReceipt }
		}).as('getSession');

		cy.visit('/lq-ai/autonomous', {
			onBeforeLoad: (win) => setAuthStorage(win, { autonomousEnabled: true })
		});

		cy.wait('@listSessions');

		// Open the modal via the header button.
		cy.contains('button', 'Run now').click();

		// Modal renders with its title.
		cy.contains('h2', 'Run a skill or playbook once').should('exist');

		// Skill is the default target — pick the seeded skill.
		cy.get('select[aria-label="Select skill"]', { timeout: 10000 }).select('nda-review');

		// Submit the modal (the primary "Run now" button inside the dialog).
		cy.get('.modal-actions').contains('button', 'Run now').click();

		cy.wait('@runNow');

		// On success the app navigates to the new session's receipt.
		cy.url({ timeout: 10000 }).should('include', `/lq-ai/autonomous/sessions/${SESSION_ID}`);
	});
});
