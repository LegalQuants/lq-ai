/**
 * Wave A chrome smoke test.
 *
 * Exercises the visual foundation end-to-end: log in, see the left
 * sidebar's navigation (ADR 0045 §6; it replaced the top bar and tab row in
 * the sidebar cutover), see that the top bar's self-hosted pill and command-K
 * hint are gone, navigate to Skills from the Customise group. The last two
 * tests still assert Wave A's ComingSoonModal and AmbientFooter and are
 * stale; that is why this spec is excluded from the tracks (spec-tracks.ts).
 *
 * Run requires a live stack:
 *   docker compose up -d
 *   docker compose exec api python -m app.cli reset-admin-password
 *   (note the printed password; export LQAI_ADMIN_PASSWORD or update env)
 *   cd web && npx cypress run --spec 'cypress/e2e/wave-a-chrome.cy.ts'
 */
describe('Wave A — LQ.AI chrome', () => {
  beforeEach(() => {
    cy.visit('/lq-ai/login');
    cy.get('input[type="email"]').type(Cypress.env('LQAI_ADMIN_EMAIL') || 'admin@lq.ai');
    cy.get('input[type="password"]').type(Cypress.env('LQAI_ADMIN_PASSWORD') || 'LQ-AI-smoke-test-Pw1!');
    cy.get('button[type="submit"]').click();
    cy.url().should('not.include', '/login');
  });

  const nav = '[data-testid="lq-shell-sidebar"] nav[aria-label="Primary"]';

  it('renders the sidebar with role-aware visibility', () => {
    cy.get(nav).within(() => {
      for (const id of ['new', 'home', 'tabular', 'customise', 'all-matters', 'all-chats'])
        cy.get(`[data-nav-id="${id}"]`).should('be.visible');
      // Customise holds Skills, Knowledge, Playbooks and Saved prompts.
      for (const id of ['skills', 'knowledge', 'playbooks', 'saved-prompts'])
        cy.get(`[data-nav-id="${id}"]`).should('exist');
      for (const id of ['learn', 'trust', 'account']) cy.get(`[data-nav-id="${id}"]`).should('be.visible');
      cy.get('[data-nav-id="admin"]').should('be.visible'); // visible because we logged in as admin
      cy.get('[data-nav-id="labs"]').should('not.exist'); // Automations is off for a fresh admin
    });
  });

  it('has no top bar, tab row or self-hosted pill', () => {
    cy.get('[data-testid="lq-shell-sidebar"]').should('be.visible');
    cy.get('.lq-topbar').should('not.exist');
    cy.get('.lq-tabbar').should('not.exist');
    cy.get('[role="tablist"]').should('not.exist');
    // The top bar's self-hosted pill is gone; Home's trust panel keeps its own, in the page.
    cy.get('[data-testid="lq-shell-sidebar"]').should('not.contain.text', 'self-hosted');
    cy.get('.lq-chrome').should('not.exist');
    cy.contains('⌘K').should('not.exist');
  });

  it('navigates to Skills from the Customise group', () => {
    cy.get(`${nav} button[data-nav-id="customise"]`).click();
    cy.get(`${nav} a[data-nav-id="skills"]`).click();
    cy.url().should('include', '/lq-ai/skills');
    cy.get(`${nav} a[data-nav-id="skills"]`).should('have.attr', 'aria-current', 'page');
  });

  it('opens ComingSoonModal for not-yet-shipped tabs', () => {
    cy.contains('nav[aria-label="Primary"] button', 'Matters').click();
    cy.get('[role="dialog"]').within(() => {
      cy.contains('Matters');
      cy.contains('Wave C');
      cy.contains('design spec');
      cy.contains('Got it').click();
    });
    cy.get('[role="dialog"]').should('not.exist');
    // URL didn't change because the modal was used:
    cy.url().should('not.include', '/lq-ai/matters');
  });

  it('AmbientFooter renders on the chat surface with provider + tier + audit pills', () => {
    cy.visit('/lq-ai');
    cy.get('footer[aria-label="Chat status"]').within(() => {
      cy.contains('audit on');
    });
  });
});
