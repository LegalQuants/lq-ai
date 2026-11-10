/**
 * Wave B v2 surface smoke tests.
 *
 * Covers the eight new surfaces that shipped in Wave B v2:
 *
 *   1. Post-login lands on the Guided Dashboard at /lq-ai (not the chat shell)
 *   2. Chats tab routes to /lq-ai/chats — no ComingSoonModal; chat shell renders
 *   3. /lq-ai/settings/appearance toggle persists across reload (real backend PATCH)
 *   4. /lq-ai/trust renders all four trust cards
 *   5. /lq-ai/admin/developer renders all five developer-support cards
 *   6. ✨ Enhance Prompt loading, success/actions, skipped and error/retry states
 *   7. /lq-ai/skills/[id] detail page renders SkillDetailTabs; tab switching works
 *   8. Source tab does not execute a hostile skill body (D-01 XSS regression)
 *
 * Run requires a live stack:
 *   docker compose up -d
 *   docker compose exec api python -m app.cli reset-admin-password
 *   (note the printed password; export LQAI_ADMIN_PASSWORD or update env)
 *   cd web && npx cypress run --spec 'cypress/e2e/wave-b-surfaces.cy.ts'
 */

import { getBearerToken } from '../support/lq-ai-helpers';
import type { EnhancePromptResponse } from '../../src/lib/lq-ai/types';

/** Direct API base — the SvelteKit web container has no POST proxy for user-skills routes. */
const API_BASE = () => Cypress.env('LQAI_API_BASE') ?? 'http://localhost:8000';

const ORIGINAL = 'review this NDA for unusual provisions';
const ENHANCED =
	'Review the NDA and identify unusual confidentiality, term and governing-law provisions.';
const INTERACTION_ID = '00000000-0000-4000-8000-000000000006';
const enhancedResponse: EnhancePromptResponse = {
	interaction_id: INTERACTION_ID,
	expansion_applied: true,
	expanded_prompt: ENHANCED,
	reasoning: ['Make the requested review scope explicit.'],
	routed_inference_tier: 1,
	routed_provider: 'fixture'
};

// Hold the network response until the browser has visibly entered loading.
// This covers a genuinely delayed response without a wall-clock sleep or a
// race between an immediate fixture and an assertion on the loading state.
function holdEnhancement(
	response: { body: EnhancePromptResponse | { detail: string }; statusCode?: number },
	alias = 'enhance'
) {
	let reply: (() => void) | undefined;
	cy.intercept(
		'POST',
		'**/api/v1/enhance-prompt',
		(req) =>
			new Cypress.Promise<void>((resolve) => {
				reply = () => {
					req.reply(response);
					resolve();
				};
			})
	).as(alias);
	return () =>
		cy
			.wrap(null)
			.should(() => {
				expect(reply, 'enhancement request reached its fixture').to.be.a('function');
			})
			.then(() => {
				if (reply) reply();
			});
}

function openEnhancement() {
	cy.visit('/lq-ai/chats');
	cy.intercept('POST', '**/api/v1/chats').as('createChat');
	cy.intercept('PATCH', '**/api/v1/enhance-prompt/' + INTERACTION_ID, {
		body: enhancedResponse
	}).as('enhanceOutcome');
	cy.get('[data-testid="lq-ai-new-chat-btn"]').click();
	cy.wait('@createChat', { timeout: 60000 }).its('response.statusCode').should('eq', 201);
	cy.get('[data-testid="lq-ai-composer-input"]').type(ORIGINAL);
	cy.get('[data-testid="lq-ai-enhance-btn"]').should('not.be.disabled').click();
	cy.get('[data-testid="lq-ai-enhance-loading"]').should('be.visible');
	cy.get('[data-testid="lq-ai-enhance-use"]').should('not.exist');
	cy.get('[data-testid="lq-ai-enhance-error"]').should('not.exist');
}

describe('Wave B v2 — new surfaces', () => {
	beforeEach(() => {
		cy.visit('/lq-ai/login');
		cy.get('input[type="email"]').type(Cypress.env('LQAI_ADMIN_EMAIL') || 'admin@lq.ai');
		cy.get('input[type="password"]').type(
			Cypress.env('LQAI_ADMIN_PASSWORD') || 'LQ-AI-smoke-test-Pw1!'
		);
		cy.intercept('POST', '**/api/v1/auth/login').as('login');
		cy.get('button[type="submit"]').click();
		cy.wait('@login', { timeout: 30000 }).its('response.statusCode').should('eq', 200);
		// If must-change-password gate fires (fresh password reset), log and continue.
		// CI smoke environments are expected to have a stable post-change password.
		cy.url().then((url) => {
			if (url.includes('/change-password')) {
				cy.log(
					'must-change-password gate triggered; ensure the smoke password is the post-change one'
				);
			}
		});
		cy.url({ timeout: 15000 }).should('not.include', '/login');
	});

	// ── Test 1 ───────────────────────────────────────────────────────────────────
	// Post-login lands on the Guided Dashboard, not the chat shell.
	it('post-login lands on Guided Dashboard at /lq-ai', () => {
		cy.url().should('match', /\/lq-ai\/?$/);
		// GuidedDashboardWelcome renders "Welcome back, <name>" — use partial match.
		cy.contains(/Welcome back/i).should('be.visible');
	});

	// ── Test 2 ───────────────────────────────────────────────────────────────────
	// Chats tab is now available=true; clicking it routes to /lq-ai/chats and
	// the chat shell renders instead of ComingSoonModal.
	it('Chats tab routes to /lq-ai/chats with no ComingSoonModal', () => {
		cy.contains('nav[aria-label="Primary"] button', 'Chats').click();
		cy.url().should('include', '/lq-ai/chats');
		// No dialog should be present (was the ComingSoonModal path).
		cy.get('[role="dialog"]').should('not.exist');
		// The chat shell root element must be in the DOM.
		cy.get('[data-testid="lq-ai-chat-shell"]').should('exist');
	});

	// ── Test 3 ───────────────────────────────────────────────────────────────────
	// /lq-ai/settings/appearance: toggling "Featured tools" to "Inline" persists
	// across a full page reload (real backend PATCH via the T2 preferences store).
	it('Featured tools toggle persists across reload', () => {
		cy.visit('/lq-ai/settings/appearance');

		// The SettingsToggleGroup for "Featured tools" renders a <fieldset> with
		// <legend> text "Featured tools". Inside, each option is a <label> wrapping
		// an <input type="radio">. We click the label whose text is "Inline toolbar only".
		cy.intercept('PATCH', '**/api/v1/users/me/preferences').as('savePreferences');
		cy.contains('fieldset', 'Featured tools', { timeout: 60000 }).within(() => {
			cy.contains('label', 'Inline toolbar only')
				.find('input[type="radio"]')
				.then(($input) => {
					if ($input.is(':checked')) {
						cy.contains('label', 'Prominent cards on dashboard').click();
						cy.wait('@savePreferences', { timeout: 60000 })
							.its('response.statusCode')
							.should('eq', 200);
					}
				});
			cy.contains('label', 'Inline toolbar only').click();
		});
		cy.wait('@savePreferences', { timeout: 60000 }).its('response.statusCode').should('eq', 200);

		cy.intercept('GET', '**/api/v1/users/me').as('loadUser');
		cy.reload();
		cy.wait('@loadUser', { timeout: 60000 }).its('response.statusCode').should('eq', 200);

		// After reload the radio for "Inline toolbar only" should be checked.
		cy.contains('fieldset', 'Featured tools', { timeout: 60000 }).within(() => {
			cy.contains('label', 'Inline toolbar only').find('input[type="radio"]').should('be.checked');
		});

		// Restore default (Prominent) so this test is idempotent.
		cy.contains('fieldset', 'Featured tools').within(() => {
			cy.contains('label', 'Prominent cards on dashboard').click();
		});
		cy.wait('@savePreferences', { timeout: 60000 }).its('response.statusCode').should('eq', 200);
	});

	// ── Test 4 ───────────────────────────────────────────────────────────────────
	// /lq-ai/trust renders all four trust cards using their actual h3 titles.
	it('/lq-ai/trust renders all four trust cards', () => {
		cy.visit('/lq-ai/trust');
		// TrustDataResidencyCard: h3 = "Where your data lives"
		cy.contains('h3', 'Where your data lives').should('be.visible');
		// TrustProvidersCard: h3 = "Configured providers"
		cy.contains('h3', 'Configured providers').should('be.visible');
		// TrustExternalTurnsCard: h3 = "External-turn usage"
		cy.contains('h3', 'External-turn usage').should('be.visible');
		// TrustArtifactsCard: h3 = "Trust artifacts"
		cy.contains('h3', 'Trust artifacts').should('be.visible');
	});

	// ── Test 5 ───────────────────────────────────────────────────────────────────
	// /lq-ai/admin/developer renders all five developer-support cards.
	// Card titles are h2 elements inside each DevXxx component.
	it('/lq-ai/admin/developer renders all five developer cards', () => {
		cy.visit('/lq-ai/admin/developer');
		cy.get('.dev-grid h2').should('have.length', 5);
		for (const title of [
			'API documentation',
			'API playground',
			'Role management',
			'Skill reference policy',
			'Build your own frontend'
		]) {
			cy.get('.dev-grid').contains('h2', title).scrollIntoView();
			cy.get('.dev-grid').contains('h2', title).should('be.visible');
		}
	});

	// ── Test 6 ───────────────────────────────────────────────────────────────────
	// Every inference response and outcome write is intercepted. Real login and
	// chat creation remain covered; this track never needs provider credentials.
	for (const action of [
		{ name: 'use', used: true, edited_before_use: false, composer: ENHANCED },
		{ name: 'edit', used: true, edited_before_use: true, composer: ENHANCED },
		{ name: 'keep', used: false, composer: ORIGINAL }
	]) {
		it('Enhance Prompt waits for success and records ' + action.name, () => {
			const release = holdEnhancement({ body: enhancedResponse });
			openEnhancement();
			release();
			cy.wait('@enhance').its('request.body.raw_input').should('eq', ORIGINAL);
			cy.get('[data-testid="lq-ai-enhance-loading"]').should('not.exist');
			cy.get('[data-testid="lq-ai-enhance-original"]').should('contain', ORIGINAL);
			cy.get('[data-testid="lq-ai-enhance-enhanced"]').should('contain', ENHANCED);
			const button = '[data-testid="lq-ai-enhance-' + action.name + '"]';
			cy.get(button).scrollIntoView();
			cy.get(button).should('be.visible').click();
			cy.wait('@enhanceOutcome')
				.its('request.body')
				.should('deep.equal', {
					used: action.used,
					...(action.edited_before_use === undefined
						? {}
						: { edited_before_use: action.edited_before_use })
				});
			cy.get('[data-testid="lq-ai-enhance-panel"]').should('not.exist');
			cy.get('[data-testid="lq-ai-composer-input"]').should('have.value', action.composer);
		});
	}

	it('Enhance Prompt shows a skipped result and keeps the original', () => {
		const release = holdEnhancement({
			body: {
				...enhancedResponse,
				expansion_applied: false,
				expanded_prompt: ORIGINAL,
				reasoning: [],
				skip_reason: 'already_structured'
			}
		});
		openEnhancement();
		release();
		cy.wait('@enhance');
		cy.get('[data-testid="lq-ai-enhance-loading"]').should('not.exist');
		cy.get('[data-testid="lq-ai-enhance-skipped"]').should('contain', 'already_structured');
		cy.get('[data-testid="lq-ai-enhance-skipped-ok"]').scrollIntoView();
		cy.get('[data-testid="lq-ai-enhance-skipped-ok"]').should('be.visible').click();
		cy.wait('@enhanceOutcome').its('request.body').should('deep.equal', { used: false });
		cy.get('[data-testid="lq-ai-enhance-panel"]').should('not.exist');
		cy.get('[data-testid="lq-ai-composer-input"]').should('have.value', ORIGINAL);
	});

	it('Enhance Prompt shows an error, retries, and dismisses without changing the prompt', () => {
		const error = { statusCode: 502, body: { detail: 'Fixture enhancement unavailable' } };
		const release = holdEnhancement(error);
		openEnhancement();
		release();
		cy.wait('@enhance').its('response.statusCode').should('eq', 502);
		cy.get('[data-testid="lq-ai-enhance-loading"]').should('not.exist');
		cy.get('[data-testid="lq-ai-enhance-error"]').should(
			'contain',
			'Fixture enhancement unavailable'
		);
		const releaseRetry = holdEnhancement(error, 'retryEnhance');
		cy.get('[data-testid="lq-ai-enhance-retry"]').scrollIntoView();
		cy.get('[data-testid="lq-ai-enhance-retry"]').should('be.visible').click();
		cy.get('[data-testid="lq-ai-enhance-loading"]').should('be.visible');
		releaseRetry();
		cy.wait('@retryEnhance').its('response.statusCode').should('eq', 502);
		cy.get('[data-testid="lq-ai-enhance-error"]').should(
			'contain',
			'Fixture enhancement unavailable'
		);
		cy.get('[data-testid="lq-ai-enhance-error-dismiss"]').scrollIntoView();
		cy.get('[data-testid="lq-ai-enhance-error-dismiss"]').should('be.visible').click();
		cy.get('[data-testid="lq-ai-enhance-panel"]').should('not.exist');
		cy.get('[data-testid="lq-ai-composer-input"]').should('have.value', ORIGINAL);
		cy.get('@enhanceOutcome.all').should('have.length', 0);
	});

	// ── Test 7 ───────────────────────────────────────────────────────────────────
	// /lq-ai/skills/[id] detail page: SkillDetailTabs renders with "Use it" active
	// by default; clicking "View source" switches the tab and SkillSourceView renders
	// "Frontmatter" as the section heading.
	it('skill detail page renders SkillDetailTabs and tab switching works', () => {
		const ts = Date.now();
		const skillSlug = `cypress-skill-detail-${ts}`;

		// A fresh stack has no user skills, so create the row this test opens.
		getBearerToken((token) => {
			cy.request({
				method: 'POST',
				url: `${API_BASE()}/api/v1/user-skills`,
				headers: { Authorization: `Bearer ${token}` },
				body: {
					scope: 'user',
					slug: skillSlug,
					display_name: `Cypress skill detail ${ts}`,
					description: 'Cypress fixture for skill detail tabs',
					body: '# Cypress skill detail',
					version: '1.0.0'
				}
			})
				.its('status')
				.should('eq', 201);
		});

		cy.visit('/lq-ai/skills');
		cy.intercept('GET', `**/api/v1/skills/${skillSlug}`).as('loadSkill');
		cy.get(`a[href="/lq-ai/skills/${skillSlug}"]`).should('be.visible').click();
		cy.url().should('match', /\/lq-ai\/skills\/[^/]+$/);
		cy.wait('@loadSkill', { timeout: 60000 }).its('response.statusCode').should('eq', 200);

		// SkillDetailTabs: the tablist container
		cy.get('nav[role="tablist"][aria-label="Skill detail tabs"]', { timeout: 15000 }).should(
			'exist'
		);

		// "Use it" tab is active by default (aria-selected="true")
		cy.contains('button[role="tab"]', 'Use it').should('have.attr', 'aria-selected', 'true');

		// Click "View source" — switches the active tab
		cy.contains('button[role="tab"]', 'View source').click();
		cy.contains('button[role="tab"]', 'View source').should('have.attr', 'aria-selected', 'true');

		// SkillSourceView renders a "Frontmatter" section heading (h2.lq-text-label)
		cy.contains('h2', 'Frontmatter').should('be.visible');
	});

	// ── Test 8 ───────────────────────────────────────────────────────────────────
	// D-01 regression: SkillSourceView renders the skill body through {@html}, so a
	// crafted body used to run script in the viewer's authenticated session (and the
	// auth token lives in localStorage, so that is session takeover). The fix wraps
	// the marked() output in DOMPurify.sanitize.
	//
	// The skill is seeded through the real API rather than stubbed, because the
	// server deliberately stores the body verbatim (api/app/api/skills.py returns
	// row.body unchanged) — so this exercises the whole path, and would still catch
	// the bug if the storage layer changed underneath the component.
	it('source tab does not execute a hostile skill body', () => {
		const ts = Date.now();
		const skillSlug = `d-01-xss-regression-${ts}`;

		// Three payload shapes DOMPurify's default profile must neutralise: an event
		// handler on a tag that loads eagerly, a raw script element, and a
		// javascript: URL. marked() passes raw HTML through untouched, so each one
		// reaches the {@html} sink exactly as written here.
		const hostileBody = [
			'# Benign heading',
			'',
			'Ordinary prose so the render is visibly non-empty.',
			'',
			'<img src=x onerror="window.__xssFired = true">',
			'<script>window.__xssFired = true;</script>',
			'',
			'[click me](javascript:window.__xssFired=true)'
		].join('\n');

		getBearerToken((token) => {
			cy.request({
				method: 'POST',
				url: `${API_BASE()}/api/v1/user-skills`,
				headers: { Authorization: `Bearer ${token}` },
				body: {
					scope: 'user',
					slug: skillSlug,
					display_name: `D-01 XSS regression ${ts}`,
					description: 'Cypress fixture: hostile body must render inert',
					body: hostileBody,
					version: '1.0.0'
				}
			})
				.its('status')
				.should('eq', 201);
		});

		// ?tab=source deep-links straight to SkillSourceView (VALID tabs are
		// use|source|try|versions on the [id] route).
		cy.visit(`/lq-ai/skills/${skillSlug}?tab=source`);

		// Assert the body actually rendered BEFORE asserting on absences — otherwise
		// a page that failed to load would satisfy every "should not exist" below and
		// the test would pass while proving nothing.
		cy.contains('h2', 'Body').should('be.visible');
		cy.get('.lq-prose').should('contain.text', 'Benign heading');

		// The payloads survived storage but must not survive sanitization. Assert on
		// the rendered markup rather than on element presence: DOMPurify keeps the
		// <img> and drops only its handler, so a `cy.get('.lq-prose img')` chain
		// would report a confusing failure if the tag were ever stripped entirely.
		cy.get('.lq-prose script').should('not.exist');
		cy.get('.lq-prose').then(($prose) => {
			const html = $prose.html();
			expect(html, 'script element stripped').to.not.include('<script');
			expect(html, 'event handler stripped').to.not.include('onerror');
			expect(html, 'javascript: URL stripped').to.not.include('javascript:');
		});

		// And the point of all of it: nothing ran. Every payload assigns this flag,
		// so it is defined only if one of them executed.
		cy.window().then((win) => {
			expect(
				(win as unknown as Record<string, unknown>).__xssFired,
				'no payload executed'
			).to.equal(undefined);
		});
	});
});
