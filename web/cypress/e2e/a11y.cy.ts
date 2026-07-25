/**
 * DE-232 — WCAG 2.1 AA automated accessibility gate (axe-core via cypress-axe).
 *
 * SCOPE — LQ.AI-owned routes only. The inherited OpenWebUI shell has never
 * been audited and would fail wholesale; gating on it would bury LQ.AI
 * regressions in upstream noise. This mirrors the `check:lq-ai` precedent
 * (tsconfig.lq-ai.json scopes svelte-check the same way). Upstream surfaces
 * are tracked as manual-audit work in docs/compliance/accessibility-audit.md.
 *
 * WHAT THIS GATE IS — and is NOT. axe-core automates roughly 30-50% of
 * WCAG 2.1 AA success criteria. A green run here means "no regressions on
 * the automatable-rule subset"; it is NOT a WCAG 2.1 AA compliance claim.
 * The audit half of DE-232 (keyboard nav, screen reader, zoom, color
 * independence) is a manual deliverable — see the compliance doc.
 *
 * SEVERITY RATCHET (per the engineering-discipline testing memo):
 *   - impact "critical"           → FAIL, always. No baseline escape.
 *   - impact "serious"            → FAIL unless the (route, rule) pair is in
 *                                   the checked-in baseline
 *                                   (cypress/a11y-baseline.json). The
 *                                   baseline may only shrink — fixing a
 *                                   violation means deleting its entry.
 *   - impact "moderate"/"minor"   → logged to cypress/results/a11y-report.json,
 *                                   never fail.
 *
 * Every audited state (including non-initial states like an open modal) is
 * recorded in the report, all impacts included, so the full inventory stays
 * visible even while only critical/serious gate.
 *
 * DETERMINISM — fully cy.intercept-mocked (auth + every backend list the
 * audited pages call), same pattern as m4-autonomous.cy.ts /
 * m3-c-tabular-review.cy.ts. No real backend writes; safe against a live
 * dev stack. Rides the DETERMINISTIC track in CI (cypress.config.ts).
 *
 * Run:
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/a11y.cy.ts'
 *
 * Baseline regeneration (only when intentionally accepting a pre-existing
 * serious violation — see the compliance doc for the policy):
 *   1. run the spec; 2. copy the failing (route, rule) rows from
 *   cypress/results/a11y-report.json into cypress/a11y-baseline.json with a
 *   dated comment; 3. re-run to green.
 */

/// <reference types="cypress" />

import type { Result } from 'axe-core';

import { gateViolations } from '../support/a11y-gate';
import type { BaselineFile, RecordedViolation } from '../support/a11y-gate';

// ---------------------------------------------------------------------------
// axe run options — WCAG 2.1 A + AA automatable rules only.
// ---------------------------------------------------------------------------

const A11Y_RUN_OPTIONS = {
	runOnly: {
		type: 'tag' as const,
		values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
	}
};

// ---------------------------------------------------------------------------
// Baseline + report plumbing
// ---------------------------------------------------------------------------

let baseline: BaselineFile = { comment: [], entries: [] };
const recorded: RecordedViolation[] = [];

function recordViolations(route: string, violations: Result[]): void {
	// Idempotent per audited state (guards against double-recording on retry).
	for (let i = recorded.length - 1; i >= 0; i -= 1) {
		if (recorded[i].route === route) recorded.splice(i, 1);
	}
	for (const v of violations) {
		recorded.push({
			route,
			rule: v.id,
			impact: v.impact ?? 'unknown',
			nodes: v.nodes.length,
			help: v.help,
			helpUrl: v.helpUrl,
			targets: v.nodes.slice(0, 5).map((n) => n.target.join(' '))
		});
	}
}

function describeViolations(list: RecordedViolation[]): string {
	return list.map((v) => `${v.rule} (${v.nodes} node(s); ${v.helpUrl})`).join('; ');
}

/**
 * Audit the CURRENT page state. `stateLabel` distinguishes non-initial
 * states (open modal, expanded menu) of the same route. Call `injectAxe`
 * once per page load before the first audit (the audit helpers below do it).
 */
function auditState(route: string, stateLabel?: string): void {
	const id = stateLabel ? `${route} [${stateLabel}]` : route;
	cy.checkA11y(
		undefined,
		A11Y_RUN_OPTIONS,
		(violations) => recordViolations(id, violations),
		true // skipFailures — pass/fail is decided by the ratchet below
	);
	cy.then(() => {
		const here = recorded.filter((v) => v.route === id);
		const gate = gateViolations(here, baseline);
		expect(
			gate.critical,
			`critical a11y violations on ${id}: ${describeViolations(gate.critical)}`
		).to.have.length(0);
		expect(
			gate.newSerious,
			`serious a11y violations on ${id} not in cypress/a11y-baseline.json: ` +
				describeViolations(gate.newSerious)
		).to.have.length(0);
	});
}

// ---------------------------------------------------------------------------
// Mocked auth + backend (pattern from m4-autonomous.cy.ts) — the audited
// pages read lists only; every list endpoint they touch returns empty so
// the spec never talks to the real backend and never writes anything.
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

const mockPreferences = {
	reasoning_visibility: 'disclosure',
	featured_tools: 'prominent',
	workspace_layout: 'three_pane',
	trust_pills: 'labels',
	provenance_pills: 'always',
	autonomous_enabled: false
};

function setAuthStorage(win: Window): void {
	win.localStorage.setItem(
		'lq_ai_auth',
		JSON.stringify({
			access_token: 'fake-token-a11y',
			refresh_token: null,
			expires_at: Date.now() + 3600 * 1000,
			user: mockUser
		})
	);
	win.localStorage.setItem('lq-ai:preferences-cache', JSON.stringify(mockPreferences));
}

function interceptBaseRequests(): void {
	cy.intercept('GET', '**/api/v1/users/me', { statusCode: 200, body: mockUser }).as('getMe');
	cy.intercept('GET', '**/api/v1/users/me/preferences', {
		statusCode: 200,
		body: mockPreferences
	}).as('getPreferences');
	cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
		statusCode: 200,
		body: { default_password_active: false, logs_hint: '' }
	}).as('bootstrapStatus');
	cy.intercept('GET', '**/api/v1/projects**', { statusCode: 200, body: [] }).as('listProjects');
	cy.intercept('GET', '**/api/v1/chats**', {
		statusCode: 200,
		body: { items: [], next_cursor: null }
	}).as('listChats');
	cy.intercept('GET', '**/api/v1/knowledge-bases**', { statusCode: 200, body: [] }).as('listKbs');
	cy.intercept('GET', '**/api/v1/user-skills**', { statusCode: 200, body: [] }).as(
		'listUserSkills'
	);
	cy.intercept('GET', '**/api/v1/skills**', { statusCode: 200, body: [] }).as('listSkills');
	cy.intercept('GET', '**/api/v1/saved-prompts**', { statusCode: 200, body: [] }).as(
		'listSavedPrompts'
	);
	cy.intercept('GET', '**/api/v1/teams**', { statusCode: 200, body: [] }).as('listTeams');
	cy.intercept('GET', '**/api/v1/autonomous/notifications**', {
		statusCode: 200,
		body: { notifications: [], total_count: 0, limit: 50, offset: 0 }
	}).as('listNotifications');
}

function visitAuthed(path: string): void {
	interceptBaseRequests();
	cy.visit(path, { onBeforeLoad: (win) => setAuthStorage(win) });
}

// ---------------------------------------------------------------------------
// The audits — one it() per route so a failure on one surface doesn't hide
// the others; the report in after() aggregates everything regardless.
// ---------------------------------------------------------------------------

describe('DE-232 — a11y gate over LQ.AI-owned routes (axe, wcag2a/wcag2aa/wcag21a/wcag21aa)', () => {
	before(() => {
		cy.readFile('cypress/a11y-baseline.json').then((b: BaselineFile) => {
			baseline = b;
		});
	});

	after(() => {
		// Full inventory — every audited state, every impact level. This is
		// the log-all half of the ratchet and the input for any baseline edit.
		cy.writeFile('cypress/results/a11y-report.json', {
			generated_by: 'cypress/e2e/a11y.cy.ts (DE-232)',
			run_options: A11Y_RUN_OPTIONS,
			violations: recorded
		});
	});

	it('/lq-ai/login (unauthenticated)', () => {
		interceptBaseRequests();
		cy.visit('/lq-ai/login');
		cy.get('[data-testid="lq-ai-login-submit"]').should('be.visible');
		cy.injectAxe();
		auditState('/lq-ai/login');
	});

	it('/lq-ai (guided dashboard)', () => {
		visitAuthed('/lq-ai');
		cy.get('.lq-tabbar', { timeout: 10000 }).should('exist');
		cy.injectAxe();
		auditState('/lq-ai');
	});

	it('/lq-ai/matters (list + new-matter modal state)', () => {
		visitAuthed('/lq-ai/matters');
		cy.contains('h1', 'Matters', { timeout: 10000 }).should('be.visible');
		cy.injectAxe();
		auditState('/lq-ai/matters');

		// Non-initial state: the New-matter dialog (per-state auditing — the
		// memo's "biggest miss is auditing only initial render").
		cy.contains('button', '+ New matter').first().click();
		cy.get('[role="dialog"]').should('be.visible');
		auditState('/lq-ai/matters', 'new-matter modal');
	});

	it('/lq-ai/knowledge (knowledge bases list)', () => {
		visitAuthed('/lq-ai/knowledge');
		cy.get('.lq-tabbar', { timeout: 10000 }).should('exist');
		cy.injectAxe();
		auditState('/lq-ai/knowledge');
	});

	it('/lq-ai/skills (skill creator landing)', () => {
		visitAuthed('/lq-ai/skills');
		cy.get('.lq-tabbar', { timeout: 10000 }).should('exist');
		cy.injectAxe();
		auditState('/lq-ai/skills');
	});

	it('/lq-ai/settings/appearance (settings surface)', () => {
		visitAuthed('/lq-ai/settings/appearance');
		cy.get('.lq-tabbar', { timeout: 10000 }).should('exist');
		cy.injectAxe();
		auditState('/lq-ai/settings/appearance');
	});
});
