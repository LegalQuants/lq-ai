/**
 * Wave B v2 surface smoke tests.
 *
 * Covers the seven new surfaces that shipped in Wave B v2:
 *
 *   1. Post-login lands on the Guided Dashboard at /lq-ai (not the chat shell)
 *   2. Chats tab routes to /lq-ai/chats — no ComingSoonModal; chat shell renders
 *   3. /lq-ai/settings/appearance toggle persists across reload (real backend PATCH)
 *   4. /lq-ai/trust renders all four trust cards
 *   5. /lq-ai/admin/developer renders the four developer-support cards
 *   6. ✨ Enhance Prompt button opens the expansion panel (or error state)
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

/** Direct API base — the SvelteKit web container has no POST proxy for user-skills routes. */
const API_BASE = () => Cypress.env('LQAI_API_BASE') ?? 'http://localhost:8000';

describe('Wave B v2 — new surfaces', () => {
  beforeEach(() => {
    cy.visit('/lq-ai/login');
    cy.get('input[type="email"]').type(Cypress.env('LQAI_ADMIN_EMAIL') || 'admin@lq.ai');
    cy.get('input[type="password"]').type(
      Cypress.env('LQAI_ADMIN_PASSWORD') || 'LQ-AI-smoke-test-Pw1!'
    );
    cy.get('button[type="submit"]').click();
    // If must-change-password gate fires (fresh password reset), log and continue.
    // CI smoke environments are expected to have a stable post-change password.
    cy.url().then((url) => {
      if (url.includes('/change-password')) {
        cy.log(
          'must-change-password gate triggered; ensure the smoke password is the post-change one'
        );
      }
    });
    cy.url().should('not.include', '/login');
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
    cy.contains('fieldset', 'Featured tools').within(() => {
      cy.contains('label', 'Inline toolbar only').click();
    });

    cy.reload();

    // After reload the radio for "Inline toolbar only" should be checked.
    cy.contains('fieldset', 'Featured tools').within(() => {
      cy.contains('label', 'Inline toolbar only')
        .find('input[type="radio"]')
        .should('be.checked');
    });

    // Restore default (Prominent) so this test is idempotent.
    cy.contains('fieldset', 'Featured tools').within(() => {
      cy.contains('label', 'Prominent cards on dashboard').click();
    });
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
  // /lq-ai/admin/developer renders all four developer-support cards.
  // Card titles are h2 elements inside each DevXxx component.
  it('/lq-ai/admin/developer renders all four developer cards', () => {
    cy.visit('/lq-ai/admin/developer');
    // DevApiDocsCard: h2 = "API documentation"
    cy.contains('h2', 'API documentation').should('be.visible');
    // DevApiPlaygroundCard: h2 = "API playground"
    cy.contains('h2', 'API playground').should('be.visible');
    // DevRoleManagementCard: h2 = "Role management"
    cy.contains('h2', 'Role management').should('be.visible');
    // DevForkCallout: h2 = "Build your own frontend"
    cy.contains('h2', 'Build your own frontend').should('be.visible');
  });

  // ── Test 6 ───────────────────────────────────────────────────────────────────
  // ✨ Enhance Prompt button on the chat composer opens the expansion panel.
  // Accepts the success state (Original + Enhanced cards) OR the error state
  // (Enhance Prompt failed message) — the backend enhance-prompt service may
  // not be reachable in all smoke environments.
  it('✨ Enhance Prompt button opens the expansion panel', () => {
    cy.visit('/lq-ai/chats');
    // Type a prompt so the ✨ button becomes enabled.
    cy.get('[data-testid="lq-ai-composer-input"]').type(
      'review this NDA for unusual provisions'
    );
    // The enhance button is enabled only when composerText is non-empty.
    cy.get('[data-testid="lq-ai-enhance-btn"]').should('not.be.disabled').click();
    // The panel root must appear (covers all non-closed states).
    cy.get('[data-testid="lq-ai-enhance-panel"]', { timeout: 30000 }).should('exist');
    // Accept either the success path (Original card) or the error path.
    cy.get('[data-testid="lq-ai-enhance-panel"]').then(($panel) => {
      const text = $panel.text();
      const successPath =
        $panel.find('[data-testid="lq-ai-enhance-original"]').length > 0 ||
        $panel.find('[data-testid="lq-ai-enhance-enhanced"]').length > 0 ||
        $panel.find('[data-testid="lq-ai-enhance-skipped"]').length > 0;
      const errorPath = text.includes('Enhance Prompt failed');
      expect(successPath || errorPath, 'enhancement panel shows a result or error').to.be.true;
    });
  });

  // ── Test 7 ───────────────────────────────────────────────────────────────────
  // /lq-ai/skills/[id] detail page: SkillDetailTabs renders with "Use it" active
  // by default; clicking "View source" switches the tab and SkillSourceView renders
  // "Frontmatter" as the section heading.
  it('skill detail page renders SkillDetailTabs and tab switching works', () => {
    cy.visit('/lq-ai/skills');
    // Click the first skill name link — these are anchors with href="/lq-ai/skills/<slug>"
    // (not /edit or /new). The skills list page uses data-testid="lq-ai-user-skill-row"
    // rows; each title cell has an <a href="/lq-ai/skills/{slug}">.
    cy.get('a[href^="/lq-ai/skills/"]')
      .not('[href*="/edit"]')
      .not('[href*="/new"]')
      .first()
      .click();
    cy.url().should('match', /\/lq-ai\/skills\/[^/]+$/);

    // SkillDetailTabs: the tablist container
    cy.get('nav[role="tablist"][aria-label="Skill detail tabs"]').should('exist');

    // "Use it" tab is active by default (aria-selected="true")
    cy.contains('button[role="tab"]', 'Use it').should('have.attr', 'aria-selected', 'true');

    // Click "View source" — switches the active tab
    cy.contains('button[role="tab"]', 'View source').click();
    cy.contains('button[role="tab"]', 'View source').should(
      'have.attr',
      'aria-selected',
      'true'
    );

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
